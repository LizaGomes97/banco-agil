import { Moon, Sun, Menu, PanelLeftClose, PanelLeft } from 'lucide-react';

interface AppHeaderProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  isDark: boolean;
  onToggleDark: () => void;
}

export function AppHeader({ sidebarOpen, onToggleSidebar, isDark, onToggleDark }: AppHeaderProps) {
  return (
    <header className="h-14 border-b border-border bg-background flex items-center justify-between px-4 flex-shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="p-2 hover:bg-muted rounded-lg transition-colors"
          title={sidebarOpen ? 'Recolher conversas' : 'Mostrar conversas'}
        >
          {sidebarOpen
            ? <PanelLeftClose className="w-5 h-5" />
            : <PanelLeft className="w-5 h-5" />
          }
        </button>

        <div className="flex items-center gap-2">
          <span className="text-xl select-none">🏦</span>
          <div>
            <h1 className="font-semibold text-base leading-none">Banco Ágil</h1>
            <p className="text-[11px] text-muted-foreground leading-none mt-0.5">
              Assistente Financeiro com IA
            </p>
          </div>
        </div>
      </div>

      <button
        onClick={onToggleDark}
        className="p-2 hover:bg-muted rounded-lg transition-colors"
        title={isDark ? 'Modo claro' : 'Modo escuro'}
      >
        {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
      </button>
    </header>
  );
}
