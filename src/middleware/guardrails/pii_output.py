"""
Guardrail: PII Leak na saída (output)

Detecta vazamento de dados pessoais identificáveis (PII) na resposta
que o LLM está prestes a entregar ao cliente.

Checks (ordem de execução: crítico → alto):
    CRITICO — CPF completo ou número de conta explícito na resposta
    ALTO    — data de nascimento completa ou combinação de campos sensíveis
"""

from __future__ import annotations

import re

from ._base import GuardrailBase, GuardrailResult, Severidade

_MSG_BLOQUEIO_CRITICO = (
    "Ocorreu um problema ao processar sua resposta. "
    "Por segurança, entre em contato com nossa central: 0800 000 0000."
)
_MSG_BLOQUEIO_ALTO = (
    "Não consegui completar essa consulta. "
    "Tente novamente ou acesse nossos canais de atendimento."
)

# CRITICO: CPF no formato XXX.XXX.XXX-XX ou 11 dígitos seguidos
_RE_CPF = re.compile(
    r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b"
)

# CRITICO: número de conta bancária (padrão: 5-8 dígitos + dígito verificador)
_RE_CONTA = re.compile(
    r"\bconta\s*n[uú]mero\s*:?\s*\d{4,8}-?\d\b",
    re.IGNORECASE,
)

# ALTO: data de nascimento completa no formato DD/MM/AAAA ou DD-MM-AAAA
_RE_DATA_NASC = re.compile(
    r"\b(0[1-9]|[12]\d|3[01])[\/\-](0[1-9]|1[0-2])[\/\-](19|20)\d{2}\b"
)

# ALTO: agência bancária com 4 dígitos
_RE_AGENCIA = re.compile(
    r"\bag[eê]ncia\s*:?\s*\d{4}\b",
    re.IGNORECASE,
)


class PiiOutputGuardrail(GuardrailBase):
    nome = "pii_output"

    def _check_critico(self, texto: str) -> GuardrailResult:
        if _RE_CPF.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.CRITICO,
                motivo="CPF detectado na resposta do LLM",
                mensagem_cliente=_MSG_BLOQUEIO_CRITICO,
            )
        if _RE_CONTA.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.CRITICO,
                motivo="número de conta detectado na resposta do LLM",
                mensagem_cliente=_MSG_BLOQUEIO_CRITICO,
            )
        return GuardrailResult.ok()

    def _check_alto(self, texto: str) -> GuardrailResult:
        if _RE_DATA_NASC.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.ALTO,
                motivo="data de nascimento completa detectada na resposta",
                mensagem_cliente=_MSG_BLOQUEIO_ALTO,
            )
        if _RE_AGENCIA.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.ALTO,
                motivo="número de agência detectado na resposta",
                mensagem_cliente=_MSG_BLOQUEIO_ALTO,
            )
        return GuardrailResult.ok()

    def run(self, texto: str) -> GuardrailResult:
        for check in (self._check_critico, self._check_alto):
            resultado = check(texto)
            if not resultado.aprovado:
                return resultado
        return GuardrailResult.ok()
