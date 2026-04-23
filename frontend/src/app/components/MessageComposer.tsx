import { Send } from 'lucide-react';
import { useState } from 'react';

interface MessageComposerProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function MessageComposer({
  onSend,
  disabled = false,
  placeholder = 'Digite sua mensagem...',
}: MessageComposerProps) {
  const [message, setMessage] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = message.trim();
    if (trimmed && !disabled) {
      onSend(trimmed);
      setMessage('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <div className="flex items-end gap-3">
        <div className="flex-1 relative">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="w-full px-4 py-3 bg-card border border-border rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed text-[15px]"
            style={{ minHeight: '52px', maxHeight: '200px' }}
            onInput={(e) => {
              const t = e.target as HTMLTextAreaElement;
              t.style.height = 'auto';
              t.style.height = Math.min(t.scrollHeight, 200) + 'px';
            }}
          />
          {message.length > 0 && (
            <div className="absolute bottom-2 right-2 text-[10px] text-muted-foreground bg-background/90 px-2 py-0.5 rounded">
              Enter ↵ envia
            </div>
          )}
        </div>

        <button
          type="submit"
          disabled={disabled || !message.trim()}
          className="p-3 bg-primary text-primary-foreground rounded-xl transition-colors hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 shadow-sm"
          title="Enviar mensagem"
        >
          <Send className="w-5 h-5" />
        </button>
      </div>

      <p className="text-[11px] text-muted-foreground mt-2 text-center">
        Banco Ágil — Assistente Financeiro IA • Seus dados são protegidos
      </p>
    </form>
  );
}
