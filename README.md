# Banco Ágil — Agente Bancário Inteligente

Sistema de atendimento ao cliente para o banco digital fictício **Banco Ágil**, construído com múltiplos agentes de IA orquestrados por **LangGraph**. O cliente interage com um único chat e os agentes trabalham nos bastidores, fazendo handoffs imperceptíveis conforme o assunto muda.

---

## Visão Geral

O Banco Ágil oferece quatro agentes especializados que colaboram em um único grafo de estados:

| Agente | Responsabilidade |
|--------|-----------------|
| **Triagem** | Autentica o cliente (CPF + data de nascimento) e identifica a intenção |
| **Crédito** | Consulta limite, processa solicitações de aumento e verifica score |
| **Entrevista de Crédito** | Conduz entrevista financeira e recalcula score com fórmula ponderada |
| **Câmbio** | Consulta cotações em tempo real via Tavily |

**Diferenciais técnicos implementados além do escopo mínimo:**
- Router de intenção baseado em LLM (sem keyword matching)
- Memória semântica por cliente no Qdrant (histórico entre sessões)
- Persistência de sessão com Redis + LangGraph checkpointing
- Pipeline de decisão de crédito em duas fases (Flash coleta → Pro decide)
- Formulário de captura de leads para clientes não encontrados na base

---

## Arquitetura do Sistema

### Grafo LangGraph

```
                    ┌─────────────────┐
  Usuário ──────▶  │  agente_triagem │ ◀──────────────────────┐
                    └────────┬────────┘                        │
                             │ autenticado + intenção          │ troca de assunto
                    ┌────────▼────────┐                        │
                    │     router()    │ ── encerrado ──▶ [salvar_memoria] ──▶ END
                    └────────┬────────┘
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
    ┌──────────────┐  ┌────────────┐  ┌─────────────┐
    │agente_credito│  │agente_     │  │agente_cambio│
    │              │  │entrevista  │  │             │
    └──────┬───────┘  └─────┬──────┘  └─────────────┘
           │ score baixo    │ recalcular
           └────────────────┘
```

### Fluxo de dados

```
Mensagem do usuário
    │
    ├─▶ [Redis] Recupera checkpoint da sessão (LangGraph)
    │
    ├─▶ [agente_triagem]
    │       ├─▶ Se não autenticado: extrai CPF + data → busca clientes.csv
    │       │       └─▶ Se autenticado: busca memórias no Qdrant (por CPF)
    │       └─▶ Se autenticado: [LLM] classifica intenção → router()
    │
    ├─▶ [agente_credito / agente_entrevista / agente_cambio]
    │       ├─▶ Injeta dados do cliente + memórias no system prompt
    │       ├─▶ Executa tools (CSV, score, Tavily) inline
    │       └─▶ Retorna AIMessage
    │
    ├─▶ [Redis] Salva checkpoint atualizado
    │
    └─▶ Se encerrado: [salvar_memoria] → gera resumo LLM → grava no Qdrant
```

### Persistência e memória

| Componente | Uso |
|---|---|
| **Redis** | Checkpointing do LangGraph (estado da conversa por sessão) |
| **Qdrant** | Memória semântica por cliente — busca pelo CPF nos metadados |
| **clientes.csv** | Base de autenticação e scores |
| **solicitacoes_aumento_limite.csv** | Registro de pedidos de aumento |
| **leads.csv** | Clientes não encontrados que preencheram o formulário |

---

## Funcionalidades Implementadas

### Agente de Triagem
- Saudação inicial e coleta de CPF + data de nascimento
- Autenticação contra `clientes.csv` (até 3 tentativas, depois encerra)
- Identificação de intenção via LLM (não keyword matching)
- Handoff imperceptível: o cliente não sabe que "trocou de agente"
- Busca de memórias semânticas do cliente no Qdrant após autenticação

### Agente de Crédito
- Consulta de limite de crédito disponível
- Solicitação de aumento: registra em `solicitacoes_aumento_limite.csv`
- Verificação de score: aprovação automática se score ≥ 500
- Rejeição com oferta de redirecionamento para Entrevista de Crédito

