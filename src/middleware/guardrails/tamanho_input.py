"""
Guardrail: Tamanho do Input (input)

Detecta mensagens anormalmente longas que podem indicar tentativas de
sobrecarga do contexto do LLM (context stuffing) ou envio acidental de
documentos inteiros pelo usuário.

Checks:
    MEDIO — input acima do limite configurado (padrão: 2.000 caracteres)

Nota: limite definido com margem para acomodar CPF + data + texto normal.
      Uma pergunta bancária legítima raramente passa de 500 caracteres.
"""

from __future__ import annotations

from ._base import GuardrailBase, GuardrailResult, Severidade

LIMITE_CARACTERES: int = 2_000


class TamanhoInputGuardrail(GuardrailBase):
    nome = "tamanho_input"

    def __init__(self, limite: int = LIMITE_CARACTERES) -> None:
        self._limite = limite

    def _check_medio(self, texto: str) -> GuardrailResult:
        if len(texto) > self._limite:
            return GuardrailResult(
                aprovado=False,
                severidade=Severidade.MEDIO,
                motivo=f"input com {len(texto)} caracteres (limite: {self._limite})",
            )
        return GuardrailResult.ok()

    def run(self, texto: str) -> GuardrailResult:
        return self._check_medio(texto)
