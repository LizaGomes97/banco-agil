/** Serviço de comunicação com o backend FastAPI do Banco Ágil. */

export function getApiBase(): string {
  const v = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (v && v.trim()) {
    return v.replace(/\/$/, '');
  }
  if (import.meta.env.DEV) {
    return '';
  }
  return 'http://localhost:8000';
}

async function parseJsonSafe(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface SendChatParams {
  message: string;
  conversationId?: string;
}

export interface SendChatResult {
  reply: string;
  conversationId: string;
  authenticated: boolean;
  encerrado: boolean;
  turnoId?: string;
}

export async function sendChatMessage(params: SendChatParams): Promise<SendChatResult> {
  const body: Record<string, unknown> = { message: params.message };
  if (params.conversationId) {
    body.conversation_id = params.conversationId;
  }

  const res = await fetch(`${getApiBase()}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  const data = (await parseJsonSafe(res)) as Record<string, unknown> | null;

  if (res.status === 429) {
    throw new Error('429: Muitas requisições. Aguarde um momento.');
  }
  if (!res.ok) {
    const detail =
      (data?.detail as string) ||
      (typeof data?.message === 'string' ? data.message : null) ||
      `HTTP ${res.status}`;
    throw new Error(detail);
  }

  const reply = typeof data?.reply === 'string' ? data.reply : '';
  const convId =
    typeof data?.conversation_id === 'string' ? data.conversation_id : undefined;

  const turnoId = typeof data?.turno_id === 'string' ? data.turno_id : undefined;

  return {
    reply: reply || '_Sem conteúdo na resposta._',
    conversationId: convId || params.conversationId || '',
    authenticated: Boolean(data?.authenticated),
    encerrado: Boolean(data?.encerrado),
    turnoId,
  };
}

// ── Feedback (thumbs up/down) ────────────────────────────────────────────────

export type FeedbackValue = 1 | -1;

export async function sendFeedback(
  turnoId: string,
  feedback: FeedbackValue,
): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ turno_id: turnoId, feedback }),
  });
  if (!res.ok) {
    const data = (await parseJsonSafe(res)) as { detail?: string } | null;
    throw new Error(data?.detail || `feedback: HTTP ${res.status}`);
  }
}

// ── Conversas ─────────────────────────────────────────────────────────────────

export interface SessionSummary {
  id: string;
  title: string;
  updated_at: string;
  created_at?: string;
}

export async function listConversations(): Promise<SessionSummary[]> {
  const res = await fetch(`${getApiBase()}/api/conversations?limit=50&offset=0`);
  const data = (await parseJsonSafe(res)) as { sessions?: SessionSummary[] } | null;
  if (!res.ok) {
    throw new Error(`conversas: HTTP ${res.status}`);
  }
  return data?.sessions ?? [];
}

export async function createConversationApi(title = 'Nova conversa'): Promise<SessionSummary> {
  const res = await fetch(`${getApiBase()}/api/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title.trim() || 'Nova conversa' }),
  });
  const data = (await parseJsonSafe(res)) as SessionSummary | null;
  if (!res.ok) {
    throw new Error(`criar conversa: HTTP ${res.status}`);
  }
  if (!data?.id) {
    throw new Error('Resposta inválida ao criar conversa.');
  }
  return data;
}

export interface ApiMessageRow {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ConversationDetail {
  session: SessionSummary;
  messages: ApiMessageRow[];
  authenticated: boolean;
  encerrado: boolean;
}

export async function fetchConversationDetail(
  conversationId: string
): Promise<ConversationDetail> {
  const res = await fetch(
    `${getApiBase()}/api/conversations/${encodeURIComponent(conversationId)}`
  );
  const data = (await parseJsonSafe(res)) as ConversationDetail | null;
  if (res.status === 404) {
    throw new Error('Conversa não encontrada.');
  }
  if (!res.ok || !data?.messages) {
    throw new Error(`carregar conversa: HTTP ${res.status}`);
  }
  return {
    session: data.session,
    messages: data.messages,
    authenticated: Boolean(data.authenticated),
    encerrado: Boolean(data.encerrado),
  };
}

export function apiMessageToUi(m: ApiMessageRow): {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
} {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    timestamp: m.created_at ? new Date(m.created_at) : new Date(),
  };
}
