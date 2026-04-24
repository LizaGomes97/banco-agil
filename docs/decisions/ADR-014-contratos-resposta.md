# ADR-014 — Sistema de Contratos de Resposta (Anti-Alucinação)

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Decisores** | Equipe de desenvolvimento |

---

## Contexto

Durante os testes, observamos que o LLM alucinava valores financeiros quando respondia sem ter os dados explicitamente no contexto — por exemplo, informando "seu limite é R$ 3.500,00" quando o limite real do cliente era R$ 3.000,00.

Dois vetores de risco foram identificados:

1. **Dados ausentes no contexto**: o agente de triagem inicialmente injetava apenas `nome` e `cpf` no system prompt, sem `limite_credito` ou `score`. O LLM inventava valores plausíveis.
2. **Dados presentes mas ignorados**: mesmo com os dados no contexto, o LLM ocasionalmente "ajustava" valores (arredondamentos, aproximações) ao formular a resposta.

Corrigir apenas o primeiro vetor (injetar os dados) não era suficiente para **garantir** que o valor correto apareceria na resposta.

---

## Decisão

Implementar um **sistema de contratos de resposta** em duas camadas:

### Camada 1 — Framework base (`src/infrastructure/response_contract.py`)

Define os componentes reutilizáveis:

```python
@dataclass
class CampoContrato:
    nome: str
    valor_esperado: Any  # gera automaticamente todos os formatos (BR/EN)
    obrigatorio: bool = True

    def presente_em(self, texto: str) -> bool:
        """Verifica se algum formato do valor aparece no texto."""
        ...

@dataclass
class ResponseContract:
    campos: list[CampoContrato]
    max_retries: int = 1

    def validar(self, resposta: str) -> tuple[bool, list[CampoContrato]]:
        """Retorna (satisfeito, campos_faltando)."""
        ...

    def executar(self, invocar_fn, corrigir_fn=None) -> str:
        """Chama invocar_fn, valida, faz retry com prompt corretivo se necessário."""
        ...
```

Funções de conveniência pré-definidas:
- `contrato_financeiro(limite, score)` — valida limite e score
- `contrato_score(score)` — valida apenas o score
- `corrigir_com_dados(resposta, faltando, cliente)` — correção programática

### Camada 2 — Contratos por agente (`src/agents/<nome>/contract.py`)

Cada agente define seus próprios contratos em função do que **aquele agente específico deve garantir**:

```
triagem/contract.py
  contrato_consulta_financeira(cliente)  → valida limite + score
  contrato_autenticacao_falha()          → sem validação (cliente não autenticado)

credito/contract.py
  contrato_flash_direto(cliente)         → valida limite + score (Flash sem tools)
  contrato_sintese_pro(cliente)          → valida limite + score (síntese Pro)

cambio/contract.py
  contrato_cotacao()                     → valida presença de R$ (valor externo)
  contrato_resposta_generica()           → sem validação

entrevista/contract.py
  contrato_resultado_entrevista(score)   → valida novo score calculado
  contrato_coleta_dados()                → sem validação (coleta em andamento)
```

### Fluxo de execução

```
invocar_fn(None) → resposta LLM
         │
         ▼
  validar(resposta)
         │
    satisfeito? ──── SIM ──────────────────────────► retorna resposta
         │
        NÃO
         │
  logger.warning (campos ausentes registrados)
         │
         ▼
  invocar_fn([prompt_corretivo]) → nova resposta
         │
         ▼
  validar(nova resposta)
         │
    satisfeito? ──── SIM ──────────────────────────► retorna nova resposta
         │
        NÃO (esgotou max_retries)
         │
  logger.error
         │
         ▼
  corrigir_com_dados() → injeta valores reais programaticamente
         │
         ▼
  retorna resposta corrigida (cliente sempre vê o dado correto)
```

### Validação multi-formato

Para evitar falsos negativos, o sistema reconhece todos os formatos monetários brasileiros e internacionais:

```python
# Para limite_credito = 3000.0, os formatos aceitos são:
["3000", "3,000", "3.000", "3,000.00", "3.000,00", "R$ 3.000", "R$ 3.000,00"]
```

---

## Justificativa

### Por que não confiar apenas no prompt de sistema?
Prompts como "use EXATAMENTE os valores acima" reduzem mas não eliminam alucinações. LLMs são estocásticos e, especialmente com valores numéricos, podem "corrigir" para um número que parece mais natural. O contrato fornece uma **rede de segurança determinística** após a geração.

### Por que retry com prompt corretivo em vez de rejeitar direto?
A rejeição direta usaria um fallback genérico que não reflete o contexto da conversa. O retry com instrução específica ("você deve mencionar R$ 3.000,00") tem alta taxa de sucesso e mantém a qualidade da resposta.

