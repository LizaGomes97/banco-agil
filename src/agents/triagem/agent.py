"""Agente de Triagem — autenticação e roteamento.

Responsável por autenticar o cliente via CPF + data de nascimento
e identificar a intenção para redirecionar ao agente correto.

O roteamento usa um classificador LLM (intent_classifier.py) em vez de
keyword matching, tornando o handoff robusto a variações de linguagem natural.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from langchain_core.messages import AIMessage, SystemMessage

from src.config import MAX_TENTATIVAS_AUTH
from src.infrastructure.model_provider import invocar_com_fallback
from src.infrastructure.qdrant_memory import buscar_memorias
from src.models.state import BancoAgilState
from src.tools.csv_repository import buscar_cliente
from src.tools.intent_classifier import classificar_intencao

from .contract import contrato_consulta_financeira, corrigir_resposta

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo", "obrigado"}

_RE_TOOL_CALL = re.compile(
    r"^(tools\.|functions\.|<tool_call>|\{\"name\"|<function_calls>)", re.IGNORECASE
)
_RE_CODE_BLOCK = re.compile(
    r"(```[\s\S]{0,20}?\n|^\s*import\s+\w|^\s*from\s+\w+\s+import|"
    r"tool_input\s*=|^\s*\{\s*[\"'](cpf|args|name)[\"'])",
    re.IGNORECASE | re.MULTILINE,
)


def _sanitizar(texto: str) -> str | None:
    """Retorna None se o texto parecer uma chamada de ferramenta ou código."""
    stripped = (texto or "").strip()
    if not stripped:
        logger.warning("[TRIAGEM] Resposta LLM vazia rejeitada")
        return None
    if _RE_TOOL_CALL.match(stripped):
        logger.warning("[TRIAGEM] Rejeitado (padrão tool_call): %.120s", stripped)
        return None
    if _RE_CODE_BLOCK.search(stripped):
        logger.warning("[TRIAGEM] Rejeitado (padrão código): %.120s", stripped)
        return None
    return stripped


def _invocar_llm_seguro(messages: list, fallback_msg: str, hints: list | None = None) -> str:
    msgs = messages + (hints or [])
    resposta = invocar_com_fallback(msgs)
    raw = getattr(resposta, "content", "") or ""
    logger.debug("[TRIAGEM] LLM raw: %.200s", raw)
    texto = _sanitizar(raw)
    if not texto:
        logger.warning("[TRIAGEM] Usando fallback: %s", fallback_msg)
        return fallback_msg
    return texto


def _identificar_agente(mensagem: str) -> str | None:
    intencao = classificar_intencao(mensagem)
    return None if intencao == "nenhum" else intencao


def _extrair_cpf(texto: str) -> str | None:
    m = re.search(r"\b\d{3}[\.\-]?\d{3}[\.\-]?\d{3}[\.\-]?\d{2}\b", texto)
    return m.group(0) if m else None


def _extrair_data(texto: str) -> str | None:
    m = re.search(r"\b(\d{2}[/\-]\d{2}[/\-]\d{4}|\d{4}[/\-]\d{2}[/\-]\d{2})\b", texto)
    return m.group(0) if m else None


def no_triagem(state: BancoAgilState) -> dict:
    """Nó do grafo responsável pela triagem e autenticação.

    Contrato de saída:
      resposta_final = str  → gerou mensagem para o usuário
      resposta_final = None → apenas roteou, sem mensagem
    """
    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    ultima_msg_lower = ultima_msg.lower()

    # ── Cliente já autenticado ────────────────────────────────────────────────
    if state.get("cliente_autenticado"):
        agente_atual = state.get("agente_ativo", "triagem")

        if agente_atual != "triagem":
            if any(p in ultima_msg_lower for p in _INTENCOES_ENCERRAR):
                return {"encerrado": True, "resposta_final": None}
            novo_agente = _identificar_agente(ultima_msg)
            if novo_agente and novo_agente != "encerrar" and novo_agente != agente_atual:
                return {"agente_ativo": novo_agente, "resposta_final": None}
            return {"resposta_final": None}

        agente = _identificar_agente(ultima_msg)
        if agente == "encerrar":
            return {"encerrado": True, "resposta_final": None}
        if agente in ("credito", "cambio", "entrevista"):
            return {"agente_ativo": agente, "resposta_final": None}

        # Sem intenção clara: LLM responde com dados reais do cliente
        cliente = state["cliente_autenticado"]
        limite = float(cliente.get("limite_credito", 0))
        score = int(cliente.get("score", 0))

        contexto = (
            f"\n\n## Dados do cliente autenticado\n"
            f"- Nome: {cliente.get('nome', '')}\n"
            f"- CPF: {cliente.get('cpf', '')}\n"
            f"- Limite de crédito disponível: R$ {limite:,.2f}\n"
            f"- Score de crédito: {score}\n"
            f"\nIMPORTANTE: use EXATAMENTE os valores acima. Nunca invente ou arredonde valores financeiros."
        )
        messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + list(state["messages"])

        contrato = contrato_consulta_financeira(cliente)

        def _invocar(hints: list | None) -> str:
            return _invocar_llm_seguro(
                messages,
                fallback_msg="Como posso ajudá-lo hoje?",
                hints=[SystemMessage(content=h["content"]) for h in (hints or [])],
            )

        texto = contrato.executar(
            invocar_fn=_invocar,
            corrigir_fn=lambda r, f: corrigir_resposta(r, f, cliente),
        )
        return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

    # ── Não autenticado: verificar se temos CPF + data ───────────────────────
    historico = " ".join(
        m.content for m in state["messages"] if hasattr(m, "content")
    ).lower()

    cpf_detectado = _extrair_cpf(historico)
    data_detectada = _extrair_data(historico)

    if cpf_detectado and data_detectada:
        cliente = buscar_cliente(cpf_detectado, data_detectada)
        if cliente:
            logger.info("Cliente autenticado: %s", cliente.cpf)
            memorias = buscar_memorias(
                cpf=cliente.cpf,
                consulta=ultima_msg or "atendimento bancário",
                top_k=3,
            )
            return {
                "cliente_autenticado": cliente.to_dict(),
                "tentativas_auth": 0,
                "agente_ativo": "triagem",
                "memoria_cliente": memorias,
                "memoria_salva": False,
                "resposta_final": None,
            }
        else:
            tentativas = state.get("tentativas_auth", 0) + 1
            logger.warning("Falha na autenticação — tentativa %d", tentativas)
            messages = [SystemMessage(content=_SYSTEM_PROMPT)] + list(state["messages"])
            texto = _invocar_llm_seguro(
                messages,
                fallback_msg="Não encontrei seus dados. Verifique o CPF e a data de nascimento e tente novamente.",
            )
            updates: dict = {
                "messages": [AIMessage(content=texto)],
                "tentativas_auth": tentativas,
                "resposta_final": texto,
            }
            if tentativas >= MAX_TENTATIVAS_AUTH:
                updates["encerrado"] = True
            return updates

    # ── Sem dados suficientes: LLM conduz a coleta ───────────────────────────
    messages = [SystemMessage(content=_SYSTEM_PROMPT)] + list(state["messages"])
    texto = _invocar_llm_seguro(
        messages,
        fallback_msg="Por favor, informe seu CPF e data de nascimento para continuar.",
    )
    return {"messages": [AIMessage(content=texto)], "resposta_final": texto}
