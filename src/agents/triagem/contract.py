"""Contratos de resposta do Agente de Triagem.

Define quais campos uma resposta da triagem deve obrigatoriamente conter,
de acordo com o tipo de consulta sendo respondida.
"""
from __future__ import annotations

from src.infrastructure.response_contract import (
    CampoContrato,
    ResponseContract,
    contrato_financeiro,
    corrigir_com_dados,
)


def contrato_consulta_financeira(cliente: dict, max_retries: int = 1) -> ResponseContract:
    """Contrato para respostas que incluem dados financeiros (saldo, limite, score).

    Garante que o LLM use os valores exatos do estado, não valores alucinados.

    Campos obrigatórios:
        - limite_credito: valor exato do limite do cliente
        - score:          pontuação exata de crédito
    """
    return contrato_financeiro(
        limite=float(cliente.get("limite_credito", 0)),
        score=int(cliente.get("score", 0)),
        max_retries=max_retries,
    )


def contrato_autenticacao_falha() -> ResponseContract:
    """Contrato para mensagens de falha de autenticação.

    Não valida valores financeiros (cliente não autenticado),
    apenas garante que a resposta não está vazia.
    """
    return ResponseContract(campos=[], max_retries=0)


def corrigir_resposta(resposta: str, faltando: list[CampoContrato], cliente: dict) -> str:
    """Corrige programaticamente a resposta quando o contrato não é satisfeito."""
    return corrigir_com_dados(resposta, faltando, cliente)
