"""Montagem do StateGraph LangGraph — topologia do sistema Banco Ágil.

Este arquivo define a estrutura do grafo: nós, edges e função de roteamento.
Ver ADR-001 (LangGraph) e ADR-003 (handoff implícito) para decisões de design.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agents.cambio import no_cambio
from src.agents.credito import no_credito
from src.agents.entrevista import no_entrevista
from src.agents.triagem import no_triagem
from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.infrastructure.checkpointer import criar_checkpointer
from src.infrastructure.qdrant_memory import salvar_interacao
from src.models.state import BancoAgilState

logger = logging.getLogger(__name__)

_PROMPT_RESUMO = """\
Você é um assistente interno do Banco Ágil. Sua tarefa é criar um resumo conciso \
da conversa abaixo para ser armazenado como memória do cliente.

O resumo deve conter em 2-4 frases:
- O que o cliente solicitou
- Quais agentes atenderam (triagem, crédito, entrevista, câmbio)
- O resultado final (aprovado, negado, informação fornecida, etc.)

Seja direto e factual. Não use bullet points.
"""


def no_salvar_memoria(state: BancoAgilState) -> dict:
    """Gera um resumo semântico da sessão e persiste no Qdrant antes do END.

    Só executa se o cliente estava autenticado e a memória ainda não foi salva.
    Falhas são logadas mas não interrompem o encerramento da conversa.
    """
    cliente = state.get("cliente_autenticado")
    if not cliente or state.get("memoria_salva"):
        return {"memoria_salva": True}

    cpf = cliente.get("cpf", "")
    if not cpf:
        return {"memoria_salva": True}

    try:
        llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            temperature=0,
            google_api_key=GEMINI_API_KEY,
            max_output_tokens=300,
        )
        historico = "\n".join(
            f"{'Cliente' if isinstance(m, HumanMessage) else 'Agente'}: {m.content}"
            for m in state.get("messages", [])
            if hasattr(m, "content") and m.content
        )
        resumo_msg = llm.invoke([
            SystemMessage(content=_PROMPT_RESUMO),
            HumanMessage(content=historico[-3000:]),
        ])
        resumo = resumo_msg.content.strip()

        agentes = list({
            state.get("agente_ativo", "triagem"),
            "triagem",
        })

        salvar_interacao(
            cpf=cpf,
            resumo=resumo,
            agentes_usados=agentes,
            resultado="sessão encerrada",
        )
        logger.info("Memória da sessão salva para CPF %s", cpf[-4:])
    except Exception as exc:
        logger.error("Falha ao salvar memória da sessão: %s", exc)

    return {"memoria_salva": True}


def router(state: BancoAgilState) -> str:
    """Decide qual nó deve receber o próximo turno.

    Função determinística — não usa LLM. Baseia-se exclusivamente
    nos campos do estado. Ver ADR-003 para justificativa.

    Fluxo de encerramento:
      encerrado=True + memoria_salva=False → salvar_memoria → END
      encerrado=True + memoria_salva=True  → END
    """
    from langchain_core.messages import AIMessage

    if state.get("encerrado"):
        if not state.get("memoria_salva"):
            return "salvar_memoria"
        return END

    # ── Turno encerrado: agente produziu resposta ─────────────────────────────
    msgs = state.get("messages", [])
    if msgs and isinstance(msgs[-1], AIMessage):
        return END

    # ── Turno em andamento: rotear para o agente correto ─────────────────────
    if not state.get("cliente_autenticado"):
        return "agente_triagem"

    agente = state.get("agente_ativo", "triagem")
    destino = f"agente_{agente}"

    mapa_valido = {"agente_triagem", "agente_credito", "agente_entrevista", "agente_cambio"}
    if destino not in mapa_valido:
        logger.warning("agente_ativo inválido '%s', retornando para triagem", agente)
        return "agente_triagem"

    return destino


def criar_grafo():
    """Cria e compila o StateGraph com checkpointer Redis.

    Retorna o grafo compilado pronto para uso via .invoke() ou .stream().
    """
    workflow = StateGraph(BancoAgilState)

    # Registra os nós
    workflow.add_node("agente_triagem", no_triagem)
    workflow.add_node("agente_credito", no_credito)
    workflow.add_node("agente_entrevista", no_entrevista)
    workflow.add_node("agente_cambio", no_cambio)
    workflow.add_node("salvar_memoria", no_salvar_memoria)

    # Ponto de entrada: sempre começa pela triagem
    workflow.set_entry_point("agente_triagem")

    # Edges condicionais: após cada nó de agente, o router decide o próximo
    for agente in ["agente_triagem", "agente_credito", "agente_entrevista", "agente_cambio"]:
        workflow.add_conditional_edges(agente, router)

    # salvar_memoria sempre vai para END — não precisa de router
    workflow.add_edge("salvar_memoria", END)

    checkpointer = criar_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)

    logger.info("Grafo Banco Ágil compilado com sucesso")
    return graph


# Instância global reutilizada pelo Streamlit
_graph = None


def get_graph():
    """Retorna a instância singleton do grafo."""
    global _graph
    if _graph is None:
        _graph = criar_grafo()
    return _graph
