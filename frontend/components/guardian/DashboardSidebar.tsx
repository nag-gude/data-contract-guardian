"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ClipboardList,
  ExternalLink,
  FileText,
  Network,
  Activity,
  RefreshCw,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { backendPublicUrl } from "@/lib/api";
import { resolveSystemHealth, systemHealthLabel, type PlatformStatus } from "@/lib/platform";
import { GuardianLogo } from "./GuardianLogo";

const NAV = [
  { href: "/", label: "Agent home", icon: ShieldCheck, section: "step-home" },
  { href: "/contracts", label: "Contracts", icon: FileText, section: "step-contracts" },
  { href: "/#mcp-discovery", label: "MCP discovery", icon: Workflow, section: "step-mcp" },
  { href: "/incidents", label: "Incidents", icon: ClipboardList, section: "step-incidents" },
] as const;

export function DashboardSidebar({ platform }: { platform?: PlatformStatus | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const health = resolveSystemHealth(platform ?? null);
  const healthDot =
    health === "operational"
      ? "bg-dcg-on-tertiary-container"
      : health === "demo"
        ? "bg-amber-500"
        : "bg-dcg-error";

  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-dcg-outline-variant/50 bg-dcg-surface-container-lowest lg:flex">
      <div className="flex items-center justify-between gap-2 border-b border-dcg-outline-variant/40 px-4 py-4">
        <Link href="/" className="flex items-center gap-2.5">
          <GuardianLogo />
          <div>
            <p className="text-sm font-semibold leading-tight text-dcg-on-surface">Data Contract</p>
            <p className="text-xs text-dcg-on-surface-variant">Guardian</p>
          </div>
        </Link>
        <button
          type="button"
          onClick={() => router.refresh()}
          className="rounded-lg p-2 text-dcg-outline transition-colors hover:bg-dcg-surface-container-high hover:text-dcg-secondary"
          title="Refresh"
          aria-label="Refresh"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const base = href.split("#")[0];
          const active = base === "/" ? pathname === "/" : pathname.startsWith(base);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                active
                  ? "bg-dcg-surface-container-high font-medium text-dcg-secondary"
                  : "text-dcg-on-surface-variant hover:bg-dcg-surface-container-low hover:text-dcg-on-surface"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-0.5 border-t border-dcg-outline-variant/40 p-3">
        <a
          href="/#system-status"
          className="flex items-center gap-3 rounded-lg p-2 text-xs transition-colors hover:bg-dcg-surface-container-high"
        >
          <Activity className="h-4 w-4 text-dcg-secondary" />
          <div className="min-w-0">
            <p className="font-medium text-dcg-on-surface">System status</p>
            <p className="flex items-center gap-1.5 text-dcg-on-surface-variant">
              <span className={`h-2 w-2 rounded-full ${healthDot}`} />
              {systemHealthLabel(health)}
            </p>
          </div>
        </a>
        <a
          href={`${backendPublicUrl()}/docs`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 rounded-lg p-2 font-mono text-xs text-dcg-on-surface-variant transition-colors hover:bg-dcg-surface-container-high hover:text-dcg-primary"
        >
          <ExternalLink className="h-4 w-4" />
          API docs
        </a>
        <div className="flex items-center gap-2 px-2 py-1 text-[10px] uppercase tracking-wide text-dcg-outline">
          <Network className="h-3 w-3" />
          Fivetran MCP · read-only
        </div>
      </div>
    </aside>
  );
}
