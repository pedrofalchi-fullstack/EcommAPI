"""
bling_client.py
Cliente minimalista para a API v3 do Bling com OAuth 2.0 e refresh
automático de token.

Pré-requisito: você já fez a autorização inicial UMA vez (veja o README)
e tem um arquivo bling_tokens.json com access_token e refresh_token.

Variáveis de ambiente esperadas (.env):
    BLING_CLIENT_ID
    BLING_CLIENT_SECRET
    BLING_SANDBOX=1   # opcional: usa o ambiente de homologação
"""

import os
import json
import base64
import time
import threading
from pathlib import Path

import requests

TOKENS_FILE = Path(os.getenv("BLING_TOKENS_FILE", "bling_tokens.json"))

# --- Rate limiter global (token bucket simples) ---
# O Bling permite 3 req/s e 120k/dia. Ficamos abaixo (2/s) de propósito
# para nunca encostar no bloqueio de pico (600 req em 10s).
_MIN_INTERVALO = 1.0 / float(os.getenv("BLING_REQ_POR_SEG", "2"))
_lock = threading.Lock()
_ultima_chamada = [0.0]


def _throttle() -> None:
    with _lock:
        agora = time.monotonic()
        espera = _MIN_INTERVALO - (agora - _ultima_chamada[0])
        if espera > 0:
            time.sleep(espera)
        _ultima_chamada[0] = time.monotonic()

# Ambiente de homologação (sandbox) vs. produção.
# COMECE SEMPRE no sandbox até confiar no fluxo.
_SANDBOX = os.getenv("BLING_SANDBOX", "0") == "1"
BASE_URL = (
    "https://api.bling.com.br/Api/v3/homologacao"
    if _SANDBOX
    else "https://api.bling.com.br/Api/v3"
)
TOKEN_URL = "https://api.bling.com.br/Api/v3/oauth/token"


class BlingError(Exception):
    pass


def _load_tokens() -> dict:
    if not TOKENS_FILE.exists():
        raise BlingError(
            f"Arquivo {TOKENS_FILE} não encontrado. "
            "Faça a autorização inicial primeiro (veja o README)."
        )
    return json.loads(TOKENS_FILE.read_text())


def _save_tokens(tokens: dict) -> None:
    tokens["_salvo_em"] = int(time.time())
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2, ensure_ascii=False))


def _basic_auth_header() -> str:
    cid = os.environ["BLING_CLIENT_ID"]
    secret = os.environ["BLING_CLIENT_SECRET"]
    raw = f"{cid}:{secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _refresh_token() -> dict:
    """Renova o access_token usando o refresh_token."""
    tokens = _load_tokens()
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise BlingError(f"Falha ao renovar token: {resp.status_code} {resp.text}")
    novo = resp.json()
    # O Bling devolve novos access_token e refresh_token; guarde os dois.
    _save_tokens(novo)
    return novo


def _request(method: str, path: str, *, params=None, body=None,
             _auth_retry=True, _tentativa=0) -> dict:
    """
    Requisição autenticada com:
      - throttle global (respeita o limite de req/s do Bling)
      - refresh de token automático em 401
      - retry com backoff exponencial em 429 (rate limit) e 5xx
    """
    _throttle()
    tokens = _load_tokens()
    url = f"{BASE_URL}{path}"
    resp = requests.request(
        method, url,
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params=params, json=body, timeout=30,
    )

    if resp.status_code == 401 and _auth_retry:
        _refresh_token()
        return _request(method, path, params=params, body=body,
                        _auth_retry=False, _tentativa=_tentativa)

    # 429 = estourou rate limit; 5xx = erro temporário do servidor.
    if resp.status_code in (425, 429) or resp.status_code >= 500:
        if _tentativa < 5:
            espera = min(2 ** _tentativa, 30)  # 1, 2, 4, 8, 16, 30s
            time.sleep(espera)
            return _request(method, path, params=params, body=body,
                            _auth_retry=_auth_retry, _tentativa=_tentativa + 1)

    if resp.status_code >= 400:
        raise BlingError(f"{method} {path} -> {resp.status_code}: {resp.text}")

    if resp.text.strip():
        return resp.json()
    return {}


