# Consciência Coletiva — IA para o Mercado de Carbono Regulado

Sistema de inteligência artificial baseado em **Mixture of Experts (MoE)** para co-escrita, análise e consultoria sobre o mercado regulado de carbono brasileiro, fundamentado na **Lei 15.042/2024 (SBCE)**.

## Visão Geral

A Consciência Coletiva opera como um ecossistema de 24 especialistas de IA + 1 handler de upload, orquestrados por uma IA superior que roteia consultas em linguagem natural para os experts corretos via function calling.

**Unidade de medida padrão:** tonelada de dióxido de carbono equivalente (tCO₂e)

### Categorias de Especialistas

| Categoria | Exemplos |
|-----------|----------|
| Jurídico | Elegibilidade, Sanções/Multas, Governança, Transparência Internacional |
| Técnico | REDD+, MRV, Sumidouros, Inventário de Emissões, Registro de Créditos |
| Financeiro | Mercado de Capitais (CVM), Tributação, Leilões de CBE, Precificação |
| Setorial | Agropecuária, Resíduos Sólidos, Indústria, Energia |
| Social | Povos Indígenas, Comunidades Quilombolas, Reforma Agrária, Repartição de Benefícios |
| Transversal | Compliance, Planos Setoriais, Comparativos Internacionais |

## Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Framework Web | FastAPI (async) |
| LLM Primário | Google Gemini 2.5 (Lite / Flash / Pro) |
| LLM Fallback | OpenAI GPT-4o, Groq Llama 70B |
| Banco Vetorial | Qdrant (25 coleções isoladas) |
| Banco Relacional | PostgreSQL |
| Cache | Redis |
| Embeddings | Gemini embedding-001 (768d) |
| Autenticação | JWT Bearer Token |

## Estrutura do Projeto

```
backend/
├── main.py                        # Endpoints FastAPI
├── config.py                      # Configurações centralizadas
├── agent/
│   ├── orchestrator.py            # Orquestrador MoE (Fast → Pro)
│   ├── prompts_carbono.py         # System prompt da Consciência Coletiva
│   ├── router_carbono.py          # Classificação de intents
│   ├── upload_handler.py          # Ingestão de documentos do usuário
│   ├── providers.py               # Abstração multi-LLM com fallback
│   ├── experts/
│   │   ├── expert_profiles.py     # 24 perfis de especialistas
│   │   ├── expert_definitions.py  # Definições de tools (function calling)
│   │   └── expert_rag_executor.py # Executores RAG genéricos
│   └── tools/
│       ├── __init__.py            # Registro de executores
│       ├── web_search.py          # Busca na web
│       ├── chart_generator.py     # Geração de gráficos
│       └── criar_grafico_customizado.py
├── memory/
│   ├── vector_store.py            # Interface Qdrant (25 coleções)
│   ├── memory_manager.py          # Gestão de memória conversacional
│   └── embeddings/                # Providers de embedding
└── models/
    └── schemas.py                 # Schemas Pydantic
```

## Quick Start

```bash
# 1. Clonar e configurar
cd backend
cp .env.example .env
# Editar .env com suas chaves de API

# 2. Iniciar venv e instalar dependências
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# 3. Subir infraestrutura
# PostgreSQL, Redis e Qdrant devem estar rodando

# 4. Iniciar o servidor
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Requisitos de Saída

- **Rastreabilidade**: toda resposta indica qual especialista foi consultado, a linha de raciocínio e os artigos da Lei 15.042/2024 que fundamentaram a conclusão
- **Co-autoria**: o sistema permite a evolução colaborativa de textos entre usuário e IA
- **Multi-expert**: consultas complexas ativam múltiplos especialistas em paralelo

## Documentação

- [Arquitetura MoE](./docs/ARQUITETURA_MOE.md) — Visão geral da arquitetura de agentes
- [Catálogo de Especialistas](./docs/CATALOGO_ESPECIALISTAS.md) — Detalhamento dos 24 especialistas
- [API de Carbono](./docs/API_CARBONO.md) — Referência completa dos endpoints
- [Guia de Setup e Deploy](./docs/SETUP_DEPLOY.md) — Configuração, ingestão de dados e deploy
