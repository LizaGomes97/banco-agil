# ADR-008: Lead Capture para Não Clientes

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O case técnico exige que a autenticação seja conduzida **pelo Agente de Triagem via chat** — esse requisito é inegociável e não foi alterado.

Porém, durante o desenvolvimento identificamos uma oportunidade de negócio não coberta pelo fluxo principal: o que acontece com um usuário que tenta ser atendido mas **não está cadastrado na base de clientes**? Atualmente o sistema simplesmente encerra após 3 tentativas falhas, sem capturar nenhuma informação.

Em um produto bancário real, esse é exatamente o perfil de um **lead qualificado** — alguém interessado nos serviços do banco que ainda não é cliente.

---

## Decisão

**Adicionar um formulário de lead capture na camada de UI (Streamlit), sem alterar nenhum agente.**

A feature opera em dois pontos de entrada:
1. **Pós-encerramento por falha de auth**: quando o chat encerra após 3 tentativas falhas, a UI exibe um card convidando o usuário a solicitar cadastro
2. **Sidebar permanente**: botão "Quero me tornar cliente" sempre visível, independente do estado da conversa

Os dados coletados são salvos em `data/leads.csv`.

---

## Justificativa

### Por que na camada UI e não no agente?

O case exige explicitamente que o **Agente de Triagem** faça a autenticação. Implementar o lead capture no agente criaria um conflito de responsabilidades — o agente estaria simultaneamente autenticando clientes e captando leads, além de desviar do escopo definido no desafio.

A separação é limpa:
- **Agente de Triagem**: autentica clientes existentes (requisito do case)
- **UI Streamlit**: captura leads de não clientes (feature extra)

### Por que é um bom extra para o case?

| Dimensão | Impacto |
|----------|---------|
| Visão de produto | Demonstra pensar além do requisito técnico |
| Valor de negócio | Transforma falhas de auth em oportunidade comercial |
| Complexidade zero | Não afeta nenhum agente existente |
| Demonstrável | Visível e tangível durante a apresentação |

---

## Dados capturados

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `nome` | string | Sim | Nome completo |
| `cpf` | string | Sim | CPF informado (não autenticado) |
| `telefone` | string | Sim | Número para contato |
| `limite_desejado` | float | Não | Limite de crédito desejado |
| `criado_em` | datetime | Auto | Timestamp da solicitação |

Arquivo: `data/leads.csv`

---

## Alternativas consideradas

| Opção | Descartada por |
|-------|----------------|
| Capturar lead dentro do Agente de Triagem | Conflita com o requisito do case (agente autentica, não capta leads) |
| Banco de dados externo (SQLite, PostgreSQL) | Overhead desnecessário para um case de demonstração |
| Formulário apenas pós-falha | Perderíamos leads de pessoas curiosas que nunca tentaram o chat |

---

## Consequências

**Positivas:**
- Feature demonstrável durante apresentação do case
- Zero impacto nos agentes existentes
- Dados de lead disponíveis para análise posterior
- UX mais completa: nenhum visitante "sai com as mãos vazias"

**Negativas / trade-offs aceitos:**
- Dados de CPF não verificados (pessoa pode inserir qualquer CPF no form de lead)
- `leads.csv` não tem deduplicação — mesma pessoa pode se cadastrar múltiplas vezes

---

## Referências

- [ADR-003](ADR-003-handoff-agentes.md) — Estrutura do estado (encerrado=True detectado pela UI)
- [ADR-007](ADR-007-estrutura-codigo.md) — Separação de responsabilidades UI vs agentes
