import { unstable_cache } from "next/cache";
import { cache } from "react";
import { apiGet } from "./api";

export type PlatformStatus = {
  disclaimer?: string;
  generated_at?: string;
  agent: string;
  agent_builder: { enabled: boolean; adk_installed: boolean; framework: string };
  gemini: { model: string; backend: string; safety_threshold?: string };
  fivetran_mcp: {
    protocol: string;
    transport: string;
    mock_mode: boolean;
    integration_source?: string;
    tools: string[];
    allow_writes: boolean;
    credentials_configured?: boolean;
  };
  bigquery: { mock_mode: boolean; live_available: boolean; project_id?: string };
  workflow?: {
    open_incidents?: number;
    awaiting_approval: number;
    resolved: number;
    validation_runs: number;
  };
};

const fetchPlatformStatus = unstable_cache(
  async (): Promise<PlatformStatus | null> => {
    try {
      return await apiGet<PlatformStatus>("/api/agent/platform");
    } catch {
      return null;
    }
  },
  ["platform-status"],
  { revalidate: 15 },
);

/** Deduped per request; cached across navigations for 15s to avoid repeated MCP work. */
export const getPlatformStatus = cache(fetchPlatformStatus);

export type SystemHealth = "operational" | "demo" | "degraded" | "unknown";

export function resolveSystemHealth(platform: PlatformStatus | null): SystemHealth {
  if (!platform) return "unknown";
  const liveMcp = !platform.fivetran_mcp.mock_mode;
  const liveBq = !platform.bigquery.mock_mode;
  if (liveMcp && liveBq) return "operational";
  if (platform.fivetran_mcp.mock_mode || platform.bigquery.mock_mode) return "demo";
  return "degraded";
}

export function systemHealthLabel(health: SystemHealth): string {
  switch (health) {
    case "operational":
      return "Live integrations active";
    case "demo":
      return "Demo mode — mock warehouse or MCP";
    case "degraded":
      return "Partial configuration";
    default:
      return "Status unavailable";
  }
}
