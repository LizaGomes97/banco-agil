# ADR-023 — Memória de Padrões (Golden Set + Aprendizado Supervisionado)

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Substitui** | ADR-010 (removido), ADR-020 (removido) |
| **Atualiza** | ADR-021 (few-shot agora busca templates em vez de turnos curados) |

## Contexto

O sistema acumulou três coleções vetoriais pensadas para "aprender" com conversas reais:
`banco_agil_memoria_cliente` (resumos por cliente), `banco_agil_interacoes_curadas`
(pares pergunta+resposta aprovados) e `banco_agil_feedbacks_negativos` (pares com
thumbs-down). O worker de curadoria alimentava as duas últimas com pares **completos**
(pergunta do usuário + resposta do agente).

Três problemas aparecem nessa arquitetura, amplificados pela restrição do case
(cadastro em CSV, sem banco relacional de clientes):

1. **Valores voláteis virando "verdade".** Uma resposta curada com "seu limite é
   R$ 5.000" entra no índice e, por similaridade, influencia respostas futuras de
   outros clientes — reforçando o número errado mesmo quando o limite muda.
2. **PII em memória compartilhada.** CPF, nome e data de nascimento apareciam
   embebidos no texto vetorizado e podiam vazar entre sessões via RAG.
3. **Sinal fraco.** Pares literais como few-shot não generalizam bem: cada par é
   uma instância, não uma regra. O Pro rejeitava muito (~80% de rejeição
   observada) porque não havia critério claro do que merecia ser lembrado.

Objetivo do sistema é: (i) rotear para o agente certo, (ii) evitar alucinação em
valores, (iii) manter tom e formato consistentes. Memória deve servir a esses
objetivos — e **não** substituir ferramentas como fonte de dados do cliente.

## Decisão

**Escolha:** substituir o modelo "par pergunta+resposta" por uma arquitetura de
memória em 3 tipos disjuntos, bootstrapped por um **golden set curado à mão** e
enriquecida progressivamente pelo worker, sempre com tag `source` separando
humano de automático.

### Princípio condutor

> Ferramenta é oráculo. Memória é o caminho até a ferramenta certa e a forma
> certa de apresentar a resposta. **Dados de cliente nunca são memorizados.**

### Três tipos de memória

| Tipo | Onde | O que guarda | Quem consome |
|---|---|---|---|
| **Roteamento** | Qdrant `banco_agil_learned_routing` | 1 ponto por *exemplo* (texto curto) → payload com `intent`, `agente`, `source` | `intent_classifier` (k-NN few-shot) |
| **Template** | Qdrant `banco_agil_learned_templates` | 1 ponto por *template* → payload com `esqueleto` (com placeholders `{limite}`, `{moeda}`), `tool_fonte`, `evitar` | Cada agente, antes de responder, busca templates por (input + intent) e injeta no prompt |
| **Lição** | SQLite `curator_lessons` (com `source`, `aplicavel_a`, `ativa`, `motivo`) | Regra textual abstrata | Prompt do agente inclui seção "Regras ativas" filtrada por `aplicavel_a` |

### Fluxo do aprendizado

1. **Bootstrap**: humano cura `seeds/patterns.json` (versionado no Git) →
   `scripts/seed_patterns.py` popula routing, templates e lições com
   `source='golden'`.
2. **Runtime**: k-NN em `learned_routing` + `learned_templates` aplica **boost de
   +0.25 no score** quando `source == 'golden'` (constante
   `GOLDEN_SCORE_BOOST` em `vector_store.py`). Resultado: padrões humanos
   dominam o ranking quando existem, aprendidos complementam.
3. **Aprendizado**: worker de curadoria gera *candidatos* a novo routing/template/
   lição a partir de turnos em staging, grava com `source='worker'`, nunca
   toca nos `source='golden'`. O Pro auditor valida consistência com o golden set.
4. **Observabilidade**: dashboard mostra contagem por `source`, permitindo
   comparar "quanto humano / quanto aprendido / quanto rejeitado".

### O que morre

