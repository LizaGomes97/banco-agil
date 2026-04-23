# ADR-001: Framework de Orquestração de Agentes

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O sistema Banco Ágil exige múltiplos agentes especializados (Triagem, Crédito, Entrevista de Crédito, Câmbio) que precisam colaborar em um fluxo conversacional único. O desafio central é garantir que as transições entre agentes sejam **imperceptíveis ao cliente** — para ele, existe apenas um atendente com múltiplas habilidades.

Restrições identificadas:
- Fluxo conversacional sequencial (não paralelo)
- Coleta de dados estruturada em múltiplas etapas (CPF, data de nascimento, dados financeiros)
- Lógica de retry com limite (máximo 3 tentativas de autenticação)
- Estado compartilhado entre agentes (cliente autenticado, histórico, score)
- Prazo de entrega curto — framework deve ter boa documentação e exemplos

---

## Decisão

**Escolha:** `LangGraph (LangChain)`

Usaremos LangGraph como framework de orquestração, modelando o sistema como um **grafo de estados** onde cada nó representa um agente ou etapa do fluxo.

---

## Justificativa

| Critério | Peso | Avaliação |
|----------|------|-----------|
| Handoff implícito nativo | Alto | LangGraph usa estado compartilhado — o cliente não percebe a troca |
| Controle de fluxo condicional | Alto | Edges condicionais permitem retry, desvios e encerramento |
| Coleta de dados do usuário | Alto | `interrupt()` nativo pausa o grafo aguardando input |
| Testabilidade por nó | Médio | Cada nó é uma função Python isolada e testável |
| Ecossistema e documentação | Médio | Ampla comunidade, exemplos de multi-agente bem documentados |
| Free tier LLM compatível | Alto | Compatível com Gemini, GPT, Groq via LiteLLM |

O requisito de **handoff implícito** é o mais diferenciador: em LangGraph, todos os agentes compartilham o mesmo objeto `state`. Quando o Agente de Triagem autentica o cliente e transfere para o Agente de Crédito, o histórico completo é preservado automaticamente. O LLM do próximo agente recebe o contexto e continua a conversa naturalmente.

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **CrewAI** | API de alto nível, fácil de iniciar, role-based | Controle de estado limitado, handoff explícito por design, difícil pausar para input do usuário | Handoff implícito seria workaround complexo |
| **Google ADK** | Integração nativa com Gemini, suporte Google | Ecossistema menor, vendor lock-in, menos exemplos de fluxo conversacional estruturado | Portabilidade e maturidade de comunidade |
| **LangChain puro** | Sem overhead de grafo, mais simples | Gerenciamento manual de estado entre agentes, sem controle de fluxo declarativo | Complexidade operacional alta sem ganho de controle |
| **LlamaIndex** | Excelente para RAG e indexação | Não focado em agentes conversacionais sequenciais | Escopo inadequado para este caso |

---

## Consequências

**Positivas:**
- Fluxo de handoff imperceptível ao cliente implementado nativamente
- Cada nó do grafo é testável de forma independente
- Estado da conversa centralizado e auditável
- Controle declarativo de retry (autenticação com 3 tentativas via loop no grafo)

**Negativas / trade-offs aceitos:**
- Curva de aprendizado maior que CrewAI para quem não conhece o conceito de grafo de estados
- Verbose nas definições de nós e edges comparado a frameworks de mais alto nível
- Dependência do ecossistema LangChain

---

## Referências

- [LangGraph Documentation — Multi-agent systems](https://langchain-ai.github.io/langgraph/)
- [LangGraph — How to implement handoffs](https://langchain-ai.github.io/langgraph/how-tos/agent-handoffs/)
- [LangGraph — interrupt() for human-in-the-loop](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
