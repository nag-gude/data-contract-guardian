export function GuardianLogo({ className = "h-8 w-8 shrink-0" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" fill="none" aria-hidden>
      <rect width="40" height="40" rx="10" className="fill-dcg-primary-container" />
      <path
        d="M20 8L30 14V26L20 32L10 26V14L20 8Z"
        stroke="#5bb8fe"
        strokeWidth="1.5"
        fill="none"
      />
      <path d="M16 20L19 23L25 17" stroke="#4edea3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
