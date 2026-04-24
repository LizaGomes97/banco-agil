import { useState } from 'react';
import Markdown from 'markdown-to-jsx';
import { sendFeedback, type FeedbackValue } from '../services/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  turnoId?: string;
}

interface ChatMessageProps {
  message: Message;
}

type FeedbackState = 'idle' | 'sending' | 'sent' | 'error';

export function ChatMessage({ message }: ChatMessageProps) {
  const { role, content, timestamp, turnoId } = message;
  const isUser = role === 'user';
  const timeStr = timestamp
    ? timestamp.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : null;

  const [feedback, setFeedback] = useState<FeedbackValue | null>(null);
  const [state, setState] = useState<FeedbackState>('idle');

  async function handleFeedback(value: FeedbackValue) {
    if (!turnoId || state === 'sending' || feedback !== null) {
      return;
    }
    setState('sending');
    try {
      await sendFeedback(turnoId, value);
      setFeedback(value);
      setState('sent');
    } catch {
      setState('error');
    }
  }

  if (isUser) {
    return (
      <div className="flex w-full justify-end py-2 pl-8 sm:pl-16 animate-fade-in">
        <div className="flex max-w-[min(90%,28rem)] flex-col items-end gap-1">
          <div
            className="rounded-2xl rounded-br-md bg-primary px-4 py-3 text-primary-foreground shadow-md"
            role="status"
            aria-label="Sua mensagem"
          >
            <p className="break-words whitespace-pre-wrap text-[15px] leading-relaxed">{content}</p>
          </div>
          {timeStr && (
            <span className="text-[11px] text-muted-foreground tabular-nums pr-1">{timeStr}</span>
          )}
        </div>
      </div>
    );
  }

  const showFeedback = Boolean(turnoId);

  return (
    <div className="flex w-full justify-start py-2 pr-4 sm:pr-16 animate-fade-in">
      <div className="min-w-0 flex-1 max-w-[min(100%,48rem)] flex flex-col gap-2">
        <div
          className="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3 text-card-foreground shadow-sm"
          role="article"
          aria-label="Resposta do assistente"
        >
          <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-semibold prose-p:leading-relaxed prose-pre:bg-muted prose-pre:p-3 prose-p:my-2 prose-headings:my-3">
            <Markdown>{content}</Markdown>
          </div>
        </div>

        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          {timeStr && <span className="tabular-nums">{timeStr}</span>}

          {showFeedback && (
            <div className="flex items-center gap-1" aria-label="Avaliar resposta">
              <button
                type="button"
                onClick={() => handleFeedback(1)}
                disabled={state === 'sending' || feedback !== null}
                className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
                  feedback === 1
                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400'
                    : 'hover:bg-muted'
                } disabled:cursor-not-allowed`}
                aria-label="Resposta útil"
                title={feedback === 1 ? 'Você marcou como útil' : 'Marcar como útil'}
              >
                <ThumbsUpIcon />
              </button>
              <button
                type="button"
                onClick={() => handleFeedback(-1)}
                disabled={state === 'sending' || feedback !== null}
                className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
                  feedback === -1
                    ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-400'
                    : 'hover:bg-muted'
                } disabled:cursor-not-allowed`}
                aria-label="Resposta não ajudou"
                title={feedback === -1 ? 'Você marcou como não útil' : 'Marcar como não útil'}
              >
                <ThumbsDownIcon />
              </button>
              {state === 'sent' && (
                <span className="ml-1 text-[10px] text-muted-foreground/70">Obrigado!</span>
              )}
              {state === 'error' && (
                <span className="ml-1 text-[10px] text-rose-500">Erro ao enviar</span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ThumbsUpIcon() {
  return (
    <svg
      width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7V10l4-9a1.5 1.5 0 0 1 3 0Z" />
    </svg>
  );
}

function ThumbsDownIcon() {
  return (
    <svg
      width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H17v12l-4 9a1.5 1.5 0 0 1-3 0Z" />
    </svg>
  );
}
