# ADR-001 — Stack do Frontend

| Campo       | Valor                              |
|-------------|------------------------------------|
| **Status**  | Aceito                             |
| **Data**    | 2026-04-23                         |
| **Autor**   | Lizan / Agente IA (Cursor)         |

---

## Contexto

O case do Banco Ágil exige uma interface de chat conversacional que transmita profissionalismo e confiança — atributos centrais para um produto bancário. A alternativa natural para um projeto Python é o **Streamlit**, mas ele apresenta limitações que comprometem a qualidade da entrega:

- Visual genérico e difícil de personalizar
- Sem controle preciso de layout responsivo
- Não suporta animações, temas dark/light ou componentes de mercado
- Percepção de "protótipo" por avaliadores técnicos

---

## Decisão

Adotar uma stack **React 18 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui** como interface do agente, servida por uma bridge **FastAPI** que expõe o grafo LangGraph via HTTP.

---

## Stack escolhida e justificativas

### React 18 + TypeScript
- Padrão de mercado para SPAs de alta qualidade
- TypeScript garante segurança de tipos nas chamadas de API e nos estados do chat
- Ecossistema maduro: `react-hook-form`, `sonner`, `lucide-react`

### Vite 6
- Build ultrarrápido com HMR (Hot Module Replacement)
- Proxy nativo para `/api` → `localhost:8000` simplifica o desenvolvimento local
- Configuração mínima comparado ao CRA (Create React App)

### Tailwind CSS 4
- Utility-first: permite customização total sem lutar contra CSS pré-definido
- Design tokens via variáveis CSS (`theme.css`) → troca de tema sem reescrever classes
- Dark mode nativo com classe `dark` no `documentElement`

### shadcn/ui (Radix UI + Tailwind)
- Componentes acessíveis por padrão (Radix UI)
- Código copiado para o projeto — zero dependência de biblioteca externa de UI
- Estilo totalmente sob controle do desenvolvedor

### markdown-to-jsx
- Respostas do agente chegam formatadas em Markdown
- Renderização segura sem XSS com opções de customização

### FastAPI (bridge)
- Expõe endpoints REST simples que o React consome
- Roda no mesmo processo Python do backend LangGraph
- Contrato mínimo: `POST /api/chat`, `GET /api/conversations`, `GET /api/conversations/{id}`

---

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|-------------|-------------------|
| **Streamlit** | Visual amador, sem controle de layout, percepção de protótipo |
| **Next.js** | Overhead desnecessário para SPA sem SSR/SSG; adiciona complexidade de deploy |
| **Vue 3** | Stack menos conhecida pelo time; ecossistema menor para componentes bancários |
| **Angular** | Curva de aprendizado alta; verbosidade excessiva para um MVP de case |
| **Vanilla JS** | Sem componentes reutilizáveis; manutenção custosa |

---

## Consequências

**Positivas:**
- Interface profissional com tema azul bancário, dark/light mode e animações
- Sidebar de histórico de conversas com busca
- Mensagens do agente renderizadas em Markdown (listas, negrito, tabelas)
- Separação clara de responsabilidades: UI (React) ↔ Lógica (LangGraph via FastAPI)
- Frontend pode ser evoluído independentemente do backend

**Negativas / trade-offs:**
- Duas etapas para iniciar em desenvolvimento: `uvicorn api.main:app` + `pnpm dev`
- Requer Node.js e pnpm instalados além do Python
- A bridge FastAPI adiciona uma camada de latência (mínima: ~1ms local)

---

## Referências

- [Vite Docs](https://vitejs.dev/)
- [shadcn/ui](https://ui.shadcn.com/)
- [Tailwind CSS v4](https://tailwindcss.com/)
- [FastAPI](https://fastapi.tiangolo.com/)
- `api/main.py` — implementação da bridge
