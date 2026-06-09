import Link from "next/link";
import { getPlatformStatus } from "@/lib/platform";
import { AgentPipelinePanel } from "@/components/guardian/AgentPipelinePanel";
import { HumanInLoopBanner } from "@/components/guardian/HumanInLoopBanner";
import { PipelineDiscoveryPanel } from "@/components/guardian/PipelineDiscoveryPanel";
import { WorkflowProgressStepper } from "@/components/guardian/WorkflowProgressStepper";
import { StepPanel } from "@/components/guardian/ui";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const platform = await getPlatformStatus();
  const liveBigQuery = platform ? !platform.bigquery.mock_mode : false;
  const wf = platform?.workflow;
  let completedThrough = 1;
  if (wf?.validation_runs) completedThrough = 2;
  if (wf && ((wf.open_incidents ?? 0) > 0 || wf.awaiting_approval > 0)) {
    completedThrough = Math.max(completedThrough, 4);
  }
  if ((wf?.resolved ?? 0) > 0) completedThrough = 5;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-widest text-dcg-on-surface-variant">
          Hackathon demo · network contracts only
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-dcg-on-surface sm:text-4xl">Data Contract Guardian</h1>
        <p className="max-w-2xl text-base text-dcg-on-surface-variant">
          Orchestrating data contract validation across Fivetran → BigQuery pipelines. Agent Builder + Gemini
          investigate failures with MCP evidence — human approval required before remediation.
        </p>
        <WorkflowProgressStepper completedThrough={completedThrough} />
      </header>

      <HumanInLoopBanner />

      <StepPanel step={1} title="Reliability workflow" bodyClassName="p-6">
        <p className="text-sm text-dcg-on-surface-variant">
          Validate YAML contracts against warehouse state, discover connector lineage via Fivetran MCP, open
          evidence-grounded incidents, and approve fingerprinted remediations with live re-validation.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link
            href="/incidents"
            className="inline-flex items-center justify-center rounded-lg bg-dcg-secondary px-4 py-2 text-sm font-medium text-dcg-on-secondary shadow-sm hover:bg-[#00547a]"
          >
            View incidents
          </Link>
          <Link
            href="/contracts"
            className="inline-flex items-center justify-center rounded-lg border border-dcg-outline-variant bg-dcg-surface px-4 py-2 text-sm font-medium text-dcg-secondary hover:bg-dcg-surface-container"
          >
            Contracts registry
          </Link>
        </div>
      </StepPanel>

      <AgentPipelinePanel
        liveBigQuery={liveBigQuery}
        validationRuns={wf?.validation_runs ?? 0}
        openIncidents={wf?.open_incidents ?? 0}
      />

      <PipelineDiscoveryPanel step={3} />
    </div>
  );
}
