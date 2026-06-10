import type { ReactNode } from "react";
import Link from "next/link";
import type { PlatformStatus } from "@/lib/platform";
import { DashboardSidebar } from "./DashboardSidebar";
import { GuardianLogo } from "./GuardianLogo";
import { SystemStatusBar } from "./SystemStatusBar";

export function AppShell({
  children,
  platform,
}: {
  children: ReactNode;
  platform: PlatformStatus | null;
}) {
  return (
    <div className="flex min-h-screen bg-dcg-surface">
      <DashboardSidebar platform={platform} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-dcg-outline-variant/50 bg-dcg-surface-container-lowest px-4 py-3 lg:hidden">
          <Link href="/" className="flex items-center gap-2">
            <GuardianLogo className="h-7 w-7" />
            <span className="text-sm font-semibold">Data Contract Guardian</span>
          </Link>
          <nav className="flex gap-3 text-xs">
            <Link href="/incidents" className="text-dcg-secondary">
              Incidents
            </Link>
            <Link href="/contracts" className="text-dcg-on-surface-variant">
              Contracts
            </Link>
          </nav>
        </header>
        <SystemStatusBar platform={platform} />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
        <footer className="border-t border-dcg-outline-variant/40 px-6 py-4 text-center text-xs text-dcg-outline">
          © {new Date().getFullYear()} Data Contract Guardian — Fivetran MCP · human-in-the-loop
        </footer>
      </div>
    </div>
  );
}
