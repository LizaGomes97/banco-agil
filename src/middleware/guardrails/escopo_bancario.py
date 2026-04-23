"""
Guardrail: Escopo Bancário (input)

Detecta perguntas claramente fora do domínio do Banco Ágil.

Checks (ordem de execução: alto → médio):
    ALTO  — tópicos inequivocamente fora do escopo (saúde, código, política)
    MEDIO — tópicos ambíguos que podem tangenciar finanças mas não são bancários
"""

from __future__ import annotations

import re

from ._base import GuardrailBase, GuardrailResult, Severidade

_MSG_BLOQUEIO_ALTO = (
    "Só consigo ajudar com assuntos relacionados ao Banco Ágil, "
    "como conta, cartão, crédito e câmbio. "
    "Como posso ajudar com sua conta hoje?"
)


# ALTO: tópicos nitidamente fora do escopo financeiro/bancário
_RE_ALTO = re.compile(
    r"\b("
    # Saúde
    r"diagn[oó]stico\s+m[eé]dico|remdio|rem[eé]dio|sintoma|doen[cç]a|hospital"
    r"|prescri[cç][aã]o\s+m[eé]dica|consulta\s+m[eé]dica"
    # Programação fora de contexto
    r"|escreva\s+(um\s+)?c[oó]digo|me\s+d[eê]\s+(um\s+)?script"
    r"|programe\s+(um\s+|uma\s+)?fun[cç][aã]o|fa[cç]a\s+(um\s+)?algoritmo"
    # Política / religião
    r"|partido\s+pol[ií]tico|voto\s+(em|no|na)|religi[aã]o|deus\s+existe"
    # Entretenimento / conteúdo adulto
    r"|escreva\s+(uma\s+)?hist[oó]ria\s+de\s+amor|conte[uú]do\s+adulto"
    r"|filme\s+para\s+(baixar|ver\s+de\s+gra[cç]a)"
    r")\b",
    re.IGNORECASE,
)

# MEDIO: tópicos financeiros que não são bancários (cripto, bolsa pessoal)
_RE_MEDIO = re.compile(
    r"\b("
    r"bitcoin|ethereum|cripto(moeda)?|nft"
    r"|a[cç][aõ]es\s+da\s+bolsa|comprar\s+a[cç][oõ]es"
    r"|imposto\s+de\s+renda|declara[cç][aã]o\s+(do\s+)?ir"
    r"|financiamento\s+imobili[aá]rio\s+(de\s+outro\s+banco|fora)"
    r")\b",
    re.IGNORECASE,
)


class EscopoBancarioGuardrail(GuardrailBase):
    nome = "escopo_bancario"

    def _check_alto(self, texto: str) -> GuardrailResult:
        if _RE_ALTO.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.ALTO,
                motivo="tópico fora do escopo bancário detectado",
                mensagem_cliente=_MSG_BLOQUEIO_ALTO,
            )
        return GuardrailResult.ok()

    def _check_medio(self, texto: str) -> GuardrailResult:
        if _RE_MEDIO.search(texto):
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.MEDIO,
                motivo="tópico financeiro fora do portfólio do banco (cripto, bolsa, IR)",
            )
        return GuardrailResult.ok()

    def run(self, texto: str) -> GuardrailResult:
        for check in (self._check_alto, self._check_medio):
            resultado = check(texto)
            if not resultado.aprovado:
                return resultado
        return GuardrailResult.ok()
