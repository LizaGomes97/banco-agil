# ADR-009 — Router de Intenção Baseado em LLM

**Status:** ✅ Aceito  
**Data:** 2026-04-22  
**Substitui:** Keyword matching em `triagem.py`

---

## Contexto

A versão inicial do Agente de Triagem usava keyword matching para identificar a intenção do cliente: listas de palavras-chave por domínio (`_INTENCOES_CREDITO`, `_INTENCOES_CAMBIO`, etc.) com comparação direta no texto normalizado.

O problema se manifestou em testes reais:

> "se eu usar meu crédito para comprar dólares, quanto fica?"

A frase contém tanto "crédito" quanto "dólares". O matching capturou "crédito" primeiro (por ordem de verificação) e roteou incorretamente para o Agente de Crédito, quando a intenção real era câmbio.

Outros casos problemáticos:
- Erros de digitação: "cotaçao" sem acento não casava com "cotação"
- Frases compostas: "obrigado pelo crédito, tchau" era roteada para crédito em vez de encerramento
- Variações naturais: "quero saber sobre minha margem" não era reconhecida

---

## Decisão

Substituir o keyword matching por uma **chamada focada ao LLM** (`src/tools/intent_classifier.py`) com as seguintes características:

- Modelo: `gemini-2.0-flash` (mesmo tier do agente)
- `temperature=0` para respostas determinísticas
- `max_output_tokens=10` — resposta é uma única palavra
- Prompt de classificação com 4 categorias: `credito`, `cambio`, `encerrar`, `nenhum`
- Regra de desempate explícita no prompt: câmbio > crédito em casos ambíguos
- Cache L1 em memória (ver ADR-011) para evitar chamadas repetidas

---

## Justificativa

| Critério | Keyword matching | Router LLM |
|----------|-----------------|------------|
| Precisão em frases ambíguas | ❌ Falha | ✅ Correto |
| Tolerância a erros de digitação | ❌ Não suporta | ✅ Suporta |
| Variações de linguagem | ❌ Limitado | ✅ Natural |
| Custo | ✅ Zero | ⚠️ ~0.001 USD/msg (mitigado pelo cache) |
| Latência | ✅ < 1ms | ⚠️ ~500ms (mitigado pelo cache) |
| Manutenção | ❌ Adicionar palavras manualmente | ✅ Prompt editável |

O custo e latência adicionais são mitigados pelo cache de 5 minutos (ADR-011). Mensagens idênticas não fazem nova chamada ao LLM.

---

## Alternativas descartadas

- **Manter keyword matching com mais palavras**: escala mal; cada nova variação requer edição de código.
- **Classificador local (sentence-transformers)**: requer modelo em memória (~500MB), incompatível com o objetivo de leveza do projeto.
- **Regex com expressões complexas**: mais preciso que keywords simples, mas ainda não lida com semântica ou contexto.

---

## Consequências

- **Positivas**: roteamento correto em casos ambíguos, sem manutenção de listas de keywords
- **Negativas**: +1 chamada LLM por mensagem quando não está em cache; requer API key ativa
- **Mitigação**: fallback retorna `"nenhum"` em caso de falha da API, e o agente de triagem trata o caso com o LLM conversacional normalmente
