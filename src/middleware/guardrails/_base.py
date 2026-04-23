"""
Base do sistema de guardrails: tipos, contrato de retorno e executor.

Fluxo de execução dentro de cada guardrail:
    crítico → alto → médio  (para no primeiro que reprovar)

Comportamento por severidade (decidido em debate — ver ADR-015):
    CRITICO → bloqueia imediatamente, mensagem fixa, sem LLM
    ALTO    → bloqueia o turno, permite nova tentativa do usuário
    MEDIO   → só registra em log, cliente não vê nada
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class Severidade(str, Enum):
    CRITICO = "CRITICO"
    ALTO = "ALTO"
    MEDIO = "MEDIO"


@dataclass
class GuardrailResult:
    aprovado: bool
    severidade: Optional[Severidade] = None
    motivo: str = ""
    # mensagem exibida ao cliente apenas em CRITICO e ALTO
    mensagem_cliente: Optional[str] = None

    @staticmethod
    def ok() -> "GuardrailResult":
        return GuardrailResult(aprovado=True)


class GuardrailBase(ABC):
    """Contrato que todo guardrail deve implementar."""

    nome: str = "guardrail"

    @abstractmethod
    def run(self, texto: str) -> GuardrailResult:
        """
        Executa os checks internos do mais severo para o menos severo.
        Para no primeiro que reprovar.
        """


class GuardrailRunner:
    """
    Executa uma lista ordenada de guardrails e reage de acordo com
    a severidade do primeiro que reprovar.

    Uso:
        runner = GuardrailRunner(INPUT_GUARDRAILS)
        resultado = runner.executar(texto_usuario)
        if not resultado.aprovado:
            return resultado.mensagem_cliente
    """

    def __init__(self, guardrails: List[GuardrailBase]) -> None:
        self._guardrails = guardrails

    def executar(self, texto: str) -> GuardrailResult:
        for guardrail in self._guardrails:
            resultado = guardrail.run(texto)

            if resultado.aprovado:
                continue

            if resultado.severidade == Severidade.MEDIO:
                # Médio: só loga, não bloqueia, não informa o cliente
                logger.info(
                    "[GUARDRAIL:%s] severidade=MEDIO motivo=%s",
                    guardrail.nome,
                    resultado.motivo,
                )
                continue

            if resultado.severidade == Severidade.ALTO:
                logger.warning(
                    "[GUARDRAIL:%s] severidade=ALTO motivo=%s",
                    guardrail.nome,
                    resultado.motivo,
                )
                return resultado

            if resultado.severidade == Severidade.CRITICO:
                logger.error(
                    "[GUARDRAIL:%s] severidade=CRITICO motivo=%s",
                    guardrail.nome,
                    resultado.motivo,
                )
                return resultado

        return GuardrailResult.ok()
