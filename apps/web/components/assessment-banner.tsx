import { ShieldAlert } from "lucide-react";

export function AssessmentBanner() {
  return (
    <aside
      aria-label="Assessment data warning"
      className="border-b border-amber-300 bg-amber-100 text-amber-950"
    >
      <div className="mx-auto flex max-w-6xl gap-3 px-5 py-3 text-sm leading-6 sm:px-8">
        <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <p>
          <strong>Use synthetic data only.</strong> Every Google-authenticated
          reviewer can view submitted data. Real PII and real CVs must not be
          used in this assessment.
        </p>
      </div>
    </aside>
  );
}
