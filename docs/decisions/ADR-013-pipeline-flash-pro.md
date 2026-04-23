# ADR-013 — Pipeline Flash→Pro para Decisão de Crédito

**Status:** ✅ Aceito  
**Data:** 2026-04-22  
**Relacionado:** ADR-002 (modelos LLM), ADR-005 (score determinístico), ADR-012 (resiliência)

---

## Contexto

O Agente de Crédito realiza duas atividades com perfis de complexidade completamente diferentes:

1. **Coleta conversacional**: entender o que o cliente quer, pedir o valor desejado, chamar as tools de verificação e registro. Tarefa simples, repetitiva, com estrutura previsível.

2. **Comunicação da decisão**: após a análise, explicar o resultado ao cliente de forma empática, contextualizada e personalizada. Se reprovado, oferecer alternativas, explicar a diferença de pontos, motivar o cliente a tentar a entrevista.

Usar um único modelo (Flash) para ambas as tarefas significa que a **comunicação da decisão** — o momento mais crítico da experiência do cliente — fica subotimizada. O Flash é excelente para tool calling e diálogos simples, mas o Pro tem raciocínio mais sofisticado para nuances comunicacionais.

---

## Decisão

Implementar um pipeline em duas fases no `no_credito` (`src/agents/credito.py`):

```
┌─────────────────────────────────────────────────────┐
│  Fase 1 — Flash (fast)                              │
│  • Conduz conversa de coleta                        │
│  • Chama verificar_elegibilidade_aumento()          │
│  • Chama registrar_pedido_aumento()                 │
│  • Executa tools inline                             │
└──────────────────────────┬──────────────────────────┘
                           │ Se houve tool calls
                           ▼
┌─────────────────────────────────────────────────────┐
│  Fase 2 — Pro                                       │
│  • Recebe: conversa + resultados das tools          │
│  • Prompt dedicado: credito_pro_sintese.md          │
│  • Formula resposta final: empática, clara,         │
│    personalizada, com alternativas se reprovado     │
└─────────────────────────────────────────────────────┘
```

**Gatilho da Fase 2**: apenas quando Flash faz tool calls (ou seja, houve uma decisão real de aprovação/reprovação). Consultas simples ("qual meu limite?") usam só o Flash.

**Tools criadas para o Flash** (`src/tools/credit_tools.py`):
- `verificar_elegibilidade_aumento(score_atual, limite_atual, novo_limite_solicitado)` — lógica determinística, não LLM
- `registrar_pedido_aumento(cpf, limite_atual, novo_limite_solicitado, status)` — persiste no CSV

---

## Justificativa

**Por que separar coleta de síntese?**

O modelo Flash é otimizado para velocidade e custo — é excelente para tool calling sequencial, mas tende a respostas mais mecânicas em situações emocionalmente sensíveis (crédito reprovado é uma notícia ruim). O Pro tem melhor capacidade de raciocínio contextual e comunicação nuançada.

**Por que não usar Pro para tudo?**

O Pro custa ~10x mais por token que o Flash e tem maior latência. Usá-lo para coleta de dados simples (perguntar qual limite o cliente quer) seria desperdício.

**Por que não é o LLM que decide aprovação/reprovação?**

ADR-005 define que o cálculo é determinístico (Python). A tool `verificar_elegibilidade_aumento` aplica a regra `score ≥ 500 → aprovado` de forma determinística. O Pro recebe o resultado da tool — ele **comunica** a decisão, não a **toma**.

Esse é o princípio de separação: LLM como comunicador, Python como calculadora.

---

## Alternativas descartadas

- **Flash para tudo**: mais simples, mas comunicação da decisão fica genérica.
- **Pro para tudo**: mais caro e mais lento sem ganho na fase de coleta.
- **Flash com prompt melhor**: prompt engineering tem limite; o Pro simplesmente é melhor em raciocínio contextual.
- **Modelo de fine-tuning**: fora do escopo; requer dados de treinamento e infraestrutura específica.

---

## Consequências

- **Positivas**: melhor experiência na comunicação da decisão; custo controlado (Pro só quando necessário)
- **Negativas**: decisões de crédito têm +1 chamada LLM (latência extra ~1-2s)
- **Observabilidade**: log `INFO` ao concluir o pipeline informa o CPF (últimos 4 dígitos) para rastreabilidade
- **Resiliência**: se o Pro falhar, o fallback (ADR-012) usa Flash — o cliente recebe uma resposta, possivelmente menos elaborada, mas sem quebrar a conversa
