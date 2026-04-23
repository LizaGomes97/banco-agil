# Banco Ágil — Frontend

Interface web do assistente financeiro do Banco Ágil, construída com React 18, TypeScript e Tailwind CSS 4.

## Stack

| Tecnologia | Versão | Papel |
|---|---|---|
| React | 18 | UI declarativa com hooks |
| TypeScript | 5 | Tipagem estática |
| Vite | 6 | Build tool e dev server |
| Tailwind CSS | 4 | Utilitários CSS |
| shadcn/ui (Radix UI) | latest | Componentes acessíveis |
| Lucide React | latest | Ícones |
| Sonner | latest | Notificações toast |
| pnpm | 9 | Gerenciador de pacotes |

## Pré-requisitos

- Node.js 20+
- pnpm 9+
- Backend FastAPI rodando em `localhost:8000`

## Instalação

```bash
pnpm install
```

## Desenvolvimento

```bash
pnpm dev
# → http://localhost:5173
```

O Vite redireciona requisições `/api/*` para `http://localhost:8000` (configurado em `vite.config.ts`).

## Build

```bash
pnpm build
# → dist/
```

## Variáveis de ambiente

Crie um arquivo `.env` na raiz de `frontend/`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Estrutura

```
frontend/
├── src/
│   ├── app/
│   │   ├── components/
│   │   │   ├── AuthCard.tsx         # Input estruturado CPF + data de nascimento
│   │   │   ├── ContactCard.tsx      # Canais de atendimento pós-3 falhas de auth
│   │   │   ├── AppHeader.tsx        # Header com branding e toggle dark mode
│   │   │   ├── ChatMessage.tsx      # Balão de mensagem (usuário e assistente)
│   │   │   ├── MessageComposer.tsx  # Input de texto + botão enviar
│   │   │   ├── ConversationSidebar.tsx  # Lista de conversas
│   │   │   ├── TypingIndicator.tsx  # Animação "digitando..."
│   │   │   └── SkeletonLoader.tsx   # Skeleton enquanto carrega histórico
│   │   ├── services/
│   │   │   └── api.ts               # HTTP client (sendChatMessage, listConversations...)
│   │   └── App.tsx                  # Orquestrador: estado, autenticação, mensagens
│   ├── styles/
│   │   └── theme.css                # Paleta de cores Banco Ágil (azul/navy)
│   └── main.tsx
├── docs/
│   └── ADR-001-stack-frontend.md
├── index.html
├── vite.config.ts
├── tailwind.config.ts
└── package.json
```

## Funcionalidades

### Autenticação estruturada (`AuthCard`)
- Input com máscara de CPF (`000.000.000-00`) e data (`DD/MM/AAAA`)
- Validação client-side antes de enviar
- Prop `retry={true}` ajusta o texto para tentativas subsequentes
- Desaparece após autenticação bem-sucedida (`authenticated: true`)
- Reexibido automaticamente após falha de autenticação

### Bloqueio pós-3 falhas (`ContactCard`)
Quando o backend retorna `encerrado: true`:
- `AuthCard` não é mais exibido
- `MessageComposer` some completamente do DOM
- `ContactCard` aparece com:
  - Central 0800 722 4001 (24h)
  - WhatsApp (11) 99999-4001
  - www.bancoagil.com.br
  - sac@bancoagil.com.br

### Gerenciamento de conversas
- Sidebar com lista de sessões (carregadas do backend via Redis)
- Botão "Nova conversa" reseta estado de autenticação
- Histórico de cada sessão carregado ao selecionar

### Tema
Paleta azul/navy definida em `src/styles/theme.css`. Suporte a modo escuro via `dark:` classes do Tailwind.

---

## Contrato de API

O frontend consome os seguintes endpoints da FastAPI:

| Endpoint | Método | Payload / Query | Retorno |
|---|---|---|---|
| `/api/chat` | `POST` | `{message, conversation_id?}` | `{reply, conversation_id, authenticated, encerrado}` |
| `/api/conversations` | `GET` | — | `{sessions: [{id, title, updated_at}]}` |
| `/api/conversations` | `POST` | `{title}` | `{id, title, created_at, updated_at}` |
| `/api/conversations/:id` | `GET` | — | `{session, messages}` |
| `/api/health` | `GET` | — | `{status, service}` |
| `/api/debug/logs` | `GET` | `?n=100` | `{total_lines, lines}` |

### Campos de resposta do `/api/chat`

| Campo | Tipo | Significado |
|---|---|---|
| `reply` | `string` | Texto a exibir no chat |
| `conversation_id` | `string` | UUID da sessão (para manter continuidade) |
| `authenticated` | `boolean` | `true` → esconde AuthCard, exibe Composer |
| `encerrado` | `boolean` | `true` → exibe ContactCard, oculta Composer |