### Agente de Entrevista de Crédito
- Coleta estruturada: renda, tipo de emprego, despesas, dependentes, dívidas
- Cálculo determinístico de score (Python puro, não LLM) com fórmula ponderada
- Atualização do score em `clientes.csv`
- Redirecionamento automático de volta ao Agente de Crédito

### Agente de Câmbio
- Consulta em tempo real via Tavily Search API
- Execução de tool call inline (sem anunciar "vou verificar")
- Suporte a qualquer moeda: dólar, euro, libra, iene etc.

### Extras além do escopo
- **Memória semântica por cliente (Qdrant)**: o agente "lembra" de interações anteriores
- **Persistência de sessão (Redis)**: conversa continua após recarregar a página
- **Formulário de leads**: clientes não cadastrados podem solicitar cadastro
- **ADRs documentados**: 8 Architecture Decision Records explicando cada escolha

---

## Desafios Enfrentados e Soluções

### 1. GraphRecursionError — loop infinito no grafo
**Problema:** O LangGraph continuava re-executando o mesmo nó após o agente responder, atingindo o limite de recursão (25 iterações).

**Causa:** A função `router()` não detectava que o turno havia terminado, pois não verificava se a última mensagem era uma `AIMessage`.

**Solução:** Adicionamos uma condição explícita no `router()`:
```python
if msgs and isinstance(msgs[-1], AIMessage):
    return END
```

### 2. Keyword matching frágil para intenção
**Problema:** A frase "quero comprar dólares com meu crédito" era roteada incorretamente para o Agente de Crédito porque "crédito" aparecia na mensagem.

**Solução:** Substituímos o keyword matching por uma chamada focada ao LLM (`intent_classifier.py`) com `temperature=0` e `max_output_tokens=10`. O modelo classifica a intenção com muito mais precisão, incluindo uma regra de desempate câmbio > crédito.

### 3. Agente anunciava a consulta antes de executar
**Problema:** O Agente de Câmbio enviava uma mensagem dizendo "vou verificar a cotação" mas, como já havia consumido o turno, não conseguia enviar o resultado na mesma interação.

**Solução:** Implementamos execução de tool calls inline dentro do nó LangGraph:
1. LLM decide chamar a tool
2. Tool executa imediatamente no mesmo nó
3. LLM recebe o resultado e formula a resposta final
4. O router vê apenas a AIMessage final (sem `tool_calls` pendentes)

### 4. Triagem interferindo nos agentes especialistas
**Problema:** Após a autenticação, cada mensagem passava pela triagem antes de chegar ao agente especialista, gerando respostas genéricas indesejadas.

**Solução:** Implementamos "passthrough silencioso": se um agente especialista já está ativo e a mensagem não indica troca de assunto ou encerramento, a triagem retorna `{}` sem invocar LLM, e o router encaminha diretamente ao agente ativo.

---

## Escolhas Técnicas e Justificativas

| Decisão | Alternativas | Justificativa |
|---------|-------------|---------------|
| **LangGraph** | CrewAI, AutoGen | Grafo explícito de estados com edges condicionais — handoff imperceptível sem troca de contexto |
| **Gemini 2.0 Flash** | GPT-4o, Claude | Free tier generoso, excelente em português, suporte nativo a tool calling |
| **Redis** para checkpointing | Memória local, SQLite | Produção-ready, TTL configurável, suporte nativo no LangGraph |
| **Qdrant** para memória semântica | ChromaDB, Pinecone | Self-hosted, filtros por metadados (isolamento por CPF), dimensão 3072 |
| **Score em Python** | LLM calcular | Determinismo e auditabilidade — cálculo financeiro não pode ser não-determinístico |
| **Tavily** para câmbio | SerpAPI, Alpha Vantage | Integração nativa com LangChain, free tier adequado |
| **Streamlit** | Gradio, FastAPI+React | Desenvolvimento rápido, componentes de chat nativos, sidebar para features extras |

Para cada decisão, existe um ADR detalhado em `docs/decisions/`.

---

