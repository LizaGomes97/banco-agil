export function TypingIndicator() {
  return (
    <div className="flex w-full justify-start py-2 pr-4 sm:pr-16 animate-fade-in">
      <div className="inline-flex items-center gap-2 rounded-2xl rounded-bl-md border border-border bg-muted/50 px-4 py-3 shadow-sm">
        <div className="flex gap-1">
          <div
            className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground"
            style={{ animationDelay: '0ms' }}
          />
          <div
            className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground"
            style={{ animationDelay: '150ms' }}
          />
          <div
            className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground"
            style={{ animationDelay: '300ms' }}
          />
        </div>
        <span className="text-sm text-muted-foreground">Digitando…</span>
      </div>
    </div>
  );
}
