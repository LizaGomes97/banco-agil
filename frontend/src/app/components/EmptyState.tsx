interface EmptyStateProps {
  onSuggestionClick?: (msg: string) => void;
}

const SUGGESTIONS = [
  'Qual é o meu limite de crédito atual?',
  'Quero solicitar aumento de limite',
  'Quero investir em dólar — qual a cotação?',
  'Como funciona a entrevista de emprego assistida por IA?',
];

export function EmptyState({ onSuggestionClick }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="w-20 h-20 bg-primary/10 rounded-full flex items-center justify-center mb-6 text-4xl select-none">
        🏦
      </div>

      <h2 className="text-2xl font-semibold mb-2">Olá! Sou o assistente do Banco Ágil.</h2>
      <p className="text-muted-foreground text-sm max-w-md leading-relaxed mb-8">
        Posso ajudá-lo com consulta de limite, solicitação de crédito, câmbio de moedas e muito mais.
        Para começar, basta se identificar.
      </p>

      {onSuggestionClick && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSuggestionClick(s)}
              className="text-left px-4 py-3 rounded-xl border border-border bg-card hover:bg-accent hover:border-primary/30 transition-colors text-sm text-muted-foreground hover:text-foreground"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
