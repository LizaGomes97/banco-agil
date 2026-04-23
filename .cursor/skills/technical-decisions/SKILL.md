---
name: technical-decisions
description: Documenta decisões técnicas usando o padrão ADR (Architecture Decision Record). Use quando tomar uma decisão de tecnologia, framework, padrão de código, ou design que precise ser justificada e rastreada. Ativar ao escolher entre frameworks, definir estrutura de dados, selecionar LLM, ou qualquer decisão que impacte o projeto.
---

# Registro de Decisões Técnicas (ADR)

Documenta **o quê** foi decidido, **por quê**, e quais alternativas foram descartadas.

> "Se não está documentado, não foi decidido — foi improvisado."

## Quando criar um ADR

- Escolha de framework de agentes (LangGraph vs CrewAI vs ADK)
- Escolha de LLM (Gemini vs GPT vs Groq)
- Definição de arquitetura (mono-agente vs multi-agente)
- Estratégia de handoff entre agentes
- Escolha de storage (CSV vs SQLite vs in-memory)
- Qualquer decisão que você precisaria explicar em uma entrevista

## Onde salvar

`docs/decisions/ADR-NNN-titulo-curto.md`

Exemplos:
- `docs/decisions/ADR-001-framework-agentes.md`
- `docs/decisions/ADR-002-modelo-llm.md`
- `docs/decisions/ADR-003-estrategia-handoff.md`

## Template ADR

```markdown
# ADR-NNN: [Título da Decisão]

**Data:** YYYY-MM-DD  
**Status:** [Proposto | Aceito | Depreciado | Substituído por ADR-XXX]  
**Autor:** [nome]

## Contexto

[Descreva o problema ou necessidade que gerou esta decisão.
Seja específico: qual era a situação, quais restrições existiam.]

## Decisão

[Declare claramente o que foi decidido, em uma frase direta.]

**Escolha:** `[tecnologia/padrão escolhido]`

## Justificativa

[Por que essa opção foi escolhida? Quais critérios pesaram mais?]

- **Critério 1:** [ex: custo zero no free tier] → favorece X
- **Critério 2:** [ex: suporte nativo a tool calling] → favorece X
- **Critério 3:** [ex: latência baixa] → neutro

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| Opção A | ... | ... | [motivo] |
| Opção B | ... | ... | [motivo] |

## Consequências

**Positivas:**
- [benefício concreto]

**Negativas / trade-offs:**
- [limitação aceita conscientemente]

## Referências

- [link ou doc relevante]
```

## Exemplo preenchido: Escolha de Framework

```markdown
# ADR-001: Framework de Orquestração de Agentes

**Data:** 2026-04-22  
**Status:** Aceito

## Contexto

O sistema exige múltiplos agentes especializados com handoffs contextuais.
Precisamos de um framework que suporte grafos de estado, tool calling, e
que tenha free tier viável para demonstração.

## Decisão

**Escolha:** `LangGraph`

## Justificativa

- Controle granular do grafo de estados (crítico para handoff implícito)
- Suporte nativo a "interrupt" para coleta de dados do usuário
- Integração com LangChain tools (amplo ecossistema)
- Documentação madura com exemplos de multi-agente

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| CrewAI | API simples, role-based | Menos controle de estado | Handoff implícito complexo |
| Google ADK | Nativo Google, integrado Gemini | Ecossistema menor, vendor lock | Portabilidade |
| LlamaIndex | Bom para RAG | Não foco em agentes conversacionais | Escopo diferente |

## Consequências

**Positivas:** Controle total do fluxo, testável unitariamente por nó.  
**Negativas:** Curva de aprendizado maior que CrewAI.
```

## Índice de ADRs

Manter em `docs/decisions/INDEX.md`:

```markdown
| ADR | Título | Status | Data |
|-----|--------|--------|------|
| [ADR-001](ADR-001-framework-agentes.md) | Framework de Agentes | Aceito | 2026-04-22 |
```

## Checklist ADR

- [ ] Contexto descreve o problema real (não a solução)
- [ ] Decisão é declarada em uma frase
- [ ] Pelo menos 2 alternativas avaliadas
- [ ] Consequências negativas reconhecidas honestamente
- [ ] Status atualizado
