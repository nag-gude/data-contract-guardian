import type { ReactNode } from "react";

export function StepPanel({
  id,
  step,
  title,
  headerRight,
  children,
  className = "",
  dimmed,
  bodyClassName = "p-6",
}: {
  id?: string;
  step?: number;
  title: string;
  headerRight?: ReactNode;
  children: ReactNode;
  className?: string;
  dimmed?: boolean;
  bodyClassName?: string;
}) {
  return (
    <section
      id={id}
      className={`overflow-hidden rounded-2xl border border-dcg-outline-variant/60 bg-dcg-surface-container-lowest shadow-sm ${
        dimmed ? "opacity-60" : ""
      } ${className}`}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-dcg-outline-variant/40 bg-dcg-surface-container-low px-6 py-4">
        <div className="flex items-center gap-3">
          {step !== undefined ? (
            <span className="rounded-md bg-dcg-primary px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-dcg-on-primary">
              Step {step}
            </span>
          ) : null}
          <h2 className="text-base font-semibold text-dcg-on-surface">{title}</h2>
        </div>
        {headerRight}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  loading,
  variant = "secondary",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary" | "outline";
  type?: "button" | "submit";
}) {
  const styles = {
    primary: "bg-dcg-primary text-dcg-on-primary hover:opacity-90",
    secondary: "bg-dcg-secondary text-dcg-on-secondary shadow-sm hover:bg-[#00547a] disabled:hover:bg-dcg-secondary",
    outline:
      "border border-dcg-outline-variant bg-dcg-surface text-dcg-secondary hover:bg-dcg-surface-container",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]}`}
    >
      {loading ? "Working…" : children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}) {
  const tones = {
    neutral: "border border-dcg-outline-variant bg-dcg-surface text-dcg-on-surface-variant",
    success: "border border-[#CEEAD6] bg-[#E6F4EA] text-dcg-on-tertiary-container",
    warning: "border border-[#FAD2CF] bg-[#FCE8E6] text-dcg-on-error-container",
    danger: "border border-[#FAD2CF] bg-dcg-error-container text-dcg-on-error-container",
    info: "border border-dcg-secondary-container/30 bg-dcg-surface-container-high text-dcg-on-secondary-container",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}
