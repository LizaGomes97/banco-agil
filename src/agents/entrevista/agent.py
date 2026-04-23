"""Agente de Entrevista de Crédito — coleta dados financeiros e recalcula score.

A tool call de cálculo de score é executada inline neste nó, garantindo
que o score seja calculado e o CSV atualizado antes do router encerrar o turno.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.infrastructure.model_provider import criar_llm, invocar_com_fallback
from src.models.state import BancoAgilState
from src.tools.csv_repository import atualizar_score
from src.tools.score_calculator import calcular_score_credito

from .contract import contrato_coleta_dados, contrato_resultado_entrevista, corrigir_resposta_score

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo"}

_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|encaminh)",
    re.IGNORECASE,
)


def no_entrevista(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Entrevista de Crédito.

    Quando todos os dados forem coletados, o LLM chama calcular_score_credito.
    A tool executa inline, o score é atualizado no CSV e o cliente é
    redirecionado ao Agente de Crédito — tudo no mesmo turno.
    """
    llm = criar_llm().bind_tools([calcular_score_credito])

    cliente = state.get("cliente_autenticado", {})
    nome = cliente.get("nome", "").split()[0]
    ultima_msg = state["messages"][-1].content if state["messages"] else ""

    if any(p in ultima_msg.lower() for p in _INTENCOES_ENCERRAR):
        return {"encerrado": True, "resposta_final": None}

    contexto = (
        f"\n\n## Dados do cliente\n"
        f"- Nome: {cliente.get('nome', '')}\n"
        f"- Score atual: {cliente.get('score', 0)}\n"
    )
    memorias = state.get("memoria_cliente") or []
    if memorias:
        contexto += "\n## Interações anteriores\n" + "\n".join(f"- {m}" for m in memorias)

    messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + list(state["messages"])

    # ── 1ª chamada: LLM conduz entrevista ou chama a tool ────────────────────
    try:
        resposta_inicial = llm.invoke(messages)
    except Exception as exc:
        logger.error("[ENTREVISTA] Falha na 1ª chamada LLM: %s", exc)
        fallback = f"{nome}, vamos continuar nossa conversa. Pode me dizer sua renda mensal?"
        return {"messages": [AIMessage(content=fallback)], "resposta_final": fallback}

    # ── Sem tool call: entrevista em andamento (coletando dados) ─────────────
    if not getattr(resposta_inicial, "tool_calls", None):
        texto = (resposta_inicial.content or "").strip()
        if _RE_HANDOFF.search(texto):
            logger.warning("[ENTREVISTA] Handoff detectado — descartado: %.100s", texto)
            texto = f"{nome}, ótimo! Seu perfil financeiro está sendo atualizado. Posso ajudar com mais alguma coisa?"
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}
        # Contrato de coleta: sem validação de valor, apenas não-vazio
        contrato_coleta_dados().validar(texto)
        return {"messages": [resposta_inicial], "resposta_final": texto}

    # ── Com tool call: calcular score inline ─────────────────────────────────
    mensagens_com_tool = messages + [resposta_inicial]
    tool_messages = []
    novo_score: int | None = None
    updates: dict = {}

    for tc in resposta_inicial.tool_calls:
        if tc.get("name") == "calcular_score_credito":
            try:
                resultado = calcular_score_credito.invoke(tc["args"])
                novo_score = resultado["score"]
                tool_messages.append(ToolMessage(content=str(resultado), tool_call_id=tc["id"]))
                logger.info("Score calculado: %d", novo_score)
            except Exception as exc:
                logger.error("Erro no cálculo de score: %s", exc)
                tool_messages.append(ToolMessage(content="Erro no cálculo.", tool_call_id=tc["id"]))

    if novo_score is not None:
        cpf = cliente.get("cpf", "")
        if cpf:
            atualizar_score(cpf, novo_score)
            updates["cliente_autenticado"] = {**cliente, "score": novo_score}
            updates["agente_ativo"] = "credito"

    # ── 2ª chamada: LLM apresenta resultado com o score calculado ────────────
    try:
        resposta_llm = invocar_com_fallback(mensagens_com_tool + tool_messages)
        texto = (resposta_llm.content or "").strip()
        msgs_retorno = [resposta_inicial] + tool_messages + [resposta_llm]
    except Exception as exc:
        logger.error("[ENTREVISTA] Falha na 2ª chamada LLM: %s", exc)
        texto = f"Seu perfil foi atualizado com o score {novo_score}. Posso ajudá-lo a solicitar um aumento de limite agora."
        msgs_retorno = [resposta_inicial] + tool_messages + [AIMessage(content=texto)]

    if _RE_HANDOFF.search(texto):
        logger.warning("[ENTREVISTA] Handoff na 2ª chamada — descartado: %.100s", texto)
        score_info = f" Seu novo score é {novo_score}." if novo_score else ""
        texto = f"{nome}, seu perfil financeiro foi atualizado com sucesso!{score_info} Deseja solicitar um aumento de limite agora?"
        msgs_retorno = [resposta_inicial] + tool_messages + [AIMessage(content=texto)]

    # ── Contrato: garante que o novo score aparece na resposta ───────────────
    if novo_score is not None:
        contrato = contrato_resultado_entrevista(novo_score)

        def _invocar_hint(hints: list | None) -> str:
            if not hints:
                return texto
            try:
                msgs_hint = mensagens_com_tool + tool_messages + [SystemMessage(content=hints[0]["content"])]
                r = invocar_com_fallback(msgs_hint)
                return (r.content or "").strip()
            except Exception:
                return texto

        texto = contrato.executar(
            invocar_fn=_invocar_hint,
            corrigir_fn=lambda r, f: corrigir_resposta_score(r, f, novo_score),
        )
        msgs_retorno[-1] = AIMessage(content=texto)

    updates["messages"] = msgs_retorno
    updates["resposta_final"] = texto
    return updates
