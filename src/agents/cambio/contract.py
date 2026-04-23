"""Contratos de resposta do Agente de Câmbio.

O câmbio tem uma particularidade: o valor da cotação é externo (API Tavily)
e desconhecido antes da chamada. Por isso o contrato valida a PRESENÇA de um
valor numérico em formato monetário, não um valor fixo pré-definido.
"""
from __future__ import annotations

import re

from src.infrastructure.response_contract import CampoContrato, ResponseContract


class _CampoCotacao(CampoContrato):
    """Campo que valida se a resposta contém algum valor monetário (ex.: R$ 5,12)."""

    def presente_em(self, texto: str) -> bool:
        return bool(re.search(r"R\$\s*[\d.,]+", texto))

    def descricao_corretiva(self) -> str:
        return '"cotacao" = valor em R$ obtido pela ferramenta buscar_cotacao_cambio'


def contrato_cotacao(max_retries: int = 1) -> ResponseContract:
    """Contrato para respostas de cotação de câmbio.

    Garante que a resposta inclui um valor monetário em reais (R$),
    impedindo que o LLM responda sem informar o preço efetivo.
    """
    return ResponseContract(
        campos=[_CampoCotacao(nome="cotacao", valor_esperado=0.0)],
        max_retries=max_retries,
    )


def contrato_resposta_generica() -> ResponseContract:
    """Contrato para respostas genéricas do câmbio (sem cotação).

    Sem validação de valor — apenas garante resposta não vazia.
    Usado quando o cliente faz perguntas que não requerem consulta de preço.
    """
    return ResponseContract(campos=[], max_retries=0)
