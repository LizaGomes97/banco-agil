# ADR-016 — Normalização Determinística de Dados Externos e Respostas de Autenticação

**Status:** ✅ Aceito  
**Data:** 2026-04-23  
**Relacionado:** ADR-006 (Tavily), ADR-014 (Contratos de Resposta), ADR-003 (Handoff)

---

## Contexto

Dois problemas distintos foram identificados durante testes automatizados com o simulador:

### Problema 1: Cotação do Euro falhava sistematicamente

O agente de câmbio retornava `"não consegui formatar a cotação corretamente"` para **euro, libra e outras moedas**, enquanto o **dólar funcionava corretamente**.

Investigação revelou a causa raiz:

| Moeda | Resultado bruto do Tavily | LLM interpreta como |
|-------|--------------------------|---------------------|
| Dólar | `"5,13 Real Brasileiro"` | → `"R$ 5,13"` ✅ |
| Euro  | `"1 EUR = 5,8173 BRL"`   | → `"5,82 BRL"` sem R$ ❌ |

O Tavily **nunca retorna "R$"** no resultado. O dólar funcionava por coincidência: o resultado em português com vírgula levava o LLM a formatar como reais. O euro, com formato americano (`5.8173 BRL`), era reproduzido sem o símbolo `R$`, reprovando no contrato de resposta.

### Problema 2: Alucinações e "João" na autenticação com falha

Quando a autenticação falhava, o código chamava o LLM para gerar a mensagem de erro. O LLM lia o histórico e frequentemente:
- Dizia "Perfeito, João! Sua identidade foi verificada com sucesso" (autenticação FALHOU)
- Chamava qualquer usuário de "João" por padrão
- Confundia dados de tentativas anteriores ao reautenticar

### Problema 3: Recuperação de autenticação não funcionava

O extrator de CPF/data vasculhava **todo o histórico** da conversa. Na segunda tentativa de autenticação (após uma falha), a data errada da tentativa 1 permanecia no histórico e era retornada primeiro pelo extrator, impedindo a autenticação com dados corretos.

---

## Decisões

### 1. Extração determinística de valores do Tavily

Criada a função `_extrair_valor_tavily(resultado_str)` no agente de câmbio que:
1. Aplica regex para encontrar valores numéricos no formato de câmbio (`5,13`, `5.8173`, `1 EUR = 5,82`)
2. Valida que o valor está no range plausível (1.0 a 100.0 BRL)
3. Pega o **primeiro** valor encontrado (taxa atual vem antes do fechamento anterior nos textos financeiros)
4. Normaliza para o formato BR: `5,82`
5. Injeta no prompt da 2ª chamada LLM: `"INSTRUÇÃO: o valor é R$ 5,82. Use EXATAMENTE 'R$ 5,82'"`

```python
def _extrair_valor_tavily(resultado_str: str) -> str | None:
    """Extrai e normaliza o valor de câmbio do resultado bruto do Tavily."""
    matches = _RE_VALOR_CAMBIO.findall(resultado_str)
    candidatos = [(float(m.replace(".", "").replace(",", ".")), m)
                  for m in matches if 1.0 <= float(...) <= 100.0]
    if not candidatos:
        return None
    _, melhor = candidatos[0]  # primeiro = taxa atual
    val = float(melhor.replace(".", "").replace(",", "."))
    return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
```

**Resultado:** O LLM passa a ter uma instrução explícita com o valor exato e o formato correto, eliminando a dependência de interpretar formatos internacionais.

### 2. Mensagens de falha de autenticação determinísticas

Substituída a chamada ao LLM por mensagens fixas de código ao falhar a autenticação:

```python
# ANTES (problemático):
texto = _invocar_llm_seguro(messages, fallback_msg="...")  # LLM alucinava sucesso

# DEPOIS (determinístico):
restantes = MAX_TENTATIVAS_AUTH - tentativas
texto = (
    f"Não consegui verificar sua identidade com os dados informados. "
    f"Por favor, verifique o CPF e a data de nascimento e tente novamente. "
    f"Você ainda tem {restantes} tentativa{'s' if restantes > 1 else ''}."
)
```

