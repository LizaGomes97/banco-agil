# Índice de Decisões de Arquitetura (ADRs)

Todas as decisões técnicas relevantes do projeto Banco Ágil são registradas aqui.

## Decisões registradas

| # | Título | Status | Data |
|---|---|---|---|
| [ADR-001](ADR-001-framework-agentes.md) | Framework de Agentes: LangGraph | Aceito | 2026-04 |
| [ADR-002](ADR-002-modelo-llm.md) | Modelo LLM: Gemini 2.5 Flash + Pro | Aceito (atualizado 23/04) | 2026-04 |
| [ADR-003](ADR-003-handoff-agentes.md) | Handoff Implícito e Contrato `resposta_final` | Aceito | 2026-04 |
| [ADR-004](ADR-004-persistencia-estado.md) | Persistência de Estado: Redis | Aceito | 2026-04 |
| [ADR-005](ADR-005-calculo-score.md) | Cálculo de Score em Python (sem LLM) | Aceito | 2026-04 |
| [ADR-006](ADR-006-api-cambio.md) | API de Câmbio: Tavily | Aceito | 2026-04 |
| [ADR-007](ADR-007-estrutura-codigo.md) | Estrutura de Código: Módulos por Agente | Aceito | 2026-04 |
| [ADR-008](ADR-008-lead-capture.md) | Captura de Leads Pós-Falha de Autenticação | Aceito | 2026-04 |
| [ADR-009](ADR-009-router-llm.md) | Classificador de Intenção via LLM | Aceito | 2026-04 |
| [ADR-011](ADR-011-cache-classificador.md) | Cache do Classificador com TTL | Aceito | 2026-04 |
| [ADR-012](ADR-012-resiliencia-modelo.md) | Resiliência com Fallback de Modelo | Aceito | 2026-04 |
| [ADR-013](ADR-013-pipeline-flash-pro.md) | Pipeline Flash → Pro para Crédito | Aceito | 2026-04 |
| [ADR-014](ADR-014-contratos-resposta.md) | Sistema de Contratos de Resposta (Anti-Alucinação) | Aceito | 2026-04 |
| [ADR-015](ADR-015-guardrails.md) | Sistema de Guardrails por Domínio e Criticidade | Aceito | 2026-04 |
| [ADR-016](ADR-016-normalizacao-dados-externos.md) | Normalização Determinística de Dados Externos e Auth | Aceito | 2026-04 |
| [ADR-017](ADR-017-estrategia-testes-simulador.md) | Estratégia de Testes: Simulador Automatizado de Clientes | Aceito | 2026-04 |
| [ADR-018](ADR-018-arquitetura-prompts-python.md) | Arquitetura de Prompts: Funções Python em vez de `.md` | Aceito | 2026-04 |
| [ADR-019](ADR-019-estrutura-prompts-when-not-to-use.md) | Estrutura de Prompts: "Quando Usar / Quando NÃO Usar" | Aceito | 2026-04 |
| [ADR-021](ADR-021-few-shot-dinamico.md) | Few-Shot Dinâmico com Exemplos Curados | Aceito | 2026-04 |
| [ADR-022](ADR-022-llm-as-judge.md) | LLM-as-Judge como Sinal de Qualidade | Aceito | 2026-04 |
| [ADR-023](ADR-023-memoria-padroes-golden.md) | Memória de Padrões (Golden Set + Source Tag) | Aceito | 2026-04 |
| [ADR-024](ADR-024-tabela-score-limite.md) | Tabela `score_limite.csv` — tetos por faixa de score | Aceito | 2026-04 |
| [ADR-025](ADR-025-tool-calling-react.md) | Tool Calling Robusto: Loop ReAct + Retry Forçado | Aceito | 2026-04 |

## Como criar um novo ADR

1. Copie o template abaixo para um novo arquivo `ADR-NNN-titulo-curto.md`
2. Preencha todos os campos
3. Adicione uma linha neste índice

```markdown
# ADR-NNN — Título

| Campo | Valor |
|---|---|
| **Status** | Proposto / Aceito / Substituído / Depreciado |
| **Data** | AAAA-MM-DD |
| **Decisores** | ... |

## Contexto
## Decisão
## Justificativa
## Alternativas consideradas
## Consequências
## Referências
```

## Legenda de status

| Status | Significado |
|---|---|
| **Proposto** | Em discussão, ainda não implementado |
| **Aceito** | Implementado e em produção |
| **Substituído** | Substituído por um ADR mais recente |
| **Depreciado** | Funcionalidade removida ou obsoleta |
