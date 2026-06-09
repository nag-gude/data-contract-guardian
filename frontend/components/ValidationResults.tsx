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

function latestPerContract(runs: ValidationRun[]): ValidationRun[] {
  const byContract = new Map<string, ValidationRun>();
  for (const run of runs) {
    const existing = byContract.get(run.contract_id);
    if (!existing || run.created_at > existing.created_at) {
      byContract.set(run.contract_id, run);
    }
  }
  return Array.from(byContract.values()).sort((a, b) => a.contract_id.localeCompare(b.contract_id));
}

export function ValidationResults({
  runs,
  liveBigQuery,
  openIncidentCount = 0,
}: {
  runs: ValidationRun[];
  liveBigQuery: boolean;
  openIncidentCount?: number;
}) {
  const latest = latestPerContract(runs);
  if (latest.length === 0) return null;

  const passed = latest.filter((r) => r.passed).length;
  const failed = latest.length - passed;
  const source = latest.find((r) => r.details?.warehouse_source)?.details?.warehouse_source ?? "—";

  return (
    <section className="overflow-hidden rounded-2xl border border-dcg-outline-variant/60 bg-dcg-surface-container-lowest shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-dcg-outline-variant/40 bg-dcg-surface-container-low px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-dcg-secondary">Latest validation</h2>
        <p className="text-xs text-dcg-on-surface-variant">
          {passed}/{latest.length} passed · source: {source}
        </p>
      </header>
      <div className="overflow-x-auto p-4">
        <table className="w-full text-left text-xs">
          <thead className="text-dcg-on-surface-variant">
            <tr>
              <th className="pb-2 pr-4">Contract</th>
              <th className="pb-2 pr-4">Result</th>
              <th className="pb-2">Details</th>
            </tr>
          </thead>
          <tbody className="text-dcg-on-surface">
            {latest.map((r) => {
              const failedChecks = (r.details.checks ?? []).filter((c) => !c.passed).map((c) => c.name);
              const detail =
                r.details.error ??
                (failedChecks.length > 0 ? failedChecks.join(", ") : r.passed ? "All checks passed" : "Failed");
              return (
                <tr key={r.id} className="border-t border-dcg-outline-variant/40">
                  <td className="py-2 pr-4 font-mono">{r.contract_id}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={`rounded px-2 py-0.5 font-medium ${
                        r.passed
                          ? "bg-[#E6F4EA] text-dcg-on-tertiary-container"
                          : "bg-dcg-error-container text-dcg-on-error-container"
                      }`}
                    >
                      {r.passed ? "pass" : "fail"}
                    </span>
                  </td>
                  <td className="py-2 text-dcg-on-surface-variant">{detail}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {liveBigQuery && failed === 0 && openIncidentCount === 0 && (
        <p className="border-t border-dcg-outline-variant/40 px-4 py-3 text-sm text-dcg-on-tertiary-container">
          All contracts passed against live BigQuery — no new incidents to open.
        </p>
      )}
      {liveBigQuery && failed === 0 && openIncidentCount > 0 && (
        <p className="border-t border-dcg-outline-variant/40 px-4 py-3 text-sm text-dcg-on-error-container">
          Latest validation passed, but {openIncidentCount} incident(s) still await approval or were opened on an
          earlier failed run.
        </p>
      )}
    </section>
  );
}
