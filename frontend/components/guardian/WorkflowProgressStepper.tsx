import { Check } from "lucide-react";

/** Data Contract Guardian closed loop: contracts → warehouse → MCP → incidents → approval. */
const PHASES = [
  { key: "contracts", label: "Contracts" },
  { key: "validate", label: "Validate" },
  { key: "mcp_evidence", label: "MCP evidence" },
  { key: "incidents", label: "Incidents" },
  { key: "approve", label: "Approve" },
] as const;

export function WorkflowProgressStepper({ completedThrough = 0 }: { completedThrough?: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs font-medium text-dcg-on-surface-variant sm:gap-0">
      {PHASES.map((phase, index) => {
        const complete = index < completedThrough;
        const isLast = index === PHASES.length - 1;
        return (
          <li key={phase.key} className="flex items-center">
            <span className="flex items-center gap-2 rounded-full border border-dcg-outline-variant/60 bg-dcg-surface-container-lowest px-3 py-1.5">
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] ${
                  complete
                    ? "bg-dcg-secondary text-dcg-on-secondary"
                    : "bg-dcg-surface-container text-dcg-on-surface-variant"
                }`}
              >
                {complete ? <Check className="h-3 w-3" /> : index + 1}
              </span>
              <span className={complete ? "text-dcg-secondary" : ""}>{phase.label}</span>
            </span>
            {!isLast && <span className="mx-1 hidden h-px w-6 bg-dcg-outline-variant sm:block" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}
