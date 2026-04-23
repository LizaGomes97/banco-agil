export function TypingIndicator() {
  return (
    <div className="flex w-full justify-start gap-3 py-2 pr-4 sm:pr-8 animate-fade-in">
      <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/12 text-sm ring-1 ring-primary/20">
        🌱
      </div>
      <div className="min-w-0 flex-1 max-w-[min(100%,48rem)]">
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
          <span className="text-sm text-muted-foreground">Consultando especialistas…</span>
        </div>
      </div>
    </div>
  );
}
