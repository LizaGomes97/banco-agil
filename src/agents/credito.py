"""Agente de Crédito — consulta e solicitação de aumento de limite."""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TEMPERATURE
from src.models.schemas import SolicitacaoAumento
from src.models.state import BancoAgilState
from src.tools.csv_repository import registrar_solicitacao, atualizar_status_solicitacao
from src.tools.score_calculator import calcular_score_credito, score_aprovado

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "credito.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def no_credito(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Crédito."""
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=LLM_TEMPERATURE,
        google_api_key=GEMINI_API_KEY,
    ).bind_tools([calcular_score_credito])

    cliente = state.get("cliente_autenticado", {})

    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    if any(p in ultima_msg.lower() for p in ("encerrar", "tchau", "sair", "até logo", "obrigado")):
        return {"encerrado": True}

    # Injeta dados do cliente e memórias semânticas no contexto
    contexto_cliente = (
        f"\n\n## Dados do cliente autenticado\n"
        f"- Nome: {cliente.get('nome', '')}\n"
        f"- CPF: {cliente.get('cpf', '')}\n"
        f"- Limite atual: R$ {cliente.get('limite_credito', 0):,.2f}\n"
        f"- Score atual: {cliente.get('score', 0)}\n"
        f"- Score suficiente para aprovação (≥500): {'Sim' if score_aprovado(cliente.get('score', 0)) else 'Não'}"
    )

    memorias = state.get("memoria_cliente") or []
    if memorias:
        historico_str = "\n".join(f"- {m}" for m in memorias)
        contexto_cliente += f"\n\n## Interações anteriores do cliente\n{historico_str}"

    messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto_cliente)] + list(state["messages"])
    resposta = llm.invoke(messages)

    # Verifica se o agente quer redirecionar para entrevista
    conteudo = resposta.content.lower() if hasattr(resposta, "content") else ""
    if "entrevista" in conteudo and "score" in conteudo:
        return {"messages": [resposta], "agente_ativo": "entrevista"}

    return {"messages": [resposta]}
