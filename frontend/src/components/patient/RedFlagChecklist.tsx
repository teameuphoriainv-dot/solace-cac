import { Fragment } from "react";
import { Check } from "lucide-react";
import { RED_FLAG_IDS, type RedFlagId } from "../../lib/api-patient";
import { t, type I18nKey } from "../../lib/i18n";

/** One checklist row. "ingestion" (pills, poison or a battery) joined the K1 list in wave 2. */
export type ChecklistId = RedFlagId | "ingestion";

/**
 * The rows in K1 screen order: breathing, chest, faint, confusion, bleeding,
 * self_harm, ingestion, pregnancy, stroke, infant_fever, none. The ids come from
 * lib/api-patient.ts; "ingestion" goes right after "self_harm" when that list
 * does not have it yet.
 */
export const CHECKLIST_IDS: readonly ChecklistId[] = (RED_FLAG_IDS as readonly ChecklistId[]).includes("ingestion")
  ? RED_FLAG_IDS
  : RED_FLAG_IDS.flatMap((id): ChecklistId[] => (id === "self_harm" ? [id, "ingestion"] : [id]));

/** Adds the patient's taps to the intake form as a JSON array of known ids, in screen order. */
export function appendChecklistFlags(form: FormData, flags: readonly string[]): void {
  const clean = CHECKLIST_IDS.filter((id) => flags.includes(id));
  if (clean.length > 0) form.append("red_flags", JSON.stringify(clean));
}

const LABEL: Record<ChecklistId, I18nKey> = {
  breathing: "redflag_breathing",
  chest: "redflag_chest",
  faint: "redflag_faint",
  confusion: "redflag_confusion",
  bleeding: "redflag_bleeding",
  self_harm: "redflag_self_harm",
  ingestion: "redflag_ingestion",
  pregnancy: "redflag_pregnancy",
  stroke: "redflag_stroke",
  infant_fever: "redflag_infant_fever",
  none: "redflag_none",
};

/** Multi-select, except that "None of these" and the other rows clear each other. */
export function toggleRedFlag(current: readonly ChecklistId[], id: ChecklistId): ChecklistId[] {
  if (current.includes(id)) return current.filter((x) => x !== id);
  if (id === "none") return ["none"];
  return [...current.filter((x) => x !== "none"), id];
}

type Props = {
  lang: string;
  value: ChecklistId[];
  onChange: (next: ChecklistId[]) => void;
};

/**
 * "Is any of this happening right now?" The patient taps the danger signs that
 * apply. It works the same in every language, so it catches emergencies the
 * word rules cannot read. Any tapped sign raises the priority on the server.
 */
export function RedFlagChecklist({ lang, value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 id="redflag-title" className="text-2xl font-bold tracking-editorial rtl:tracking-normal mb-1">
          {t("redflag_title", lang)}
        </h2>
        <p id="redflag-subtitle" className="text-text-muted text-sm">
          {t("redflag_subtitle", lang)}
        </p>
      </div>
      <div
        role="group"
        aria-labelledby="redflag-title"
        aria-describedby="redflag-subtitle"
        className="flex flex-col gap-2"
      >
        {CHECKLIST_IDS.map((id) => {
          const on = value.includes(id);
          return (
            <Fragment key={id}>
              {id === "none" && <div className="h-px bg-line my-1" aria-hidden="true" />}
              <button
                type="button"
                data-flag={id}
                aria-pressed={on}
                onClick={() => onChange(toggleRedFlag(value, id))}
                className={`w-full min-h-[56px] flex items-center gap-3 px-4 py-3 rounded-lg text-start text-[16px] leading-snug font-medium text-ink transition-all active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 ${
                  on ? "bg-primary-fixed ring-2 ring-primary shadow-soft" : "bg-surface-lowest ring-1 ring-line hover:ring-primary/40"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`shrink-0 w-6 h-6 rounded-md flex items-center justify-center ${
                    on ? "bg-primary text-white" : "bg-surface-lowest ring-2 ring-line"
                  }`}
                >
                  {on && <Check size={16} strokeWidth={3} />}
                </span>
                <span className="flex-1 min-w-0 break-words">{t(LABEL[id], lang)}</span>
              </button>
              {id === "self_harm" && (
                // The same 988 sentence the result screen uses, shown as soon as it is tapped.
                <div aria-live="polite" className="empty:hidden">
                  {on && (
                    <p
                      data-testid="redflag-crisis-note"
                      className="rounded-lg bg-surface-low px-4 py-3 text-[15px] leading-relaxed text-ink"
                    >
                      {t("result_explain_crisis", lang)}
                    </p>
                  )}
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
