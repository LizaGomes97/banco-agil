# ADR-007 — Estrutura de Código: Módulos por Agente

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Decisores** | Equipe de desenvolvimento |
| **Substitui** | Estrutura plana com `src/agents/*.py` e `src/prompts/*.md` |

---

## Contexto

A estrutura inicial do projeto organizava cada agente como um único arquivo Python (`triagem.py`, `credito.py`, etc.) e centralizava todos os system prompts em `src/prompts/`. À medida que adicionamos contratos de resposta, prompts adicionais (ex.: `credito_pro_sintese.md`) e lógica de validação específica por agente, ficou evidente que:

1. **Coesão baixa**: o prompt do agente de crédito estava longe do seu código.
2. **Difícil manutenção**: para entender um agente era preciso navegar em três diretórios diferentes.
3. **Contratos espalhados**: ao criar `response_contract.py`, a lógica de validação ficaria num local distante dos agentes que a usam.
4. **Expansibilidade comprometida**: adicionar um novo agente exigia criar arquivos em múltiplos locais.

---

## Decisão

Cada agente é um **módulo Python independente** com estrutura padronizada:

```
src/agents/
  <nome_agente>/
    __init__.py       # Exporta a função principal (no_<agente>)
    agent.py          # Lógica do nó do grafo LangGraph
    contract.py       # Contratos de validação de resposta deste agente
    prompt.md         # System prompt principal
    [prompt_*.md]     # Prompts adicionais (ex.: prompt_pro.md para crédito)
```

### Estrutura atual completa

```
src/agents/
  triagem/
    __init__.py       → exporta no_triagem
    agent.py          → autenticação, roteamento, classificação de intenção
    contract.py       → contrato_consulta_financeira, contrato_autenticacao_falha
    prompt.md         → system prompt do assistente de triagem
  credito/
    __init__.py       → exporta no_credito
    agent.py          → pipeline Flash→Pro, execução de credit_tools
    contract.py       → contrato_flash_direto, contrato_sintese_pro
    prompt.md         → system prompt do Flash (coleta + tools)
    prompt_pro.md     → system prompt do analista sênior (síntese Pro)
  cambio/
    __init__.py       → exporta no_cambio
    agent.py          → tool calling inline (Tavily), ciclo 1ª+2ª chamada LLM
    contract.py       → contrato_cotacao (valida presença de R$)
    prompt.md         → system prompt do agente de câmbio
  entrevista/
    __init__.py       → exporta no_entrevista
    agent.py          → coleta de dados financeiros, calcular_score_credito
    contract.py       → contrato_resultado_entrevista, contrato_coleta_dados
    prompt.md         → system prompt da entrevista financeira
```

### Camada de infraestrutura separada

Código reutilizável entre agentes reside em `src/infrastructure/`:

```
src/infrastructure/
  response_contract.py  # Framework base: CampoContrato, ResponseContract
  logging_config.py     # Logging centralizado + tail_log()
  model_provider.py     # invocar_com_fallback, tiers fast/pro
  checkpointer.py       # RedisSaver para LangGraph
  qdrant_memory.py      # buscar_memorias, salvar_interacao
  cache.py              # CacheComTTL + decorator com_cache
```

---

## Justificativa

### Co-localização (Single Responsibility Principle)
Tudo que define o comportamento de um agente está no mesmo diretório. Um desenvolvedor que abre `src/agents/credito/` encontra imediatamente o código, o prompt e os contratos — sem navegar por outras pastas.

### Contratos como cidadãos de primeira classe
Cada `contract.py` documenta **o que o agente garante** sobre suas respostas. É o equivalente a uma interface em linguagens tipadas: quem consome o agente sabe exatamente o que esperar.

### Analogia com projetos .NET / Clean Architecture
A estrutura espelha o padrão de **Feature Folders** (ou Vertical Slices) adotado em projetos .NET modernos: cada feature (agente) agrupa todos os seus componentes em vez de dividir por tipo técnico.

### Importações limpas no grafo
```python
# graph.py — limpo e expressivo
from src.agents.triagem import no_triagem
from src.agents.credito import no_credito
from src.agents.cambio  import no_cambio
from src.agents.entrevista import no_entrevista
```

### Expansão sem fricção
Adicionar um novo agente segue um template claro: criar a pasta, os 4 arquivos obrigatórios e registrar em `graph.py`. Sem arquivos soltos, sem prompts em pasta separada.

---

## Alternativas consideradas

### Estrutura plana original (`src/agents/*.py` + `src/prompts/`)
- **Vantagem:** menos diretórios, mais simples inicialmente.
- **Desvantagem:** escala mal; prompts e contratos ficam longe do código que os usa. Rejeitada após a adição dos contratos.

### Monolito (`agent.py` único com tudo)
- **Vantagem:** um arquivo por agente.
- **Desvantagem:** mistura lógica, prompts e contratos, tornando o arquivo longo e difícil de testar. Rejeitada.

### Pacote separado por agente com `pyproject.toml`
- **Vantagem:** isolamento máximo, controle de versão por agente.
- **Desvantagem:** overhead desnecessário para um monorrepo pequeno. Reservada para evolução futura.

---

## Consequências

**Positivas:**
- Cada módulo é testável isoladamente (mock do estado, validação do contrato).
- Onboarding mais rápido: um novo desenvolvedor entende o agente de câmbio lendo apenas `src/agents/cambio/`.
- Prompts versionados junto ao código que os usa — sem dessincronização.

**Negativas / trade-offs:**
- Mais diretórios do que a estrutura plana original.
- `__init__.py` de cada módulo é trivial mas obrigatório para as importações funcionarem.

---

## Referências

- ADR-001: Framework de agentes (LangGraph)
- ADR-014: Sistema de contratos de resposta
- [Feature Folders / Vertical Slice Architecture](https://jimmybogard.com/vertical-slice-architecture/)
