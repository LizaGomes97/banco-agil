"""Agente de Crédito — pipeline Flash→Pro para decisão de limite.

Fase 1 (Flash): modelo rápido e barato conduz a conversa e chama as tools
  de verificação de elegibilidade e registro do pedido.

Fase 2 (Pro): acionado apenas quando houve tool calls (= decisão real).
  Recebe todo o contexto — conversa + resultados das tools — e formula
  a resposta final com raciocínio mais rico e empático.

Conversas simples (consulta de limite, dúvidas genéricas) usam só o Flash.
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage

from src.infrastructure.model_provider import invocar_com_fallback
from src.models.state import BancoAgilState
from src.tools.credit_tools import registrar_pedido_aumento, verificar_elegibilidade_aumento
from src.tools.score_calculator import score_aprovado

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "credito.md"
_PROMPT_PRO_PATH = Path(__file__).parent.parent / "prompts" / "credito_pro_sintese.md"

_SYSTEM_PROMPT_FLASH = _PROMPT_PATH.read_text(encoding="utf-8")
_SYSTEM_PROMPT_PRO = _PROMPT_PRO_PATH.read_text(encoding="utf-8")

_TOOLS_FLASH = [verificar_elegibilidade_aumento, registrar_pedido_aumento]

_TOOL_MAP = {
    "verificar_elegibilidade_aumento": verificar_elegibilidade_aumento,
    "registrar_pedido_aumento": registrar_pedido_aumento,
}


def no_credito(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Crédito (pipeline Flash→Pro).

    Flash coleta dados e aciona tools → Pro sintetiza a resposta final.
    Para consultas simples sem tool calls, Flash responde diretamente.
    """
    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""

    if any(p in ultima_msg.lower() for p in ("encerrar", "tchau", "sair", "até logo", "obrigado")):
        return {"encerrado": True}

    # ── Contexto injetado no system prompt ───────────────────────────────────
    contexto = (
        f"\n\n## Dados do cliente autenticado\n"
        f"- Nome: {cliente.get('nome', '')}\n"
        f"- CPF: {cliente.get('cpf', '')}\n"
        f"- Limite atual: R$ {cliente.get('limite_credito', 0):,.2f}\n"
        f"- Score atual: {cliente.get('score', 0)}\n"
        f"- Elegível para aumento (score ≥ 500): "
        f"{'Sim' if score_aprovado(cliente.get('score', 0)) else 'Não'}"
    )

    memorias = state.get("memoria_cliente") or []
    if memorias:
        historico_str = "\n".join(f"- {m}" for m in memorias)
        contexto += f"\n\n## Interações anteriores do cliente\n{historico_str}"

    messages = [SystemMessage(content=_SYSTEM_PROMPT_FLASH + contexto)] + list(state["messages"])

    # ── Fase 1: Flash — coleta + tool calling ─────────────────────────────────
    resposta_flash = invocar_com_fallback(messages, tier="fast", tools=_TOOLS_FLASH)

    # Sem tool calls: conversa simples → Flash responde diretamente
    if not getattr(resposta_flash, "tool_calls", None):
        conteudo = resposta_flash.content.lower() if hasattr(resposta_flash, "content") else ""
        if "entrevista" in conteudo:
            return {"messages": [resposta_flash], "agente_ativo": "entrevista"}
        return {"messages": [resposta_flash]}

    # ── Execução inline das tools ─────────────────────────────────────────────
    tool_messages: list[ToolMessage] = []
    for tc in resposta_flash.tool_calls:
        tool_fn = _TOOL_MAP.get(tc.get("name", ""))
        try:
            if tool_fn:
                resultado = tool_fn.invoke(tc["args"])
            else:
                resultado = {"erro": f"Tool '{tc.get('name')}' não reconhecida."}
            logger.info("Tool '%s' executada: %s", tc.get("name"), resultado)
        except Exception as exc:
            logger.error("Erro na tool '%s': %s", tc.get("name"), exc)
            resultado = {"erro": str(exc)}

        tool_messages.append(ToolMessage(content=str(resultado), tool_call_id=tc["id"]))

    # ── Fase 2: Pro — síntese da decisão final ───────────────────────────────
    mensagens_com_tools = messages + [resposta_flash] + tool_messages
    system_pro = SystemMessage(content=_SYSTEM_PROMPT_PRO + contexto)

    resposta_pro = invocar_com_fallback(
        [system_pro] + mensagens_com_tools,
        tier="pro",
    )

    logger.info("Pipeline Flash→Pro concluído para CPF %s", str(cliente.get("cpf", ""))[-4:])

    # Verifica se o Pro quer redirecionar para entrevista
    conteudo_pro = resposta_pro.content.lower() if hasattr(resposta_pro, "content") else ""
    updates: dict = {"messages": [resposta_flash] + tool_messages + [resposta_pro]}
    if "entrevista" in conteudo_pro and ("score" in conteudo_pro or "reajust" in conteudo_pro):
        updates["agente_ativo"] = "entrevista"

    return updates
