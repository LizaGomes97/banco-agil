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

    resposta_final: Optional[str]
    """Contrato explícito de saída dos agentes (padrão Result<T>).

    - Agente tem resposta para o usuário  → str com o texto
    - Agente apenas roteia / processa     → None

    O router usa este campo para decidir se o turno acabou.
    A API lê este campo diretamente — sem precisar inferir pelo histórico de msgs.
    Cada nó SEMPRE retorna este campo (str ou None) para resetar entre turnos.
    """

    turno_id: Optional[str]
    """ID do turno registrado no staging (ver ADR-023).

    Preenchido pelo nó `registrar_turno` após cada resposta. A API expõe
    este id ao frontend para que o botão thumbs up/down possa referenciar
    exatamente o turno avaliado. None enquanto o turno ainda não foi
    persistido (antes do `registrar_turno`) ou quando a gravação falhou.
    """

    intent_detectada: Optional[str]
    """Última intenção classificada pelo intent_classifier.

    Propagada pelos agentes para o staging — permite filtrar o dashboard
    de curadoria por intenção ("mostrar apenas turnos de crédito").
    """

    session_id: Optional[str]
    """Identificador da sessão (thread_id do LangGraph).

    Preenchido pela API em cada /api/chat para que o nó `registrar_turno`
    consiga associar cada turno ao checkpoint da conversa. É só uma cópia
    do thread_id do configurable — LangGraph não expõe isso no state por padrão.
    """

    pedido_pendente: Optional[dict]
    """Solicitação de aumento que aguarda retomada após entrevista de crédito.

    Preenchido pelo agente de crédito quando uma solicitação é rejeitada
    e o cliente aceita passar pela entrevista. Após a entrevista atualizar
    o score, o agente de crédito usa este campo para retomar o pedido sem
    perguntar o valor novamente.
    Exemplo: {"limite_solicitado": 7000.0, "limite_atual": 5000.0}
    None quando não há pedido em andamento.
    """

    aguardando_confirmacao: Optional[str]
    """Sinaliza que o agente fez uma pergunta de confirmação no turno anterior
    e agora aguarda sim/não do cliente. Valores possíveis:
      - "entrevista" -> cliente foi perguntado se quer fazer entrevista de crédito
      - "retomada"   -> cliente foi perguntado se quer retomar pedido após novo score
      - None         -> nenhum consentimento pendente
    Permite que o agente trate a próxima mensagem como resposta binária
    sem precisar re-classificar como nova intenção."""
