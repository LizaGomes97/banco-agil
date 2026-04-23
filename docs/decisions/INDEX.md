# Índice de Decisões de Arquitetura (ADRs)

Todas as decisões técnicas relevantes do projeto Banco Ágil são registradas aqui.

## Decisões registradas

| # | Título | Status | Data |
|---|---|---|---|
| [ADR-001](ADR-001-framework-agentes.md) | Framework de Agentes: LangGraph | Aceito | 2026-04 |
| [ADR-002](ADR-002-modelo-llm.md) | Modelo LLM: Gemini 2.0 Flash + Pro | Aceito | 2026-04 |
| [ADR-003](ADR-003-handoff-agentes.md) | Handoff Implícito e Contrato `resposta_final` | Aceito | 2026-04 |
| [ADR-004](ADR-004-persistencia-estado.md) | Persistência de Estado: Redis | Aceito | 2026-04 |
| [ADR-005](ADR-005-calculo-score.md) | Cálculo de Score em Python (sem LLM) | Aceito | 2026-04 |
| [ADR-006](ADR-006-api-cambio.md) | API de Câmbio: Tavily | Aceito | 2026-04 |
| [ADR-007](ADR-007-estrutura-codigo.md) | Estrutura de Código: Módulos por Agente | Aceito | 2026-04 |
| [ADR-008](ADR-008-lead-capture.md) | Captura de Leads Pós-Falha de Autenticação | Aceito | 2026-04 |
| [ADR-009](ADR-009-router-llm.md) | Classificador de Intenção via LLM | Aceito | 2026-04 |
| [ADR-010](ADR-010-memoria-semantica-qdrant.md) | Memória Semântica com Qdrant | Aceito | 2026-04 |
| [ADR-011](ADR-011-cache-classificador.md) | Cache do Classificador com TTL | Aceito | 2026-04 |
| [ADR-012](ADR-012-resiliencia-modelo.md) | Resiliência com Fallback de Modelo | Aceito | 2026-04 |
| [ADR-013](ADR-013-pipeline-flash-pro.md) | Pipeline Flash → Pro para Crédito | Aceito | 2026-04 |
| [ADR-014](ADR-014-contratos-resposta.md) | Sistema de Contratos de Resposta (Anti-Alucinação) | Aceito | 2026-04 |
| [ADR-015](ADR-015-guardrails.md) | Sistema de Guardrails por Domínio e Criticidade | Aceito | 2026-04 |

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
