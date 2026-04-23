# ADR-007: Estrutura de Código e Separação de Responsabilidades

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

A organização do código impacta diretamente a legibilidade, manutenibilidade e a impressão que o avaliador terá ao navegar pelo repositório. O case exige explicitamente:

> *"Estrutura organizada do código (divisão clara por módulos e responsabilidades dos agentes)."*

A decisão central é como separar: lógica dos agentes, prompts do sistema, ferramentas, modelos de dados e infraestrutura.

---

## Decisão

**Escolha:** Arquitetura modular com separação explícita de prompts

Cada agente vive em seu próprio módulo. Os prompts do sistema são arquivos `.md` separados do código Python, carregados em runtime. As ferramentas são módulos independentes e reutilizáveis.

---

## Estrutura adotada

```
banco-agil/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── triagem.py          ← nó do grafo + lógica de autenticação
│   │   ├── credito.py          ← nó do grafo + lógica de crédito
│   │   ├── entrevista.py       ← nó do grafo + condução da entrevista
│   │   └── cambio.py           ← nó do grafo + chamada de câmbio
│   ├── prompts/
│   │   ├── triagem.md          ← system prompt do agente de triagem
│   │   ├── credito.md          ← system prompt do agente de crédito
│   │   ├── entrevista.md       ← system prompt do agente de entrevista
│   │   └── cambio.md           ← system prompt do agente de câmbio
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── csv_repository.py   ← leitura/escrita de CSVs
│   │   ├── score_calculator.py ← cálculo de score (ver ADR-005)
│   │   └── exchange_rate.py    ← integração Tavily (ver ADR-006)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── state.py            ← BancoAgilState (TypedDict do grafo)
│   │   └── schemas.py          ← dataclasses para Cliente, Solicitacao
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   └── checkpointer.py     ← setup do Redis (ver ADR-004)
│   ├── graph.py                ← montagem do StateGraph e edges
│   └── config.py               ← variáveis de ambiente e constantes
├── app.py                      ← entrypoint Streamlit
├── data/
│   ├── clientes.csv
│   └── solicitacoes_aumento_limite.csv
├── docs/
│   ├── decisions/              ← ADRs
│   ├── diagrams/               ← diagramas de arquitetura
│   └── flows/                  ← fluxos de sequência
├── tests/
│   ├── test_score_calculator.py
│   ├── test_csv_repository.py
│   └── test_agents/
├── .env.example
├── requirements.txt
└── README.md
```

---

## Justificativa

### Por que prompts como arquivos `.md` separados?

**"Prompt as Configuration"** — o mesmo princípio de separar configuração de código:

1. **Iteração rápida:** Ajustar o tom do agente sem tocar no código Python
2. **Versionamento explícito:** `git diff prompts/triagem.md` mostra exatamente o que mudou no comportamento
3. **Legibilidade:** Um prompt de 50 linhas no meio de código Python polui o arquivo
4. **Testabilidade:** Permite testar variações de prompt independentemente da lógica

```python
# src/agents/triagem.py — carregamento do prompt
from pathlib import Path

def carregar_prompt(nome: str) -> str:
    caminho = Path(__file__).parent.parent / "prompts" / f"{nome}.md"
    return caminho.read_text(encoding="utf-8")

SYSTEM_PROMPT = carregar_prompt("triagem")
```

### Por que `models/state.py` separado?

O `BancoAgilState` é o contrato entre todos os agentes. Isolá-lo em um arquivo próprio:
- Torna as dependências explícitas
- Evita imports circulares
- Facilita entender o que cada agente lê/escreve

### Por que `graph.py` separado dos agentes?

Montagem do grafo (`StateGraph`, `add_node`, `add_edge`, `compile`) é infraestrutura, não lógica de negócio. Separar permite:
- Testar agentes individualmente sem instanciar o grafo completo
- Visualizar a topologia do sistema em um único arquivo

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **Tudo em `app.py`** | Rápido de criar | Impossível de manter, mistura responsabilidades | Viola requisito explícito do case |
| **Prompts inline no código** | Menos arquivos | Dificulta iteração, polui lógica Python | Boas práticas de engenharia de prompts |
| **Um arquivo por feature** (auth.py, credit.py...) | Alternativo | Não alinha com responsabilidade por agente | Menos intuitivo para o contexto multi-agente |

---

## Consequências

**Positivas:**
- Código navegável — avaliador encontra cada coisa em 10 segundos
- Prompts versionados e legíveis
- Tools reutilizáveis entre agentes
- Testes unitários possíveis para cada camada

**Negativas / trade-offs aceitos:**
- Mais arquivos para gerenciar que uma solução monolítica
- Carregamento de prompts em runtime adiciona leitura de arquivo na inicialização (negligível)

---

## Referências

- [Prompt Engineering — Prompt as Configuration pattern](https://www.promptingguide.ai/)
- [Clean Architecture — separação de camadas](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [ADR-003](ADR-003-handoff-agentes.md) — Estrutura do BancoAgilState
- [ADR-004](ADR-004-persistencia-estado.md) — Infraestrutura Redis
