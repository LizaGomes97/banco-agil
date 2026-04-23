from __future__ import annotations

from typing import Annotated, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class BancoAgilState(TypedDict):
    """Estado compartilhado entre todos os nós do grafo.

    Todos os agentes leem e escrevem neste objeto.
    O Redis persiste cada versão como checkpoint (ver ADR-004).
    """

    messages: Annotated[list[BaseMessage], add_messages]
    """Histórico completo de mensagens da conversa."""

    cliente_autenticado: Optional[dict]
    """Dados do cliente após autenticação bem-sucedida.
    None enquanto não autenticado.
    Exemplo: {"cpf": "123.456.789-00", "nome": "Ana Silva",
               "limite_credito": 5000.0, "score": 650}
    """

    agente_ativo: str
    """Agente que deve receber o próximo turno.
    Valores válidos: "triagem" | "credito" | "entrevista" | "cambio"
    """

    tentativas_auth: int
    """Contador de tentativas de autenticação falhas. Máximo: 3."""

    encerrado: bool
    """True quando o atendimento deve ser encerrado.
    Qualquer agente pode setar este campo.
    O router retorna END ao encontrá-lo como True.
    """

    memoria_cliente: Optional[list]
    """Resumos semânticos das interações anteriores do cliente (via Qdrant).
    Preenchido após autenticação, injetado no contexto de cada agente especialista.
    None até o cliente ser autenticado.
    """

    memoria_salva: bool
    """True após o nó salvar_memoria ter persistido o resumo da sessão no Qdrant.
    Evita dupla gravação caso o router passe pelo nó mais de uma vez.
    """
