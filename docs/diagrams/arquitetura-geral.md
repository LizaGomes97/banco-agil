# Diagrama: Arquitetura Geral do Sistema

**Data:** 2026-04-22  
**Versão:** 1.0  
**Referências:** [ADR-001](../decisions/ADR-001-framework-agentes.md) · [ADR-003](../decisions/ADR-003-handoff-agentes.md) · [ADR-004](../decisions/ADR-004-persistencia-estado.md)

---

## Visão de Camadas

```mermaid
graph TD
    subgraph UI["🖥️ Camada de Apresentação"]
        Streamlit["Streamlit App\n(app.py)"]
    end

    subgraph Graph["🤖 Camada de Orquestração — LangGraph StateGraph"]
        Router{{"Router\n(edges condicionais)"}}

        subgraph Agents["Agentes Especializados"]
            AT["Agente Triagem\nagents/triagem.py"]
            AC["Agente Crédito\nagents/credito.py"]
            AE["Agente Entrevista\nagents/entrevista.py"]
            ACB["Agente Câmbio\nagents/cambio.py"]
        end

        State[["BancoAgilState\nmodels/state.py"]]
    end

    subgraph Tools["🔧 Camada de Ferramentas"]
        CSV["csv_repository.py\nclientes.csv\nsolicitacoes.csv"]
        Score["score_calculator.py\nFórmula ponderada"]
        Tavily["exchange_rate.py\nTavily Search API"]
    end

    subgraph LLM["🧠 Camada de Linguagem"]
        Gemini["Gemini 2.0 Flash\nGoogle AI API"]
    end

    subgraph Infra["🗄️ Camada de Infraestrutura"]
        Redis[("Redis\nCheckpointer\nEstado por thread_id")]
    end

    Streamlit -->|"mensagem do usuário"| Router
    Router --> AT & AC & AE & ACB
    AT & AC & AE & ACB <-->|"lê/escreve"| State
    AT -->|"autenticar()"| CSV
    AC -->|"consultar/registrar()"| CSV
    AE -->|"calcular_score()"| Score
    ACB -->|"buscar_cotacao()"| Tavily
    AT & AC & AE & ACB -->|"tool calling"| Gemini
    State <-->|"checkpoint"| Redis
    Router <---|"resposta ao usuário"| Streamlit
```

---

## Visão de Componentes (mais detalhada)

```mermaid
graph LR
    subgraph src["src/"]
        direction TB
        graph_py["graph.py\nMonta o StateGraph\nDefine nós e edges"]

        subgraph agents_dir["agents/"]
            triagem["triagem.py"]
            credito["credito.py"]
            entrevista["entrevista.py"]
            cambio["cambio.py"]
        end

        subgraph prompts_dir["prompts/"]
            pt["triagem.md"]
            pc["credito.md"]
            pe["entrevista.md"]
            pcb["cambio.md"]
        end

        subgraph tools_dir["tools/"]
            csv_r["csv_repository.py"]
            score["score_calculator.py"]
            exchange["exchange_rate.py"]
        end

        subgraph models_dir["models/"]
            state["state.py\nBancoAgilState"]
            schemas["schemas.py\nCliente, Solicitacao"]
        end

        subgraph infra_dir["infrastructure/"]
            chk["checkpointer.py\nRedisSaver"]
        end

        config["config.py\nVariáveis de ambiente"]
    end

    triagem -.->|"carrega"| pt
    credito -.->|"carrega"| pc
    entrevista -.->|"carrega"| pe
    cambio -.->|"carrega"| pcb

    graph_py -->|"importa"| agents_dir
    graph_py -->|"importa"| state
    graph_py -->|"importa"| chk
```

---

## Princípios arquiteturais ilustrados

| Camada | Responsabilidade única |
|--------|----------------------|
| `agents/` | Lógica conversacional e chamadas LLM |
| `prompts/` | Comportamento e persona do agente |
| `tools/` | Operações determinísticas (I/O, cálculos) |
| `models/` | Contratos de dados (state, schemas) |
| `infrastructure/` | Setup de serviços externos (Redis) |
| `graph.py` | Topologia do sistema (quem chama quem) |
