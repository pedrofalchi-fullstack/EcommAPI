"""
server.py
Servidor MCP que conecta o Claude ao seu Bling.

Filosofia de segurança:
  - Ferramentas de LEITURA/ANÁLISE podem rodar livremente.
  - Ferramentas que ESCREVEM (preço, descrição) usam DUAS FASES:
      1) propor_*  -> só registra a proposta + mostra o diff
      2) aplicar_alteracoes_aprovadas -> executa SÓ os IDs que VOCÊ aprovar
  - Toda alteração aplicada é logada com antes/depois (applied_log.jsonl).
  - Variações de preço acima de MAX_VARIACAO_PCT são bloqueadas por padrão.

Rodar:
    pip install "mcp[cli]" requests python-dotenv
    mcp dev server.py        # para testar
    (ou conecte no Claude Desktop/Code — veja o README)
"""

import os
import json
import time
import uuid
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import bling_client as bling

load_dotenv()

mcp = FastMCP("bling-ecommerce")

DATA_DIR = Path(os.getenv("BLING_DATA_DIR", "."))
PENDENTES_FILE = DATA_DIR / "pending_changes.json"
LOG_FILE = DATA_DIR / "applied_log.jsonl"

# Trava de segurança: rejeita variações grandes a menos que forçadas.
MAX_VARIACAO_PCT = float(os.getenv("MAX_VARIACAO_PCT", "30"))


# ---------------- utilidades de persistência ----------------

def _ler_pendentes() -> dict:
    if PENDENTES_FILE.exists():
        return json.loads(PENDENTES_FILE.read_text())
    return {}


def _salvar_pendentes(p: dict) -> None:
    PENDENTES_FILE.write_text(json.dumps(p, indent=2, ensure_ascii=False))


def _log_aplicacao(registro: dict) -> None:
    registro["timestamp"] = int(time.time())
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _campos_produto(p: dict) -> dict:
    d = p.get("data", p)
    return {
        "id": d.get("id"),
        "nome": d.get("nome"),
        "codigo": d.get("codigo"),
        "preco": d.get("preco"),
        "precoCusto": d.get("precoCusto"),
        "situacao": d.get("situacao"),
        "estoque": (d.get("estoque") or {}).get("saldoVirtualTotal"),
    }


def _margem_pct(preco, custo):
    try:
        preco = float(preco or 0)
        custo = float(custo or 0)
        if preco > 0 and custo > 0:
            return round((preco - custo) / preco * 100, 2)
    except (TypeError, ValueError):
        pass
    return None


def _agregar_vendas(data_inicial: str, data_final: str, max_pedidos: int):
    """
    Percorre os pedidos do período e soma quantidade/receita por produto.
    Retorna (agregado, total_pedidos), onde agregado[produto_id] =
    {"nome", "qtd", "receita", "pedidos"}.
    """
    agregado = defaultdict(lambda: {"nome": None, "qtd": 0.0,
                                    "receita": 0.0, "pedidos": 0})
    processados = 0
    pagina = 1
    while processados < max_pedidos:
        resp = bling.get_vendas(data_inicial, data_final, pagina=pagina)
        pedidos = resp.get("data", [])
        if not pedidos:
            break
        for ped in pedidos:
            if processados >= max_pedidos:
                break
            # A listagem nem sempre traz os itens; busca o detalhe.
            detalhe = bling.get_venda(ped["id"]).get("data", {})
            for item in detalhe.get("itens", []):
                prod = item.get("produto", {}) or {}
                pid = prod.get("id") or item.get("id")
                if pid is None:
                    continue
                qtd = float(item.get("quantidade") or 0)
                valor = float(item.get("valor") or 0) * qtd
                a = agregado[pid]
                a["nome"] = a["nome"] or prod.get("nome") or item.get("descricao")
                a["qtd"] += qtd
                a["receita"] += valor
                a["pedidos"] += 1
            processados += 1
        pagina += 1
    return agregado, processados


# ---------------- ferramentas de LEITURA ----------------

@mcp.tool()
def listar_produtos(pagina: int = 1, limite: int = 50) -> str:
    """Lista produtos do Bling (paginado). Retorna campos resumidos."""
    resp = bling.get_produtos(pagina=pagina, limite=limite)
    itens = resp.get("data", [])
    return json.dumps([_campos_produto({"data": i}) for i in itens],
                      ensure_ascii=False, indent=2)


