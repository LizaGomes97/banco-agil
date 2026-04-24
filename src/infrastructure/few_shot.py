"""Few-shot dinâmico — adaptador fino sobre `learned_memory`.

Historicamente (ADR-021) este módulo buscava pares pergunta+resposta curados em
`banco_agil_interacoes_curadas`. Com o ADR-023 a arquitetura de memória mudou:
agora buscamos **templates** (esqueletos com placeholders) em
`banco_agil_learned_templates`. A API pública foi preservada para não exigir
mudança nos agentes.

Interface mantida:
  - buscar_exemplos_curados(mensagem, intent, top_k) -> list[str]
  - formatar_exemplos_para_prompt(exemplos) -> str
"""
from __future__ import annotations

import logging

from src.infrastructure.learned_memory import buscar_templates_formatados

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 2  # templates são densos — 1-2 basta


def buscar_exemplos_curados(
    mensagem_usuario: str,
    intent: str | None = None,
    top_k: int = _DEFAULT_TOP_K,
) -> list[str]:
    """Busca templates similares formatados. Compatível com o uso existente nos agents."""
    if not mensagem_usuario or not mensagem_usuario.strip():
        return []
    try:
        resultados = buscar_templates_formatados(
            mensagem_usuario.strip(), intent=intent, k=top_k,
        )
        if resultados:
            logger.debug(
                "few_shot: %d templates para intent=%s query=%.60s",
                len(resultados), intent, mensagem_usuario,
            )
        return resultados
    except Exception:
        logger.exception("Falha inesperada no few_shot (ignorando)")
        return []


def formatar_exemplos_para_prompt(exemplos: list[str]) -> str:
    """Formata os templates como seção do system prompt."""
    if not exemplos:
        return ""
    partes = ["\n\n## Padrões de resposta curados (memória destilada)"]
    partes.append(
        "Use estes padrões como referência de ESTRUTURA e TOM. "
        "Os placeholders (`{nome}`) devem ser preenchidos com valores obtidos via tool "
        "no turno atual — NUNCA invente valor e NUNCA copie número de exemplo."
    )
    for i, ex in enumerate(exemplos, 1):
        partes.append(f"\n### Padrão {i}\n{ex}")
    return "\n".join(partes)
