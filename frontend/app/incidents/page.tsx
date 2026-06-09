export const dynamic = "force-dynamic";

import Link from "next/link";
import { apiGet } from "@/lib/api";
import { getPlatformStatus } from "@/lib/platform";
import { DemoToolbar } from "@/components/DemoToolbar";
import { ValidationResults } from "@/components/ValidationResults";

type Incident = {
  id: string;
  contract_id: string;
  severity: string;
  status: string;
  root_cause: string | null;
  created_at: string;
};

type ValidationRun = {
  id: string;
  contract_id: string;
  passed: boolean;
  details: {
    warehouse_source?: string;
    error?: string;
    checks?: { name: string; passed: boolean }[];
  };
  created_at: string;
};

export default async function IncidentsPage() {
  const [openIncidents, platform, validationRuns] = await Promise.all([
    apiGet<Incident[]>("/api/incidents?open=true"),
    getPlatformStatus(),
    apiGet<ValidationRun[]>("/api/validation/results?per_contract=true").catch(() => [] as ValidationRun[]),
  ]);
  const liveBigQuery = platform ? !platform.bigquery.mock_mode : false;
  const awaitingCount = platform?.workflow?.awaiting_approval ?? 0;
  const statusMismatch = awaitingCount > 0 && openIncidents.length === 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-dcg-on-surface-variant">Step 3</p>
          <h1 className="text-2xl font-bold text-dcg-on-surface">Incidents</h1>
          <p className="text-sm text-dcg-on-surface-variant">Evidence-grounded contract violations</p>
        </div>
        <DemoToolbar liveBigQuery={liveBigQuery} />
      </div>

      {statusMismatch && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          System status reports <strong>{awaitingCount}</strong> incident(s) awaiting approval, but this page
          could not load them. Refresh the page — if it persists, redeploy the backend with a single Cloud Run
          instance (SQLite is per-instance).
        </p>
      )}

      <ValidationResults
        runs={validationRuns}
        liveBigQuery={liveBigQuery}
        openIncidentCount={openIncidents.length}
      />
      <div className="overflow-hidden rounded-2xl border border-dcg-outline-variant/60 bg-dcg-surface-container-lowest shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-dcg-surface-container-low text-dcg-on-surface-variant">
            <tr>
              <th className="px-4 py-3">ID</th>
              <th className="px-4 py-3">Contract</th>
              <th className="px-4 py-3">Severity</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {openIncidents.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-dcg-on-surface-variant">
                  {liveBigQuery ? (
                    <>
                      No open incidents. Use <strong>Run live agent pipeline</strong> on{" "}
                      <Link href="/" className="font-medium text-dcg-secondary hover:underline">
                        Agent Home
                      </Link>{" "}
                      — incidents open only when a contract fails against live BigQuery.
                    </>
                  ) : (
                    <>
                      No incidents yet. Use <strong>Seed failing</strong> then <strong>Run agent pipeline</strong> on{" "}
                      <Link href="/" className="font-medium text-dcg-secondary hover:underline">
                        Agent Home
                      </Link>
                      .
                    </>
                  )}
                </td>
              </tr>
            ) : (
              openIncidents.map((i) => (
                <tr key={i.id} className="border-t border-dcg-outline-variant/40 hover:bg-dcg-surface-container-low">
                  <td className="px-4 py-3 font-mono text-xs text-dcg-on-surface-variant">{i.id}</td>
                  <td className="px-4 py-3 text-dcg-on-surface">{i.contract_id}</td>
                  <td className="px-4 py-3">
                    <SeverityBadge s={i.severity} />
                  </td>
                  <td className="px-4 py-3 text-dcg-on-surface-variant">{i.status}</td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/incidents/${i.id}`} className="text-dcg-secondary hover:underline">
                      Open
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SeverityBadge({ s }: { s: string }) {
  const c =
    s === "critical"
      ? "bg-dcg-error-container text-dcg-on-error-container"
      : s === "high"
        ? "bg-[#FCE8E6] text-dcg-on-error-container"
        : "bg-dcg-surface-container text-dcg-on-surface-variant";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${c}`}>{s}</span>;
}
