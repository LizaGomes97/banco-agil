# ADR-010 — Memória Semântica por Cliente com Qdrant

**Status:** ✅ Aceito  
**Data:** 2026-04-22  
**Relacionado:** ADR-004 (Redis para estado da sessão)

---

## Contexto

O Redis (ADR-004) persiste o estado da **sessão atual** via LangGraph checkpointing. Quando o cliente encerra a conversa e retorna em outra sessão, o estado é perdido — o agente não tem nenhum contexto sobre interações passadas.

Isso cria uma experiência ruim: o cliente precisa explicar novamente que já tentou aumentar o limite, que fez a entrevista financeira, que o score foi atualizado. Um banco de verdade tem esse histórico.

---

## Decisão

Implementar memória semântica por cliente usando **Qdrant** (`src/infrastructure/qdrant_memory.py`):

**Ao encerrar a conversa** (`encerrado=True`):
- Um nó dedicado (`salvar_memoria` em `graph.py`) chama o LLM para gerar um resumo em 2-4 frases da sessão
- O resumo é transformado em embedding (`gemini-embedding-001`, 3072 dimensões)
- O ponto é salvo no Qdrant com metadados: `{"cpf": "...", "data": "...", "agentes_usados": [...], "resultado": "..."}`

**Ao autenticar o cliente** (triagem):
- Busca semântica no Qdrant filtrada pelo CPF
- Retorna os 3 resumos mais relevantes para a consulta atual
- As memórias são injetadas no context de cada agente especialista como "Interações anteriores"

**Isolamento crítico:** o filtro `must: cpf == X` garante que nunca há vazamento entre clientes.

---

## Justificativa

**Por que Qdrant e não PostgreSQL para memória?**

A memória semântica requer busca por similaridade vetorial, não por igualdade de campos. O cliente pode dizer "quero aumentar meu cartão" e a memória relevante pode ser "solicitação de aumento de limite de crédito reprovada". A busca semântica encontra essa relação; uma query SQL com `WHERE cpf = X ORDER BY data DESC` retornaria memórias por data, não por relevância para o assunto atual.

**Por que não armazenar o histórico completo de mensagens?**
- Custo de tokens: históricos longos consomem muito espaço no context window
- Relevância: o agente não precisa de todas as mensagens, apenas dos pontos-chave
- Privacidade: resumos contêm menos dados sensíveis que transcrições completas

**Por que usar embedding para o resumo e não o texto diretamente?**
- Busca semântica permite encontrar memórias relacionadas mesmo com palavras diferentes
- Filtragem por score de similaridade (`score_threshold=0.5`) evita memórias irrelevantes

---

## Alternativas descartadas

- **PostgreSQL com histórico de texto**: sem busca semântica, retorna por data. Menos relevante que busca vetorial.
- **Redis com TTL longo**: Redis é para estado transitório; não é otimizado para busca vetorial.
- **ChromaDB**: requer armazenamento local; Qdrant já estava disponível na VPS do projeto.

---

## Consequências

- **Positivas**: experiência personalizada entre sessões; o agente "lembra" do cliente
- **Negativas**: +1 chamada de embedding ao autenticar; +1 chamada LLM + embedding ao encerrar
- **Mitigação de falha**: erros no Qdrant são capturados com `try/except`; a conversa continua normalmente sem memória em caso de indisponibilidade
- **Custo**: embeddings `gemini-embedding-001` custam ~$0.00001 por chamada (praticamente zero)
