import { ShieldCheck } from "lucide-react";

export function HumanInLoopBanner() {
  return (
    <div className="flex gap-3 rounded-xl border border-dcg-secondary-container/40 bg-dcg-surface-container-low p-4">
      <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-dcg-secondary" />
      <div>
        <p className="text-sm font-semibold text-dcg-on-surface">Human-in-the-loop required</p>
        <p className="mt-1 text-sm text-dcg-on-surface-variant">
          MCP discovery and validation are read-only. Review evidence and explicitly approve ranked remediations
          before any side effects run.
        </p>
      </div>
    </div>
  );
}
