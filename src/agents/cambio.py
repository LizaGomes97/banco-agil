"""Agente de Câmbio — cotação de moedas em tempo real via Tavily.

A tool call é executada inline neste nó: o LLM chama a tool, a tool
executa, o resultado é injetado no histórico e o LLM responde com o
valor final. O router nunca vê uma AIMessage com tool_calls pendentes.
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TEMPERATURE
from src.models.state import BancoAgilState
from src.tools.exchange_rate import criar_tool_cambio

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "cambio.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_tool_cambio = criar_tool_cambio()
_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo"}
_INTENCOES_CREDITO = {"crédito", "credito", "limite", "aumento"}


def no_cambio(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Câmbio.

    Executa o ciclo completo de tool calling em um único turno:
    1. LLM decide chamar a tool de câmbio
    2. Tool executa e retorna o resultado
    3. LLM recebe o resultado e formula a resposta final
    O router só vê a AIMessage final (sem tool_calls pendentes).
    """
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=LLM_TEMPERATURE,
        google_api_key=GEMINI_API_KEY,
    ).bind_tools([_tool_cambio])

    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    ultima_msg_lower = ultima_msg.lower()

    if any(p in ultima_msg_lower for p in _INTENCOES_ENCERRAR):
        return {"encerrado": True}

    if any(p in ultima_msg_lower for p in _INTENCOES_CREDITO):
        return {"agente_ativo": "credito"}

    contexto = f"\n\n## Cliente: {cliente.get('nome', 'Cliente')}"
    memorias = state.get("memoria_cliente") or []
    if memorias:
        historico_str = "\n".join(f"- {m}" for m in memorias)
        contexto += f"\n\n## Interações anteriores do cliente\n{historico_str}"

    messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + list(state["messages"])

    # ── 1ª chamada: LLM decide se precisa da tool ────────────────────────────
    resposta_inicial = llm.invoke(messages)

    # ── Sem tool call: resposta direta ───────────────────────────────────────
    if not getattr(resposta_inicial, "tool_calls", None):
        return {"messages": [resposta_inicial]}

    # ── Com tool call: executar inline e re-invocar ──────────────────────────
    mensagens_com_tool = messages + [resposta_inicial]
    tool_messages = []

    for tc in resposta_inicial.tool_calls:
        try:
            resultado = _tool_cambio.invoke(tc["args"])
            tool_messages.append(
                ToolMessage(content=str(resultado), tool_call_id=tc["id"])
            )
        except Exception as exc:
            logger.error("Erro ao executar tool de câmbio: %s", exc)
            tool_messages.append(
                ToolMessage(
                    content="Não foi possível obter a cotação no momento.",
                    tool_call_id=tc["id"],
                )
            )

    # ── 2ª chamada: LLM formula resposta com o resultado da tool ─────────────
    llm_sem_tools = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=LLM_TEMPERATURE,
        google_api_key=GEMINI_API_KEY,
    )
    resposta_final = llm_sem_tools.invoke(mensagens_com_tool + tool_messages)

    return {"messages": [resposta_inicial] + tool_messages + [resposta_final]}
