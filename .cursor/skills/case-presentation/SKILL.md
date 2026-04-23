---
name: case-presentation
description: Estrutura a apresentação do case técnico para impressionar avaliadores e conquistar a vaga. Use ao preparar README, documentação de entrega, estrutura de repositório, tutorial de execução, ou quando o usuário perguntar como organizar o projeto para apresentação, como escrever o README, como documentar o case.
---

# Apresentação do Case Técnico

Este skill garante que o projeto seja avaliado pelo que realmente vale — transformando bom código em uma entrega memorável.

## Princípio central

> O avaliador leva ~10 minutos lendo seu projeto. Cada segundo conta.
> Faça a primeira impressão ser: "esse candidato pensa como engenheiro."

## Estrutura do repositório ideal

```
projeto/
├── README.md                    ← porta de entrada, deve impressionar
├── docs/
│   ├── decisions/               ← ADRs (decisões técnicas)
│   │   ├── INDEX.md
│   │   └── ADR-001-*.md
│   ├── diagrams/                ← arquitetura visual
│   │   └── arquitetura-geral.md
│   └── flows/                   ← fluxos de agentes
│       └── fluxo-autenticacao.md
├── src/
│   ├── agents/                  ← um arquivo por agente
│   ├── tools/                   ← ferramentas reutilizáveis
│   ├── models/                  ← schemas de dados
│   └── main.py
├── data/
│   ├── clientes.csv
│   └── solicitacoes_aumento_limite.csv
├── tests/
├── .env.example                 ← NUNCA commitar .env real
└── requirements.txt
```

## Template README.md

```markdown
# 🏦 Banco Ágil — Agente de Atendimento Inteligente

> Sistema multi-agente para atendimento bancário com autenticação,
> consulta de crédito, entrevista financeira e cotação de câmbio.

## Demonstração rápida

[GIF ou screenshot da UI]

## Arquitetura

[Inserir diagrama Mermaid da arquitetura geral]

## Agentes

| Agente | Responsabilidade |
|--------|-----------------|
| Triagem | Autenticação (CPF + data nasc.) e roteamento |
| Crédito | Consulta e solicitação de aumento de limite |
| Entrevista de Crédito | Recalcula score via entrevista financeira |
| Câmbio | Cotação em tempo real via API externa |

## Decisões técnicas

- [ADR-001: Framework de Agentes](docs/decisions/ADR-001-framework-agentes.md)
- [ADR-002: Modelo LLM](docs/decisions/ADR-002-modelo-llm.md)
- [ADR-003: Estratégia de Handoff](docs/decisions/ADR-003-handoff.md)

## Como executar

\`\`\`bash
# 1. Clone e instale dependências
git clone <repo>
cd banco-agil
pip install -r requirements.txt

# 2. Configure variáveis de ambiente
cp .env.example .env
# Edite .env com suas chaves de API

# 3. Execute
streamlit run src/main.py
\`\`\`

## Variáveis de ambiente necessárias

| Variável | Descrição |
|----------|-----------|
| `GEMINI_API_KEY` | Chave da API Gemini |
| `EXCHANGE_API_KEY` | Chave para cotação de câmbio |

## Desafios e soluções

### Handoff implícito entre agentes
**Desafio:** O cliente não deve perceber a transição entre agentes.  
**Solução:** [descrever abordagem]

### Autenticação com retry limit
**Desafio:** Máximo 3 tentativas de autenticação.  
**Solução:** [descrever abordagem]

## Testes

\`\`\`bash
pytest tests/ -v
\`\`\`
```

## O que diferencia um case 10/10

| Dimensão | Mediano | Excelente |
|----------|---------|-----------|
| Código | Funciona | Organizado, tipado, testável |
| Docs | README básico | ADRs + diagramas + fluxos |
| Decisões | Implícitas | Documentadas com justificativa |
| Edge cases | Não tratados | Mapeados e cobertos |
| UI | Funcional | Intuitiva, com feedback claro |
| Erros | Crash ou silêncio | Mensagem amigável + log técnico |

## Checklist final antes de entregar

### Código
- [ ] Cada agente em seu próprio módulo
- [ ] Sem credenciais hardcoded (usar `.env`)
- [ ] `.env.example` com todas as variáveis necessárias
- [ ] `requirements.txt` completo e com versões fixadas

### Documentação
- [ ] README com instruções claras de execução
- [ ] Pelo menos 3 ADRs com decisões-chave
- [ ] Diagrama de arquitetura geral
- [ ] Fluxo principal documentado

### Funcionalidade
- [ ] Autenticação com 3 tentativas máximas
- [ ] Handoff imperceptível ao usuário
- [ ] Todos os 4 agentes funcionando
- [ ] Tratamento de erros (CSV, API, entrada inválida)
- [ ] Encerramento de conversa funciona

### UI (Streamlit)
- [ ] Interface limpa e sem erros visuais
- [ ] Histórico de conversa visível
- [ ] Estado do sistema comunicado ao usuário

## Recursos adicionais

- Para estrutura de diagramas, use a skill `architecture-diagrams`
- Para documentar fluxos, use a skill `system-flows`
- Para registrar decisões, use a skill `technical-decisions`
