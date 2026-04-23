import Markdown from 'markdown-to-jsx';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const { role, content, timestamp } = message;
  const isUser = role === 'user';
  const timeStr = timestamp
    ? timestamp.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : null;

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

  return (
    <div className="flex w-full justify-start gap-3 py-2 pr-4 sm:pr-8 animate-fade-in">
      <div
        className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-base ring-1 ring-primary/20"
        aria-hidden
      >
        🏦
      </div>
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

        {timeStr && (
          <span className="text-[11px] text-muted-foreground tabular-nums">{timeStr}</span>
        )}
      </div>
    </div>
  );
}
