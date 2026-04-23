"""Contratos de resposta do Agente de Crédito.

Define contratos para as duas fases do pipeline Flash→Pro:
  - Flash direto: respostas simples de consulta de limite
  - Pro síntese: decisão final de elegibilidade/aprovação
"""
from __future__ import annotations

from src.infrastructure.response_contract import (
    CampoContrato,
    ResponseContract,
    contrato_financeiro,
    corrigir_com_dados,
)


def contrato_flash_direto(cliente: dict, max_retries: int = 1) -> ResponseContract:
    """Contrato para respostas diretas do Flash (sem tool calls).

    Aplica-se quando o cliente faz perguntas simples sobre limite ou score
    e o Flash responde sem acionar ferramentas.

    Campos obrigatórios:
        - limite_credito: valor exato do limite atual
        - score:          pontuação exata de crédito
    """
    return contrato_financeiro(
        limite=float(cliente.get("limite_credito", 0)),
        score=int(cliente.get("score", 0)),
        max_retries=max_retries,
    )


def contrato_sintese_pro(cliente: dict, max_retries: int = 1) -> ResponseContract:
    """Contrato para a síntese do Pro após execução das tools.

    O Pro deve comunicar a decisão (aprovado/reprovado) e mencionar
    os valores de limite e score relevantes para o cliente.

    Campos obrigatórios:
        - limite_credito: valor de referência na comunicação da decisão
        - score:          score usado na análise de elegibilidade
    """
    return contrato_financeiro(
        limite=float(cliente.get("limite_credito", 0)),
        score=int(cliente.get("score", 0)),
        max_retries=max_retries,
    )


def corrigir_resposta(resposta: str, faltando: list[CampoContrato], cliente: dict) -> str:
    """Corrige programaticamente a resposta quando o contrato não é satisfeito."""
    return corrigir_com_dados(resposta, faltando, cliente)
