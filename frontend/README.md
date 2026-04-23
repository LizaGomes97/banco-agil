# Banco Ágil — Frontend do Assistente IA

Interface web do agente financeiro do Banco Ágil. Construída com **React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui**, se comunica com o backend LangGraph via uma bridge **FastAPI**.

> **Decisão técnica detalhada:** ver [`docs/ADR-001-stack-frontend.md`](./docs/ADR-001-stack-frontend.md)

---

## Stack

| Tecnologia        | Versão   | Papel                                      |
|-------------------|----------|--------------------------------------------|
| React             | 18.3     | Framework UI                               |
| TypeScript        | —        | Tipagem estática                           |
| Vite              | 6.3      | Build tool + proxy de desenvolvimento      |
| Tailwind CSS      | 4.1      | Estilização utility-first                  |
| shadcn/ui (Radix) | —        | Componentes acessíveis                     |
| markdown-to-jsx   | 9.7      | Renderização de Markdown nas respostas     |
| sonner            | 2.0      | Toasts de notificação                      |
| lucide-react      | 0.487    | Ícones                                     |

---

## Pré-requisitos

- **Node.js** ≥ 18
- **pnpm** ≥ 9 (`npm install -g pnpm`)
- Backend FastAPI rodando em `localhost:8000` (ver `../api/main.py`)

---

## Instalação

```bash
cd frontend
pnpm install
```

---

## Desenvolvimento

Em dois terminais separados:

**Terminal 1 — Backend (da raiz do projeto):**
```bash
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
pnpm dev
```

Acesse em: **http://localhost:5173**

O Vite faz proxy automático de `/api/*` → `http://localhost:8000`, então não há conflito de CORS em desenvolvimento.

---

## Build para produção

```bash
cd frontend
pnpm build
```

Os arquivos estáticos ficam em `frontend/dist/`. Sirva-os com o Nginx ou via FastAPI (StaticFiles).

---

## Variáveis de ambiente

Crie um arquivo `.env` em `frontend/` (já ignorado pelo git):

```env
# URL base da API em produção (em desenvolvimento, deixe vazio — o proxy do Vite cuida)
VITE_API_BASE_URL=
```

---

## Estrutura

```
frontend/
├── docs/
│   └── ADR-001-stack-frontend.md   # Decisão de stack
├── src/
│   ├── app/
│   │   ├── App.tsx                 # Componente raiz — orquestra chat e sidebar
│   │   ├── components/
│   │   │   ├── AppHeader.tsx       # Cabeçalho com branding Banco Ágil
│   │   │   ├── ChatMessage.tsx     # Bolhas de mensagem (user/assistente)
│   │   │   ├── ConversationSidebar.tsx  # Lista de conversas com busca
│   │   │   ├── EmptyState.tsx      # Boas-vindas com sugestões clicáveis
│   │   │   ├── MessageComposer.tsx # Campo de texto + botão enviar
│   │   │   ├── TypingIndicator.tsx # Indicador "digitando..."
│   │   │   ├── SkeletonLoader.tsx  # Skeleton durante carregamento
│   │   │   └── ui/                 # Kit shadcn (button, dialog, input...)
│   │   └── services/
│   │       └── api.ts              # Chamadas HTTP ao backend FastAPI
│   ├── styles/
│   │   ├── index.css               # Entry CSS
│   │   ├── theme.css               # Design tokens (cores azul bancário, dark mode)
│   │   └── fonts.css               # Fontes
│   └── main.tsx                    # Entry point React
├── index.html
├── vite.config.ts                  # Proxy /api → :8000
├── package.json
└── pnpm-lock.yaml
```

---

## Funcionalidades

- **Chat conversacional** — mensagens do usuário à direita, agente à esquerda com avatar 🏦
- **Markdown nas respostas** — o agente pode usar listas, negrito, tabelas
- **Histórico de conversas** — sidebar com busca, persistido no Redis via LangGraph
- **Nova conversa** — botão `+` na sidebar inicia sessão limpa
- **Dark mode** — alternância claro/escuro, preferência salva na sessão
- **Sugestões de perguntas** — state vazio apresenta atalhos clicáveis
- **Indicador de digitação** — feedback visual enquanto o agente processa

---

## Contrato de API consumido

| Método | Endpoint                      | Descrição                        |
|--------|-------------------------------|----------------------------------|
| POST   | `/api/chat`                   | Envia mensagem, recebe resposta  |
| GET    | `/api/conversations`          | Lista sessões                    |
| POST   | `/api/conversations`          | Cria nova sessão                 |
| GET    | `/api/conversations/{id}`     | Histórico de uma sessão          |
| GET    | `/api/health`                 | Health check                     |
