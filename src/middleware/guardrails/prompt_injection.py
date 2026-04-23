"""
Guardrail: Prompt Injection (input)

Detecta tentativas de manipular o comportamento do LLM via input do usuário.

Checks (ordem de execução: crítico → alto → médio):
    CRITICO — padrões clássicos de jailbreak direto
    ALTO    — tentativas de redefinir identidade/papel do assistente
    MEDIO   — padrões suspeitos mas ambíguos (podem ser inocentes)
"""

from __future__ import annotations

import re

from ._base import GuardrailBase, GuardrailResult, Severidade

_MSG_BLOQUEIO_CRITICO = (
    "Não consigo processar essa solicitação. "
    "Se precisar de ajuda, entre em contato com nossa central de atendimento."
)
_MSG_BLOQUEIO_ALTO = (
    "Não entendi bem o que você quis dizer. "
    "Pode reformular sua dúvida sobre sua conta ou produtos do Banco Ágil?"
)

# CRITICO: comandos explícitos para ignorar instruções ou sair do contexto
_RE_CRITICO = re.compile(
    r"(ignore\s+(all\s+)?(previous\s+)?instructions?"
    r"|ignore\s+suas\s+instru[cç][oõ]es"
    r"|esquece?\s+(tudo|suas\s+regras)"
    r"|desative?\s+(suas\s+)?restri[cç][oõ]es"
    r"|bypass\s+(your\s+)?(safety|filter|guardrail)"
    r"|jailbreak"
    r"|dan\s+mode"
    r"|you\s+are\s+now\s+free)",
    re.IGNORECASE,
)

# ALTO: tentativas de redefinir o papel/identidade do assistente
_RE_ALTO = re.compile(
    r"(act\s+as\s+(a\s+)?(different|new|another)"
    r"|finja\s+que\s+(você\s+é|vc\s+é)"
    r"|pretend\s+you\s+are"
    r"|roleplay\s+as"
    r"|from\s+now\s+on\s+(you\s+are|act)"
    r"|a\s+partir\s+de\s+agora\s+você\s+é"
    r"|seu\s+novo\s+papel\s+é"
    r"|esqueça\s+que\s+é\s+(um\s+)?assistente)",
    re.IGNORECASE,
)

# MEDIO: padrões suspeitos — podem ser inofensivos mas merecem log
_RE_MEDIO = re.compile(
    r"(system\s*prompt"
    r"|prompt\s+original"
    r"|suas\s+instru[cç][oõ]es\s+internas"
    r"|o\s+que\s+você\s+foi\s+programado"
    r"|mostre\s+(suas\s+)?instru[cç][oõ]es"
    r"|repita\s+o\s+(seu\s+)?prompt)",
    re.IGNORECASE,
)


class PromptInjectionGuardrail(GuardrailBase):
    nome = "prompt_injection"

    def _check_critico(self, texto: str) -> GuardrailResult:
        if _RE_CRITICO.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.CRITICO,
                motivo="padrão de jailbreak direto detectado",
                mensagem_cliente=_MSG_BLOQUEIO_CRITICO,
            )
        return GuardrailResult.ok()

    def _check_alto(self, texto: str) -> GuardrailResult:
        if _RE_ALTO.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.ALTO,
                motivo="tentativa de redefinir identidade do assistente",
                mensagem_cliente=_MSG_BLOQUEIO_ALTO,
            )
        return GuardrailResult.ok()

    def _check_medio(self, texto: str) -> GuardrailResult:
        if _RE_MEDIO.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.MEDIO,
                motivo="consulta suspeita sobre instruções internas (pode ser inocente)",
            )
        return GuardrailResult.ok()

    def run(self, texto: str) -> GuardrailResult:
        for check in (self._check_critico, self._check_alto, self._check_medio):
            resultado = check(texto)
            if not resultado.aprovado:
                return resultado
        return GuardrailResult.ok()
