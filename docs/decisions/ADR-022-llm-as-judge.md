# ADR-022 — LLM-as-Judge como Sinal de Qualidade

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Decisores** | Equipe de desenvolvimento |

---

## Contexto

Mesmo com curadoria (ADR-023), feedback explícito do usuário (thumbs up/down) e contratos de resposta (ADR-014), ainda temos **pontos cegos** na qualidade:

- **Thumbs down taxa real**: <2% dos turnos recebem feedback explícito. A maioria das respostas ruins passa despercebida.
- **Regressão silenciosa**: uma atualização de prompt, mudança de modelo ou alteração de tool pode degradar o tom geral das respostas sem ninguém perceber, porque CADA resposta individualmente "parece boa".
- **Sinal tardio**: métricas de NPS / churn demoram semanas para mostrar que a qualidade caiu.

Queremos um sinal **proativo, quantitativo, contínuo** que detecte regressões antes delas virarem reclamação.

### Insight

Um LLM forte (Gemini Pro) já é capaz de avaliar a qualidade de respostas de outro LLM mais fraco (Flash) com razoável alinhamento com humanos. Esse padrão tem nome na literatura: **LLM-as-judge**. Usado em Anthropic evals, RLHF, Chatbot Arena.

Custo é marginal: uma rodada noturna de 20-50 turnos gasta poucos centavos e gera uma série temporal de qualidade.

---

## Decisão

Implementar um **job noturno** ([src/worker/judge.py](../../src/worker/judge.py)) que:

1. Amostra aleatoriamente N turnos **aprovados pelo curador** ainda não julgados (`status=approved`, `id NOT IN judge_scores`).
2. Para cada turno, pede ao **Gemini Pro** que avalie em 3 critérios numa escala 1-5:
   - **PRECISÃO**: resposta factualmente correta, usa dados certos, não alucina
   - **TOM**: profissional, empático, português correto, sem jargões vazados
   - **COMPLETUDE**: endereça o que foi pedido, sem pontas soltas
3. Persiste scores em `judge_scores` (precisao, tom, completude, score_total=média, comentario).
4. Série temporal usada para:
   - Gráficos de tendência no dashboard (`/api/debug/metrics` → extensão futura)
   - Alerta manual/automático quando `avg_total` cai abaixo de threshold
   - Identificação de clusters de baixa qualidade (ex: "intent=cambio sempre tira <3 em TOM")

### Schema

```sql
CREATE TABLE judge_scores (
    id          TEXT PRIMARY KEY,
    turno_id    TEXT NOT NULL,
    precisao    INTEGER,            -- 1..5
    tom         INTEGER,            -- 1..5
    completude  INTEGER,            -- 1..5
    score_total REAL,               -- média dos 3
    comentario  TEXT,               -- 1 frase justificando o pior score
    judged_at   TEXT NOT NULL
);
```

### Prompt do juiz (versão inicial)

```
Você é um AVALIADOR sênior de qualidade de atendimento bancário.
Pontue em 3 critérios numa escala 1-5:
  PRECISÃO   — factualmente correta, sem alucinação, dados certos
  TOM        — profissional, empático, sem jargões internos vazados
  COMPLETUDE — endereça o que foi pedido, sem pontas soltas

Responda em JSON estrito:
{"precisao": ..., "tom": ..., "completude": ..., "comentario": "..."}
```

### Cadência e amostragem

- 1x por dia (madrugada), via cron: `python -m src.worker.judge --sample 20`
- Amostragem aleatória entre aprovados SEM score → cobertura crescente com o tempo
- Para o case de demonstração: roda sob demanda via CLI; em produção, scheduler é escolha de infra

---

## Justificativa

### Por que amostrar em vez de julgar 100%?
- Custo: 100% dos turnos aumenta gasto de API ~2x.
- Latência: julgar cada turno inline é impossível no hot path (~3s/turno).
- Estatística: amostra aleatória suficiente (30+ por dia) já estima bem a média global.

### Por que só julgar turnos APROVADOS pelo curador?
- Rejeitados já têm sinal negativo claro — julgá-los seria redundante.
- Aprovados são os que vão influenciar few-shot (ADR-021). Medir a qualidade DELES é o que importa para qualidade percebida.
- Pode ser estendido no futuro para amostrar "rejected" também se quisermos medir concordância judge vs curador.

### Por que 3 critérios e não 1 score global?
- Decomposição dá insights acionáveis: se TOM cai mas PRECISÃO fica estável, sabemos que é mudança de estilo, não alucinação.
- Dimensões independentes capturam trade-offs reais (ex: resposta curta = tom bom, completude ruim).

