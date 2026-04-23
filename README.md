# Banco Ágil — Agente de Atendimento com IA

Assistente bancário digital construído com **LangGraph**, **Gemini** e **React**, desenvolvido como desafio técnico para a posição de Desenvolvedor de Agentes de IA.

## Visão geral

O sistema simula o atendimento digital de um banco moderno. Um cliente interage com um único assistente via chat web que, de forma transparente, roteia cada intenção para o agente especialista correto — sem que o cliente perceba as transições internas.

**Fluxo principal:**

```
Identificação do cliente (AuthCard)
       ↓
Agente de Triagem — autenticação CPF + data de nascimento
       ↓
Router inteligente (classificador LLM + resposta_final)
       ↓
┌──────────────┬──────────────┬──────────────────────┐
│   Crédito    │    Câmbio    │  Entrevista Financeira│
│ Flash → Pro  │  Tool call   │  Coleta + Recalcula   │
└──────────────┴──────────────┴──────────────────────┘
       ↓
salvar_memoria (Qdrant) → END
```

---

## Arquitetura

### Camadas

```
┌────────────────────────────────────────────────────┐
│  Frontend React 18 + TypeScript + Vite + Tailwind  │
│  AuthCard  ChatMessage  ContactCard  MessageComposer│
└──────────────────────┬─────────────────────────────┘
                       │ HTTP (Vite proxy → :8000)
┌──────────────────────▼─────────────────────────────┐
│  FastAPI Bridge  api/main.py                        │
│  POST /api/chat   GET /api/conversations            │
│  GET /api/debug/logs                               │
└──────────────────────┬─────────────────────────────┘
                       │ graph.invoke()
┌──────────────────────▼─────────────────────────────┐
│  LangGraph  src/graph.py                            │
│  triagem → credito → entrevista → cambio            │
│                              ↓                      │
│  Router determinístico (resposta_final / encerrado) │
│                              ↓                      │
│  salvar_memoria → END                               │
└────────────┬────────────────┬────────────────────────┘
             │                │
     ┌───────▼──────┐ ┌───────▼──────┐
     │  Redis       │ │  Qdrant      │
     │ Checkpoints  │ │ Memória      │
     │  de estado   │ │ semântica    │
     └──────────────┘ └──────────────┘
```

### Persistência

| Camada | Tecnologia | O que armazena |
|---|---|---|
| Estado da conversa | Redis (LangGraph Checkpointer) | Mensagens, campos de estado, thread_id |
| Memória semântica | Qdrant | Resumos de sessões anteriores por CPF |
| Dados de clientes | CSV local | CPF, nome, data de nascimento, limite, score |

---

## Funcionalidades

### Autenticação com guardrail
- AuthCard no frontend coleta CPF e data de nascimento via campos estruturados com máscara
- Triagem verifica contra o CSV de clientes
- Máximo de 3 tentativas; na falha final o chat é bloqueado e o `ContactCard` exibe canais de atendimento

### Contratos de resposta (anti-alucinação)
- Cada agente define contratos em `contract.py` que validam se a resposta LLM contém os valores ground-truth (limite, score, cotação)
- Se o contrato não for satisfeito, o framework faz retry com prompt corretivo
- Último recurso: injeção programática do valor real

### Roteamento via LLM
- Classificador Gemini com `temperature=0` e `max_output_tokens=10` categoriza a intenção
- Cache com TTL de 5 min para mensagens repetidas
- Categorias: `credito | cambio | encerrar | nenhum`

### Pipeline Flash → Pro (crédito)
- **Flash**: coleta dados, aciona tools (`verificar_elegibilidade`, `registrar_pedido`)
- **Pro**: recebe contexto completo e formula a decisão final com empatia
- Consultas simples (saldo, limite) encurtam o pipeline usando só o Flash

### Memória semântica contextual
- Ao encerrar, o nó `salvar_memoria` gera um resumo via LLM e persiste no Qdrant
- Na próxima autenticação, interações anteriores são injetadas no contexto de cada agente

### Cotação de câmbio em tempo real
- Agente de câmbio usa Tavily para buscar cotações reais (USD, EUR, GBP, JPY, CAD)
- Contrato valida presença de valor `R$` na resposta

---

## Decisões técnicas (ADRs)

| # | Decisão | Status |
|---|---|---|
| ADR-001 | LangGraph como framework de orquestração | Aceito |
| ADR-002 | Gemini 2.0 Flash como modelo principal | Aceito |
| ADR-003 | Handoff implícito via grafo único | Aceito |
| ADR-004 | Redis para persistência de estado | Aceito |
| ADR-005 | Cálculo de score em Python (sem LLM) | Aceito |
| ADR-006 | Tavily para cotação de câmbio | Aceito |
| ADR-007 | Estrutura modular por agente | Aceito |
| ADR-008 | Captura de leads pós-falha de auth | Aceito |
| ADR-009 | Classificador de intenção via LLM | Aceito |
| ADR-010 | Memória semântica com Qdrant | Aceito |
| ADR-011 | Cache do classificador com TTL | Aceito |
| ADR-012 | Resiliência com fallback de modelo | Aceito |
| ADR-013 | Pipeline Flash → Pro para crédito | Aceito |
| ADR-014 | Sistema de contratos de resposta | Aceito |

Todos os ADRs em `docs/decisions/`.

---

## Estrutura do projeto

