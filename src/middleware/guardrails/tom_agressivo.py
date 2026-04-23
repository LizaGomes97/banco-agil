"""
Guardrail: Tom Agressivo (input e output)

Detecta linguagem ofensiva ou ameaçadora:
    - No INPUT: mensagem do usuário com tom agressivo direcionado ao banco/assistente
    - No OUTPUT: resposta do LLM com linguagem inadequada (raro, mas possível em edge cases)

Checks:
    MEDIO — palavrões ou ameaças diretas (só loga, não bloqueia o cliente)

Decisão de design: não bloqueamos porque:
    1. O assistente deve responder com calma mesmo a clientes insatisfeitos
    2. Falsos positivos (ex.: "que absurdo essa taxa") seriam prejudiciais
    3. O log serve para análise posterior e melhoria do sistema
"""

from __future__ import annotations

import re

from ._base import GuardrailBase, GuardrailResult, Severidade

# Lista conservadora — apenas termos inequivocamente agressivos
# Evitamos palavrões comuns que aparecem em expressões cotidianas ("puta que pariu")
_RE_MEDIO = re.compile(
    r"\b("
    r"vou\s+(processar|destruir|acabar\s+com)\s+(o\s+)?banco"
    r"|lixo\s+de\s+(banco|atendimento|sistema)"
    r"|incompat[eí]vel\s+com\s+ser\s+humano"
    r"|idiota|imbecil|incompetente"
    r"|v[aã]o\s+se\s+f(oder|erre)"
    r"|cala\s+a?\s+boca"
    r")\b",
    re.IGNORECASE,
)


class TomAgressivoGuardrail(GuardrailBase):
    nome = "tom_agressivo"

    def _check_medio(self, texto: str) -> GuardrailResult:
        if _RE_MEDIO.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.MEDIO,
                motivo="tom agressivo detectado na mensagem",
            )
        return GuardrailResult.ok()

    def run(self, texto: str) -> GuardrailResult:
        return self._check_medio(texto)
