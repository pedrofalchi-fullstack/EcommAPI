"""
supplier_client.py
A "ponte" com o seu fornecedor. O resto do sistema NÃO conhece os detalhes
do seu fornecedor — só conhece o formato normalizado `ProdutoFornecedor`.

>>> ESTE É O ÚNICO ARQUIVO QUE VOCÊ PRECISA ADAPTAR AO SEU FORNECEDOR <<<

Preencha o método `listar_catalogo()` da classe MeuFornecedorClient com as
chamadas HTTP reais da API do seu fornecedor, convertendo a resposta dele
para uma lista de ProdutoFornecedor. O resto funciona sozinho.
"""

import os
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

import requests


@dataclass
class ProdutoFornecedor:
    """Formato NORMALIZADO. Todo fornecedor é traduzido para isto."""
    sku: str                      # identificador único (mapeia com `codigo` no Bling)
    nome: str
    preco: float                  # preço de VENDA sugerido (ou seu custo + markup)
    estoque: float
    gtin: str | None = None       # EAN/código de barras, se houver
    descricao: str | None = None
    extra: dict = field(default_factory=dict)  # qualquer campo a mais


class SupplierClient(ABC):
    """Interface. Qualquer fornecedor implementa isto."""

    @abstractmethod
    def listar_catalogo(self) -> list[ProdutoFornecedor]:
        """Retorna o catálogo inteiro já normalizado."""
        ...


class MeuFornecedorClient(SupplierClient):
    """
    >>> ADAPTE AQUI <<<
    Implementação concreta do SEU fornecedor.
    """

    def __init__(self):
        self.base_url = os.environ["FORNECEDOR_BASE_URL"]   # ex.: https://api.fornecedor.com
        self.api_key = os.getenv("FORNECEDOR_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    def listar_catalogo(self) -> list[ProdutoFornecedor]:
        produtos: list[ProdutoFornecedor] = []
        pagina = 1
        while True:
            # ---------------------------------------------------------------
            # TODO: troque pelo endpoint REAL do seu fornecedor.
            # Ajuste a URL, os parâmetros de paginação e o markup de preço.
            resp = self.session.get(
                f"{self.base_url}/produtos",
                params={"page": pagina, "per_page": 100},
                timeout=30,
            )
            resp.raise_for_status()
            dados = resp.json()
            itens = dados.get("data", dados)  # ajuste conforme a resposta dele
            if not itens:
                break

            for item in itens:
                # TODO: mapeie os NOMES DE CAMPO do seu fornecedor para o schema.
                produtos.append(ProdutoFornecedor(
                    sku=str(item["sku"]),
                    nome=item["nome"],
                    preco=float(item["preco"]),     # aplique seu markup aqui se quiser
                    estoque=float(item["estoque"]),
                    gtin=item.get("ean"),
                    descricao=item.get("descricao"),
                ))

            # TODO: ajuste a condição de parada conforme a paginação dele.
            if len(itens) < 100:
                break
            pagina += 1
            # ---------------------------------------------------------------

        return produtos
