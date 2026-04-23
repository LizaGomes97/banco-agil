---
name: system-flows
description: Cria diagramas de fluxo e sequência para documentar interações entre agentes, chamadas de ferramentas, e jornadas do usuário. Use quando precisar detalhar como um fluxo funciona passo a passo, sequência de chamadas entre componentes, happy path e edge cases de um cenário.
---

# Fluxos do Sistema

Documenta o comportamento dinâmico do sistema: quem chama quem, em que ordem, e o que acontece em cada caso.

## Quando usar

- Antes de implementar um agente (design-first)
- Para documentar um fluxo complexo recém-implementado
- Ao encontrar um bug: mapear o fluxo real vs esperado
- Para o README/documentação do case

## Padrão de saída

Salvar em `docs/flows/` com nome descritivo:
- `docs/flows/autenticacao.md`
- `docs/flows/solicitacao-credito.md`
- `docs/flows/handoff-agentes.md`

## Template: Sequência entre Agentes

```mermaid
sequenceDiagram
    actor Cliente
    participant UI as Streamlit UI
    participant T as Agente Triagem
    participant C as Agente Crédito
    participant CSV as clientes.csv

    Cliente->>UI: "Olá, quero consultar meu crédito"
    UI->>T: mensagem do usuário
    T->>Cliente: "Qual seu CPF?"
    Cliente->>T: "123.456.789-00"
    T->>Cliente: "Qual sua data de nascimento?"
    Cliente->>T: "01/01/1990"
    T->>CSV: buscar(cpf, data_nasc)
    CSV-->>T: cliente encontrado ✓

    T->>C: handoff(contexto_autenticado)
    C->>Cliente: "Seu limite atual é R$ 5.000..."
```

## Template: Fluxo com Decisões (graph TD)

```mermaid
graph TD
    Start([Cliente conecta]) --> Saudacao
    Saudacao --> ColetaCPF[Coletar CPF]
    ColetaCPF --> ColetaData[Coletar data de nascimento]
    ColetaData --> Validar{Autenticar no CSV}

    Validar -->|Sucesso| IdentificarIntencao[Identificar intenção]
    Validar -->|Falha - 1ª ou 2ª| NovasTentativas[Solicitar novamente]
    Validar -->|Falha - 3ª| Encerrar([Encerrar com mensagem amigável])
    NovasTentativas --> Validar

    IdentificarIntencao -->|Crédito| AgenteCredito[Agente de Crédito]
    IdentificarIntencao -->|Câmbio| AgenteCambio[Agente de Câmbio]
    IdentificarIntencao -->|Encerrar| Encerrar
```

## Template: Fluxo de Decisão de Score

```mermaid
graph TD
    Entrevista --> Calculo[Calcular score ponderado]
    Calculo --> Aprovado{Score suficiente?}
    Aprovado -->|Sim| StatusAprovado[status: aprovado]
    Aprovado -->|Não| StatusReprovado[status: reprovado]
    StatusReprovado --> OfertaEntrevista{Cliente quer entrevista?}
    OfertaEntrevista -->|Sim| AgenteEntrevista[Agente Entrevista de Crédito]
    OfertaEntrevista -->|Não| Encerrar([Encerrar ou redirecionar])
```

## Convenções de notação

| Símbolo | Significado |
|---------|-------------|
| `actor` | Usuário externo |
| `participant` | Componente do sistema |
| `-->>`  | Resposta / retorno assíncrono |
| `->>`   | Chamada / requisição |
| `Note over X` | Anotação de contexto |
| `alt / else` | Condicionais no sequenceDiagram |

## Checklist do fluxo

- [ ] Happy path documentado
- [ ] Edge cases mapeados (falha de auth, API fora, CSV corrompido)
- [ ] Responsabilidade de cada agente clara (sem overlap)
- [ ] Handoffs entre agentes explícitos
- [ ] Fluxo de encerramento coberto
