"""
sync_worker.py
O coração do serviço 24/7. A cada ciclo:
  1. baixa o catálogo do fornecedor (1 download)
  2. compara com o estado local (diff)
  3. aplica AUTOMÁTICO: estoque, criação de novos, desativação sem estoque
  4. PREÇO: cria proposta na fila de aprovação (não aplica direto)

Rodar:
    pip install requests python-dotenv apscheduler
    python sync_worker.py            # roda em loop, para sempre
    python sync_worker.py --once     # roda um ciclo só (para testar)
"""

import os
import sys
import json
import time
import uuid
import logging
from pathlib import Path

from dotenv import load_dotenv

import bling_client as bling
import state
from supplier_client import MeuFornecedorClient

load_dotenv()

# ---- configuração ----
DEPOSITO_ID = int(os.environ["BLING_DEPOSITO_ID"])      # GET /depositos para descobrir
INTERVALO_MIN = float(os.getenv("SYNC_INTERVALO_MIN", "10"))
AUTO_CRIAR = os.getenv("SYNC_AUTO_CRIAR", "1") == "1"
DESATIVAR_SEM_ESTOQUE = os.getenv("SYNC_DESATIVAR_SEM_ESTOQUE", "1") == "1"
MAX_VARIACAO_PCT = float(os.getenv("MAX_VARIACAO_PCT", "30"))

DATA_DIR = Path(os.getenv("BLING_DATA_DIR", "."))
PENDENTES_FILE = DATA_DIR / "pending_changes.json"      # mesma fila do server.py MCP
HEARTBEAT_FILE = DATA_DIR / "heartbeat.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(DATA_DIR / "sync.log", encoding="utf-8")],
)
log = logging.getLogger("sync")


# ---- fila de aprovação de preço (compatível com server.py) ----

def _propor_preco(produto_id, nome, preco_atual, preco_novo, variacao):
    pendentes = json.loads(PENDENTES_FILE.read_text()) if PENDENTES_FILE.exists() else {}
    pid = str(uuid.uuid4())[:8]
    pendentes[pid] = {
        "id_proposta": pid, "tipo": "preco", "produto_id": produto_id,
        "nome": nome, "preco_atual": preco_atual, "preco_proposto": preco_novo,
        "variacao_pct": variacao, "motivo": "Mudança de preço no fornecedor",
        "criado_em": int(time.time()),
    }
    PENDENTES_FILE.write_text(json.dumps(pendentes, indent=2, ensure_ascii=False))


# ---- processamento de um produto ----

def _resolver_bling_id(sku, est) -> int | None:
    if est and est.get("bling_id"):
        return est["bling_id"]
    encontrado = bling.buscar_produto_por_codigo(sku)
    if encontrado:
        return encontrado["id"]
    return None


def _criar_no_bling(p) -> int | None:
    payload = {
        "nome": p.nome, "codigo": p.sku, "preco": round(p.preco, 2),
        "tipo": "P", "formato": "S", "situacao": "A",
    }
    if p.gtin:
        payload["gtin"] = p.gtin
    resp = bling.criar_produto(payload)
    novo_id = (resp.get("data") or {}).get("id")
    if novo_id:
        log.info("Produto criado no Bling: %s (id %s)", p.sku, novo_id)
    return novo_id


def _processar(p, contadores) -> None:
    est = state.get_estado(p.sku)
    bling_id = _resolver_bling_id(p.sku, est)

    # --- produto novo ---
    if bling_id is None:
        if not AUTO_CRIAR:
            log.info("SKU novo %s — criação desativada, ignorando.", p.sku)
            return
        bling_id = _criar_no_bling(p)
        if bling_id is None:
            log.warning("Falha ao criar SKU %s.", p.sku)
            return
        contadores["criados"] += 1
        state.upsert_estado(p.sku, bling_id=bling_id, estoque=None, preco=p.preco, ativo=1)
        est = state.get_estado(p.sku)

    # --- estoque (automático) ---
    estoque_anterior = est.get("estoque") if est else None
    if estoque_anterior != p.estoque:
        bling.definir_estoque(bling_id, DEPOSITO_ID, p.estoque)
        state.upsert_estado(p.sku, bling_id=bling_id, estoque=p.estoque)
        contadores["estoque"] += 1

    # --- desativar / reativar conforme estoque ---
    if DESATIVAR_SEM_ESTOQUE:
        ativo_atual = (est or {}).get("ativo", 1)
        if p.estoque <= 0 and ativo_atual:
            bling.alterar_situacao(bling_id, ativo=False)
            state.upsert_estado(p.sku, bling_id=bling_id, ativo=0)
            contadores["desativados"] += 1
        elif p.estoque > 0 and not ativo_atual:
            bling.alterar_situacao(bling_id, ativo=True)
            state.upsert_estado(p.sku, bling_id=bling_id, ativo=1)
            contadores["reativados"] += 1

    # --- preço (com aprovação: vira proposta, não aplica) ---
    preco_anterior = est.get("preco") if est else None
    if preco_anterior is not None and abs(preco_anterior - p.preco) > 0.001:
        variacao = round((p.preco - preco_anterior) / preco_anterior * 100, 2) if preco_anterior else None
        _propor_preco(bling_id, p.nome, preco_anterior, round(p.preco, 2), variacao)
        # atualiza o estado para não propor o mesmo preço de novo a cada ciclo
        state.upsert_estado(p.sku, bling_id=bling_id, preco=p.preco)
        contadores["preco_propostos"] += 1
    elif preco_anterior is None:
        state.upsert_estado(p.sku, bling_id=bling_id, preco=p.preco)


# ---- ciclo completo ----

def run_cycle() -> None:
    contadores = {"estoque": 0, "criados": 0, "desativados": 0,
                  "reativados": 0, "preco_propostos": 0, "erros": 0}
    fornecedor = MeuFornecedorClient()
    catalogo = fornecedor.listar_catalogo()
    log.info("Catálogo do fornecedor: %d SKUs.", len(catalogo))

    for p in catalogo:
        try:
            _processar(p, contadores)
        except Exception as e:
            contadores["erros"] += 1
            log.error("Erro no SKU %s: %s", p.sku, e)

    HEARTBEAT_FILE.write_text(str(int(time.time())))
    log.info("Ciclo concluído: %s", contadores)
    # TODO: se contadores['erros'] > limite, dispare um alerta (Telegram/e-mail).


def main():
    state.init_db()
    if "--once" in sys.argv:
        run_cycle()
        return
    log.info("Worker iniciado. Ciclo a cada %s min.", INTERVALO_MIN)
    while True:
        try:
            run_cycle()
        except Exception as e:
            log.exception("Falha no ciclo: %s", e)
        time.sleep(INTERVALO_MIN * 60)


if __name__ == "__main__":
    main()
