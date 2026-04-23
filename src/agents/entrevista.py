"""Agente de Entrevista de Crédito — coleta dados financeiros e recalcula score.

A tool call de cálculo de score é executada inline neste nó, garantindo
que o score seja calculado e o CSV atualizado antes do router encerrar o turno.
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage

from src.infrastructure.model_provider import criar_llm, invocar_com_fallback
from src.models.state import BancoAgilState
from src.tools.csv_repository import atualizar_score
from src.tools.score_calculator import calcular_score_credito

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "entrevista.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo"}


def no_entrevista(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Entrevista de Crédito.

    Quando todos os dados forem coletados, o LLM chama calcular_score_credito.
    A tool executa inline, o score é atualizado no CSV e o cliente é
    redirecionado ao Agente de Crédito — tudo no mesmo turno.
    """
    llm = criar_llm().bind_tools([calcular_score_credito])

    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""

    if any(p in ultima_msg.lower() for p in _INTENCOES_ENCERRAR):
        return {"encerrado": True}

    contexto = (
        f"\n\n## Dados do cliente\n"
        f"- Nome: {cliente.get('nome', '')}\n"
        f"- Score atual: {cliente.get('score', 0)}\n"
    )

    memorias = state.get("memoria_cliente") or []
    if memorias:
        historico_str = "\n".join(f"- {m}" for m in memorias)
        contexto += f"\n## Interações anteriores do cliente\n{historico_str}"

    messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + list(state["messages"])

    # ── 1ª chamada: LLM conduz entrevista ou chama a tool ────────────────────
    resposta_inicial = llm.invoke(messages)

    # ── Sem tool call: entrevista em andamento (coletando dados) ─────────────
    if not getattr(resposta_inicial, "tool_calls", None):
        return {"messages": [resposta_inicial]}

    # ── Com tool call: calcular score inline ─────────────────────────────────
    mensagens_com_tool = messages + [resposta_inicial]
    tool_messages = []
    novo_score = None
    updates: dict = {}

    for tc in resposta_inicial.tool_calls:
        if tc.get("name") == "calcular_score_credito":
            try:
                resultado = calcular_score_credito.invoke(tc["args"])
                novo_score = resultado["score"]
                tool_messages.append(
                    ToolMessage(content=str(resultado), tool_call_id=tc["id"])
                )
                logger.info("Score calculado: %d", novo_score)
            except Exception as exc:
                logger.error("Erro no cálculo de score: %s", exc)
                tool_messages.append(
                    ToolMessage(content="Erro no cálculo.", tool_call_id=tc["id"])
                )

    # Persiste score no CSV e atualiza estado
    if novo_score is not None:
        cpf = cliente.get("cpf", "")
        if cpf:
            atualizar_score(cpf, novo_score)
            cliente_atualizado = {**cliente, "score": novo_score}
            updates["cliente_autenticado"] = cliente_atualizado
            updates["agente_ativo"] = "credito"

    # ── 2ª chamada: LLM apresenta resultado com o score calculado ────────────
    resposta_final = invocar_com_fallback(mensagens_com_tool + tool_messages)

    updates["messages"] = [resposta_inicial] + tool_messages + [resposta_final]
    return updates
