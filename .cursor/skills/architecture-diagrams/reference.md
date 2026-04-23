# Referência de Diagramas Mermaid

## Tipos disponíveis

| Tipo | Sintaxe | Uso |
|------|---------|-----|
| Fluxo | `graph TD` ou `graph LR` | Arquitetura geral, dependências |
| Sequência | `sequenceDiagram` | Interações entre agentes (ver system-flows) |
| Classes | `classDiagram` | Estrutura de código, herança |
| Estado | `stateDiagram-v2` | Máquinas de estado, ciclo de vida |
| ER | `erDiagram` | Modelo de dados |
| Gantt | `gantt` | Cronograma de entrega |

## Diagrama de Estado (exemplo para autenticação)

```mermaid
stateDiagram-v2
    [*] --> Aguardando
    Aguardando --> ColetandoCPF : cliente conecta
    ColetandoCPF --> ColetandoData : CPF recebido
    ColetandoData --> Autenticando : data recebida
    Autenticando --> Autenticado : sucesso
    Autenticando --> Tentativa2 : falha (1ª)
    Tentativa2 --> Autenticando : nova tentativa
    Tentativa2 --> Tentativa3 : falha (2ª)
    Tentativa3 --> Encerrado : falha (3ª)
    Autenticado --> [*]
    Encerrado --> [*]
```

## Diagrama ER (exemplo para modelo de dados)

```mermaid
erDiagram
    CLIENTE {
        string cpf PK
        string nome
        date data_nascimento
        float limite_credito
        int score
    }
    SOLICITACAO {
        string id PK
        string cpf FK
        float limite_solicitado
        string status
        datetime criado_em
    }
    CLIENTE ||--o{ SOLICITACAO : "faz"
```