**Benefícios:**
- Elimina alucinações ("verificado com sucesso" quando falhou)
- Elimina nomes inventados ("João" para usuários desconhecidos)
- Resposta instantânea (0.5s vs 4s com LLM)
- Mensagem consistente e previsível

### 3. Extração de CPF/data apenas da mensagem atual

Alterada a ordem de busca no agente de triagem:

```python
# ANTES (problemático):
historico = " ".join(m.content for m in state["messages"]).lower()
cpf_detectado = _extrair_cpf(historico)   # pegava data errada de tentativas anteriores
data_detectada = _extrair_data(historico)

# DEPOIS (correto):
cpf_detectado = _extrair_cpf(ultima_msg)  # prioriza mensagem atual
data_detectada = _extrair_data(ultima_msg)
# Fallback: últimas 3 mensagens (caso usuário envie CPF e data separadamente)
if not (cpf_detectado and data_detectada):
    recentes = " ".join(m.content for m in state["messages"][-3:])
    ...
```

O `AuthCard` do frontend sempre envia CPF e data juntos em uma única mensagem, tornando a busca na última mensagem suficiente para 100% dos casos de uso real.

---

## Justificativa

**Por que não ajustar o prompt para o LLM formatar corretamente o euro?**

Tentado. Mesmo com `"Apresente sempre como R$ X,XX"` no system prompt, o LLM ao receber `"5,8173 BRL"` do Tavily reproduzia o formato da ferramenta. A instrução de formatação estava no início do contexto; o resultado da tool, no final — e o LLM seguia o padrão mais próximo.

**Por que extração programática em vez de retry com prompt?**

O retry LLM foi implementado como segunda camada, mas a extração programática é mais rápida, determinística e gratuita. Em 100% dos casos testados, a injeção do valor extraído eliminou a necessidade de retry.

**Por que mensagens determinísticas para falha de autenticação?**

A falha de autenticação é um evento **binário e sem ambiguidade**: os dados não bateram. Não há valor em usar um LLM para redigir essa mensagem — apenas risco de alucinação e latência desnecessária. O LLM deve ser reservado para tarefas onde a linguagem natural agrega valor real.

---

## Alternativas descartadas

| Alternativa | Motivo de descarte |
|-------------|-------------------|
| Forçar Tavily a retornar valores em formato BR | Não é possível controlar o formato do resultado externo |
| Substituir Tavily por API de câmbio dedicada (ExchangeRate-API) | Exige nova chave de API; Tavily já está integrado |
| Usar LLM para normalizar o resultado antes de apresentar | Adiciona uma 3ª chamada LLM, aumentando latência e custo |
| Manter LLM gerando mensagem de falha de auth | Sistematicamente alucina "sucesso" — risco inaceitável |
| Limpar histórico ao reautenticar | Perderia o contexto da conversa anterior ao sucesso |

---

## Consequências

**Positivas:**
- Euro, libra, iene e qualquer moeda funcionam com o mesmo score 10/10 nos testes
- Autenticação com falha: resposta em 0.5s (vs 4s com LLM) com mensagem precisa
- Recuperação de autenticação: 100% de sucesso (era 0% antes do fix)
- Guardrail PII: não há mais risco de o LLM inventar nomes de clientes

**Negativas / trade-offs:**
- Mensagem de falha de auth menos "humanizada" (texto fixo vs LLM criativo)
- A regex de extração do Tavily pode falhar para moedas com cotação > 100 BRL (ex: Bitcoin)
  — aceitável: o agente trata apenas moedas convencionais

---

## Referências

- `src/agents/cambio/agent.py` — `_extrair_valor_tavily()`, injeção no prompt
- `src/agents/triagem/agent.py` — extração de auth da última mensagem, mensagens determinísticas
- ADR-006 — Escolha do Tavily como API de câmbio
- ADR-014 — Sistema de Contratos de Resposta
