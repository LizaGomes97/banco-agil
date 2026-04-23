---
name: architecture-diagrams
description: Cria diagramas de arquitetura do sistema usando Mermaid. Use quando precisar visualizar a estrutura do sistema, relação entre componentes, camadas da aplicação, ou quando o usuário pedir um diagrama de arquitetura, mapa de componentes, visão geral do sistema.
---

# Diagramas de Arquitetura

Gera diagramas Mermaid que documentam visualmente a arquitetura do sistema.

## Quando usar

- Início de um novo módulo ou feature
- Após definir componentes principais do sistema
- Para comunicar decisões arquiteturais ao time/avaliador
- Sempre que uma decisão impactar a estrutura geral

## Padrão de saída

Sempre salvar o diagrama em `docs/diagrams/` com nome descritivo, por exemplo:
- `docs/diagrams/arquitetura-geral.md`
- `docs/diagrams/fluxo-agentes.md`
- `docs/diagrams/modelo-dados.md`

## Templates por tipo

### Arquitetura Geral (graph TD)

```mermaid
graph TD
    UI[Interface Streamlit] --> Orquestrador

    subgraph "Camada de Agentes"
        Orquestrador --> ATriagem[Agente Triagem]
        ATriagem --> ACredito[Agente Crédito]
        ATriagem --> AEntrevista[Agente Entrevista]
        ATriagem --> ACambio[Agente Câmbio]
    end

    subgraph "Camada de Ferramentas"
        ATriagem --> CSV[(clientes.csv)]
        ACredito --> CSVS[(solicitacoes.csv)]
        ACambio --> API[API Câmbio Externo]
    end

    subgraph "Camada LLM"
        ATriagem & ACredito & AEntrevista & ACambio --> LLM[Gemini / GPT]
    end
```

### Diagrama de Classes / Módulos (classDiagram)

```mermaid
classDiagram
    class AgentBase {
        +nome: str
        +llm: LLM
        +tools: list
        +run(mensagem): str
    }
    class AgenteTriagem {
        +autenticar(cpf, data_nasc): bool
        +identificar_intencao(msg): str
        +redirecionar(agente): Agent
    }
    AgentBase <|-- AgenteTriagem
```

### Arquitetura de Infraestrutura

```mermaid
graph LR
    Dev -->|push| GitHub
    GitHub -->|CI/CD| Docker
    Docker --> VPS
    VPS --> Streamlit
```

## Checklist antes de publicar diagrama

- [ ] Título claro e data no arquivo
- [ ] Legenda para siglas não óbvias
- [ ] Nível de detalhe adequado (nem muito simples, nem verboso demais)
- [ ] Reflete o estado **atual** do sistema (não o planejado)
- [ ] Referenciado em algum ADR ou doc de decisão

## Recursos adicionais

- Para tipos de diagrama avançados, ver [reference.md](reference.md)
