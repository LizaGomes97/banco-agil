import { useState } from 'react';
import { ArrowRight, Calendar, CreditCard } from 'lucide-react';

interface AuthCardProps {
  onSubmit: (cpf: string, dataNascimento: string) => void;
  disabled?: boolean;
  /** true quando é uma nova tentativa após falha de autenticação */
  retry?: boolean;
}

function formatCpf(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  if (digits.length <= 3) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`;
  if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`;
  return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`;
}

function formatDate(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

export function AuthCard({ onSubmit, disabled = false, retry = false }: AuthCardProps) {
  const [cpf, setCpf] = useState('');
  const [dataNasc, setDataNasc] = useState('');
  const [error, setError] = useState('');

  const cpfDigits = cpf.replace(/\D/g, '');
  const dateDigits = dataNasc.replace(/\D/g, '');
  const isValid = cpfDigits.length === 11 && dateDigits.length === 8;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (cpfDigits.length !== 11) {
      setError('CPF inválido. Informe os 11 dígitos.');
      return;
    }
    if (dateDigits.length !== 8) {
      setError('Data de nascimento inválida.');
      return;
    }

    const [dia, mes, ano] = dataNasc.split('/');
    const dataFormatada = `${dia}-${mes}-${ano}`;
    onSubmit(cpf, dataFormatada);
  };

  return (
    <div className="flex w-full justify-start gap-3 py-2 pr-4 sm:pr-8 animate-fade-in">
      {/* Avatar do agente */}
      <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-base ring-1 ring-primary/20">
        🏦
      </div>

      <div className="min-w-0 flex-1 max-w-sm flex flex-col gap-3">
        {/* Balão de saudação ou retry */}
        {!retry && (
          <div className="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3 text-card-foreground shadow-sm">
            <p className="text-[15px] leading-relaxed">
              Olá! Bem-vindo ao <strong>Banco Ágil</strong>. 👋
              <br />
              Para continuar, precisamos verificar sua identidade.
            </p>
          </div>
        )}

        {/* Card de autenticação */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl rounded-bl-md border border-border bg-card shadow-sm overflow-hidden"
        >
          {/* Cabeçalho do card */}
          <div className="px-4 py-3 border-b border-border bg-muted/40">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Identificação do cliente
            </p>
          </div>

          {/* Campos */}
          <div className="px-4 py-4 space-y-4">
            {/* CPF */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <CreditCard className="w-3.5 h-3.5" />
                CPF
              </label>
              <input
                type="text"
                inputMode="numeric"
                placeholder="000.000.000-00"
                value={cpf}
                onChange={(e) => setCpf(formatCpf(e.target.value))}
                disabled={disabled}
                className="w-full px-3 py-2.5 bg-background border border-border rounded-lg text-[15px] focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 tracking-wider"
              />
            </div>

            {/* Data de nascimento */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Calendar className="w-3.5 h-3.5" />
                Data de nascimento
              </label>
              <input
                type="text"
                inputMode="numeric"
                placeholder="DD/MM/AAAA"
                value={dataNasc}
                onChange={(e) => setDataNasc(formatDate(e.target.value))}
                disabled={disabled}
                className="w-full px-3 py-2.5 bg-background border border-border rounded-lg text-[15px] focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              />
            </div>

            {error && (
              <p className="text-xs text-destructive">{error}</p>
            )}
          </div>

          {/* Botão */}
          <div className="px-4 pb-4">
            <button
              type="submit"
              disabled={disabled || !isValid}
              className="w-full flex items-center justify-center gap-2 py-3 bg-primary text-primary-foreground rounded-xl font-medium text-[15px] transition-all hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Continuar
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
