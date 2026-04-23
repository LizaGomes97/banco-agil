import { Phone, MessageCircle, Globe, Mail } from 'lucide-react';

const CONTACTS = [
  {
    icon: <Phone className="w-4 h-4 text-primary" />,
    label: 'Central de Atendimento',
    value: '0800 722 4001',
    sub: 'Gratuito • 24h por dia, 7 dias por semana',
    href: 'tel:08007224001',
  },
  {
    icon: <MessageCircle className="w-4 h-4 text-green-500" />,
    label: 'WhatsApp',
    value: '(11) 99999-4001',
    sub: 'Atendimento de seg a sex, 8h às 20h',
    href: 'https://wa.me/5511999994001',
  },
  {
    icon: <Globe className="w-4 h-4 text-primary" />,
    label: 'Site',
    value: 'www.bancoagil.com.br',
    sub: 'Acesse sua conta e serviços online',
    href: 'https://www.bancoagil.com.br',
  },
  {
    icon: <Mail className="w-4 h-4 text-primary" />,
    label: 'SAC',
    value: 'sac@bancoagil.com.br',
    sub: 'Resposta em até 5 dias úteis',
    href: 'mailto:sac@bancoagil.com.br',
  },
];

export function ContactCard() {
  return (
    <div className="flex w-full justify-start gap-3 py-2 pr-4 sm:pr-8 animate-fade-in">
      <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-base ring-1 ring-primary/20">
        🏦
      </div>

      <div className="min-w-0 w-full max-w-sm flex flex-col gap-0 rounded-2xl rounded-bl-md border border-border bg-card shadow-sm overflow-hidden">
        {/* Cabeçalho */}
        <div className="px-4 py-3 border-b border-border bg-muted/40">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Canais de atendimento
          </p>
        </div>

        {/* Contatos */}
        <div className="divide-y divide-border">
          {CONTACTS.map((c) => (
            <a
              key={c.label}
              href={c.href}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-3 px-4 py-3 hover:bg-accent transition-colors group"
            >
              <div className="mt-0.5 flex-shrink-0">{c.icon}</div>
              <div className="min-w-0">
                <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                  {c.label}
                </p>
                <p className="text-[15px] font-semibold text-foreground group-hover:text-primary transition-colors">
                  {c.value}
                </p>
                <p className="text-[11px] text-muted-foreground mt-0.5">{c.sub}</p>
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
