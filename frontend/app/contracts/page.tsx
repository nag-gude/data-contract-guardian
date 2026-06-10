import { apiGet } from "@/lib/api";
import { StepPanel } from "@/components/guardian/ui";

export const dynamic = "force-dynamic";

export default async function ContractsPage() {
  let contracts: Record<string, unknown>[] | null = null;
  let error: string | null = null;
  try {
    contracts = await apiGet<Record<string, unknown>[]>("/api/contracts");
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load contracts";
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-widest text-dcg-on-surface-variant">Registry</p>
        <h1 className="text-2xl font-bold text-dcg-on-surface">Contracts</h1>
      </div>
      <StepPanel title="YAML contract definitions" bodyClassName="p-0">
        {error ? (
          <p className="p-4 text-sm text-dcg-on-error-container">
            {error}. Start the API:{" "}
            <code className="rounded bg-dcg-surface-container px-1">
              cd backend && uvicorn app.main:app --reload --port 8000
            </code>
          </p>
        ) : (
          <pre className="max-h-[70vh] overflow-auto p-4 font-mono text-xs text-dcg-on-surface-variant">
            {JSON.stringify(contracts, null, 2)}
          </pre>
        )}
      </StepPanel>
    </div>
  );
}