# ---- Operações de alto nível usadas pelo servidor MCP ----

def get_produtos(pagina: int = 1, limite: int = 50, criterio: int | None = None) -> dict:
    params = {"pagina": pagina, "limite": limite}
    if criterio is not None:
        params["criterio"] = criterio
    return _request("GET", "/produtos", params=params)


def get_produto(produto_id: int) -> dict:
    return _request("GET", f"/produtos/{produto_id}")


def get_vendas(data_inicial: str, data_final: str, pagina: int = 1, limite: int = 100) -> dict:
    params = {
        "dataInicial": data_inicial,  # formato YYYY-MM-DD
        "dataFinal": data_final,
        "pagina": pagina,
        "limite": limite,
    }
    return _request("GET", "/pedidos/vendas", params=params)


def get_venda(pedido_id: int) -> dict:
    """Detalhe de um pedido (inclui os itens, que a listagem nem sempre traz)."""
    return _request("GET", f"/pedidos/vendas/{pedido_id}")


def atualizar_campos_produto(produto_id: int, campos: dict) -> dict:
    """
    Lê o produto inteiro, sobrescreve APENAS os campos informados e reenvia
    via PUT. Isso evita zerar os demais campos (o PUT do Bling espera o
    recurso completo). `campos` ex.: {"preco": 99.9} ou {"nome": "..."}.
    """
    atual = get_produto(produto_id)
    dados = atual.get("data", atual)  # a API costuma embrulhar em "data"
    if not isinstance(dados, dict) or "id" not in dados:
        raise BlingError(f"Produto {produto_id} não retornou dados válidos.")
    dados.update(campos)
    return _request("PUT", f"/produtos/{produto_id}", body=dados)


def atualizar_preco_produto(produto_id: int, novo_preco: float) -> dict:
    """Atalho: atualiza só o preço."""
    return atualizar_campos_produto(produto_id, {"preco": round(float(novo_preco), 2)})


# ---- Endpoints usados pelo worker de sincronização ----

def get_depositos() -> dict:
    """Lista os depósitos de estoque (você precisa do id do depósito)."""
    return _request("GET", "/depositos")


def buscar_produto_por_codigo(codigo: str) -> dict | None:
    """
    Procura um produto pelo SKU (campo `codigo`). Retorna o dict do produto
    ou None se não existir. É assim que mapeamos SKU do fornecedor -> Bling.
    """
    resp = _request("GET", "/produtos", params={"codigo": codigo, "limite": 1})
    itens = resp.get("data", [])
    return itens[0] if itens else None


def definir_estoque(produto_id: int, deposito_id: int, saldo: float) -> dict:
    """
    SETA o saldo absoluto de estoque via operação de balanço ("B").
    No Bling v3 estoque é movimentação de depósito, não campo do produto.
    """
    body = {
        "produto": {"id": produto_id},
        "deposito": {"id": deposito_id},
        "operacao": "B",  # B = balanço (define o saldo absoluto)
        "quantidade": round(float(saldo), 2),
        "observacoes": "Sincronização automática do fornecedor",
    }
    return _request("POST", "/estoques", body=body)


def criar_produto(dados: dict) -> dict:
    """
    Cria um produto. `dados` deve seguir o schema do Bling, ex.:
    {"nome": "...", "codigo": "SKU123", "preco": 99.9, "tipo": "P",
     "formato": "S", "situacao": "A"}
    """
    return _request("POST", "/produtos", body=dados)


def alterar_situacao(produto_id: int, ativo: bool) -> dict:
    """Ativa/inativa um produto (PATCH na situação). 'A' = ativo, 'I' = inativo."""
    return _request("PATCH", f"/produtos/{produto_id}/situacoes",
                    body={"situacao": "A" if ativo else "I"})
