import { useMemo, useState } from 'react';
import { MessageSquare, Plus, Search } from 'lucide-react';

interface Conversation {
  id: string;
  title: string;
  lastMessage?: string;
  timestamp: Date;
}

interface ConversationSidebarProps {
  conversations: Conversation[];
  activeConversationId?: string;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  loading?: boolean;
}

export function ConversationSidebar({
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  loading = false,
}: ConversationSidebarProps) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        (c.lastMessage && c.lastMessage.toLowerCase().includes(q))
    );
  }, [conversations, query]);

  return (
    <div className="w-80 h-screen bg-sidebar border-r border-sidebar-border flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-sidebar-border">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium text-sidebar-foreground">Conversas</h2>
          <button
            onClick={onNewConversation}
            className="p-2 hover:bg-sidebar-accent rounded-lg transition-colors"
            title="Nova conversa"
          >
            <Plus className="w-5 h-5" />
          </button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar conversas..."
            className="w-full pl-9 pr-3 py-2 bg-sidebar-accent rounded-lg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-sidebar-ring"
          />
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-8 text-center text-muted-foreground text-sm">Carregando conversas…</div>
        ) : conversations.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-sm">
            Nenhuma conversa ainda.
            <br />
            Clique em + para começar.
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-sm">
            Nenhuma conversa corresponde à busca.
          </div>
        ) : (
          <div className="p-2">
            {filtered.map((conv) => (
              <button
                key={conv.id}
                onClick={() => onSelectConversation(conv.id)}
                className={`w-full text-left p-3 rounded-lg mb-1 transition-colors ${
                  activeConversationId === conv.id
                    ? 'bg-sidebar-accent'
                    : 'hover:bg-sidebar-accent/50'
                }`}
              >
                <div className="flex items-start gap-2">
                  <MessageSquare className="w-4 h-4 mt-1 flex-shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm truncate">{conv.title}</p>
                    {conv.lastMessage && (
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {conv.lastMessage}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground mt-1">
                      {conv.timestamp.toLocaleDateString('pt-BR', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                      })}
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
