"use client";

import { useRouter } from "next/navigation";
import { PrimaryButton } from "@/components/guardian/ui";
import { runAgentPipeline, summarizePipelineResult } from "@/lib/agentPipeline";

export function DemoToolbar({ liveBigQuery = false }: { liveBigQuery?: boolean }) {
  const router = useRouter();

  const run = async (path: string) => {
    const r = await fetch(path, { method: "POST" });
    const text = await r.text();
    if (!r.ok) {
      alert(`Request failed (${r.status}): ${text}`);
      return;
    }
    router.refresh();
  };

  const runPipeline = async () => {
    const label = liveBigQuery ? "Live agent pipeline" : "Agent pipeline";
    const result = await runAgentPipeline();
    if (!result.ok) {
      alert(`Request failed (${result.status}): ${result.raw}`);
      return;
    }
    alert(summarizePipelineResult(result, label));
    router.refresh();
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-xs uppercase tracking-wide text-dcg-on-surface-variant">Demo</span>
      {!liveBigQuery && (
        <>
          <button
            type="button"
            onClick={() => run("/api/demo/seed-all-failing")}
            className="rounded-lg border border-dcg-error-container bg-dcg-error-container/30 px-3 py-1.5 text-xs font-medium text-dcg-on-error-container hover:bg-dcg-error-container/50"
          >
            Seed failing
          </button>
          <button
            type="button"
            onClick={() => run("/api/demo/seed-all-passing")}
            className="rounded-lg border border-[#CEEAD6] bg-[#E6F4EA] px-3 py-1.5 text-xs font-medium text-dcg-on-tertiary-container hover:opacity-90"
          >
            Seed passing
          </button>
        </>
      )}
      {liveBigQuery ? (
        <PrimaryButton onClick={runPipeline} variant="secondary">
          Run live agent pipeline
        </PrimaryButton>
      ) : (
        <>
          <PrimaryButton onClick={runPipeline} variant="secondary">
            Run agent pipeline
          </PrimaryButton>
          <button
            type="button"
            onClick={() => run("/api/validation/run")}
            className="rounded-lg border border-dcg-outline-variant bg-dcg-surface px-3 py-1.5 text-xs font-medium text-dcg-secondary hover:bg-dcg-surface-container"
          >
            Run validation
          </button>
        </>
      )}
      <button
        type="button"
        onClick={() => run("/api/demo/prune-duplicate-incidents")}
        className="rounded-lg border border-dcg-outline-variant px-3 py-1.5 text-xs font-medium text-dcg-on-surface-variant hover:border-dcg-outline hover:text-dcg-on-surface"
      >
        Prune duplicates
      </button>
    </div>
  );
}
