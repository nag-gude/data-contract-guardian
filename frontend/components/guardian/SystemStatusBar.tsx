import { Activity, Bot, Database, Network, Sparkles } from "lucide-react";
import {
  getPlatformStatus,
  resolveSystemHealth,
  systemHealthLabel,
  type PlatformStatus,
} from "@/lib/platform";

function StatusPill({
  label,
  value,
  live,
}: {
  label: string;
  value: string;
  live: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-lowest px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-dcg-outline">{label}</p>
      <p className="mt-0.5 truncate text-sm font-medium text-dcg-on-surface">{value}</p>
      <span
        className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
          live
            ? "bg-[#E6F4EA] text-dcg-on-tertiary-container"
            : "bg-dcg-surface-container text-dcg-on-surface-variant"
        }`}
      >
        {live ? "live" : "mock"}
      </span>
    </div>
  );
}

export async function SystemStatusBar({ platform: platformProp }: { platform?: PlatformStatus | null }) {
  const platform = platformProp ?? (await getPlatformStatus());
  const health = resolveSystemHealth(platform);

  const dotClass =
    health === "operational"
      ? "bg-dcg-on-tertiary-container shadow-[0_0_0_3px_rgba(0,150,104,0.25)]"
      : health === "demo"
        ? "bg-amber-500 shadow-[0_0_0_3px_rgba(245,158,11,0.25)]"
        : "bg-dcg-error shadow-[0_0_0_3px_rgba(186,26,26,0.2)]";

  const wf = platform?.workflow;

  return (
    <section
      id="system-status"
      className="border-b border-dcg-outline-variant/50 bg-dcg-surface-container-low px-4 py-4 sm:px-6 lg:px-8"
      aria-label="System status"
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className={`h-3 w-3 shrink-0 rounded-full ${dotClass}`} aria-hidden />
            <div>
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-dcg-secondary">
                <Activity className="h-3.5 w-3.5" />
                System status
              </p>
              <p className="text-sm font-semibold text-dcg-on-surface">{systemHealthLabel(health)}</p>
            </div>
          </div>
          {platform?.generated_at && (
            <p className="text-xs text-dcg-outline">
              Updated {new Date(platform.generated_at).toLocaleString()}
            </p>
          )}
        </div>

        {platform ? (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <StatusPill
              label="Agent Builder"
              value={platform.agent_builder.adk_installed ? "ADK installed" : "Deterministic loop"}
              live={platform.agent_builder.adk_installed}
            />
            <StatusPill
              label="Gemini"
              value={`${platform.gemini.model}`}
              live={platform.gemini.backend !== "none"}
            />
            <StatusPill
              label="Fivetran MCP"
              value={
                platform.fivetran_mcp.mock_mode
                  ? "Mock transport"
                  : `${platform.fivetran_mcp.transport} · ${platform.fivetran_mcp.integration_source ?? "live"}`
              }
              live={!platform.fivetran_mcp.mock_mode}
            />
            <StatusPill
              label="BigQuery"
              value={
                platform.bigquery.mock_mode
                  ? "Mock warehouse"
                  : platform.bigquery.project_id ?? "Live warehouse"
              }
              live={!platform.bigquery.mock_mode}
            />
            <div className="min-w-0 rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-lowest px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-dcg-outline">Workflow</p>
              <p className="mt-0.5 text-sm font-medium text-dcg-on-surface">
                {(wf?.awaiting_approval ?? 0) > 0
                  ? `${wf?.awaiting_approval} awaiting approval`
                  : (wf?.open_incidents ?? 0) > 0
                    ? `${wf?.open_incidents} open incidents`
                    : `${wf?.validation_runs ?? 0} validation runs`}
              </p>
              <span className="mt-1 inline-block rounded-full bg-dcg-surface-container px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-dcg-on-surface-variant">
                {(wf?.resolved ?? 0) > 0 ? `${wf?.resolved} resolved` : "healthy"}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-dcg-on-surface-variant">
            Could not reach the platform status API. Check backend connectivity.
          </p>
        )}

        {platform && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-dcg-on-surface-variant">
            <span className="inline-flex items-center gap-1">
              <Bot className="h-3.5 w-3.5 text-dcg-secondary" />
              {platform.agent_builder.framework}
            </span>
            <span className="inline-flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5 text-dcg-secondary" />
              {platform.gemini.backend}
            </span>
            <span className="inline-flex items-center gap-1">
              <Network className="h-3.5 w-3.5 text-dcg-secondary" />
              {platform.fivetran_mcp.tools.length} MCP tools · read-only
            </span>
            <span className="inline-flex items-center gap-1">
              <Database className="h-3.5 w-3.5 text-dcg-secondary" />
              {platform.bigquery.live_available ? "BigQuery ready" : "BigQuery offline"}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
