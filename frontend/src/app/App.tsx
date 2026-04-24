import { useState, useRef, useEffect } from 'react';
import { AppHeader } from './components/AppHeader';
import { ChatMessage } from './components/ChatMessage';
import { MessageComposer } from './components/MessageComposer';
import { AuthCard } from './components/AuthCard';
import { ContactCard } from './components/ContactCard';
import { TypingIndicator } from './components/TypingIndicator';
import { toast } from 'sonner';
import { sendChatMessage } from './services/api';

/** Formata CPF + data para a mensagem enviada ao agente de triagem. */
function buildAuthMessage(cpf: string, dataNasc: string): string {
  return `CPF: ${cpf}\nData de nascimento: ${dataNasc}`;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  turnoId?: string;
}

export default function App() {
  const [isDark, setIsDark] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isEncerrado, setIsEncerrado] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [messages, setMessages] = useState<Message[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  }, [isDark]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleNewConversation = () => {
    setConversationId(undefined);
    setMessages([]);
    setIsAuthenticated(false);
    setIsEncerrado(false);
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
      }
      if (result.authenticated) setIsAuthenticated(true);
      if (result.encerrado) setIsEncerrado(true);

      const assistantMsg: Message = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: result.reply,
        timestamp: new Date(),
        turnoId: result.turnoId,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Erro ao enviar mensagem: ${msg}`);
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-background text-foreground overflow-hidden">
      <AppHeader
        isDark={isDark}
        onToggleDark={() => setIsDark((p) => !p)}
        onNewConversation={handleNewConversation}
      />

      {/* Área de mensagens */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}

          {/* Atendimento encerrado após 3 tentativas falhas */}
          {isEncerrado && !isAuthenticated && <ContactCard />}

          {/* AuthCard: aparece no início e após falha de autenticação */}
          {!isAuthenticated && !isEncerrado && (
            <AuthCard
              onSubmit={(cpf, dataNasc) =>
                handleSendMessage(buildAuthMessage(cpf, dataNasc))
              }
              disabled={isLoading}
              retry={messages.length > 0}
            />
          )}

          {isLoading && <TypingIndicator />}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Composer — oculto quando sessão encerrada sem autenticação */}
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
  );
}
