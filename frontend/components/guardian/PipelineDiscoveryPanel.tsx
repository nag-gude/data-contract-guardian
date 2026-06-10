"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, CircleDashed, GitBranch, Workflow } from "lucide-react";
import { Badge, PrimaryButton, StepPanel } from "./ui";

type TraceStep = {
  tool: string;
  ok: boolean;
  summary?: string;
  mcp_mode?: string;
};

type LineageEntry = {
  connector_alias: string;
  service: string;
  schema: string;
  health: string;
  connection_id?: string;
};

type DiscoveryResult = {
  mcp_trace: TraceStep[];
  pipeline_lineage: LineageEntry[];
  discovery_source: string;
  tools_run: number;
};

const SOURCE_LABEL: Record<string, string> = {
  mcp_stdio: "Fivetran MCP runtime",
  mock: "Mock adapter",
  configured: "Configured",
};

export function PipelineDiscoveryPanel({
  initial,
  step = 3,
}: {
  initial?: DiscoveryResult | null;
  step?: number;
}) {
  const [data, setData] = useState<DiscoveryResult | null>(initial ?? null);
  const [loading, setLoading] = useState(!initial);
  const [error, setError] = useState<string | null>(null);
  const autoStarted = useRef(Boolean(initial));

  const runDiscovery = async () => {
    setError(null);
    setLoading(true);
    try {
      const r = await fetch("/api/agent/mcp-discovery", { method: "POST" });
      const text = await r.text();
      if (!r.ok) throw new Error(text.slice(0, 200));
      setData(JSON.parse(text) as DiscoveryResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discovery failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (autoStarted.current) return;
    autoStarted.current = true;
    void runDiscovery();
  }, []);

  const trace = data?.mcp_trace ?? [];
  const lineage = data?.pipeline_lineage ?? [];

  return (
    <StepPanel
      id="mcp-discovery"
      step={step}
      title="Fivetran MCP discovery"
      headerRight={
        <PrimaryButton onClick={runDiscovery} loading={loading} variant="secondary">
          {data ? "Refresh" : "Run MCP discovery"}
        </PrimaryButton>
      }
    >
      {error && (
        <p className="mb-4 rounded-lg border border-dcg-error-container bg-dcg-error-container/40 px-3 py-2 text-sm text-dcg-on-error-container">
          {error}
        </p>
      )}

      {loading && !data ? (
        <div className="animate-pulse space-y-3" aria-busy="true">
          <div className="h-4 w-2/3 rounded bg-dcg-surface-container" />
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <div
                key={n}
                className="h-12 rounded-lg border border-dcg-outline-variant/40 bg-dcg-surface-container-low"
              />
            ))}
          </div>
          <p className="text-sm text-dcg-on-surface-variant">Running read-only Fivetran MCP discovery…</p>
        </div>
      ) : !data ? (
        <p className="text-sm text-dcg-on-surface-variant">
          Run discovery to execute read-only Fivetran MCP tools:{" "}
          <code className="rounded bg-dcg-surface-container px-1">get_account_info</code>,{" "}
          <code className="rounded bg-dcg-surface-container px-1">list_connections</code>,{" "}
          <code className="rounded bg-dcg-surface-container px-1">get_connection_details</code>,{" "}
          <code className="rounded bg-dcg-surface-container px-1">get_connection_state</code>,{" "}
          <code className="rounded bg-dcg-surface-container px-1">list_destinations</code>.
        </p>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">
              <Workflow className="mr-1 inline h-3 w-3" />
              MCP tools run: {data.tools_run}
            </Badge>
            {data.discovery_source && (
              <Badge tone="neutral">{SOURCE_LABEL[data.discovery_source] ?? data.discovery_source}</Badge>
            )}
          </div>

          <div>
            <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-dcg-on-surface-variant">
              <GitBranch className="h-3.5 w-3.5" />
              Tool trace
            </h3>
            <ul className="space-y-2">
              {trace.map((step) => (
                <li
                  key={step.tool}
                  className="flex items-start gap-3 rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-low px-3 py-2.5 text-sm"
                >
                  {step.ok ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-dcg-on-tertiary-container" />
                  ) : (
                    <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-dcg-error" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs font-medium text-dcg-secondary">{step.tool}</p>
                    <p className="mt-0.5 text-dcg-on-surface-variant">{step.summary}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {lineage.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-dcg-on-surface-variant">
                Pipeline lineage
              </h3>
              <ul className="grid gap-2 sm:grid-cols-2">
                {lineage.map((entry) => (
                  <li
                    key={entry.connector_alias}
                    className="rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-low p-3 text-sm"
                  >
                    <p className="font-medium text-dcg-on-surface">{entry.connector_alias}</p>
                    <p className="text-dcg-on-surface-variant">
                      {entry.service} → {entry.schema}
                    </p>
                    <Badge tone={entry.health === "healthy" ? "success" : entry.health === "offline" ? "danger" : "warning"}>
                      {entry.health}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </StepPanel>
  );
}
