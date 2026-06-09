export type PipelineOutcome = {
  contract_id: string;
  passed?: boolean;
  validation_passed?: boolean;
  incident_id?: string | null;
};

export type PipelineResult = {
  ok: boolean;
  status: number;
  summary?: { total: number; passed: number; failed: number };
  outcomes: PipelineOutcome[];
  raw?: string;
};

export function summarizePipelineResult(result: PipelineResult, label: string): string {
  const { outcomes, summary } = result;
  const failed = outcomes.filter(
    (o) => o.validation_passed === false || o.passed === false,
  ).length;
  const opened = outcomes.filter((o) => o.incident_id).length;
  const total = summary?.total ?? outcomes.length;
  const passed = summary?.passed ?? total - failed;
  const failCount = summary?.failed ?? failed;

  return (
    `${label} complete\n\n` +
    `Passed: ${passed}/${total}\n` +
    `Failed: ${failCount}/${total}\n` +
    `Incidents opened: ${opened}`
  );
}

export async function runAgentPipeline(): Promise<PipelineResult> {
  const r = await fetch("/api/agent/run-pipeline", { method: "POST" });
  const text = await r.text();
  if (!r.ok) {
    return { ok: false, status: r.status, outcomes: [], raw: text };
  }
  try {
    const j = JSON.parse(text) as {
      summary?: { total: number; passed: number; failed: number };
      outcomes?: PipelineOutcome[];
    };
    return {
      ok: true,
      status: r.status,
      summary: j.summary,
      outcomes: j.outcomes ?? [],
    };
  } catch {
    return { ok: true, status: r.status, outcomes: [] };
  }
}