## Tutorial de Execução

### Pré-requisitos
- Python 3.11+
- Redis rodando na porta 6379
- Qdrant rodando na porta 6333
- Chave da API Gemini (Google AI Studio — free tier)
- Chave da API Tavily (free tier)

### Opção A — Infraestrutura local com Docker
```bash
# Redis
docker run -d --name redis-banco-agil -p 6379:6379 redis:alpine

# Qdrant
docker run -d --name qdrant-banco-agil -p 6333:6333 qdrant/qdrant
```

### Opção B — VPS via SSH tunnel
```bash
ssh -i ~/.ssh/chave.key \
    -L 5432:127.0.0.1:5432 \
    -L 6333:127.0.0.1:6333 \
    -L 6379:127.0.0.1:6379 \
    usuario@ip-do-servidor -N
```

### Instalação
```bash
# 1. Clonar o repositório
git clone <url-do-repo>
cd agente-bancario-banco-agil

# 2. Criar e ativar ambiente virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com suas chaves de API
```

### Configuração do `.env`
```env
GEMINI_API_KEY=sua_chave_do_google_ai_studio
GEMINI_MODEL=gemini-2.0-flash
TAVILY_API_KEY=sua_chave_do_tavily

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=           # deixar vazio se Redis local sem senha

QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=           # deixar vazio se Qdrant local sem autenticação
```

### Inicializar collections do Qdrant
```bash
python scripts/setup_qdrant.py
```

### Executar a aplicação
```bash
streamlit run app.py
```

Acesse `http://localhost:8501` no navegador.

### Executar os testes
```bash
pytest tests/ -v
```

### Dados de teste (clientes cadastrados)

| Nome | CPF | Data de Nascimento | Limite | Score |
|------|-----|--------------------|--------|-------|
| Ana Silva | 123.456.789-00 | 15/01/1990 | R$ 5.000 | 650 |
| Bruno Costa | 987.654.321-00 | 22/08/1985 | R$ 3.000 | 420 |
| Carla Mendes | 111.222.333-44 | 30/03/1995 | R$ 8.000 | 780 |

> **Dica:** Use o CPF com máscara (`123.456.789-00`) ou só os números (`12345678900`) — o agente aceita os dois formatos.

---

## Estrutura do Projeto

```
banco-agil/
├── app.py                          # Interface Streamlit
├── requirements.txt
├── .env.example
├── data/
│   ├── clientes.csv                # Base de clientes para autenticação
│   └── solicitacoes_aumento_limite.csv
├── src/
│   ├── config.py                   # Variáveis de ambiente centralizadas
│   ├── graph.py                    # StateGraph LangGraph + router()
│   ├── agents/
│   │   ├── triagem.py              # Autenticação e roteamento
│   │   ├── credito.py              # Limite e aumento de crédito
│   │   ├── entrevista.py           # Entrevista financeira e score
│   │   └── cambio.py              # Cotação de moedas
│   ├── prompts/                    # System prompts em Markdown
│   ├── tools/
│   │   ├── csv_repository.py       # CRUD nos arquivos CSV
│   │   ├── score_calculator.py     # Cálculo determinístico de score
│   │   ├── exchange_rate.py        # Tool Tavily para câmbio
│   │   └── intent_classifier.py   # Classificador de intenção via LLM
│   ├── models/
│   │   ├── state.py                # BancoAgilState (TypedDict)
│   │   └── schemas.py              # Dataclasses Cliente e Solicitação
│   └── infrastructure/
│       ├── checkpointer.py         # Redis checkpointer (fallback: MemorySaver)
│       └── qdrant_memory.py        # Memória semântica por CPF
├── docs/
│   ├── decisions/                  # 8 ADRs — Architecture Decision Records
│   ├── diagrams/                   # Diagramas Mermaid (arquitetura, grafo, dados)
│   └── flows/                      # Fluxos de sequência por cenário
├── scripts/
│   └── setup_qdrant.py             # Inicializa collections no Qdrant
└── tests/
    ├── test_score_calculator.py
    └── test_csv_repository.py
```
