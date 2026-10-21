import { ArrowRight, Clock, Home, Hospital, MoveUp, Eye } from "lucide-react";
import type { Disposition } from "../../types";

type Props = {
  disposition: Disposition;
};

// Discharge is shown in a neutral color on purpose: a suggestion is never a green light.
function dispoBadge(value: Disposition["disposition"]) {
  switch (value) {
    case "admit":
      return { Icon: Hospital, label: "Admit", cls: "bg-error/15 text-error" };
    case "observe":
      return { Icon: Eye, label: "Observe", cls: "bg-warning/15 text-warning" };
    case "discharge":
      return { Icon: Home, label: "Discharge", cls: "bg-surface-high text-ink" };
    case "transfer":
      return { Icon: MoveUp, label: "Transfer", cls: "bg-primary/15 text-primary" };
    default:
      return { Icon: ArrowRight, label: "Pending", cls: "bg-surface-low text-text-muted" };
  }
}

export function DispositionPanel({ disposition }: Props) {
  if (!disposition) return null;

  const pending = disposition.status === "pending" || !disposition.disposition;
  const badge = dispoBadge(pending ? "" : disposition.disposition);
  const label = pending ? "Pending" : disposition.label || "Suggestion, for the clinician to decide";
  const draftBeforeExam = !pending && disposition.basis === "ai_draft" && disposition.before_exam;

  return (
    <section>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="text-[12px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Disposition
        </div>
        <span className="text-[12px] font-medium text-text-muted">{label}</span>
      </div>
      <div className="bg-surface-lowest rounded-lg p-4 shadow-soft flex flex-col gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <span
            className={`inline-flex items-center gap-1.5 px-3 h-8 rounded-md text-sm font-bold uppercase tracking-wider ${badge.cls}`}
          >
            <badge.Icon size={14} aria-hidden="true" />
            {badge.label}
          </span>
          {!pending && disposition.level_of_care && (
            <span className="text-sm font-mono text-text-muted">· {disposition.level_of_care}</span>
          )}
          {!pending && disposition.expected_los_hours > 0 && (
            <span className="inline-flex items-center gap-1 text-sm font-mono text-text-muted">
              <Clock size={13} aria-hidden="true" />
              about {disposition.expected_los_hours}h in the ER
            </span>
          )}
        </div>

        {draftBeforeExam && (
          <p className="text-[12px] text-warning font-medium">
            Drafted from the check-in answers only, before any vitals or exam.
          </p>
        )}

        {disposition.rationale && (
          <p className={`text-[14px] leading-relaxed ${pending ? "text-text-muted" : ""}`}>
            {disposition.rationale}
          </p>
        )}

        {!pending && disposition.discharge_criteria.length > 0 && (
          <div>
            <div className="text-[12px] uppercase tracking-wider text-text-muted mb-1">Discharge criteria</div>
            <ul className="list-disc list-inside text-[13px] space-y-0.5">
              {disposition.discharge_criteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        )}

        {!pending && disposition.return_precautions.length > 0 && (
          <div>
            <div className="text-[12px] uppercase tracking-wider text-error mb-1 font-semibold">
              Return precautions
            </div>
            <ul className="list-disc list-inside text-[13px] space-y-0.5 text-ink">
              {disposition.return_precautions.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
