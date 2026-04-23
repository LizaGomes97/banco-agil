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
import re
from pathlib import Path

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.infrastructure.model_provider import invocar_com_fallback
from src.models.state import BancoAgilState
from src.tools.credit_tools import registrar_pedido_aumento, verificar_elegibilidade_aumento
from src.tools.score_calculator import score_aprovado

from .contract import contrato_flash_direto, contrato_sintese_pro, corrigir_resposta

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_PROMPT_PRO_PATH = Path(__file__).parent / "prompt_pro.md"

_SYSTEM_PROMPT_FLASH = _PROMPT_PATH.read_text(encoding="utf-8")
_SYSTEM_PROMPT_PRO = _PROMPT_PRO_PATH.read_text(encoding="utf-8")

_TOOLS_FLASH = [verificar_elegibilidade_aumento, registrar_pedido_aumento]
_TOOL_MAP = {
    "verificar_elegibilidade_aumento": verificar_elegibilidade_aumento,
    "registrar_pedido_aumento": registrar_pedido_aumento,
}

_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|aguarde)",
    re.IGNORECASE,
)


def no_credito(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Crédito (pipeline Flash→Pro).

    Flash coleta dados e aciona tools → Pro sintetiza a resposta final.
    Para consultas simples sem tool calls, Flash responde diretamente.
    """
    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""

    if any(p in ultima_msg.lower() for p in ("encerrar", "tchau", "sair", "até logo", "obrigado")):
        return {"encerrado": True, "resposta_final": None}

    limite = float(cliente.get("limite_credito", 0))
    score = int(cliente.get("score", 0))

    contexto = (
        f"\n\n## Dados do cliente autenticado\n"
        f"- Nome: {cliente.get('nome', '')}\n"
        f"- CPF: {cliente.get('cpf', '')}\n"
        f"- Limite atual: R$ {limite:,.2f}\n"
        f"- Score atual: {score}\n"
        f"- Elegível para aumento (score ≥ 500): "
        f"{'Sim' if score_aprovado(score) else 'Não'}\n"
        f"\nIMPORTANTE: use EXATAMENTE os valores acima. Nunca invente ou arredonde valores financeiros."
    )

    memorias = state.get("memoria_cliente") or []
    if memorias:
        contexto += "\n\n## Interações anteriores\n" + "\n".join(f"- {m}" for m in memorias)

    messages = [SystemMessage(content=_SYSTEM_PROMPT_FLASH + contexto)] + list(state["messages"])

    # ── Fase 1: Flash ─────────────────────────────────────────────────────────
    try:
        resposta_flash = invocar_com_fallback(messages, tier="fast", tools=_TOOLS_FLASH)
    except Exception as exc:
        logger.error("[CREDITO] Falha no Flash: %s", exc)
        fallback = "Entendido! Como posso te ajudar com seu crédito hoje?"
        return {"messages": [AIMessage(content=fallback)], "resposta_final": fallback}

    # Sem tool calls: Flash responde diretamente
    if not getattr(resposta_flash, "tool_calls", None):
        texto = (resposta_flash.content or "").strip()

        if _RE_HANDOFF.search(texto):
            logger.warning("[CREDITO] Flash gerou handoff — descartado: %.100s", texto)
            nome = cliente.get("nome", "").split()[0]
            texto = (
                f"{nome}, seu limite atual é R$ {limite:,.2f} e seu score é {score}. "
                f"Posso ajudar com mais alguma coisa?"
            )
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

        contrato = contrato_flash_direto(cliente)

        def _invocar_flash_hint(hints: list | None) -> str:
            if not hints:
                return texto
            try:
                msgs_hint = messages + [SystemMessage(content=hints[0]["content"])]
                r = invocar_com_fallback(msgs_hint, tier="fast", tools=_TOOLS_FLASH)
                return (r.content or "").strip()
            except Exception:
                return texto

        texto = contrato.executar(
            invocar_fn=_invocar_flash_hint,
            corrigir_fn=lambda r, f: corrigir_resposta(r, f, cliente),
        )

        if "entrevista" in texto.lower():
            return {"messages": [AIMessage(content=texto)], "agente_ativo": "entrevista", "resposta_final": texto}
        return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

    # ── Execução inline das tools ─────────────────────────────────────────────
    tool_messages: list[ToolMessage] = []
    for tc in resposta_flash.tool_calls:
        tool_fn = _TOOL_MAP.get(tc.get("name", ""))
        try:
            resultado = tool_fn.invoke(tc["args"]) if tool_fn else {"erro": f"Tool '{tc.get('name')}' não reconhecida."}
            logger.info("Tool '%s' executada: %s", tc.get("name"), resultado)
        except Exception as exc:
            logger.error("Erro na tool '%s': %s", tc.get("name"), exc)
            resultado = {"erro": str(exc)}
        tool_messages.append(ToolMessage(content=str(resultado), tool_call_id=tc["id"]))

    # ── Fase 2: Pro — síntese da decisão ─────────────────────────────────────
    mensagens_com_tools = messages + [resposta_flash] + tool_messages
    system_pro = SystemMessage(content=_SYSTEM_PROMPT_PRO + contexto)

    try:
        resposta_pro = invocar_com_fallback([system_pro] + mensagens_com_tools, tier="pro")
        texto_pro = (resposta_pro.content or "").strip()
        msgs_retorno = [resposta_flash] + tool_messages + [resposta_pro]
    except Exception as exc:
        logger.error("[CREDITO] Falha no Pro: %s", exc)
        texto_pro = "Processamos sua solicitação. Em breve você receberá a confirmação."
        msgs_retorno = [resposta_flash] + tool_messages + [AIMessage(content=texto_pro)]

    contrato_pro = contrato_sintese_pro(cliente)

    def _invocar_pro_hint(hints: list | None) -> str:
        if not hints:
            return texto_pro
        try:
            msgs_hint = [system_pro] + mensagens_com_tools + [SystemMessage(content=hints[0]["content"])]
            r = invocar_com_fallback(msgs_hint, tier="pro")
            return (r.content or "").strip()
        except Exception:
            return texto_pro

    texto_pro = contrato_pro.executar(
        invocar_fn=_invocar_pro_hint,
        corrigir_fn=lambda r, f: corrigir_resposta(r, f, cliente),
    )

    logger.info("Pipeline Flash→Pro concluído para CPF %s", str(cliente.get("cpf", ""))[-4:])

    updates: dict = {"messages": msgs_retorno, "resposta_final": texto_pro}
    if "entrevista" in texto_pro.lower() and ("score" in texto_pro.lower() or "reajust" in texto_pro.lower()):
        updates["agente_ativo"] = "entrevista"

    return updates
