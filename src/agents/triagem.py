"""Agente de Triagem — autenticação e roteamento.

Responsável por autenticar o cliente via CPF + data de nascimento
e identificar a intenção para redirecionar ao agente correto.

O roteamento usa um classificador LLM (intent_classifier.py) em vez de
keyword matching, tornando o handoff robusto a variações de linguagem natural.
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TEMPERATURE, MAX_TENTATIVAS_AUTH
from src.infrastructure.qdrant_memory import buscar_memorias
from src.models.state import BancoAgilState
from src.tools.csv_repository import buscar_cliente
from src.tools.intent_classifier import classificar_intencao

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "triagem.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def _identificar_agente(mensagem: str) -> str | None:
    """Classifica a intenção via LLM e retorna o agente correspondente.

    Retorna "credito", "cambio", "encerrar" ou None (sem intenção clara).
    """
    intencao = classificar_intencao(mensagem)
    if intencao == "nenhum":
        return None
    return intencao


def no_triagem(state: BancoAgilState) -> dict:
    """Nó do grafo responsável pela triagem e autenticação."""
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=LLM_TEMPERATURE,
        google_api_key=GEMINI_API_KEY,
    )

    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    ultima_msg_lower = ultima_msg.lower()

    # ── Cliente já autenticado ────────────────────────────────────────────────
    if state.get("cliente_autenticado"):
        agente_atual = state.get("agente_ativo", "triagem")

        # Se um agente especialista já está ativo, triagem só intercepta
        # encerramentos e trocas de assunto — do contrário, passa silenciosamente.
        if agente_atual != "triagem":
            if any(p in ultima_msg_lower for p in _INTENCOES_ENCERRAR):
                return {"encerrado": True}
            novo_agente = _identificar_agente(ultima_msg)
            if novo_agente and novo_agente != "encerrar" and novo_agente != agente_atual:
                return {"agente_ativo": novo_agente}
            # Passthrough: sem LLM, sem mensagem — router encaminha ao agente ativo
            return {}

        # agente_ativo == "triagem": identificar o que o cliente precisa
        agente = _identificar_agente(ultima_msg)
        if agente == "encerrar":
            return {"encerrado": True}
        if agente in ("credito", "cambio", "entrevista"):
            return {"agente_ativo": agente}

        # Sem intenção clara — LLM cumprimenta/pergunta (injeta dados do cliente)
        cliente = state["cliente_autenticado"]
        contexto = (
            f"\n\n## Cliente autenticado\n"
            f"Nome: {cliente.get('nome', '')}\n"
            f"CPF: {cliente.get('cpf', '')}"
        )
        messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + list(state["messages"])
        resposta = llm.invoke(messages)
        return {"messages": [resposta]}

    # ── Não autenticado: verificar se temos CPF + data para tentar auth ───────
    historico = " ".join(
        m.content for m in state["messages"] if hasattr(m, "content")
    ).lower()

    cpf_detectado = _extrair_cpf(historico)
    data_detectada = _extrair_data(historico)

    if cpf_detectado and data_detectada:
        cliente = buscar_cliente(cpf_detectado, data_detectada)
        if cliente:
            logger.info("Cliente autenticado: %s", cliente.cpf)
            # Busca memórias semânticas do cliente no Qdrant (isoladas por CPF)
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
            }
        else:
            tentativas = state.get("tentativas_auth", 0) + 1
            logger.warning("Falha na autenticação — tentativa %d", tentativas)
            # Sempre produz AI message para o router parar neste turno
            messages = [SystemMessage(content=_SYSTEM_PROMPT)] + list(state["messages"])
            resposta = llm.invoke(messages)
            if tentativas >= MAX_TENTATIVAS_AUTH:
                return {"messages": [resposta], "tentativas_auth": tentativas, "encerrado": True}
            return {"messages": [resposta], "tentativas_auth": tentativas}

    # ── Sem dados suficientes: LLM conduz a coleta ───────────────────────────
    messages = [SystemMessage(content=_SYSTEM_PROMPT)] + list(state["messages"])
    resposta = llm.invoke(messages)
    return {"messages": [resposta]}


def _extrair_cpf(texto: str) -> str | None:
    """Extrai sequência de 11 dígitos do texto (CPF com ou sem máscara)."""
    import re
    m = re.search(r"\b\d{3}[\.\-]?\d{3}[\.\-]?\d{3}[\.\-]?\d{2}\b", texto)
    return m.group(0) if m else None


def _extrair_data(texto: str) -> str | None:
    """Extrai data de nascimento do texto em formatos comuns."""
    import re
    m = re.search(r"\b(\d{2}[/\-]\d{2}[/\-]\d{4}|\d{4}[/\-]\d{2}[/\-]\d{2})\b", texto)
    return m.group(0) if m else None