- `banco_agil_memoria_cliente` é desativada (não salvamos dados de cliente).
- `banco_agil_interacoes_curadas` é substituída por `learned_routing` +
  `learned_templates`.
- `banco_agil_feedbacks_negativos` **não é mais consultada em runtime**; segue
  existindo só como *buffer de evidência* para o curator Pro destilar lições.

## Justificativa

- **Separação de concerns**: "qual agente chamar" (Tipo A), "como apresentar a
  resposta" (Tipo B) e "que regra sempre vale" (Tipo C) são problemas
  diferentes — misturá-los em um par pergunta+resposta força o LLM a extrair
  três sinais de uma só unidade, e ele faz isso mal.
- **Zero PII em índice vetorial** resolve LGPD e contaminação cruzada de uma vez.
- **Templates com placeholders em vez de valores concretos** eliminam a maior
  causa de alucinação detectada: o modelo "decorar" números específicos.
- **Golden set versionado em JSON** permite: diff no Git, revisão humana, re-seed
  idempotente a qualquer momento, e comparação clara "antes/depois" no case.
- **Boost golden vs worker** dá um caminho seguro de evolução: o worker pode
  errar sem contaminar a base humana.
- **Compatível com restrição do case (CSV)**: nenhuma tabela relacional de
  cliente é necessária — o CSV permanece como única fonte de dados do cliente,
  consultado por tool em cada turno.

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|---|---|---|---|
| Manter `interacoes_curadas` com anonimização/masking posterior | Menos refactor | Ainda mistura os 3 sinais; masking é frágil; não resolve problema de templates | Sinal continua fraco, e valores voláteis ainda contaminam few-shot |
| Perfil do cliente em tabela SQL (com `atualizado_em`, versioning) | Detecção de mudança elegante | Exige banco relacional → viola restrição do case (CSV) | Restrição explícita do case |
| 100% automático (worker escreve direto, sem golden) | Sem trabalho manual | Sem âncora de qualidade; o viés do curador fica sem contraponto | Evidência empírica: curator já aprovava só 20% dos itens, sinal ruidoso |
| RAG com reranker fino (BGE/Cohere) em cima dos pares | Ganho de precisão no retrieval | Não resolve contaminação por valores nem PII | Problema é semântico, não de ranking |

## Consequências

**Positivas:**

- Memória agnóstica a cliente → sem risco de vazamento entre sessões.
- Alucinação de valor mitigada por design (templates carregam esqueleto, não
  número).
- Curva clara de evolução visível no dashboard (golden N, worker M, lições K).
- Re-seed idempotente permite recomeçar a qualquer momento (mostrou valor no
  reset de 2026-04-23).
- Case ganha narrativa forte: "memória não é log de conversa, é conhecimento
  destilado e governado".

**Negativas / trade-offs:**

- Bootstrap manual de ~30 itens exige trabalho humano upfront (aceito como
  custo fixo).
- Worker precisa ser reescrito para gerar candidatos a padrão em vez de
  aprovar/rejeitar pares (fase 3 do plano de implementação).
- k-NN com boost customizado é levemente mais custoso que busca pura (overhead
  desprezível, <1ms).
- Perder a `memoria_cliente` implica que conversas não têm "memória longa" entre
  sessões — a única memória por cliente é o checkpoint do LangGraph durante a
  sessão atual. Aceitável para o escopo do case e mais seguro.

## Referências

- `seeds/patterns.json` — fonte de verdade do golden set.
- `scripts/seed_patterns.py` — script idempotente de seed.
- `scripts/reset_learning_data.py` — reset auditado do aprendizado.
- `src/infrastructure/vector_store.py` — constantes `COLLECTION_LEARNED_*`,
  `SOURCE_GOLDEN`, `GOLDEN_SCORE_BOOST`.
- `src/infrastructure/staging_store.py` — migrations em `curator_lessons`,
  métodos `salvar_licao_golden` e `listar_licoes_ativas`.
- ADR-021 — few-shot dinâmico (atualizado para buscar templates).
