# Fluxo: Handoff Completo entre Agentes

**Data:** 2026-04-22  
**Versão:** 1.0  
**Referências:** [ADR-003](../decisions/ADR-003-handoff-agentes.md) · [ADR-001](../decisions/ADR-001-framework-agentes.md)

---

## Visão geral de uma sessão completa

Este fluxo documenta uma sessão real cobrindo todos os agentes — da entrada até o encerramento — para ilustrar como o handoff implícito funciona na prática.

```mermaid
sequenceDiagram
    actor Cliente
    participant G as StateGraph (LangGraph)
    participant T as Agente Triagem
    participant C as Agente Crédito
    participant E as Agente Entrevista
    participant CB as Agente Câmbio
    participant R as Redis

    Note over G,R: thread_id criado — sessão iniciada

    %% === TRIAGEM ===
    rect rgb(230, 240, 255)
        Note over T: FASE 1: TRIAGEM
        Cliente->>G: "Olá"
        G->>R: carregar estado (vazio)
        G->>T: roteado (sem autenticação)
        T-->>Cliente: "Olá! Bem-vindo ao Banco Ágil.\nInforme seu CPF, por favor."
        Cliente->>G: "123.456.789-00"
        G->>T: roteado
        T-->>Cliente: "Obrigado! Data de nascimento?"
        Cliente->>G: "01/01/1990"
        G->>T: roteado
        T->>T: buscar_cliente(CPF, data)
        T->>R: {cliente_autenticado: {nome: "Ana"...}}
        T-->>Cliente: "Autenticado! Como posso ajudar, Ana?"
        Cliente->>G: "quero ver meu câmbio"
        G->>T: roteado
        T->>R: {agente_ativo: "cambio"}
    end

    %% === CÂMBIO ===
    rect rgb(230, 255, 240)
        Note over CB: FASE 2: CÂMBIO (handoff imperceptível)
        G->>CB: roteado automaticamente
        CB-->>Cliente: "Qual moeda você gostaria de consultar?"
        Cliente->>G: "dólar"
        G->>CB: roteado
        CB->>CB: buscar_cotacao_cambio("cotação dólar hoje")
        CB-->>Cliente: "O dólar está cotado a R$ 5,87 hoje.\nPosso ajudá-lo com mais alguma coisa?"
        Cliente->>G: "sim, quero ver meu crédito"
        G->>CB: roteado
        CB->>R: {agente_ativo: "credito"}
    end

    %% === CRÉDITO ===
    rect rgb(255, 245, 230)
        Note over C: FASE 3: CRÉDITO (handoff imperceptível)
        G->>C: roteado automaticamente
        C-->>Cliente: "Seu limite atual é R$ 3.000,00.\nDeseja solicitar aumento?"
        Cliente->>G: "sim, quero R$ 8.000"
        G->>C: roteado
        C->>C: verificar score → 320 (insuficiente)
        C-->>Cliente: "Seu score atual não permite esse aumento.\nGostaria de fazer uma entrevista financeira?"
        Cliente->>G: "sim"
        G->>C: roteado
        C->>R: {agente_ativo: "entrevista"}
    end

    %% === ENTREVISTA ===
    rect rgb(255, 230, 255)
        Note over E: FASE 4: ENTREVISTA (handoff imperceptível)
        G->>E: roteado automaticamente
        E-->>Cliente: "Qual sua renda mensal?"
        Cliente->>G: "R$ 6.000"
        G->>E: roteado
        E-->>Cliente: "Tipo de emprego?"
        Cliente->>G: "formal"
        G->>E: roteado
        E-->>Cliente: "Número de dependentes?"
        Cliente->>G: "0"
        G->>E: roteado
        E-->>Cliente: "Possui dívidas ativas?"
        Cliente->>G: "não"
        G->>E: roteado
        E->>E: calcular_score(6000, formal, 0, não) → 880
        E->>R: {agente_ativo: "credito"}
    end

    %% === RETORNO AO CRÉDITO ===
    rect rgb(255, 245, 230)
        Note over C: FASE 5: RETORNO AO CRÉDITO
        G->>C: roteado automaticamente
        C-->>Cliente: "Seu novo score é 880! Limite aprovado\npara R$ 8.000,00. Parabéns!"
        Cliente->>G: "obrigado, pode encerrar"
        G->>C: roteado
        C->>R: {encerrado: true}
    end

    G-->>Cliente: "Foi um prazer atendê-la, Ana.\nAté a próxima!"
    Note over G,R: Sessão encerrada — TTL Redis: 30min
```

---

## O que o cliente experimenta

Do ponto de vista do cliente, a conversa foi com **um único atendente** que:
1. Consultou câmbio
2. Consultou crédito
3. Fez uma entrevista
4. Voltou ao crédito e aprovou o aumento

Nenhuma mensagem de "transferência", nenhuma reautenticação, nenhuma quebra de contexto.

---

## O que acontece por baixo dos panos

```mermaid
graph LR
    M1["Turno 1-4\nagente_ativo=triagem"] -->|"CPF+data validados"| M2
    M2["Turno 5\nagente_ativo=cambio"] -->|"cotação retornada"| M3
    M3["Turno 6-7\nagente_ativo=credito"] -->|"score insuficiente"| M4
    M4["Turno 8-12\nagente_ativo=entrevista"] -->|"score recalculado"| M5
    M5["Turno 13\nagente_ativo=credito"] -->|"encerrado=true"| END([FIM])
```

Cada seta representa uma atualização silenciosa no `BancoAgilState` do Redis. O cliente não vê nenhuma dessas transições.

---

## Encerramento de conversa

Qualquer agente pode encerrar a conversa a qualquer momento:

```python
# Em qualquer nó do grafo
if detectar_intencao_encerramento(mensagem):
    return {"encerrado": True}
# O router lê encerrado=True e retorna END
```

Frases que devem acionar encerramento:
- "encerrar", "fechar", "sair", "tchau", "obrigado, até logo", "não preciso de mais nada"
