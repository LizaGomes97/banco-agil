# ADR-003 — Handoff Implícito via Grafo Único e Contrato `resposta_final`

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Decisores** | Equipe de desenvolvimento |

---

## Contexto

O sistema precisa rotear cada mensagem do cliente para o agente especialista correto (triagem, crédito, câmbio, entrevista) de forma transparente — o cliente nunca deve perceber que há múltiplos agentes.

Havia dois desafios centrais:

1. **Como sinalizar que um agente produziu uma resposta final** vs. apenas roteou internamente?
2. **Como garantir que o router não encerre um turno prematuramente ou entre em loop?**

A solução inicial usava apenas o histórico de mensagens (`AIMessage`) para inferir o fim do turno, o que era frágil: tool calls, mensagens intermediárias e fallbacks geravam falsos positivos.

---

## Decisão

### Contrato `resposta_final`

Todo agente retorna o campo `resposta_final` no dicionário de saída:

```python
# Agente tem resposta para o usuário:
return {"messages": [...], "resposta_final": "Seu limite é R$ 5.000,00."}

# Agente apenas roteou, sem mensagem ao usuário:
return {"agente_ativo": "credito", "resposta_final": None}
```

O `router` usa este campo como **único critério** para decidir se o turno acabou:

```python
def router(state: BancoAgilState) -> str:
    # 1. Encerramento explícito
    if state.get("encerrado"):
        return "salvar_memoria" if not state.get("memoria_salva") else END

    # 2. Agente sinalizou resposta final → fim do turno
    if state.get("resposta_final") is not None:
        return END

    # 3. Turno em andamento → rotear para o agente ativo
    if not state.get("cliente_autenticado"):
        return "agente_triagem"

    agente = state.get("agente_ativo", "triagem")
    return f"agente_{agente}"
```

### Estado completo: `BancoAgilState`

```python
class BancoAgilState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    """Histórico acumulativo de mensagens (reducer add_messages)."""

    cliente_autenticado: Optional[dict]
    """Dados do cliente após autenticação. None enquanto não autenticado.
    Ex.: {"cpf": "123.456.789-00", "nome": "Ana Silva",
           "limite_credito": 5000.0, "score": 650}"""

    agente_ativo: str
    """Próximo agente a receber o turno: "triagem"|"credito"|"entrevista"|"cambio"."""

    tentativas_auth: int
    """Contador de tentativas de autenticação falhas (máximo: MAX_TENTATIVAS_AUTH=3)."""

    encerrado: bool
    """True quando qualquer agente sinaliza fim de atendimento.
    Router encaminha para salvar_memoria → END."""

    memoria_cliente: Optional[list]
    """Resumos semânticos de sessões anteriores (Qdrant), injetados no contexto."""

    memoria_salva: bool
    """True após salvar_memoria ter persistido o resumo no Qdrant (evita dupla gravação)."""

    resposta_final: Optional[str]
    """Contrato de saída dos agentes.
    str  → agente tem resposta para o usuário → router vai para END
    None → agente apenas roteou → router continua avaliando destino"""
```

### Topologia do grafo

```
START
  └─► agente_triagem
            │ router()
            ├─► agente_credito
            │       │ router()
            │       └─► END  (resposta_final != None)
            ├─► agente_cambio
            │       │ router()
            │       └─► END
            ├─► agente_entrevista
            │       │ router()
            │       └─► agente_credito (após recalcular score)
            ├─► salvar_memoria ──► END  (encerrado=True)
            └─► END  (resposta_final != None)
```

---

## Justificativa

### Por que `resposta_final` em vez de inferir pelo histórico?
Inferir pelo histórico de mensagens era ambíguo: tool calls, ToolMessages e AIMessages intermediárias geravam falsos positivos. Com `resposta_final`, cada agente declara explicitamente seu "contrato de saída" — análogo ao padrão `Result<T>` em linguagens funcionais.

### Por que router determinístico (sem LLM)?
O router é chamado após **cada nó**, potencialmente múltiplas vezes por turno. Usar um LLM ali adicionaria latência significativa e risco de comportamento não-determinístico. A lógica é puramente baseada em campos de estado, tornando-a previsível e testável.

