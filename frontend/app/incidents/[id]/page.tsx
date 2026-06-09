import Link from "next/link";
import { notFound } from "next/navigation";
import { apiGet } from "@/lib/api";
import { ApprovePanel } from "@/components/ApprovePanel";
import { McpTracePanel } from "@/components/McpTracePanel";
import { StepPanel } from "@/components/guardian/ui";

export const dynamic = "force-dynamic";

type IncidentDetail = {
  id: string;
  contract_id: string;
  severity: string;
  status: string;
  root_cause: string | null;
  confidence: number | null;
  evidence_bundle_ids: string[];
  action_fingerprint: string | null;
  ranked_remediations: { rank: number; title: string; risk_class: string; rationale: string }[];
  events: {
    type?: string;
    step?: string;
    message?: string;
    tool?: string;
    orchestrator?: string;
    model?: string;
    created_at?: string;
  }[];
  evidence: Record<string, unknown>[];
};

export default async function IncidentDetailPage({ params }: { params: { id: string } }) {
  let data: IncidentDetail;
  try {
    data = await apiGet<IncidentDetail>(`/api/incidents/${params.id}`);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link href="/incidents" className="text-sm text-dcg-secondary hover:underline">
        ← Incidents
      </Link>
      <StepPanel title={data.id} bodyClassName="p-6">
        <p className="text-sm text-dcg-on-surface-variant">
          {data.contract_id} · {data.severity} · {data.status}
        </p>
        {data.root_cause && (
          <div className="mt-4 rounded-lg border border-dcg-outline-variant/50 bg-dcg-surface-container-low p-4">
            <p className="text-xs uppercase text-dcg-on-surface-variant">Root cause</p>
            <p className="mt-1 text-dcg-on-surface">{data.root_cause}</p>
            {data.confidence != null && (
              <p className="mt-2 text-xs text-dcg-outline">Confidence: {(data.confidence * 100).toFixed(0)}%</p>
            )}
          </div>
        )}
        <ApprovePanel incidentId={data.id} fingerprint={data.action_fingerprint} status={data.status} />
      </StepPanel>

      <McpTracePanel evidence={data.evidence} />

      <div className="grid gap-6 lg:grid-cols-2">
        <StepPanel title="Agent transcript" bodyClassName="p-4">
          <ul className="space-y-2 font-mono text-xs text-dcg-on-surface-variant">
            {data.events.map((e, i) => (
              <li key={i} className="rounded border border-dcg-outline-variant/40 bg-dcg-surface-container-low p-2">
                <span className="text-dcg-secondary">{e.type || "event"}</span>{" "}
                {e.step && <span className="text-dcg-on-error-container">{e.step}</span>}
                {e.tool && <span className="ml-2 text-dcg-on-secondary-container">{e.tool}</span>}
                {e.message && <div className="mt-1 text-dcg-on-surface">{e.message}</div>}
                {e.created_at && <div className="mt-1 text-dcg-outline">{e.created_at}</div>}
              </li>
            ))}
          </ul>
        </StepPanel>
        <StepPanel title="Evidence bundles" bodyClassName="p-4">
          <pre className="max-h-96 overflow-auto rounded bg-dcg-primary-container/5 p-3 text-xs text-dcg-on-surface-variant">
            {JSON.stringify(data.evidence, null, 2)}
          </pre>
        </StepPanel>
      </div>

      <StepPanel title="ARP — ranked remediations" bodyClassName="p-4">
        <ol className="list-decimal space-y-3 pl-5 text-sm text-dcg-on-surface">
          {data.ranked_remediations?.map((r) => (
            <li key={r.rank}>
              <span className="font-medium">{r.title}</span>{" "}
              <span className="rounded bg-dcg-surface-container px-1.5 py-0.5 text-xs text-dcg-on-surface-variant">
                {r.risk_class}
              </span>
              <p className="mt-1 text-dcg-on-surface-variant">{r.rationale}</p>
            </li>
          ))}
        </ol>
      </StepPanel>
    </div>
  );
}
