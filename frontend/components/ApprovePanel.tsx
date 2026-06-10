"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PrimaryButton } from "@/components/guardian/ui";

export function ApprovePanel({
  incidentId,
  fingerprint,
  status,
}: {
  incidentId: string;
  fingerprint: string | null;
  status: string;
}) {
  const router = useRouter();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!fingerprint) return null;
  const canAct = status === "awaiting_approval" || status === "verify_failed";
  if (!canAct) {
    return (
      <p className="mt-4 rounded-lg border border-dcg-outline-variant bg-dcg-surface-container-low p-3 text-sm text-dcg-on-surface-variant">
        No approval required (status: <strong className="text-dcg-on-surface">{status}</strong>).
      </p>
    );
  }

  const submit = async (approve: boolean) => {
    if (approve && !confirmed) return;
    setBusy(true);
    const body = {
      incident_id: incidentId,
      action_fingerprint: fingerprint,
      approver_id: "operator",
      approve,
      idempotency_key: `${incidentId}-${approve}-${Date.now()}`,
    };
    const r = await fetch("/api/approve-remediation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    setBusy(false);
    if (!r.ok) {
      alert(`Approval failed: ${JSON.stringify(j, null, 2)}`);
      return;
    }
    const failed = Array.isArray(j.failed_checks) ? j.failed_checks.join(", ") : "";
    const execSummary = j.execution?.summary as string | undefined;
    const msg = j.duplicate
      ? "Duplicate approval (idempotent retry) — no double execution."
      : approve
        ? j.verification_passed
          ? "Approved and verified — incident resolved."
          : [
              "Approved, but contract checks still failing.",
              failed ? `Failed: ${failed}.` : "",
              execSummary ? `Action: ${execSummary}` : "",
              j.execution?.await_verification
                ? "BigQuery may need more time after the Fivetran sync — re-approve or run validation again shortly."
                : "Review remediation steps or fix upstream manually.",
            ]
              .filter(Boolean)
              .join(" ")
        : "Remediation rejected.";
    alert(msg);
    router.refresh();
  };

  return (
    <div className="mt-4 rounded-xl border border-dcg-secondary-container/40 bg-dcg-surface-container-low p-4">
      <p className="text-sm font-medium text-dcg-on-surface">
        Human-in-the-loop gate — nothing runs until you explicitly approve the fingerprinted plan.
      </p>
      <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm text-dcg-on-surface-variant">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1" />
        <span>
          I reviewed the evidence bundles and ranked remediations for incident <code>{incidentId}</code>.
        </span>
      </label>
      <div className="mt-4 flex flex-wrap gap-3">
        <PrimaryButton disabled={!confirmed || busy} onClick={() => submit(true)} variant="secondary">
          Approve &amp; re-verify
        </PrimaryButton>
        <button
          type="button"
          disabled={busy}
          onClick={() => submit(false)}
          className="rounded-lg border border-dcg-outline-variant px-4 py-2 text-sm text-dcg-on-surface-variant hover:border-dcg-outline disabled:opacity-40"
        >
          Reject
        </button>
      </div>
      <p className="mt-3 font-mono text-xs text-dcg-outline">action fingerprint: {fingerprint.slice(0, 24)}…</p>
    </div>
  );
}
