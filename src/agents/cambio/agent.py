"""Agente de Câmbio — cotação de moedas em tempo real via Tavily.

A tool call é executada inline neste nó: o LLM chama a tool, a tool
executa, o resultado é injetado no histórico e o LLM responde com o
valor final. O router nunca vê uma AIMessage com tool_calls pendentes.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.infrastructure.model_provider import criar_llm, invocar_com_fallback
from src.models.state import BancoAgilState
from src.tools.exchange_rate import criar_tool_cambio

from .contract import contrato_cotacao

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_tool_cambio = criar_tool_cambio()
_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo"}
_INTENCOES_CREDITO = {"crédito", "credito", "limite", "aumento"}

_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|encaminh)",
    re.IGNORECASE,
)


def no_cambio(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Câmbio.

    Executa o ciclo completo de tool calling em um único turno:
    1. LLM decide chamar a tool de câmbio
    2. Tool executa e retorna o resultado
    3. LLM recebe o resultado e formula a resposta final
    O router só vê a AIMessage final (sem tool_calls pendentes).
    """
    llm = criar_llm().bind_tools([_tool_cambio])

    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    ultima_msg_lower = ultima_msg.lower()

    if any(p in ultima_msg_lower for p in _INTENCOES_ENCERRAR):
        return {"encerrado": True, "resposta_final": None}

    if any(p in ultima_msg_lower for p in _INTENCOES_CREDITO):
        return {"agente_ativo": "credito", "resposta_final": None}

    nome = cliente.get("nome", "Cliente").split()[0]
    contexto = f"\n\n## Cliente: {cliente.get('nome', 'Cliente')}"
    memorias = state.get("memoria_cliente") or []
    if memorias:
        contexto += "\n\n## Interações anteriores\n" + "\n".join(f"- {m}" for m in memorias)

    messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + list(state["messages"])

    # ── 1ª chamada: LLM decide se precisa da tool ────────────────────────────
    try:
        resposta_inicial = llm.invoke(messages)
    except Exception as exc:
        logger.error("[CAMBIO] Falha na 1ª chamada LLM: %s", exc)
        fallback = f"{nome}, qual moeda você gostaria de consultar?"
        return {"messages": [AIMessage(content=fallback)], "resposta_final": fallback}

    # ── Sem tool call: resposta direta ───────────────────────────────────────
    if not getattr(resposta_inicial, "tool_calls", None):
        texto = (resposta_inicial.content or "").strip()
        if _RE_HANDOFF.search(texto):
            logger.warning("[CAMBIO] Handoff detectado — descartado: %.100s", texto)
            texto = f"{nome}, qual moeda você gostaria de consultar? Posso verificar dólar, euro, libra e outras."
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}
        return {"messages": [resposta_inicial], "resposta_final": texto}

    # ── Com tool call: executar inline e re-invocar ──────────────────────────
    mensagens_com_tool = messages + [resposta_inicial]
    tool_messages = []

    for tc in resposta_inicial.tool_calls:
        try:
            resultado = _tool_cambio.invoke(tc["args"])
            tool_messages.append(ToolMessage(content=str(resultado), tool_call_id=tc["id"]))
        except Exception as exc:
            logger.error("Erro ao executar tool de câmbio: %s", exc)
            tool_messages.append(ToolMessage(
                content="Não foi possível obter a cotação no momento.",
                tool_call_id=tc["id"],
            ))

    # ── 2ª chamada: LLM formula resposta com resultado da tool ───────────────
    try:
        resposta_llm = invocar_com_fallback(mensagens_com_tool + tool_messages)
        texto = (resposta_llm.content or "").strip()
        msgs_retorno = [resposta_inicial] + tool_messages + [resposta_llm]
    except Exception as exc:
        logger.error("[CAMBIO] Falha na 2ª chamada LLM: %s", exc)
        texto = "Não consegui obter a cotação neste momento. Tente novamente em instantes."
        msgs_retorno = [resposta_inicial] + tool_messages + [AIMessage(content=texto)]

    if _RE_HANDOFF.search(texto):
        logger.warning("[CAMBIO] Handoff na 2ª chamada — descartado: %.100s", texto)
        texto = f"{nome}, posso ajudar com mais alguma cotação ou outra necessidade?"
        msgs_retorno = [resposta_inicial] + tool_messages + [AIMessage(content=texto)]

    # ── Contrato: garante que a resposta contenha um valor em R$ ─────────────
    contrato = contrato_cotacao()
    satisfeito, faltando = contrato.validar(texto)
    if not satisfeito:
        logger.warning("[CAMBIO] Contrato não satisfeito (sem R$) — usando fallback de cotação")
        texto = f"{nome}, não consegui formatar a cotação corretamente. Por favor, tente novamente."
        msgs_retorno[-1] = AIMessage(content=texto)

    return {"messages": msgs_retorno, "resposta_final": texto}
