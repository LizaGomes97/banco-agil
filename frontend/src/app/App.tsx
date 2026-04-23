import { useState, useRef, useEffect, useCallback } from 'react';
import { ConversationSidebar } from './components/ConversationSidebar';
import { AppHeader } from './components/AppHeader';
import { ChatMessage } from './components/ChatMessage';
import { MessageComposer } from './components/MessageComposer';
import { AuthCard } from './components/AuthCard';
import { ContactCard } from './components/ContactCard';
import { TypingIndicator } from './components/TypingIndicator';
import { SkeletonLoader } from './components/SkeletonLoader';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  sendChatMessage,
  listConversations,
  createConversationApi,
  fetchConversationDetail,
  apiMessageToUi,
  type SessionSummary,
} from './services/api';

/** Formata CPF + data para a mensagem enviada ao agente de triagem. */
function buildAuthMessage(cpf: string, dataNasc: string): string {
  return `CPF: ${cpf}\nData de nascimento: ${dataNasc}`;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
}

function sessionToConversation(s: SessionSummary): Conversation {
  return {
    id: s.id,
    title: s.title || 'Conversa',
    timestamp: new Date(s.updated_at),
  };
}

export default function App() {
  const [isDark, setIsDark] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isEncerrado, setIsEncerrado] = useState(false);

  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesViewportRef = useRef<HTMLDivElement>(null);
  const skipScrollToBottomOnceRef = useRef(false);
  const skipAutoSelectOnce = useRef(false);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (conversationLoading) return;
    const viewport = messagesViewportRef.current;
    if (skipScrollToBottomOnceRef.current && viewport) {
      skipScrollToBottomOnceRef.current = false;
      requestAnimationFrame(() => { viewport.scrollTop = 0; });
      return;
    }
    scrollToBottom();
  }, [messages, conversationLoading]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  }, [isDark]);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const sessions = await listConversations();
      const mapped = sessions.map(sessionToConversation);
      setConversations(mapped);
      setActiveConversationId((prev) => {
        if (prev && mapped.some((c) => c.id === prev)) return prev;
        return null;
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Não foi possível carregar conversas: ${msg}`);
      setConversations([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  const openConversation = useCallback(async (id: string) => {
    setConversationLoading(true);
    setActiveConversationId(id);
    setConversationId(id);
    try {
      const detail = await fetchConversationDetail(id);
      skipScrollToBottomOnceRef.current = true;
      setMessages(detail.messages.map((m) => apiMessageToUi(m)));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg);
      setMessages([]);
    } finally {
      setConversationLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (sessionsLoading) return;
    if (skipAutoSelectOnce.current) { skipAutoSelectOnce.current = false; return; }
    if (activeConversationId !== null) return;
    if (conversations.length === 0) return;
    void openConversation(conversations[0].id);
  }, [sessionsLoading, conversations, activeConversationId, openConversation]);

  const handleNewConversation = async () => {
    try {
      const s = await createConversationApi('Nova conversa');
      const conv = sessionToConversation(s);
      skipAutoSelectOnce.current = true;
      setConversations((prev) => [conv, ...prev.filter((c) => c.id !== conv.id)]);
      setActiveConversationId(conv.id);
      setConversationId(conv.id);
      setMessages([]);
      setIsAuthenticated(false);
      setIsEncerrado(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg);
    }
  };

  const handleSelectConversation = (id: string) => {
    void openConversation(id);
  };

  const handleSendMessage = async (content: string) => {
    if (!content.trim() || isLoading) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: content.trim(),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const result = await sendChatMessage({
        message: content.trim(),
        conversationId,
      });

      if (result.conversationId && result.conversationId !== conversationId) {
        setConversationId(result.conversationId);
        setActiveConversationId(result.conversationId);
      }

      if (result.authenticated) {
        setIsAuthenticated(true);
      }
      if (result.encerrado) {
        setIsEncerrado(true);
      }

      const assistantMsg: Message = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: result.reply,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Atualiza sidebar com a conversa atual
      void loadSessions();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Erro ao enviar mensagem: ${msg}`);
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Sidebar — visível em md+; escondida em mobile quando fechada */}
      <div
        className={`
          fixed inset-y-0 left-0 z-20 transition-transform duration-300
          md:relative md:translate-x-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        <ConversationSidebar
          conversations={conversations.map((c) => ({
            id: c.id,
            title: c.title,
            lastMessage: undefined,
            timestamp: c.timestamp,
          }))}
          activeConversationId={activeConversationId}
          loading={sessionsLoading}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
        />
      </div>

      {/* Área principal */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <AppHeader
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((p) => !p)}
          isDark={isDark}
          onToggleDark={() => setIsDark((p) => !p)}
        />

        {/* Corpo do chat */}
        <div
          ref={messagesViewportRef}
          className="flex-1 overflow-y-auto px-4 py-6"
        >
          <div className="max-w-3xl mx-auto space-y-4">
            {conversationLoading ? (
              <SkeletonLoader />
            ) : (
              <>
                {/* Mensagens anteriores (erros de auth, histórico) */}
                {messages.map((msg) => (
                  <ChatMessage key={msg.id} message={msg} />
                ))}

                {/* Atendimento encerrado: mostra canais de contato */}
                {isEncerrado && !isAuthenticated && <ContactCard />}

                {/* AuthCard: aparece na tela inicial E após falha (enquanto não encerrado) */}
                {!isAuthenticated && !isEncerrado && (
                  <AuthCard
                    onSubmit={(cpf, dataNasc) =>
                      handleSendMessage(buildAuthMessage(cpf, dataNasc))
                    }
                    disabled={isLoading}
                    retry={messages.length > 0}
                  />
                )}
              </>
            )}

            {isLoading && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-base flex-shrink-0">
                  🏦
                </div>
                <TypingIndicator />
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Composer — oculto quando atendimento encerrado sem autenticação */}
        {(!isEncerrado || isAuthenticated) && (
          <div className="border-t border-border bg-background/80 backdrop-blur-sm px-4 py-3">
            <div className="max-w-3xl mx-auto">
              <MessageComposer
                onSend={handleSendMessage}
                disabled={isLoading}
                placeholder="Fale com o assistente do Banco Ágil..."
              />
            </div>
          </div>
        )}
      </div>

      {/* Overlay do sidebar em mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-10 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}
