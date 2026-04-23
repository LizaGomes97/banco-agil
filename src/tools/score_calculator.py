"""Cálculo determinístico do score de crédito.

O LLM nunca realiza este cálculo — ele chama esta tool com os dados
coletados na entrevista. Ver ADR-005 para justificativa detalhada.
"""
from __future__ import annotations

from langchain_core.tools import tool

from src.config import SCORE_MINIMO_APROVACAO

# ── Pesos definidos no desafio técnico ───────────────────────────────────────
_PESO_RENDA_POR_MIL = 30
_PESO_RENDA_MAX = 900

_PESO_EMPREGO = {
    "formal": 300,
    "autônomo": 200,
    "autonomo": 200,   # sem acento
    "desempregado": 0,
}

_PESO_DEPENDENTES = {0: 100, 1: 80, 2: 60}
_PESO_DEPENDENTES_DEFAULT = 30  # 3+

_PESO_DIVIDAS = {"sim": -100, "não": 100, "nao": 100}


@tool
def calcular_score_credito(
    renda_mensal: float,
    tipo_emprego: str,
    num_dependentes: int,
    tem_dividas: str,
) -> dict:
    """Calcula o score de crédito com base nos dados da entrevista financeira.

    Args:
        renda_mensal: Renda mensal em reais (ex: 4000.0)
        tipo_emprego: "formal", "autônomo" ou "desempregado"
        num_dependentes: Número de dependentes (0, 1, 2 ou 3+)
        tem_dividas: "sim" ou "não"

    Returns:
        dict com "score" (int), "aprovado" (bool) e "detalhamento" (dict)
    """
    emprego_key = tipo_emprego.strip().lower()
    dividas_key = tem_dividas.strip().lower()

    pts_renda = min(renda_mensal / 1000 * _PESO_RENDA_POR_MIL, _PESO_RENDA_MAX)
    pts_emprego = _PESO_EMPREGO.get(emprego_key, 0)
    pts_dep = _PESO_DEPENDENTES.get(num_dependentes, _PESO_DEPENDENTES_DEFAULT)
    pts_dividas = _PESO_DIVIDAS.get(dividas_key, 0)

    score = round(pts_renda + pts_emprego + pts_dep + pts_dividas)

    return {
        "score": score,
        "aprovado": score >= SCORE_MINIMO_APROVACAO,
        "detalhamento": {
            "renda": round(pts_renda),
            "emprego": pts_emprego,
            "dependentes": pts_dep,
            "dividas": pts_dividas,
        },
    }


def score_aprovado(score: int) -> bool:
    """Verifica se um score existente é suficiente para aprovação."""
    return score >= SCORE_MINIMO_APROVACAO
