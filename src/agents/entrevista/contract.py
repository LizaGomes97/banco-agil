"""Contratos de resposta do Agente de Entrevista de Crédito.

A entrevista coleta dados financeiros e recalcula o score.
O contrato valida que o score novo aparece na resposta final,
garantindo que o cliente seja informado do resultado correto.
"""
from __future__ import annotations

from src.infrastructure.response_contract import (
    CampoContrato,
    ResponseContract,
    contrato_score,
    corrigir_com_dados,
)


def contrato_resultado_entrevista(novo_score: int, max_retries: int = 1) -> ResponseContract:
    """Contrato para a resposta final após o cálculo do score.

    Garante que o LLM informe o valor exato do novo score ao cliente,
    sem arredondar ou substituir por um valor diferente.

    Campos obrigatórios:
        - score: novo valor calculado por calcular_score_credito
    """
    return contrato_score(score=novo_score, max_retries=max_retries)


def contrato_coleta_dados() -> ResponseContract:
    """Contrato para perguntas de coleta de dados (renda, emprego, etc.).

    Durante a entrevista não há valores financeiros a validar —
    o contrato apenas garante que a resposta não está vazia.
    """
    return ResponseContract(campos=[], max_retries=0)


def corrigir_resposta_score(resposta: str, faltando: list[CampoContrato], novo_score: int) -> str:
    """Injeta o score correto na resposta quando o LLM não o incluiu."""
    cliente_simulado = {"score": novo_score, "limite_credito": 0.0}
    return corrigir_com_dados(resposta, faltando, cliente_simulado)
