# Fluxo: Autenticação do Cliente (Agente de Triagem)

**Data:** 2026-04-22  
**Versão:** 1.0  
**Referências:** [ADR-003](../decisions/ADR-003-handoff-agentes.md) · [ADR-004](../decisions/ADR-004-persistencia-estado.md)

---

## Sequência de autenticação

```mermaid
sequenceDiagram
    actor Cliente
    participant UI as Streamlit UI
    participant T as Agente Triagem
    participant CSV as clientes.csv
    participant Redis as Redis (Estado)

    Cliente->>UI: Inicia conversa
    UI->>T: nova sessão (thread_id gerado)
    T->>Redis: criar estado inicial\n{tentativas_auth: 0, autenticado: null}
    T-->>Cliente: "Olá! Bem-vindo ao Banco Ágil.\nPode me informar seu CPF?"

    Cliente->>T: informa CPF
    T-->>Cliente: "Obrigado! Agora preciso da sua\ndata de nascimento."

    Cliente->>T: informa data de nascimento
    T->>CSV: buscar(cpf, data_nascimento)

    alt Autenticação bem-sucedida
        CSV-->>T: cliente encontrado ✓
        T->>Redis: {cliente_autenticado: {...}, tentativas_auth: 0}
        T-->>Cliente: "Autenticado com sucesso, [Nome]!\nComo posso ajudá-lo hoje?"
        T->>Redis: aguarda próxima mensagem para identificar intenção
    else Autenticação falhou (1ª ou 2ª tentativa)
        CSV-->>T: cliente não encontrado ✗
        T->>Redis: {tentativas_auth: +1}
        T-->>Cliente: "Não consegui verificar seus dados.\nPoderia tentar novamente?\n(Tentativa X de 3)"
        Note over T,Cliente: Loop volta ao início da coleta de CPF
    else Autenticação falhou (3ª tentativa)
        CSV-->>T: cliente não encontrado ✗
        T->>Redis: {tentativas_auth: 3, encerrado: true}
        T-->>Cliente: "Infelizmente não foi possível autenticar\nsua identidade. Por favor, entre em\ncontato com nossa central. Até logo!"
        Note over UI: Conversa encerrada
    end
```

---

## Fluxo de decisão (visão do código)

```mermaid
flowchart TD
    Start([Nova mensagem]) --> TemCPF{CPF coletado?}
    TemCPF -->|Não| PedirCPF["Solicitar CPF"]
    TemCPF -->|Sim| TemData{Data nasc. coletada?}
    TemData -->|Não| PedirData["Solicitar data nasc."]
    TemData -->|Sim| Validar["Buscar no CSV\nbuscar_cliente(cpf, data)"]

    Validar --> Encontrado{Encontrado?}
    Encontrado -->|Sim| Autenticado["state.cliente_autenticado = dados\nstate.agente_ativo = 'triagem'"]
    Autenticado --> IdentificarIntencao["Identificar intenção do cliente"]
    IdentificarIntencao --> Redirecionar["state.agente_ativo = 'credito'|'cambio'|'entrevista'"]

    Encontrado -->|Não| ContarTentativa["state.tentativas_auth += 1"]
    ContarTentativa --> Limite{tentativas >= 3?}
    Limite -->|Não| MsgErro["Mensagem de erro amigável\nSolicitar novamente"]
    MsgErro --> PedirCPF
    Limite -->|Sim| Encerrar["state.encerrado = True\nMensagem de encerramento"]
    Encerrar --> END([FIM])
```

---

## Edge cases cobertos

| Cenário | Comportamento esperado |
|---------|----------------------|
| CPF com ou sem máscara (`123.456.789-00` vs `12345678900`) | Normalizar antes de comparar |
| Data em formatos diferentes (`01/01/1990` vs `1990-01-01`) | Normalizar para ISO antes de comparar |
| Cliente digita texto no lugar do CPF | Agente solicita novamente com orientação |
| Usuário pede para encerrar durante autenticação | `encerrado = True` imediato |
| CSV vazio ou corrompido | Mensagem de erro técnico + log, não expõe detalhes ao cliente |
