# Modelo de Dados — Banco Ágil

## Entidades do sistema

```mermaid
erDiagram
    CLIENTE {
        string cpf PK
        string nome
        date data_nascimento
        float limite_credito
        int score
    }

    SESSAO_REDIS {
        string thread_id PK
        json   state_snapshot
        string updated_at
    }

    MEMORIA_QDRANT {
        uuid   id PK
        string cpf FK
        string resumo
        vector embedding
        list   agentes_usados
        string resultado
        string created_at
    }

    CLIENTE ||--o{ SESSAO_REDIS : "autenticado em"
    CLIENTE ||--o{ MEMORIA_QDRANT : "possui histórico"
```

---

## `BancoAgilState` — Estado compartilhado LangGraph

Definido em `src/models/state.py`. Cada turno carrega e persiste este objeto via Redis.

```python
class BancoAgilState(TypedDict):

    messages: Annotated[list[BaseMessage], add_messages]
    # Reducer: add_messages (acumula, não substitui)
    # Contém: HumanMessage, AIMessage, ToolMessage

    cliente_autenticado: Optional[dict]
    # None até autenticação bem-sucedida.
    # Após: {"cpf": str, "nome": str, "limite_credito": float, "score": int,
    #         "data_nascimento": str}

    agente_ativo: str
    # "triagem" | "credito" | "entrevista" | "cambio"
    # Determina o destino do router quando resposta_final=None

    tentativas_auth: int
    # Conta falhas de autenticação consecutivas.
    # Ao atingir MAX_TENTATIVAS_AUTH (3): encerrado=True

    encerrado: bool
    # True → router vai para salvar_memoria → END
    # Qualquer agente pode setar este campo

    memoria_cliente: Optional[list]
    # Resumos semânticos das sessões anteriores deste CPF (via Qdrant)
    # Preenchido na autenticação; injetado no contexto dos agentes

    memoria_salva: bool
    # True após salvar_memoria ter executado com sucesso
    # Evita dupla gravação ao Qdrant

    resposta_final: Optional[str]
    # Contrato de saída dos agentes:
    #   str  → agente tem resposta → router vai para END
    #   None → agente apenas roteou → router continua avaliando
    # A API lê este campo diretamente (sem parsear messages)
```

### Ciclo de vida por campo

```mermaid
stateDiagram-v2
    direction LR
    [*] --> messages : HumanMessage do usuário

    state messages {
        direction TB
        HumanMessage --> AIMessage
        AIMessage --> ToolMessage : se tool call
        ToolMessage --> AIMessage : resposta final
    }

    [*] --> cliente_autenticado : None (início)
    cliente_autenticado --> AuthOk : triagem detecta CPF+data
    AuthOk --> cliente_autenticado : dict com dados do cliente

    [*] --> resposta_final : None (sempre reseta)
    resposta_final --> str : agente tem resposta
    resposta_final --> None : agente apenas roteia

    [*] --> encerrado : False
    encerrado --> True : "encerrar"|3 falhas auth|qualquer agente
```

---

## Tabela CSV de Clientes

Localização: `data/clientes.csv`

```
cpf,nome,data_nascimento,limite_credito,score
123.456.789-00,Ana Silva,1990-01-15,5000.00,650
987.654.321-00,Carlos Mendes,1985-07-22,3000.00,320
456.789.123-00,Maria Oliveira,1995-03-10,8000.00,780
321.654.987-00,João Santos,1978-11-30,1500.00,180
789.123.456-00,Fernanda Lima,2000-05-05,10000.00,850
```

Acesso via `src/tools/csv_repository.py`:
- `buscar_cliente(cpf, data_nascimento)` — autenticação
- `atualizar_score(cpf, novo_score)` — após entrevista financeira

---

## Fluxo de dados: autenticação e enriquecimento

```mermaid
sequenceDiagram
    participant T as Triagem
    participant CSV as clientes.csv
    participant Q as Qdrant
    participant State as BancoAgilState

    T->>CSV: buscar_cliente(cpf, data)
    CSV-->>T: Cliente(cpf, nome, limite, score)
    T->>Q: buscar_memorias(cpf, consulta, top_k=3)
    Q-->>T: ["Cliente consultou câmbio em 04/2026...", ...]
    T->>State: cliente_autenticado={...}, memoria_cliente=[...]
    Note over State: Todos os agentes\nusam esses campos\nno contexto LLM
```

---

## Fluxo de dados: entrevista e atualização de score

```mermaid
sequenceDiagram
    participant E as Entrevista
    participant LLM as Gemini Flash
    participant Calc as score_calculator.py
    participant CSV as clientes.csv
    participant State as BancoAgilState
    participant Contract as contract.py

    E->>LLM: Coleta renda, emprego, dependentes, dívidas
    LLM-->>E: tool_call calcular_score_credito(args)
    E->>Calc: calcular_score_credito(renda, tipo_emprego, dependentes, dividas)
    Calc-->>E: {"score": 520, "detalhes": {...}}
    E->>CSV: atualizar_score(cpf, 520)
    E->>State: cliente_autenticado.score=520, agente_ativo="credito"
    E->>LLM: Formular resposta com novo score
    LLM-->>E: "Seu novo score é 520, Ana!"
    E->>Contract: contrato_resultado_entrevista(520).validar(resposta)
    Contract-->>E: (True, []) — contrato satisfeito
    E->>State: resposta_final="Seu novo score é 520, Ana!"
```
