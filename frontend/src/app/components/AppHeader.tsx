import { Moon, Sun, Plus } from 'lucide-react';

interface AppHeaderProps {
  isDark: boolean;
  onToggleDark: () => void;
  onNewConversation: () => void;
}

export function AppHeader({ isDark, onToggleDark, onNewConversation }: AppHeaderProps) {
  return (
    <header className="h-14 border-b border-border bg-background flex items-center justify-between px-4 flex-shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-xl select-none">🏦</span>
        <div>
          <h1 className="font-semibold text-base leading-none">Banco Ágil</h1>
          <p className="text-[11px] text-muted-foreground leading-none mt-0.5">
            Assistente Financeiro com IA
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onNewConversation}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm hover:bg-muted rounded-lg transition-colors"
          title="Nova conversa"
        >
          <Plus className="w-4 h-4" />
          Nova conversa
        </button>

        <button
          onClick={onToggleDark}
          className="p-2 hover:bg-muted rounded-lg transition-colors"
          title={isDark ? 'Modo claro' : 'Modo escuro'}
        >
          {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>
      </div>
    </header>
  );
}