@mcp.tool()
def buscar_produto(produto_id: int) -> str:
    """Busca um produto específico pelo ID."""
    return json.dumps(_campos_produto(bling.get_produto(produto_id)),
                      ensure_ascii=False, indent=2)


@mcp.tool()
def listar_vendas(data_inicial: str, data_final: str, pagina: int = 1) -> str:
    """Lista pedidos de venda crus num intervalo (datas em YYYY-MM-DD)."""
    resp = bling.get_vendas(data_inicial, data_final, pagina=pagina)
    return json.dumps(resp.get("data", []), ensure_ascii=False, indent=2)


# ---------------- ferramentas de ANÁLISE (leitura) ----------------

@mcp.tool()
def analisar_vendas(data_inicial: str, data_final: str,
                    top_n: int = 10, max_pedidos: int = 200) -> str:
    """
    Analisa as vendas do período: campeões de receita, com margem por produto.
    Datas em YYYY-MM-DD. Use isto ANTES de propor mudanças de preço/descrição.
    """
    agregado, total = _agregar_vendas(data_inicial, data_final, max_pedidos)
    linhas = []
    for pid, a in agregado.items():
        prod = _campos_produto(bling.get_produto(pid))
        linhas.append({
            "produto_id": pid,
            "nome": a["nome"] or prod.get("nome"),
            "qtd_vendida": round(a["qtd"], 2),
            "receita": round(a["receita"], 2),
            "preco_atual": prod.get("preco"),
            "custo": prod.get("precoCusto"),
            "margem_pct": _margem_pct(prod.get("preco"), prod.get("precoCusto")),
            "estoque": prod.get("estoque"),
        })
    linhas.sort(key=lambda x: x["receita"], reverse=True)
    receita_total = round(sum(l["receita"] for l in linhas), 2)
    return json.dumps({
        "periodo": [data_inicial, data_final],
        "pedidos_analisados": total,
        "receita_total": receita_total,
        "mais_vendidos": linhas[:top_n],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def produtos_sem_giro(data_inicial: str, data_final: str,
                      max_produtos: int = 200, max_pedidos: int = 200) -> str:
    """
    Lista produtos COM estoque que NÃO venderam (ou venderam pouco) no período.
    Bons candidatos a promoção ou revisão de descrição.
    """
    agregado, _ = _agregar_vendas(data_inicial, data_final, max_pedidos)
    vendidos = set(agregado.keys())
    encalhados = []
    pagina = 1
    while len(encalhados) < max_produtos:
        resp = bling.get_produtos(pagina=pagina, limite=100)
        itens = resp.get("data", [])
        if not itens:
            break
        for i in itens:
            c = _campos_produto({"data": i})
            estoque = c.get("estoque") or 0
            if c["id"] not in vendidos and estoque and float(estoque) > 0:
                encalhados.append({**c,
                                   "margem_pct": _margem_pct(c["preco"], c["precoCusto"])})
            if len(encalhados) >= max_produtos:
                break
        pagina += 1
    return json.dumps({"periodo": [data_inicial, data_final],
                       "encalhados": encalhados}, ensure_ascii=False, indent=2)


# ---------------- FASE 1: propor (não aplica nada) ----------------

@mcp.tool()
def propor_alteracao_preco(produto_id: int, novo_preco: float, motivo: str,
                           forcar: bool = False) -> str:
    """
    Registra uma PROPOSTA de alteração de preço. NÃO altera o Bling.
    Variações acima de MAX_VARIACAO_PCT são bloqueadas (a menos que forcar=True).
    """
    d = bling.get_produto(produto_id).get("data", {})
    preco_atual = float(d.get("preco") or 0)
    novo_preco = round(float(novo_preco), 2)

    variacao = None
    if preco_atual > 0:
        variacao = round((novo_preco - preco_atual) / preco_atual * 100, 2)
        if abs(variacao) > MAX_VARIACAO_PCT and not forcar:
            return json.dumps({
                "status": "BLOQUEADO",
                "motivo_bloqueio": (f"Variação de {variacao}% excede o limite de "
                                    f"{MAX_VARIACAO_PCT}%. Use forcar=True para insistir."),
                "produto_id": produto_id,
                "preco_atual": preco_atual,
                "preco_proposto": novo_preco,
            }, ensure_ascii=False, indent=2)

    pendentes = _ler_pendentes()
    prop_id = str(uuid.uuid4())[:8]
    pendentes[prop_id] = {
        "id_proposta": prop_id, "tipo": "preco", "produto_id": produto_id,
        "nome": d.get("nome"), "preco_atual": preco_atual,
        "preco_proposto": novo_preco, "variacao_pct": variacao,
        "motivo": motivo, "criado_em": int(time.time()),
    }
    _salvar_pendentes(pendentes)
    return json.dumps({"status": "PROPOSTO (aguardando aprovação)",
                       **pendentes[prop_id]}, ensure_ascii=False, indent=2)


@mcp.tool()
def propor_alteracao_descricao(produto_id: int, motivo: str,
                               novo_nome: str | None = None,
                               nova_descricao_curta: str | None = None) -> str:
    """
    Registra uma PROPOSTA de alteração de nome e/ou descrição curta.
    NÃO altera o Bling. Pelo menos um dos campos deve ser informado.
    """
    if not novo_nome and not nova_descricao_curta:
        return "Informe ao menos novo_nome ou nova_descricao_curta."
    d = bling.get_produto(produto_id).get("data", {})

    campos = {}
    if novo_nome:
        campos["nome"] = {"antes": d.get("nome"), "depois": novo_nome}
    if nova_descricao_curta:
        campos["descricaoCurta"] = {"antes": d.get("descricaoCurta"),
                                    "depois": nova_descricao_curta}

    pendentes = _ler_pendentes()
    prop_id = str(uuid.uuid4())[:8]
    pendentes[prop_id] = {
        "id_proposta": prop_id, "tipo": "descricao", "produto_id": produto_id,
        "nome": d.get("nome"), "campos": campos,
        "motivo": motivo, "criado_em": int(time.time()),
    }
    _salvar_pendentes(pendentes)
    return json.dumps({"status": "PROPOSTO (aguardando aprovação)",
                       **pendentes[prop_id]}, ensure_ascii=False, indent=2)


@mcp.tool()
def listar_alteracoes_pendentes() -> str:
    """Mostra todas as propostas aguardando aprovação (preço e descrição)."""
    return json.dumps(list(_ler_pendentes().values()),
                      ensure_ascii=False, indent=2)


@mcp.tool()
def cancelar_proposta(id_proposta: str) -> str:
    """Remove uma proposta pendente sem aplicá-la."""
    pendentes = _ler_pendentes()
    removida = pendentes.pop(id_proposta, None)
    _salvar_pendentes(pendentes)
    return f"Proposta {id_proposta} cancelada." if removida else "Proposta não encontrada."


# ---------------- FASE 2: aplicar (só o que você aprovou) ----------------

@mcp.tool()
def aplicar_alteracoes_aprovadas(ids_aprovados: list[str]) -> str:
    """
    Aplica NO BLING somente as propostas cujos id_proposta estão em
    ids_aprovados. Única ferramenta que escreve. Loga antes/depois.
    """
    pendentes = _ler_pendentes()
    resultados = []
    for pid in ids_aprovados:
        prop = pendentes.get(pid)
        if not prop:
            resultados.append({"id_proposta": pid, "status": "não encontrada"})
            continue
        try:
            if prop["tipo"] == "preco":
                bling.atualizar_preco_produto(prop["produto_id"], prop["preco_proposto"])
                _log_aplicacao({"id_proposta": pid, "tipo": "preco",
                                "produto_id": prop["produto_id"],
                                "antes": prop["preco_atual"],
                                "depois": prop["preco_proposto"],
                                "motivo": prop["motivo"]})
            elif prop["tipo"] == "descricao":
                campos = {k: v["depois"] for k, v in prop["campos"].items()}
                bling.atualizar_campos_produto(prop["produto_id"], campos)
                _log_aplicacao({"id_proposta": pid, "tipo": "descricao",
                                "produto_id": prop["produto_id"],
                                "campos": prop["campos"], "motivo": prop["motivo"]})
            else:
                resultados.append({"id_proposta": pid, "status": "tipo desconhecido"})
                continue
            del pendentes[pid]
            resultados.append({"id_proposta": pid, "status": "APLICADO",
                               "produto_id": prop["produto_id"], "tipo": prop["tipo"]})
        except Exception as e:
            resultados.append({"id_proposta": pid, "status": f"ERRO: {e}"})
    _salvar_pendentes(pendentes)
    return json.dumps(resultados, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
