import { CheckCircle2, CircleDashed } from "lucide-react";
import { StepPanel } from "@/components/guardian/ui";

type TraceEntry = {
  tool: string;
  ok: boolean;
  mcp_mode?: string;
  summary?: string;
  resolved_connection_id?: string;
};

export function McpTracePanel({ evidence }: { evidence: Record<string, unknown>[] }) {
  const trace: TraceEntry[] = evidence.map((bundle) => {
    const data = (bundle.data as Record<string, unknown>) || bundle;
    const tool = String(bundle.tool_name || data.tool_name || "unknown");
    const isError = Boolean(data.is_error || data.error);
    const mode = String(data.mcp_mode || "unknown");
    let summary = isError ? String(data.error || "error") : "ok";
    if (!isError && data.sync_status) summary = `sync_status=${String(data.sync_status)}`;
    const enrichedFrom = data.enriched_from as string | undefined;
    if (!isError && enrichedFrom) {
      const fr = data.fivetran_response as Record<string, unknown> | undefined;
      const sync = fr?.sync_state ?? data.sync_state;
      summary = `sync_state=${String(sync)} (from ${enrichedFrom})`;
    }
    if (!isError && Array.isArray(data.recent_errors) && data.recent_errors.length > 0) {
      summary = `${data.recent_errors.length} schema error(s)`;
    }
    return {
      tool,
      ok: !isError,
      mcp_mode: mode,
      summary: summary.slice(0, 120),
      resolved_connection_id: data.resolved_connection_id as string | undefined,
    };
  });

  if (trace.length === 0) return null;

  const okCount = trace.filter((t) => t.ok).length;

  return (
    <StepPanel
      title="Fivetran MCP trace"
      headerRight={
        <span className="text-xs text-dcg-on-surface-variant">
          {okCount}/{trace.length} tools ok
        </span>
      }
    >
      <ul className="space-y-2">
        {trace.map((t) => (
          <li
            key={t.tool}
            className="flex items-start gap-3 rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-low px-3 py-2.5 text-xs"
          >
            {t.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-dcg-on-tertiary-container" />
            ) : (
              <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-dcg-error" />
            )}
            <div className="min-w-0 flex-1">
              <span className="font-mono font-medium text-dcg-secondary">{t.tool}</span>
              <span className="ml-2 text-dcg-outline">({t.mcp_mode})</span>
              {t.resolved_connection_id && (
                <div className="mt-0.5 text-dcg-on-surface-variant">connection: {t.resolved_connection_id}</div>
              )}
              <p className="mt-1 text-dcg-on-surface-variant">{t.summary}</p>
            </div>
          </li>
        ))}
      </ul>
    </StepPanel>
  );
}
