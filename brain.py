"""
brain.py — camada de IA "trocável" para o Bling-ApexM.

Isola o provedor de LLM (Claude ou Gemini) atrás de uma interface comum,
para que o resto do projeto NÃO dependa de qual modelo está sendo usado.

A função principal, `suggest_listing_improvements()`, apenas PROPÕE melhorias.
Ela não altera nada no Bling nem no Mercado Livre — quem aplica é outra
camada, depois da sua aprovação (human-in-the-loop).

Requisitos:
    pip install anthropic        # para usar o Claude
    pip install google-genai     # para usar o Gemini   (Python 3.10+)

Chaves de API (defina como variáveis de ambiente, nunca no código):
    ANTHROPIC_API_KEY=...        # console.anthropic.com
    GEMINI_API_KEY=...           # Google AI Studio
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol


# ---------------------------------------------------------------------------
# 1. Interface comum — o "contrato" que qualquer modelo precisa cumprir.
#    A lógica de negócio depende SÓ disto, não de Claude nem de Gemini.
# ---------------------------------------------------------------------------
class LLMProvider(Protocol):
    """Qualquer provedor de IA precisa saber responder a um prompt em texto."""

    def complete(self, system: str, user: str) -> str:
        ...


# ---------------------------------------------------------------------------
# 2. Implementação com Claude (SDK `anthropic`)
# ---------------------------------------------------------------------------
@dataclass
class ClaudeProvider:
    # claude-opus-4-8 (mais capaz) | claude-sonnet-4-6 (equilibrado) |
    # claude-haiku-4-5-20251001 (mais rápido/barato)
    model: str = "claude-sonnet-4-6"
    api_key: str | None = None

    def complete(self, system: str, user: str) -> str:
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key or os.environ["ANTHROPIC_API_KEY"]
        )
        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # A resposta vem em blocos; juntamos os blocos de texto.
        return "".join(b.text for b in message.content if b.type == "text")


# ---------------------------------------------------------------------------
# 3. Implementação com Gemini (SDK `google-genai`)
# ---------------------------------------------------------------------------
@dataclass
class GeminiProvider:
    model: str = "gemini-2.5-flash"
    api_key: str | None = None

    def complete(self, system: str, user: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key or os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",  # pede JSON puro
            ),
        )
        return response.text


# ---------------------------------------------------------------------------
# 4. Lógica de negócio — agnóstica de modelo
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "Você é um especialista em otimização de anúncios de e-commerce no "
    "Mercado Livre. Analise os dados do produto e sugira melhorias de "
    "título e descrição para aumentar a conversão.\n"
    "Responda APENAS com um objeto JSON, sem texto antes ou depois e sem "
    "marcação de código. Use exatamente este formato:\n"
    "{\n"
    '  "titulo_sugerido": "...",\n'
    '  "descricao_sugerida": "...",\n'
    '  "justificativa": "...",\n'
    '  "confianca": 0.0\n'
    "}"
)


def _build_user_prompt(product: dict) -> str:
    return (
        "Dados do produto:\n"
        f"- Título atual: {product.get('titulo', '')}\n"
        f"- Categoria: {product.get('categoria', '')}\n"
        f"- Preço: {product.get('preco', '')}\n"
        f"- Vendas nos últimos 30 dias: {product.get('vendas_30d', '')}\n"
        f"- Taxa de conversão (CVR): {product.get('cvr', '')}\n"
        f"- Descrição atual: {product.get('descricao', '')}\n"
    )


def _parse_json(raw: str) -> dict:
    """Extrai JSON da resposta, tolerando cercas ```json ... ``` que o modelo
    às vezes adiciona mesmo quando pedimos JSON puro."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(cleaned)


def suggest_listing_improvements(product: dict, provider: LLMProvider) -> dict:
    """
    Recebe os dados de um produto e devolve uma SUGESTÃO (dict) para revisão.

    Não altera nada no Bling nem no Mercado Livre — apenas propõe.
    O campo "aprovado" começa em False de propósito: a mudança só deve ser
    aplicada depois que você (ou outra etapa de validação) revisar.
    """
    raw = provider.complete(SYSTEM_PROMPT, _build_user_prompt(product))

    try:
        suggestion = _parse_json(raw)
    except (json.JSONDecodeError, IndexError):
        # Em vez de quebrar, devolve o texto bruto para você inspecionar.
        return {"erro": "resposta não veio em JSON válido", "bruto": raw}

    suggestion["produto_id"] = product.get("id")
    suggestion["aprovado"] = False  # human-in-the-loop: aguarda revisão
    return suggestion


# ---------------------------------------------------------------------------
# 5. Demonstração
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    produto_exemplo = {
        "id": "MLB123",
        "titulo": "Tênis masculino corrida",
        "categoria": "Calçados / Tênis",
        "preco": 199.90,
        "vendas_30d": 4,
        "cvr": 0.8,
        "descricao": "Tênis confortável para corrida.",
    }

    # Trocar de modelo é só trocar esta linha:
    brain: LLMProvider = ClaudeProvider()        # usa o Claude
    # brain: LLMProvider = GeminiProvider()      # ...ou o Gemini

    sugestao = suggest_listing_improvements(produto_exemplo, brain)
    print(json.dumps(sugestao, ensure_ascii=False, indent=2))
