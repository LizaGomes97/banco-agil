"""Agente de Entrevista de Crédito — coleta dados financeiros e recalcula score.

A tool call de cálculo de score é executada inline neste nó, garantindo
que o score seja calculado e o CSV atualizado antes do router encerrar o turno.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.infrastructure.model_provider import criar_llm, invocar_com_fallback, normalizar_content
from src.models.state import BancoAgilState
from src.tools.csv_repository import atualizar_score, consultar_limite_maximo_por_score
from src.tools.score_calculator import calcular_score_credito

from .contract import contrato_resultado_entrevista, corrigir_resposta_score
from .prompt import build_system_prompt

logger = logging.getLogger(__name__)

_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo"}

_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|encaminh)",
    re.IGNORECASE,
)

_RE_EMPREGO = re.compile(
    r"\b(formal|clt|carteira|autônom|autonom|pj|desempregad|sem\s+emprego)\b",
    re.IGNORECASE,
)
_RE_RENDA = re.compile(r"\b(renda|sal[aá]ri|ganh[oa])", re.IGNORECASE)
_RE_DEPENDENTES = re.compile(
    r"\b(dependent|filho|filha|mulher|esposa|marido|sozin|nenhu|sem\s+dependent)",
    re.IGNORECASE,
)
_RE_DIVIDAS = re.compile(
    r"\b(d[ií]vid|empr[eé]stim|financiament|parcel|fatura|card[aã]o|sem\s+d[ií]vid|n[aã]o\s+tenho|nenhuma\s+d[ií]vid)",
    re.IGNORECASE,
)


def _dados_entrevista_completos(mensagens) -> bool:
    """Heurística para detectar se os 4 blocos da entrevista já foram discutidos."""
    texto_hist = " ".join(
        str(getattr(m, "content", "") or "") for m in mensagens
    ).lower()
    tem_renda = bool(_RE_RENDA.search(texto_hist))
    tem_emprego = bool(_RE_EMPREGO.search(texto_hist))
    tem_dependentes = bool(_RE_DEPENDENTES.search(texto_hist))
    tem_dividas = bool(_RE_DIVIDAS.search(texto_hist))
    return tem_renda and tem_emprego and tem_dependentes and tem_dividas


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

    memorias = state.get("memoria_cliente") or []
    messages = [SystemMessage(content=build_system_prompt(cliente, memorias))] + list(state["messages"])

    # ── 1ª chamada: LLM conduz entrevista ou chama a tool ────────────────────
    try:
        resposta_inicial = llm.invoke(messages)
    except Exception as exc:
        logger.error("[ENTREVISTA] Falha na 1ª chamada LLM: %s", exc)
        fallback = f"{nome}, vamos continuar nossa conversa. Pode me dizer sua renda mensal?"
        return {"messages": [AIMessage(content=fallback)], "resposta_final": fallback}

    # ── Retry forçado: se dados parecem completos mas LLM não chamou a tool ──
    # Gemini às vezes ignora a instrução de chamar a tool e vai direto pro
    # texto final — resultado: score não recalculado, cliente fica em loop.
    if (
        not getattr(resposta_inicial, "tool_calls", None)
        and _dados_entrevista_completos(state["messages"])
    ):
        logger.warning(
            "[ENTREVISTA] Dados parecem completos mas LLM não chamou tool — retry forçado"
        )
        hint = SystemMessage(content=(
            "Os quatro dados (renda, tipo de emprego, dependentes, dívidas) já foram "
            "coletados na conversa. Você DEVE chamar calcular_score_credito AGORA com "
            "os valores informados pelo cliente. Não responda em texto; faça apenas a "
            "tool call."
        ))
        try:
            resposta_retry = llm.invoke(messages + [hint])
            if getattr(resposta_retry, "tool_calls", None):
                resposta_inicial = resposta_retry
                logger.info("[ENTREVISTA] Retry forçado teve sucesso — tool invocada")
        except Exception as exc:
            logger.error("[ENTREVISTA] Falha no retry forçado: %s", exc)

    # ── Sem tool call: entrevista em andamento (coletando dados) ─────────────
    if not getattr(resposta_inicial, "tool_calls", None):
        texto = normalizar_content(resposta_inicial.content).strip()
        if _RE_HANDOFF.search(texto):
            logger.warning("[ENTREVISTA] Handoff detectado — descartado: %.100s", texto)
            texto = f"{nome}, ótimo! Seu perfil financeiro está sendo atualizado. Posso ajudar com mais alguma coisa?"
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}
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
            pedido_pendente = state.get("pedido_pendente")
            if pedido_pendente:
                updates["aguardando_confirmacao"] = "retomada"

    # ── 2ª chamada: LLM apresenta resultado com o score calculado ────────────
    try:
        resposta_llm = invocar_com_fallback(mensagens_com_tool + tool_messages)
        texto = normalizar_content(resposta_llm.content).strip()
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

    # ── Mensagem final determinística quando há pedido pendente ─────────────
    # Compara o novo score com a tabela score_limite para dar feedback
    # honesto: viável, parcialmente viável ou inviável.
    pedido_pendente = state.get("pedido_pendente")
    if novo_score is not None and pedido_pendente:
        valor_sol = float(pedido_pendente.get("limite_solicitado", 0))
        limite_atual = float(pedido_pendente.get("limite_atual", 0))
        novo_teto = consultar_limite_maximo_por_score(novo_score) or 0.0

        if novo_teto >= valor_sol:
            # Viável: score suficiente para o valor pedido
            texto = (
                f"{nome}, boas notícias! Seu novo score é {novo_score}, que permite "
                f"um limite de até R$ {novo_teto:,.2f}. Podemos seguir com o aumento "
                f"para R$ {valor_sol:,.2f}? (sim / não)"
            )
        elif novo_teto > limite_atual:
            # Parcialmente viável: score subiu, dá pra aumentar algo, mas menos do que pediu
            updates["pedido_pendente"] = {
                "limite_solicitado": novo_teto,
                "limite_atual": limite_atual,
            }
            texto = (
                f"{nome}, seu novo score é {novo_score}. Isso permite um limite de "
                f"até R$ {novo_teto:,.2f}, abaixo do valor que você pediu "
                f"(R$ {valor_sol:,.2f}), mas acima do seu limite atual "
                f"(R$ {limite_atual:,.2f}). Posso processar o aumento para "
                f"R$ {novo_teto:,.2f}? (sim / não)"
            )
        else:
            # Inviável: score não sobe o suficiente nem para ultrapassar o atual
            updates["pedido_pendente"] = None
            updates["aguardando_confirmacao"] = None
            texto = (
                f"{nome}, seu novo score é {novo_score}. Infelizmente ele ainda não "
                f"permite aumento acima do seu limite atual de R$ {limite_atual:,.2f}. "
                f"Você pode tentar novamente no futuro após melhorar seu perfil "
                f"financeiro. Posso te ajudar com mais alguma coisa?"
            )

        msgs_retorno[-1] = AIMessage(content=texto)

    # ── Contrato: garante que o novo score aparece na resposta ───────────────
    elif novo_score is not None:
        contrato = contrato_resultado_entrevista(novo_score)

        def _invocar_hint(hints: list | None) -> str:
            if not hints:
                return texto
            try:
                msgs_hint = mensagens_com_tool + tool_messages + [SystemMessage(content=hints[0]["content"])]
                r = invocar_com_fallback(msgs_hint)
                return normalizar_content(r.content).strip()
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
