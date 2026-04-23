# ADR-015 — Sistema de Guardrails

| Campo       | Valor                              |
|-------------|------------------------------------|
| Status      | Aceito                             |
| Data        | 2026-04-22                         |
| Autor       | Time Banco Ágil                    |
| Relacionado | ADR-003, ADR-007, ADR-014          |

---

## Contexto

O agente IA do Banco Ágil lida com dados financeiros sensíveis e interage com clientes
via chat aberto. Sem proteção explícita, o sistema fica exposto a:

- **Prompt injection**: usuários tentando subverter as instruções do LLM
- **PII leak**: dados pessoais (CPF, conta) aparecendo na resposta do modelo
- **Desvio de escopo**: perguntas fora do domínio bancário chegando ao LLM
- **Abuso de entrada**: inputs excessivamente longos (context stuffing)
- **Tom inapropriado**: linguagem agressiva sem rastreabilidade

Até a implementação deste ADR, existiam guardrails informais e dispersos (regex em
agentes, sanitização em `triagem/agent.py`). A decisão foi formalizá-los em uma camada
dedicada, escalável e com criticidade explícita.

---

## Decisão

Implementar um **sistema formal de guardrails** em `src/middleware/guardrails/`,
com as seguintes características arquiteturais:

### 1. Localização

Dentro de `src/middleware/` — camada transversal ao sistema, separada da lógica
de agentes (`src/agents/`) e de infraestrutura (`src/infrastructure/`).

### 2. Um arquivo por domínio de guardrail

Cada guardrail representa um domínio de risco e vive em seu próprio arquivo.
A severidade é uma **propriedade interna de cada check**, não uma separação de pastas.

```
src/middleware/guardrails/
  _base.py                 ← tipos, contrato, executor
  prompt_injection.py      ← domínio: manipulação do LLM
  pii_output.py            ← domínio: vazamento de dados pessoais
  escopo_bancario.py       ← domínio: tópicos fora do banco
  tamanho_input.py         ← domínio: sobrecarga de contexto
  tom_agressivo.py         ← domínio: linguagem inadequada
  __init__.py              ← agregador público
```

### 3. Criticidade interna com parada antecipada

Dentro de cada guardrail, os checks rodam na ordem **crítico → alto → médio**
e param no primeiro que reprovar. Não faz sentido continuar se já há uma falha crítica.

| Severidade | Comportamento                                                              |
|------------|----------------------------------------------------------------------------|
| `CRITICO`  | Bloqueia imediatamente. Mensagem fixa ao cliente. Log como `ERROR`.        |
| `ALTO`     | Bloqueia o turno. Permite nova tentativa. Log como `WARNING`.              |
| `MEDIO`    | Só registra em log (`INFO`). Cliente não vê nada. Não interrompe o fluxo. |

### 4. `GuardrailResult` como contrato de retorno padronizado

Todos os guardrails retornam o mesmo tipo, permitindo que o executor reaja sem
conhecer os detalhes de cada implementação:

```python
@dataclass
class GuardrailResult:
    aprovado: bool
    severidade: Optional[Severidade]
    motivo: str                        # para o log interno
    mensagem_cliente: Optional[str]    # exibida apenas em CRITICO e ALTO
```

### 5. Fase de execução separada no agregador

O arquivo `__init__.py` define duas listas explícitas que determinam onde cada
guardrail atua no fluxo de requisição:

```python
input_runner  = GuardrailRunner(INPUT_GUARDRAILS)   # antes do graph.invoke()
output_runner = GuardrailRunner(OUTPUT_GUARDRAILS)  # após o graph.invoke()
```

### 6. Ponto de integração único: `api/main.py`

```
POST /api/chat
    ↓
input_runner.executar(req.message)
    ↓ (CRITICO ou ALTO: retorna imediatamente sem invocar LLM)
graph.invoke()
    ↓
output_runner.executar(reply)
    ↓ (CRITICO ou ALTO: substitui reply por mensagem segura)
Resposta ao cliente
```

---

## Guardrails implementados

| Arquivo              | Fase   | Checks                                |
|----------------------|--------|---------------------------------------|
| `prompt_injection`   | input  | CRITICO: jailbreak direto             |
|                      |        | ALTO: redefinição de identidade       |
|                      |        | MEDIO: consulta sobre prompts internos|
| `pii_output`         | output | CRITICO: CPF ou número de conta       |
|                      |        | ALTO: data de nascimento ou agência   |
| `escopo_bancario`    | input  | ALTO: tópicos inequívocos fora do banco|
|                      |        | MEDIO: finanças fora do portfólio     |
| `tamanho_input`      | input  | MEDIO: input > 2.000 caracteres       |
| `tom_agressivo`      | input  | MEDIO: linguagem ofensiva             |

---

## Alternativas consideradas

### Guardrails externos (ex.: LlamaGuard, AWS Guardrails for Bedrock)
- **Prós**: mais abrangentes, treinados especificamente para segurança
- **Contras**: latência adicional, custo por chamada, dependência externa, incompatível
  com o modelo Gemini usado neste projeto
- **Decisão**: descartado para o MVP; pode ser adicionado em produção real

### Guardrails no nível do prompt (system instructions)
- **Prós**: zero código, fácil de ajustar
- **Contras**: dependente do comportamento do LLM, não confiável para dados críticos
  (ex.: PII), sem rastreabilidade no log
- **Decisão**: complementar, não substituto — os prompts continuam com instruções de
  escopo, mas o código valida explicitamente o que importa

### Separação por pastas de severidade (`critical/`, `high/`, `medium/`)
- **Prós**: navegação direta por criticidade
- **Contras**: fragmenta a lógica de um mesmo domínio em arquivos diferentes;
  um domínio como "prompt injection" tem checks de severidades diferentes que
  precisam ser lidos juntos para fazer sentido
- **Decisão**: severidade é atributo interno do check, não separação de pastas

---

## Consequências

**Positivas:**
- Camada explícita e auditável de segurança, independente dos agentes
- Fácil de estender: novo guardrail = novo arquivo + linha no agregador
- Log estruturado por severidade permite análise de ameaças
- Sem latência adicional de rede (tudo em processo)

**Negativas:**
- Guardrails por regex têm limitações: não detectam ataques semânticos sofisticados
- Manutenção das listas de padrões exige atualização periódica
- `MEDIO` não bloqueia: linguagem ofensiva é registrada mas o cliente continua
  (decisão intencional para evitar falsos positivos)

**Próximos passos recomendados:**
- Adicionar guardrail semântico (LLM-as-judge) para casos que regex não cobre
- Implementar rate limiting por sessão como guardrail de `ALTO`
- Revisar padrões de regex a cada sprint com base nos logs acumulados
