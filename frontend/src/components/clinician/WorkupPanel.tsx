import { useMemo, useState } from "react";
import { Beaker, ScanLine, Activity, UserPlus, Check, AlertTriangle } from "lucide-react";
import type { WorkupOrders } from "../../types";

type Props = {
  orders: WorkupOrders;
};

type Section = {
  key: keyof Pick<WorkupOrders, "labs" | "imaging" | "monitoring" | "consults">;
  title: string;
  Icon: typeof Beaker;
};

const SECTIONS: Section[] = [
  { key: "labs", title: "Labs", Icon: Beaker },
  { key: "imaging", title: "Tests and imaging", Icon: ScanLine },
  { key: "monitoring", title: "Monitoring", Icon: Activity },
  { key: "consults", title: "Consults", Icon: UserPlus },
];

export function WorkupPanel({ orders }: Props) {
  const all = useMemo(() => {
    return SECTIONS.flatMap((s) => (orders[s.key] || []).map((o) => `${s.key}:${o}`));
  }, [orders]);

  const [accepted, setAccepted] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const total = all.length;
  const pending = orders.status === "pending";
  // Records from before labels existed: nothing to show.
  if (!pending && total === 0 && !orders.rationale) return null;

  const label = pending ? "Pending" : orders.label || "Suggestion, for the clinician to decide";
  const flags = orders.contraindications ?? [];
  const draftBeforeExam = !pending && orders.basis === "ai_draft" && orders.before_exam;

  return (
    <section>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="text-[12px] uppercase tracking-[0.14em] text-text-muted font-semibold">Workup orders</div>
        <div className="flex items-center gap-3">
          <span className="text-[12px] font-medium text-text-muted">{label}</span>
          {total > 0 && (
            <button
              type="button"
              onClick={() => setAccepted(new Set(all))}
              className="text-[12px] font-medium text-primary hover:text-primary-hover"
            >
              Mark all ({total})
            </button>
          )}
        </div>
      </div>
      <div className="bg-surface-lowest rounded-lg p-3 shadow-soft flex flex-col gap-3">
        {draftBeforeExam && (
          <p className="text-[12px] text-warning font-medium">
            Drafted from the check-in answers only, before any vitals or exam.
          </p>
        )}
        {SECTIONS.map((s) => {
          const items = orders[s.key] || [];
          if (items.length === 0) return null;
          return (
            <div key={s.key}>
              <div className="flex items-center gap-1.5 mb-1.5">
                <s.Icon size={13} className="text-text-muted" aria-hidden="true" />
                <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold">{s.title}</div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {items.map((order) => {
                  const id = `${s.key}:${order}`;
                  const isAccepted = accepted.has(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => toggle(id)}
                      aria-pressed={isAccepted}
                      className={`inline-flex items-center gap-1 px-2.5 h-7 rounded-md text-[12px] font-medium transition-colors ${
                        isAccepted ? "bg-primary text-white" : "bg-surface-low text-ink hover:bg-primary-fixed"
                      }`}
                    >
                      {isAccepted && <Check size={11} aria-hidden="true" />}
                      {order}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
        {flags.length > 0 && (
          <ul className="flex flex-col gap-1">
            {flags.map((f, i) => (
              <li
                key={`${f.order}-${i}`}
                className={`flex gap-1.5 text-[12px] leading-snug ${f.severity === "critical" ? "text-error" : "text-warning"}`}
              >
                <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>
                  <strong>{f.order}:</strong> {f.reason}
                </span>
              </li>
            ))}
          </ul>
        )}
        {orders.rationale && (
          <div className={`text-[12px] text-text-muted italic ${total > 0 ? "border-t border-line pt-2" : ""}`}>
            {orders.rationale}
          </div>
        )}
        {total > 0 && (
          <p className="text-[12px] text-text-muted">
            Marking an order here is only for planning. This demo does not send orders anywhere.
          </p>
        )}
      </div>
    </section>
  );
}
