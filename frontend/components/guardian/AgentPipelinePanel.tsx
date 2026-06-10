"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Play, Sparkles } from "lucide-react";
import { runAgentPipeline, summarizePipelineResult } from "@/lib/agentPipeline";
import { Badge, PrimaryButton, StepPanel } from "./ui";

export function AgentPipelinePanel({
  liveBigQuery = false,
  validationRuns = 0,
  openIncidents = 0,
}: {
  liveBigQuery?: boolean;
  validationRuns?: number;
  openIncidents?: number;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runDemo = async (path: string) => {
    setError(null);
    setMessage(null);
    setLoading(true);
    try {
      const r = await fetch(path, { method: "POST" });
      const text = await r.text();
      if (!r.ok) throw new Error(text.slice(0, 200));
      setMessage("Demo state updated. Run the agent pipeline to open incidents.");
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const runPipeline = async () => {
    setError(null);
    setMessage(null);
    setLoading(true);
    try {
      const label = liveBigQuery ? "Live agent pipeline" : "Agent pipeline";
      const result = await runAgentPipeline();
      if (!result.ok) {
        throw new Error(result.raw?.slice(0, 200) ?? `Request failed (${result.status})`);
      }
      setMessage(summarizePipelineResult(result, label));
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <StepPanel
      id="agent-pipeline"
      step={2}
      title="Validate & run agent"
      headerRight={
        <PrimaryButton onClick={runPipeline} loading={loading} variant="secondary">
          <span className="inline-flex items-center gap-2">
            <Play className="h-4 w-4" />
            {liveBigQuery ? "Run live agent pipeline" : "Run agent pipeline"}
          </span>
        </PrimaryButton>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={liveBigQuery ? "success" : "info"}>
            <Sparkles className="mr-1 inline h-3 w-3" />
            {liveBigQuery ? "Live BigQuery validation" : "Mock warehouse demo"}
          </Badge>
          {validationRuns > 0 && (
            <Badge tone="neutral">Validation runs: {validationRuns}</Badge>
          )}
          {openIncidents > 0 && (
            <Badge tone="warning">Open incidents: {openIncidents}</Badge>
          )}
        </div>

        <p className="text-sm text-dcg-on-surface-variant">
          {liveBigQuery
            ? "Validates all network contracts against live BigQuery, runs the Gemini + ADK agent on failures, and opens incidents with MCP evidence."
            : "Validates contracts against the demo warehouse, runs the agent investigation loop, and opens incidents when checks fail."}
        </p>

        {!liveBigQuery && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={loading}
              onClick={() => runDemo("/api/demo/seed-all-failing")}
              className="rounded-lg border border-dcg-error-container bg-dcg-error-container/30 px-3 py-1.5 text-xs font-medium text-dcg-on-error-container hover:bg-dcg-error-container/50 disabled:opacity-50"
            >
              Seed failing state
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => runDemo("/api/demo/seed-all-passing")}
              className="rounded-lg border border-[#CEEAD6] bg-[#E6F4EA] px-3 py-1.5 text-xs font-medium text-dcg-on-tertiary-container hover:opacity-90 disabled:opacity-50"
            >
              Seed passing state
            </button>
          </div>
        )}

        {error && (
          <p className="rounded-lg border border-dcg-error-container bg-dcg-error-container/40 px-3 py-2 text-sm text-dcg-on-error-container">
            {error}
          </p>
        )}
        {message && (
          <pre className="whitespace-pre-wrap rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-low px-3 py-2 text-sm text-dcg-on-surface">
            {message}
          </pre>
        )}

        <p className="text-sm text-dcg-on-surface-variant">
          After the pipeline completes, review{" "}
          <Link href="/incidents" className="font-medium text-dcg-secondary hover:underline">
            incidents
          </Link>{" "}
          for MCP trace and human approval.
        </p>
      </div>
    </StepPanel>
  );
}
