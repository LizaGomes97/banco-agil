"""Provedor de LLM com retry automático e fallback entre modelos.

Padrão adaptado de backend/agent/providers/model_tiers.py.
Garante que erros transitórios (429, timeout, 503) não interrompam o
atendimento — requisito explícito do case: "lidar com erros esperados
de forma controlada, informando o cliente sobre o problema de maneira
clara [...] sem interromper abruptamente a interação".

Tiers configurados:
  fast  → gemini-2.0-flash       (default — rápido e barato)
  pro   → gemini-2.5-pro         (análises mais complexas)
  lite  → gemini-2.0-flash-lite  (fallback final — menor custo)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TEMPERATURE

logger = logging.getLogger(__name__)

_MODELOS: dict[str, str] = {
    "fast": GEMINI_MODEL,                # gemini-2.0-flash (configurável via .env)
    "pro": "gemini-2.5-pro",
    "lite": "gemini-2.0-flash-lite",
}

# Ordem de fallback: se "fast" falhar, tenta "lite"
_FALLBACK: dict[str, str | None] = {
    "fast": "lite",
    "pro": "fast",
    "lite": None,
}

_MAX_TENTATIVAS = 3
_BACKOFF_BASE = 2.0  # segundos — duplica a cada tentativa


def criar_llm(tier: str = "fast", **kwargs: Any) -> ChatGoogleGenerativeAI:
    """Retorna um LLM do tier solicitado com as configurações padrão do projeto."""
    modelo = _MODELOS.get(tier, GEMINI_MODEL)
    return ChatGoogleGenerativeAI(
        model=modelo,
        temperature=kwargs.pop("temperature", LLM_TEMPERATURE),
        google_api_key=GEMINI_API_KEY,
        **kwargs,
    )


def invocar_com_fallback(
    messages: list,
    tier: str = "fast",
    tools: list | None = None,
    **kwargs: Any,
) -> Any:
    """Invoca o LLM com retry exponencial e fallback automático entre tiers.

    Args:
        messages: Lista de mensagens (SystemMessage, HumanMessage, etc.)
        tier: Tier inicial ("fast", "pro", "lite")
        tools: Lista de tools para bind (opcional)
        **kwargs: Argumentos extras para ChatGoogleGenerativeAI

    Returns:
        AIMessage com a resposta do LLM.

    Raises:
        RuntimeError: Se todos os tiers e tentativas falharem.
    """
    tier_atual = tier
    tentativa_global = 0

    while tier_atual is not None:
        modelo = _MODELOS[tier_atual]
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            tentativa_global += 1
            try:
                llm = criar_llm(tier_atual, **kwargs)
                if tools:
                    llm = llm.bind_tools(tools)
                resposta = llm.invoke(messages)
                if tentativa_global > 1:
                    logger.info(
                        "LLM respondeu após %d tentativa(s) — tier=%s modelo=%s",
                        tentativa_global, tier_atual, modelo,
                    )
                return resposta

            except Exception as exc:
                erro_str = str(exc).lower()
                is_rate_limit = "429" in erro_str or "quota" in erro_str or "resource exhausted" in erro_str
                is_transient = "503" in erro_str or "timeout" in erro_str or "unavailable" in erro_str

                if is_rate_limit or is_transient:
                    espera = _BACKOFF_BASE ** tentativa
                    logger.warning(
                        "LLM erro transitório (tier=%s tentativa=%d/%d): %s — aguardando %.1fs",
                        tier_atual, tentativa, _MAX_TENTATIVAS, exc, espera,
                    )
                    if tentativa < _MAX_TENTATIVAS:
                        time.sleep(espera)
                        continue

                logger.error("LLM falhou definitivamente no tier=%s: %s", tier_atual, exc)
                break

        # Esgotou tentativas neste tier — tenta o próximo
        proximo = _FALLBACK.get(tier_atual)
        if proximo:
            logger.warning("Fazendo fallback: %s → %s", tier_atual, proximo)
        tier_atual = proximo

    raise RuntimeError(
        f"Todos os modelos LLM falharam após {tentativa_global} tentativas. "
        "Verifique as chaves de API e a conectividade."
    )
