# Índice de Decisões Técnicas (ADRs)

Banco Ágil — Agente de Atendimento Inteligente

> ADRs documentam as decisões arquiteturais do projeto: o quê foi decidido, por quê, e quais alternativas foram descartadas. São a memória técnica do projeto.

---

## Decisões registradas

| ADR | Título | Status | Data |
|-----|--------|--------|------|
| [ADR-001](ADR-001-framework-agentes.md) | Framework de Orquestração de Agentes (LangGraph) | ✅ Aceito | 2026-04-22 |
| [ADR-002](ADR-002-modelo-llm.md) | Modelo de Linguagem — Gemini 2.0 Flash | ✅ Aceito | 2026-04-22 |
| [ADR-003](ADR-003-handoff-agentes.md) | Estratégia de Handoff entre Agentes (grafo único) | ✅ Aceito | 2026-04-22 |
| [ADR-004](ADR-004-persistencia-estado.md) | Persistência de Estado da Conversa (Redis) | ✅ Aceito | 2026-04-22 |
| [ADR-005](ADR-005-calculo-score.md) | Cálculo do Score de Crédito (Python determinístico) | ✅ Aceito | 2026-04-22 |
| [ADR-006](ADR-006-api-cambio.md) | API de Cotação de Câmbio (Tavily) | ✅ Aceito | 2026-04-22 |
| [ADR-007](ADR-007-estrutura-codigo.md) | Estrutura de Código e Separação de Responsabilidades | ✅ Aceito | 2026-04-22 |
| [ADR-008](ADR-008-lead-capture.md) | Lead Capture para Não Clientes (feature extra) | ✅ Aceito | 2026-04-22 |
| [ADR-009](ADR-009-router-llm.md) | Router de Intenção Baseado em LLM (substitui keyword matching) | ✅ Aceito | 2026-04-22 |
| [ADR-010](ADR-010-memoria-semantica-qdrant.md) | Memória Semântica por Cliente com Qdrant | ✅ Aceito | 2026-04-22 |
| [ADR-011](ADR-011-cache-classificador.md) | Cache L1 no Classificador de Intenção | ✅ Aceito | 2026-04-22 |
| [ADR-012](ADR-012-resiliencia-modelo.md) | Resiliência de Modelo: Retry Exponencial e Fallback entre Tiers | ✅ Aceito | 2026-04-22 |
| [ADR-013](ADR-013-pipeline-flash-pro.md) | Pipeline Flash→Pro para Decisão de Crédito | ✅ Aceito | 2026-04-22 |

---

## Como criar um novo ADR

1. Copie o template da skill `technical-decisions`
2. Nomeie o arquivo: `ADR-NNN-titulo-curto.md`
3. Preencha todos os campos: contexto, decisão, justificativa, alternativas, consequências
4. Atualize esta tabela
5. Referencie o ADR em outros documentos relevantes

## Legenda de status

| Status | Significado |
|--------|-------------|
| ✅ Aceito | Decisão em vigor |
| 🔄 Proposto | Em discussão |
| ⚠️ Depreciado | Substituído, mas mantido para histórico |
| ❌ Substituído | Ver ADR substituto |
