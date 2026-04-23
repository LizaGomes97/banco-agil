# Diagrama: Modelo de Dados

**Data:** 2026-04-22  
**Versão:** 1.0  
**Referências:** [ADR-005](../decisions/ADR-005-calculo-score.md) · [ADR-007](../decisions/ADR-007-estrutura-codigo.md)

---

## Entidades e Relacionamentos

```mermaid
erDiagram
    CLIENTE {
        string cpf PK "Ex: 123.456.789-00"
        string nome
        date data_nascimento
        float limite_credito "Limite atual em R$"
        int score "Score de crédito (0-1300)"
    }

    SOLICITACAO_AUMENTO {
        string id PK "UUID gerado"
        string cpf FK
        float limite_atual
        float limite_solicitado
        string status "aprovado | reprovado | pendente"
        datetime criado_em
    }

    SESSAO_REDIS {
        string thread_id PK "session_id do Streamlit"
        json messages "Histórico completo de mensagens"
        json cliente_autenticado "Dados do cliente após auth"
        string agente_ativo "triagem|credito|entrevista|cambio"
        int tentativas_auth "Contador: máx 3"
        bool encerrado "Flag de fim de conversa"
        datetime expires_at "TTL 30 minutos"
    }

    CLIENTE ||--o{ SOLICITACAO_AUMENTO : "faz"
    CLIENTE ||--o| SESSAO_REDIS : "tem sessão ativa"
```

---

## Estrutura dos CSVs

### `clientes.csv`

| Campo | Tipo | Exemplo | Observação |
|-------|------|---------|------------|
| `cpf` | string | `123.456.789-00` | Chave primária, com máscara |
| `nome` | string | `João Silva` | Nome completo |
| `data_nascimento` | date | `1990-01-15` | Formato ISO: YYYY-MM-DD |
| `limite_credito` | float | `5000.00` | Limite atual em R$ |
| `score` | int | `650` | Score atual (0–1300) |

### `solicitacoes_aumento_limite.csv`

| Campo | Tipo | Exemplo | Observação |
|-------|------|---------|------------|
| `id` | string | `uuid4` | Gerado automaticamente |
| `cpf` | string | `123.456.789-00` | FK para clientes.csv |
| `limite_atual` | float | `5000.00` | Limite no momento da solicitação |
| `limite_solicitado` | float | `10000.00` | Novo limite pedido |
| `status` | string | `aprovado` | aprovado \| reprovado \| pendente |
| `criado_em` | datetime | `2026-04-22T10:30:00` | Timestamp ISO 8601 |

---

## Estado da Conversa — `BancoAgilState`

Estrutura TypedDict que trafega pelo grafo LangGraph (ver [ADR-003](../decisions/ADR-003-handoff-agentes.md)):

```python
class BancoAgilState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    cliente_autenticado: Optional[dict]   # None até autenticar
    agente_ativo: str                     # "triagem" | "credito" | "entrevista" | "cambio"
    tentativas_auth: int                  # 0, 1, 2 — encerra na 3ª falha
    encerrado: bool                       # True = encerra o loop
```

---

## Fluxo de dados (score)

```mermaid
graph LR
    Entrevista -->|"coleta dados via LLM"| Dados["renda, emprego\ndependentes, dívidas"]
    Dados -->|"chama @tool"| ScoreCalc["score_calculator.py"]
    ScoreCalc -->|"fórmula Python\ndeterminística"| Score["score: int"]
    Score -->|"atualiza"| CSV["clientes.csv\ncoluna: score"]
    Score -->|"armazena em"| State["BancoAgilState\n.score_calculado"]
```
