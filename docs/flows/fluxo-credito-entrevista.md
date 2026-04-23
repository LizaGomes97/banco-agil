# Fluxo: Crédito e Entrevista de Crédito

**Data:** 2026-04-22  
**Versão:** 1.0  
**Referências:** [ADR-005](../decisions/ADR-005-calculo-score.md) · [ADR-003](../decisions/ADR-003-handoff-agentes.md)

---

## Sequência: Solicitação de Aumento de Limite

```mermaid
sequenceDiagram
    actor Cliente
    participant C as Agente Crédito
    participant CSV_C as clientes.csv
    participant CSV_S as solicitacoes_aumento_limite.csv
    participant E as Agente Entrevista
    participant Score as score_calculator.py

    Note over Cliente,C: Cliente já autenticado pelo Agente de Triagem

    C-->>Cliente: "Seu limite atual é R$ 5.000,00.\nPosso ajudá-lo com alguma coisa?"

    Cliente->>C: "Quero aumentar meu limite"
    C-->>Cliente: "Qual seria o novo limite desejado?"
    Cliente->>C: "R$ 10.000,00"

    C->>CSV_C: buscar_score(cpf)
    CSV_C-->>C: score = 650

    alt Score suficiente (>= 500)
        C->>CSV_S: registrar_solicitacao(cpf, 5000, 10000, 'aprovado')
        C-->>Cliente: "Parabéns! Seu limite foi aprovado\npara R$ 10.000,00."
    else Score insuficiente (< 500)
        C->>CSV_S: registrar_solicitacao(cpf, 5000, 10000, 'reprovado')
        C-->>Cliente: "Infelizmente seu score atual não\npermite esse aumento. Gostaria de\nrealizar uma entrevista financeira\npara tentar melhorar seu score?"

        alt Cliente aceita entrevista
            C->>C: state.agente_ativo = 'entrevista'
            Note over E: Handoff imperceptível para Entrevista

            E-->>Cliente: "Vou fazer algumas perguntas\npara atualizar seu perfil financeiro."
            E-->>Cliente: "Qual é sua renda mensal?"
            Cliente->>E: "R$ 4.000,00"
            E-->>Cliente: "Qual seu tipo de emprego?\n(formal, autônomo, desempregado)"
            Cliente->>E: "formal"
            E-->>Cliente: "Quantos dependentes você tem?"
            Cliente->>E: "1"
            E-->>Cliente: "Possui dívidas ativas?"
            Cliente->>E: "não"

            E->>Score: calcular_score(4000, 'formal', 1, 'não')
            Score-->>E: {score: 780, detalhamento: {...}}

            E->>CSV_C: atualizar_score(cpf, 780)
            E->>C: state.agente_ativo = 'credito'
            Note over C: Retorna ao Agente de Crédito

            C->>CSV_S: atualizar_status(solicitacao_id, 'aprovado')
            C-->>Cliente: "Ótima notícia! Seu novo score é 780\ne seu limite foi aprovado para R$ 10.000,00!"

        else Cliente recusa entrevista
            C-->>Cliente: "Entendido. Posso ajudá-lo com\nalguma outra coisa?"
        end
    end
```

---

## Fluxo de decisão do score

```mermaid
flowchart TD
    InicioCredito([Agente Crédito ativado]) --> ConsultaLimite["Consultar limite atual\nno clientes.csv"]
    ConsultaLimite --> ApresentaLimite["Apresentar limite ao cliente"]
    ApresentaLimite --> ClienteQuerAumento{Cliente quer\naumento?}

    ClienteQuerAumento -->|Não| OutrasDemandas["Encerrar ou redirecionar"]
    ClienteQuerAumento -->|Sim| ColetaNovoLimite["Coletar novo limite desejado"]
    ColetaNovoLimite --> ConsultaScore["Buscar score no CSV"]

    ConsultaScore --> ScoreSuficiente{Score >= 500?}
    ScoreSuficiente -->|Sim| RegistrarAprovado["Registrar solicitação\nstatus: aprovado"]
    RegistrarAprovado --> InformarAprovado["Informar aprovação ao cliente"]

    ScoreSuficiente -->|Não| RegistrarReprovado["Registrar solicitação\nstatus: reprovado"]
    RegistrarReprovado --> OfertarEntrevista["Oferecer redirecionamento\npara Entrevista de Crédito"]

    OfertarEntrevista --> ClienteAceita{Cliente aceita\nentrevista?}
    ClienteAceita -->|Sim| HandoffEntrevista["state.agente_ativo = 'entrevista'"]
    HandoffEntrevista --> Entrevista["Agente Entrevista\nconduz perguntas"]
    Entrevista --> ScoreRecalculado["score_calculator.py\nCalcula novo score"]
    ScoreRecalculado --> AtualizaCSV["Atualiza score\nno clientes.csv"]
    AtualizaCSV --> RetornaCredito["state.agente_ativo = 'credito'"]
    RetornaCredito --> ReprocessaScore["Reprocessa solicitação\ncom novo score"]

    ClienteAceita -->|Não| EncerrarOuRedirecionar["Encerrar atendimento\nou novo assunto"]
```

---

## Fórmula de score (referência rápida)

Conforme especificado no case e documentado no [ADR-005](../decisions/ADR-005-calculo-score.md):

```
score = peso_renda + peso_emprego + peso_dependentes + peso_dividas

Onde:
  peso_renda       = min(renda_mensal / 1000 * 30, 900)
  peso_emprego     = formal→300 | autônomo→200 | desempregado→0
  peso_dependentes = 0→100 | 1→80 | 2→60 | 3+→30
  peso_dividas     = sim→-100 | não→100

Limiar de aprovação: score >= 500
```

---

## Edge cases cobertos

| Cenário | Comportamento esperado |
|---------|----------------------|
| Cliente já tem o maior limite possível | Agente informa e encerra educadamente |
| Novo limite menor que o atual | Agente questiona e confirma antes de registrar |
| Erro ao escrever no CSV | Log técnico, mensagem amigável ao cliente |
| Cliente pede entrevista sem solicitação prévia | Agente aceita e conduz diretamente |
| Score após entrevista ainda insuficiente | Informar honestamente, sem loop infinito |
