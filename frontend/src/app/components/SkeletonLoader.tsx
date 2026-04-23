export function SkeletonLoader() {
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6 animate-pulse">
      {/* User message skeleton */}
      <div className="flex gap-4 flex-row-reverse">
        <div className="w-8 h-8 rounded-full bg-muted" />
        <div className="flex-1 max-w-md">
          <div className="h-20 bg-muted rounded-lg" />
        </div>
      </div>

      {/* Assistant message skeleton */}
      <div className="flex gap-4">
        <div className="w-8 h-8 rounded-full bg-primary/10" />
        <div className="flex-1 max-w-3xl space-y-3">
          <div className="h-32 bg-card border border-border rounded-lg" />
          <div className="flex gap-2">
            <div className="h-6 w-24 bg-muted rounded-md" />
            <div className="h-6 w-28 bg-muted rounded-md" />
            <div className="h-6 w-20 bg-muted rounded-md" />
          </div>
        </div>
      </div>
    </div>
  );
}
