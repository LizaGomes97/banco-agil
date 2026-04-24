"""Tool de cotação de câmbio via Tavily Search.

Integração nativa com LangGraph via TavilySearch.
Ver ADR-006 para justificativa da escolha.
"""
from __future__ import annotations

import os

from src.config import TAVILY_API_KEY

os.environ.setdefault("TAVILY_API_KEY", TAVILY_API_KEY)


def criar_tool_cambio():
    """Retorna a tool de busca de câmbio configurada."""
    try:
        from langchain_tavily import TavilySearch
        return TavilySearch(
            max_results=1,
            name="buscar_cotacao_cambio",
            description=(
                "Busca a cotação atual de moedas estrangeiras em tempo real. "
                "Use quando o cliente solicitar o valor de qualquer moeda estrangeira. "
                "Formule a query no padrão 'SIGLA BRL exchange rate today', por exemplo: "
                "'USD BRL exchange rate today' para dólar, "
                "'EUR BRL exchange rate today' para euro, "
                "'GBP BRL exchange rate' para libra, "
                "'100 JPY to BRL exchange rate' para iene (usar 100 unidades), "
                "'CAD BRL exchange rate' para dólar canadense."
            ),
        )
    except ImportError:
        from langchain_community.tools.tavily_search import TavilySearchResults
        return TavilySearchResults(
            max_results=1,
            name="buscar_cotacao_cambio",
            description=(
                "Busca a cotação atual de moedas estrangeiras em tempo real. "
                "Use quando o cliente solicitar o valor de qualquer moeda estrangeira. "
                "Formule a query no padrão 'SIGLA BRL exchange rate today', por exemplo: "
                "'USD BRL exchange rate today' para dólar, "
                "'GBP BRL exchange rate' para libra, "
                "'100 JPY to BRL exchange rate' para iene."
            ),
        )