### Por que contratos por agente em vez de um único contrato global?
Cada agente tem responsabilidades diferentes:
- O agente de câmbio **não sabe** a cotação antes de chamar a tool — seu contrato valida presença de `R$`, não um valor fixo.
- O agente de entrevista valida o **novo score calculado**, não o score original.
- Um contrato global não captura essas nuances.

### Por que `corrigir_com_dados` como último recurso?
Garante que o cliente vê o dado correto via substituição inline quando possível. Se a substituição falhar, o erro é logado internamente — o fallback visível ao cliente foi removido (ver "Evolução do sistema" abaixo).

---

## Alternativas consideradas

### Structured Output (`.with_structured_output()`)
- **Vantagem:** forçar o LLM a retornar JSON com os campos obrigatórios.
- **Desvantagem:** requer dois passos (structured output → render para linguagem natural); o Gemini Flash tem suporte limitado a structured outputs com tool calls simultâneos.

### Substituição regex direta (sem retry)
- **Vantagem:** simples e determinístico.
- **Desvantagem:** pode gerar respostas incoerentes (ex.: substituir um número no meio de uma frase sem contexto).

### Validação na camada da API
- **Desvantagem:** a API não tem acesso aos dados ground-truth do estado LangGraph de forma eficiente. Melhor validar dentro do agente, onde o estado está disponível.

---

## Métricas esperadas

| Situação | Comportamento |
|---|---|
| LLM inclui valor correto | Contrato satisfeito na 1ª chamada; sem overhead |
| LLM usa valor errado | Retry com prompt corretivo; ~95% de resolução |
| LLM insiste no erro | Correção programática; cliente sempre vê dado correto |
| Logs | Todos os casos registrados com `logger.warning/error` para análise |

---

## Consequências

**Positivas:**
- Alucinações de dados financeiros são detectadas e corrigidas antes de chegar ao cliente.
- O sistema é auditável: cada falha de contrato é logada com o valor esperado e o texto gerado.
- Novos contratos podem ser adicionados sem alterar o framework base.

**Negativas / trade-offs:**
- Em caso de retry, a latência aumenta (segunda chamada ao LLM).
- Requer que cada agente defina seus contratos explicitamente — mais código inicial.

---

---

## Evolução do sistema (pós-implementação inicial)

### Problema: rodapé `_(Dados confirmados: ...)_` visível ao cliente

O fallback `corrigir_com_dados` originalmente injetava um rodapé literal na mensagem:

```
_(Dados confirmados: Seu limite de crédito disponível é R$ 5.000,00 e Seu score de crédito é 650.)_
```

Esse texto aparecia em **todas** as mensagens onde o contrato falhava — inclusive em perguntas de esclarecimento como "Qual limite você deseja?" (que legitimamente não contêm valores financeiros). Isso criava ruído visual e expunha informações de debug ao cliente.

**Correção:** O rodapé foi removido de `corrigir_com_dados`. Falhas persistentes são registradas via `logger.error` para análise interna, sem impacto na mensagem exibida ao cliente.

### Problema: validação disparando em respostas sem dados financeiros

O contrato `contrato_flash_direto` exigia `limite_credito` + `score` em **toda** resposta do agente de crédito — inclusive perguntas de coleta como "Qual valor de limite você gostaria?". Como a pergunta não continha esses valores, o contrato falhava e o fallback era acionado desnecessariamente.

**Correção:** Introduzido o campo `apenas_se_reportado: bool` em `CampoContrato`. Quando `True` (padrão para contratos financeiros), a validação só ocorre se a resposta já contém dados monetários (`R$\s*[\d.,]+`). Respostas que são perguntas de esclarecimento passam automaticamente sem validação.

```python
@dataclass
class CampoContrato:
    nome: str
    valor_esperado: Any
    obrigatorio: bool = True
    apenas_se_reportado: bool = False  # novo campo

    def deve_validar(self, texto: str) -> bool:
        if not self.obrigatorio:
            return False
        if self.apenas_se_reportado:
            return bool(re.search(r"R\$\s*[\d.,]+|\b\d{3,}\b", texto))
        return True
```

### Comportamento atual dos contratos por contexto

| Contexto | `apenas_se_reportado` | Resultado |
|---|---|---|
| Triagem / crédito informando saldo (cita R$) | `True` → valida | Corrige valor errado inline |
| Crédito perguntando "qual limite deseja?" | `True` → **pula** | Sem retry desnecessário |
| Pro após decisão de elegibilidade | `False` → sempre valida | Garante que a decisão cite os valores |
| Entrevista resultado final do score | `False` → sempre valida | Garante que o novo score seja informado |

---

## Referências

- ADR-003: Contrato `resposta_final` (garantia de roteamento)
- ADR-007: Estrutura modular por agente
- ADR-012: Resiliência com fallback de modelo
- ADR-019: Estrutura de prompts "Quando NÃO usar" (camada complementar)
- `src/infrastructure/response_contract.py`
- `src/agents/*/contract.py`
- Artigo: _"Otimização de Guardrails de Segurança em Agentes Conversacionais"_ (docs/)