### Por que handoff implícito (sem mencionar ao cliente)?
O case técnico exige que o cliente sinta que fala com **um único assistente**. Todos os agentes têm em seu `prompt.py` a regra: "Você é UM ÚNICO assistente. NUNCA mencione transferências ou especialistas." Um filtro regex (`_RE_HANDOFF`) no código de cada agente descarta respostas que violem essa regra.

---

## Alternativas consideradas

### Multi-agente com endpoints separados
- **Desvantagem:** o cliente perceberia a troca; sessão não seria compartilhada.

### Inferir fim do turno pelo tipo da última mensagem
- **Desvantagem:** frágil, quebrava com tool calls e AIMessages intermediárias.

### Usar um LLM para decidir o roteamento
- **Desvantagem:** latência adicional em cada transição; risco de loops. O intent classifier cobre isso de forma mais cirúrgica.

---

## Consequências

**Positivas:**
- Comportamento do router é totalmente determinístico e testável unitariamente.
- Cada agente tem um contrato de saída explícito — fácil de auditar.
- O campo `resposta_final` serve como "resposta canônica" que a API lê diretamente, eliminando a necessidade de parsear o histórico de mensagens.

**Negativas / trade-offs:**
- Todo agente **precisa** retornar `resposta_final` (string ou None). Esquecer de incluí-lo pode causar loops. Mitigado por revisão de código e testes.

---

---

## Evolução do sistema (pós-implementação inicial)

### Roteamento para entrevista: de textual para determinístico

Na implementação inicial, o agente de crédito roteava para a entrevista verificando se o texto da resposta do LLM continha a palavra "entrevista":

```python
# Antes — frágil e contraditório
if "entrevista" in texto.lower():
    return {"agente_ativo": "entrevista", ...}
```

Isso criava um **catch-22**: o prompt proíbe mencionar nomes de agentes internos, mas o roteamento dependia exatamente dessa menção. Na prática, o roteamento para entrevista nunca ocorria.

**Correção:** O roteamento foi convertido para **determinístico**, baseado diretamente no resultado da tool `verificar_elegibilidade_aumento`. Quando `elegivel=False`, o código roteia para entrevista programaticamente, independente do texto gerado pelo LLM:

```python
# Depois — determinístico, baseado no resultado da tool
if elegibilidade_resultado and not elegibilidade_resultado.get("elegivel", True):
    logger.info("[CREDITO] Score insuficiente — roteando para entrevista")
    return {
        "messages": [...],
        "agente_ativo": "entrevista",
        "resposta_final": texto_transicao,
    }
```

Esse padrão é consistente com a filosofia do ADR: **roteamento baseado em estado, não em inferência do LLM**.

### Autenticação bem-sucedida: mensagem determinística

Na implementação inicial, quando a autenticação era bem-sucedida, o agente retornava `resposta_final=None` e o grafo fazia uma segunda chamada ao nó de triagem para gerar a mensagem de boas-vindas. O LLM, ao ver o histórico de tentativas anteriores, gerava mensagens de falha mesmo com o cliente autenticado.

**Correção:** A mensagem de boas-vindas pós-autenticação é agora **determinística e gerada imediatamente** no mesmo retorno que registra o cliente:

```python
texto_boas_vindas = (
    f"Olá, {primeiro_nome}! Identidade verificada com sucesso. "
    f"Como posso ajudar você hoje?"
)
return {
    "cliente_autenticado": cliente.to_dict(),
    "messages": [AIMessage(content=texto_boas_vindas)],
    "resposta_final": texto_boas_vindas,
}
```

Isso elimina a segunda passagem pelo LLM e previne confusão com o histórico de falhas.

---

## Referências

- ADR-001: LangGraph como framework
- ADR-009: Classificador de intenção via LLM
- ADR-014: Contratos de resposta (complemento de `resposta_final` com validação de conteúdo)
- ADR-019: Estrutura de prompts "Quando NÃO usar"
- `src/models/state.py`
- `src/graph.py`