```
.
├── api/
│   └── main.py                  # FastAPI bridge (React → LangGraph)
├── frontend/
│   ├── src/app/
│   │   ├── components/          # AuthCard, ContactCard, ChatMessage …
│   │   ├── services/api.ts      # HTTP client (sendChatMessage, etc.)
│   │   └── App.tsx              # Orquestração de estado do chat
│   └── docs/ADR-001-stack-frontend.md
├── src/
│   ├── agents/
│   │   ├── triagem/             # Autenticação e roteamento
│   │   │   ├── agent.py
│   │   │   ├── contract.py      # contrato_consulta_financeira
│   │   │   ├── prompt.md
│   │   │   └── __init__.py
│   │   ├── credito/             # Pipeline Flash → Pro
│   │   │   ├── agent.py
│   │   │   ├── contract.py      # contrato_flash_direto, contrato_sintese_pro
│   │   │   ├── prompt.md
│   │   │   ├── prompt_pro.md
│   │   │   └── __init__.py
│   │   ├── cambio/              # Cotação de moedas via Tavily
│   │   │   ├── agent.py
│   │   │   ├── contract.py      # contrato_cotacao
│   │   │   ├── prompt.md
│   │   │   └── __init__.py
│   │   └── entrevista/          # Coleta financeira e recálculo de score
│   │       ├── agent.py
│   │       ├── contract.py      # contrato_resultado_entrevista
│   │       ├── prompt.md
│   │       └── __init__.py
│   ├── infrastructure/
│   │   ├── response_contract.py # Framework de contratos (base)
│   │   ├── logging_config.py    # Log centralizado + tail_log()
│   │   ├── model_provider.py    # invocar_com_fallback, tiers fast/pro
│   │   ├── checkpointer.py      # RedisSaver para LangGraph
│   │   ├── qdrant_memory.py     # buscar_memorias, salvar_interacao
│   │   └── cache.py             # CacheComTTL + decorator com_cache
│   ├── models/
│   │   └── state.py             # BancoAgilState (TypedDict)
│   ├── tools/
│   │   ├── csv_repository.py    # buscar_cliente, atualizar_score
│   │   ├── intent_classifier.py # classificar_intencao (LLM + cache)
│   │   ├── credit_tools.py      # verificar_elegibilidade, registrar_pedido
│   │   ├── score_calculator.py  # calcular_score_credito, score_aprovado
│   │   └── exchange_rate.py     # criar_tool_cambio (Tavily)
│   ├── graph.py                 # StateGraph: nós, edges, router, singleton
│   └── config.py                # Variáveis de ambiente
├── data/
│   └── clientes.csv             # Base de clientes de teste
├── docs/
│   ├── decisions/               # ADR-001 a ADR-014
│   ├── diagrams/                # Arquitetura, grafo, modelo de dados
│   └── flows/                   # Fluxos de autenticação, handoff, crédito
├── .env.example
├── requirements.txt
└── README.md
```

---

## Instalação e execução

### Pré-requisitos
- Python 3.11+
- Node.js 20+ / pnpm 9+
- Redis e Qdrant acessíveis (local ou via SSH tunnel)
- Chaves de API: `GOOGLE_API_KEY`, `TAVILY_API_KEY`

### Backend

```bash
# 1. Ambiente virtual e dependências
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt

# 2. Variáveis de ambiente
cp .env.example .env
# Edite .env com suas chaves

# 3. Iniciar API
uvicorn api.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev        # Dev server em http://localhost:5173
pnpm build      # Build de produção
```

### Túnel SSH (bancos na VPS)

```bash
ssh -i ~/.ssh/sua-chave.key \
  -L 5432:127.0.0.1:5432 \
  -L 6333:127.0.0.1:6333 \
  -L 6379:127.0.0.1:6379 \
  usuario@seu-servidor -N
```

---

## Dados de teste

| CPF | Nome | Data de nascimento | Limite | Score |
|---|---|---|---|---|
| 123.456.789-00 | Ana Silva | 15/01/1990 | R$ 5.000 | 650 |
| 987.654.321-00 | Carlos Mendes | 22/07/1985 | R$ 3.000 | 320 |
| 456.789.123-00 | Maria Oliveira | 10/03/1995 | R$ 8.000 | 780 |
| 321.654.987-00 | João Santos | 30/11/1978 | R$ 1.500 | 180 |
| 789.123.456-00 | Fernanda Lima | 05/05/2000 | R$ 10.000 | 850 |

---

## Diagnóstico

### Logs estruturados
```bash
# Tail dos últimos 100 logs via API
curl http://localhost:8000/api/debug/logs?n=100
```

O sistema usa logging rotativo em `logs/banco_agil.log` com nível `DEBUG` configurável via `.env`.

---

## Diferenciais implementados

| Funcionalidade | Detalhe |
|---|---|
| **Contratos de resposta** | Sistema de validação LLM com retry e fallback programático — previne alucinações de dados financeiros |
| **Identidade única** | Nenhum agente menciona "transferência" ou "especialista"; filtro regex em todas as respostas |
| **Estrutura modular** | Cada agente é um módulo Python independente com código, prompt e contrato co-localizados |
| **Pipeline Flash→Pro** | Decisões de crédito têm fase rápida de coleta e fase de síntese com raciocínio rico |
| **Memória semântica** | Histórico de sessões em Qdrant é injetado no contexto a cada novo atendimento |
| **AuthCard** | Input estruturado com máscara de CPF e data — mais robusto que texto livre |
| **ContactCard** | Após 3 falhas de auth, exibe canais reais de atendimento e bloqueia o chat |
| **Logging de debug** | Endpoint `/api/debug/logs` permite diagnóstico sem acesso ao servidor |
