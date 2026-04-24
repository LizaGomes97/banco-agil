# ADR-018 — Arquitetura de Prompts: Funções Python em vez de Arquivos `.md`

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Decisores** | Equipe de desenvolvimento |

---

## Contexto

Os prompts dos agentes eram armazenados em arquivos `.md` estáticos (`prompt.md`, `prompt_pro.md`) e a parte dinâmica — dados do cliente, memórias semânticas, métricas de elegibilidade — era concatenada via f-strings diretamente no `agent.py`:

```python
# Antes: construção espalhada em agent.py
_SYSTEM_PROMPT = Path("prompt.md").read_text()

contexto = (
    f"\n\n## Dados do cliente\n"
    f"- Nome: {cliente.get('nome', '')}\n"
    f"- Limite: R$ {limite:,.2f}\n"
    f"- Score: {score}\n"
    f"- Elegível: {'Sim' if score_aprovado(score) else 'Não'}\n"
    f"\nIMPORTANTE: use EXATAMENTE os valores acima."
)

messages = [SystemMessage(content=_SYSTEM_PROMPT + contexto)] + state["messages"]
```

Esse padrão criou três problemas identificados durante o desenvolvimento:

1. **Prompt partido em dois lugares:** conteúdo estático no `.md`, contexto dinâmico no `agent.py`. Para entender o prompt completo que o LLM recebe, é necessário ler dois arquivos.
2. **Sem testabilidade:** não há como testar unitariamente a construção do prompt sem instanciar o agente inteiro.
3. **Sem suporte de IDE:** concatenações f-string não têm autocompletar, refatoração, nem "go to definition" para os dados injetados.

---

## Decisão

Substituir os arquivos `.md` por arquivos `prompt.py` em cada pasta de agente, seguindo o padrão de **funções Python que retornam strings completas** — inspirado diretamente na arquitetura dos arquivos `prompt.ts` do Claude Code, onde cada ferramenta tem uma função `getPrompt()` que monta o texto final com toda a lógica condicional:

```python
# src/agents/credito/prompt.py

_FLASH_BASE = """..."""  # conteúdo estático

def build_flash_prompt(cliente: dict, memorias: list[str] | None = None) -> str:
    limite = float(cliente.get("limite_credito", 0))
    score = int(cliente.get("score", 0))
    elegivel = score_aprovado(score)

    contexto = f"""
## Dados do cliente autenticado
- Nome: {cliente.get("nome", "")}
- Limite atual: R$ {limite:,.2f}
- Score atual: {score}
- Elegível para aumento: {"Sim" if elegivel else "Não"}

IMPORTANTE: use EXATAMENTE os valores acima."""

    if memorias:
        contexto += "\n\n## Interações anteriores\n" + "\n".join(f"- {m}" for m in memorias)

    return _FLASH_BASE + contexto
```

```python
# src/agents/credito/agent.py — após a mudança

from .prompt import build_flash_prompt, build_pro_prompt

messages = [SystemMessage(content=build_flash_prompt(cliente, memorias))] + state["messages"]
```

### Estrutura resultante por agente

```
src/agents/<nome>/
├── agent.py      # lógica de orquestração, tool calls, roteamento
├── prompt.py     # construção do system prompt (estático + dinâmico)
├── contract.py   # definição dos contratos de resposta
└── __init__.py
```

### Funções por agente

| Agente | Funções em `prompt.py` |
|---|---|
| `triagem` | `build_system_prompt(cliente?)` |
| `credito` | `build_flash_prompt(cliente, memorias?)`, `build_pro_prompt(cliente, memorias?)` |
| `cambio` | `build_system_prompt(cliente, memorias?)` |
| `entrevista` | `build_system_prompt(cliente, memorias?)` |

---

## Justificativa

### Por que Python em vez de `.md`?

| Critério | `.md` + concatenação | `prompt.py` com funções |
|---|---|---|
| Prompt completo visível | ❌ Dividido em 2 arquivos | ✅ Uma função retorna tudo |
| Testabilidade unitária | ❌ Requer instanciar agente | ✅ `assert "R$ 5.000" in build_flash_prompt(cliente)` |
| Suporte de IDE | ❌ Concatenação opaca | ✅ Assinatura tipada, autocompletar |
| Lógica condicional | ❌ `if` no `agent.py`, longe do prompt | ✅ Co-localizado na função |
| Renderização GitHub | ✅ Formatado como Markdown | ❌ Código Python |

O único trade-off é a perda de renderização Markdown no GitHub, que neste projeto é menos relevante do que a manutenibilidade do código.

### Por que se inspirar no Claude Code?

Os arquivos `prompt.ts` do Claude Code (`BashTool/prompt.ts`, `AgentTool/prompt.ts`) demonstram que mesmo sistemas de IA de produção tratam a construção de prompts como código: funções com parâmetros, lógica condicional, composição de seções. O padrão é maduro e testado em escala.

---

## Alternativas consideradas

### Jinja2 (templates `.j2`)
- **Vantagem:** templating completo com herança, partials, filtros.
- **Desvantagem:** dependência extra; a expressividade do Python f-strings é suficiente para este caso de uso; adiciona uma camada de indireção sem benefício claro.

### YAML com campos estruturados
- **Vantagem:** permite metadados (model, temperature, version) junto ao prompt.
- **Desvantagem:** multiline strings em YAML têm sintaxe estranha; interpolação de variáveis requer pós-processamento adicional.

### Manter `.md` com metadados YAML no frontmatter
- **Vantagem:** legível, padrão usado por algumas ferramentas de gestão de prompts.
- **Desvantagem:** não resolve os problemas de testabilidade e IDE; ainda requer lógica de parsing separada.

---

## Consequências

**Positivas:**
- Prompt completo (estático + dinâmico) visível em um único lugar por agente.
- Testável isoladamente: é possível verificar injeção de dados sem subir o grafo.
- `agent.py` reduzido em ~15–20 linhas por agente; foco em orquestração.
- Lógica condicional (ex.: "incluir memórias só se existirem") co-localizada com o prompt.

**Negativas / trade-offs:**
- Prompts não são mais renderizáveis diretamente no GitHub como Markdown.
- Requer reescrita de todos os prompts ao migrar (custo inicial de refatoração).

---

## Referências

- ADR-007: Estrutura de Código — Módulos por Agente
- [Claude Code `BashTool/prompt.ts`](../..): padrão de referência adotado
- `src/agents/*/prompt.py`