### Por que escala 1-5 e não 0-10 ou binária?
- 1-5 tem resolução suficiente sem induzir falsa precisão.
- LLMs calibram melhor em escalas pequenas.
- Fácil de visualizar (emoji-style: 1=péssimo, 5=excelente).

### Por que Gemini Pro como juiz quando o agente usa Flash?
Judge precisa ser mais forte que agent (princípio de LLM-as-judge). Pro também serve de auditor no curador (ver ADR-023). A chave do curador (`GEMINI_API_KEY_CURATOR`) não compete com o hot path.

---

## Alternativas consideradas

### Métricas automáticas tradicionais (BLEU, ROUGE, BERTScore)
- **Vantagem:** zero custo de API.
- **Desvantagem:** não medem qualidade conversacional de fato — correlação fraca com percepção humana em diálogos abertos.

### Avaliação humana periódica
- **Vantagem:** padrão-ouro.
- **Desvantagem:** caro, não escala, lento (semanas entre ciclos). Continuaremos fazendo em amostras pequenas, mas não como sinal contínuo.

### Usar o próprio curador como juiz (mesma função)
- **Vantagem:** reaproveita infra.
- **Desvantagem:** curador olha 1 turno para decidir "salva ou não". Juiz faz avaliação granular multi-critério. Separação preserva responsabilidades.

### NPS / CSAT do usuário como único sinal
- **Vantagem:** sinal real, não LLM opinando sobre LLM.
- **Desvantagem:** latência semanas, cobertura baixa, viés de seleção (quem responde é diferente de quem ficou satisfeito).

---

## Proteções contra viés de auto-avaliação

LLM-as-judge tem limitações conhecidas:
- **Self-preference**: modelos tendem a preferir respostas geradas por eles mesmos.
- **Position bias**: em comparações A/B, a ordem importa.
- **Verbose bias**: respostas longas parecem melhores sem sê-lo.

Mitigações adotadas:
1. **Avaliação absoluta** (score 1-5), não comparativa — elimina position bias.
2. **Juiz diferente do agente**: Pro avalia respostas do Flash — reduz self-preference.
3. **Critérios específicos**: "precisão" não é opinião, exige fatos. "Completude" olha o pedido, não o tamanho.
4. **Auditoria amostral pelo humano**: 5% das avaliações do juiz são re-lidas por humano mensalmente, buscando drift sistemático.

---

## Consequências

**Positivas:**
- Sinal diário de qualidade, zero esforço operacional.
- Detecção precoce de regressões (mudança de prompt, modelo novo → alerta em 24h).
- Comentário do juiz é insumo para debug ("precisão baixa porque agente prometeu aprovação que não ocorreu").
- Séries temporais permitem correlacionar piora com deploys.

**Negativas / trade-offs:**
- Custo marginal diário (20 chamadas Gemini Pro ≈ poucos centavos).
- Risco de "LLM judging LLM" amplificar vieses — mitigado por critérios específicos e auditoria humana amostral.
- Scores têm variância (±0.5 em média ao re-rodar o mesmo turno) — análise por tendência, não por ponto.

---

## Evolução futura

1. **Rubricas específicas por intent**: critérios de "crédito" diferem de "câmbio" (ex: completude em crédito inclui prazo; em câmbio inclui fonte da cotação).
2. **Juiz fine-tuned**: após meses de dados, treinar classificador próprio usando scores como labels, reduzindo custo por julgamento.
3. **Alerta automático**: integrar ao [src/infrastructure/metrics.py](../../src/infrastructure/metrics.py) — quando `avg_total` da última semana cai abaixo de X, dispara log warning.
4. **Comparação pareada** (fase 2): usar o juiz para A/B test de prompts, não só absoluto. Exige outro ADR para descrever a metodologia de comparação.

---

## Referências

- ADR-013: Pipeline Flash → Pro (mesmo princípio: modelo forte audita modelo fraco)
- ADR-014: Contratos de resposta (anti-alucinação — eixo PRECISÃO tem forte correlação)
- ADR-023: Memória de padrões golden (o juiz audita o que o curador promoveu)
- ADR-021: Few-shot dinâmico (exemplos vêm dos mesmos turnos julgados bem pelo juiz)
- [src/worker/judge.py](../../src/worker/judge.py)
- Artigos:
  - _"Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"_ (Zheng et al., 2023)
  - _"Scaling Laws for Reward Model Overoptimization"_ (Gao, Schulman, Hilton, 2022)
