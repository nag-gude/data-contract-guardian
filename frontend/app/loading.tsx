export default function Loading() {
  return (
    <div className="mx-auto max-w-5xl animate-pulse space-y-6" aria-busy="true" aria-label="Loading page">
      <div className="space-y-3">
        <div className="h-3 w-48 rounded bg-dcg-surface-container" />
        <div className="h-9 w-80 max-w-full rounded bg-dcg-surface-container" />
        <div className="h-4 w-full max-w-2xl rounded bg-dcg-surface-container-low" />
        <div className="h-4 w-3/4 max-w-xl rounded bg-dcg-surface-container-low" />
      </div>
      <div className="h-24 rounded-2xl border border-dcg-outline-variant/40 bg-dcg-surface-container-lowest" />
      <div className="h-40 rounded-2xl border border-dcg-outline-variant/40 bg-dcg-surface-container-lowest" />
      <div className="h-48 rounded-2xl border border-dcg-outline-variant/40 bg-dcg-surface-container-lowest" />
    </div>
  );
}
