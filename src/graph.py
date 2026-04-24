"""Montagem do StateGraph LangGraph — topologia do sistema Banco Ágil.

Este arquivo define a estrutura do grafo: nós, edges e função de roteamento.
Ver ADR-001 (LangGraph) e ADR-003 (handoff implícito) para decisões de design.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph
from langchain_core.messages import HumanMessage

from src.agents.cambio import no_cambio
from src.agents.credito import no_credito
from src.agents.entrevista import no_entrevista
from src.agents.triagem import no_triagem  # noqa: E402 — módulos com __init__.py
from src.infrastructure.checkpointer import criar_checkpointer
from src.infrastructure.staging_store import staging_store
from src.models.state import BancoAgilState

logger = logging.getLogger(__name__)


def _extrair_ultima_mensagem_usuario(state: BancoAgilState) -> str:
    """Retorna o último HumanMessage para contextualizar o turno no staging."""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return (msg.content or "").strip()
    return ""


def no_registrar_turno(state: BancoAgilState) -> dict:
    """Grava o turno atual no staging para curadoria assíncrona (ADR-023).

    Executa APÓS o agente produzir resposta_final e ANTES do END.
    Captura:
      - Pergunta do usuário + resposta do agente
      - Agente ativo + intenção detectada
      - CPF (se autenticado) + session_id (thread_id do LangGraph)

    Falhas são silenciosas: a curadoria NUNCA pode quebrar o chat.
    Turnos sem cliente autenticado (fase de triagem inicial) são ignorados —
    não há CPF para isolar e não carregam sinal de negócio.
    """
    resposta = state.get("resposta_final")
    cliente = state.get("cliente_autenticado")

    # Sentinela "skipped" impede loop no router quando não há o que registrar
    # (ex.: falha de auth sem cliente_autenticado). O router só sai do staging
    # quando turno_id é truthy — precisa retornar algo != None.
    if not resposta or not cliente:
        return {"turno_id": "skipped"}

    cpf = (cliente.get("cpf") or "").strip()
    if not cpf:
        return {"turno_id": "skipped"}

    session_id = state.get("session_id") or "desconhecido"

    turno_id = staging_store.registrar_turno_sync(
        cpf=cpf,
        session_id=session_id,
        user_message=_extrair_ultima_mensagem_usuario(state),
        agent_response=resposta,
        agent_name=state.get("agente_ativo", "triagem"),
        intent=state.get("intent_detectada"),
    )

    if turno_id:
        logger.debug(
            "[STAGING] Turno registrado | id=%s | agente=%s | intent=%s",
            turno_id[:8], state.get("agente_ativo"), state.get("intent_detectada"),
        )

    # Se o staging falhou, ainda marca "skipped" para não entrar em loop no router.
    return {"turno_id": turno_id or "skipped"}


def no_salvar_memoria(state: BancoAgilState) -> dict:
    """No-op de encerramento — apenas marca a sessão como finalizada.

    Antigamente gerava um resumo via LLM e persistia no Qdrant
    (`banco_agil_memoria_cliente`). Com o ADR-023 paramos de salvar dados
    do cliente na memória semântica, então esse nó virou apenas um ponto
    de terminação do grafo. Mantido para não mexer na topologia e para que
    o `router` ainda tenha uma transição coerente (`encerrado + memoria_salva`).
    """
    return {"memoria_salva": True}


def router(state: BancoAgilState) -> str:
    """Decide qual nó deve receber o próximo turno.

    Função determinística — não usa LLM. Baseia-se exclusivamente
    nos campos do estado. Ver ADR-003 para justificativa.

    Contrato de saída (resposta_final):
      resposta_final = str  → agente produziu resposta → registrar_turno → END
      resposta_final = None → agente apenas roteou    → continuar roteamento

    Fluxo de encerramento:
      encerrado=True + memoria_salva=False → salvar_memoria → END
      encerrado=True + memoria_salva=True  → END

    Captura para curadoria (ADR-023):
      Toda resposta final passa por `registrar_turno` antes do END,
      gravando evento estruturado no staging para o worker curador.
    """
    if state.get("encerrado"):
        if not state.get("memoria_salva"):
            return "salvar_memoria"
        return END

    # ── Contrato explícito: agente sinalizou que tem uma resposta final ───────
    if state.get("resposta_final") is not None:
        # Se ainda não registrou o turno, passa pelo staging primeiro.
        if not state.get("turno_id"):
            return "registrar_turno"
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
    workflow.add_node("registrar_turno", no_registrar_turno)
    workflow.add_node("salvar_memoria", no_salvar_memoria)

    # Ponto de entrada: sempre começa pela triagem
    workflow.set_entry_point("agente_triagem")

    # Edges condicionais: após cada nó de agente, o router decide o próximo
    for agente in ["agente_triagem", "agente_credito", "agente_entrevista", "agente_cambio"]:
        workflow.add_conditional_edges(agente, router)

    # registrar_turno passa pelo router — que já lê turno_id e manda para END
    workflow.add_conditional_edges("registrar_turno", router)

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
