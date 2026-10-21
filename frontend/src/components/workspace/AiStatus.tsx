import { useEffect, useId, useRef, useState } from "react";
import { Info, Sparkles } from "lucide-react";
import { useCapabilities, type Capabilities } from "../../lib/capabilities";

/**
 * Honest labels for anything AI touches on the clinician side.
 *
 * AiStatusPill: one small "AI on" / "AI off" indicator for the page header,
 * with a short list of what is running. AiOffNote: the line an AI card shows in
 * place of its button when the server has no AI key. AiSourceTag: marks a
 * result as written by AI or built without it.
 */

function pillLabel(caps: Capabilities): string {
  if (caps.llm) return "AI on";
  return caps.triage_model.loaded ? "AI off: rules + model" : "AI off: rules only";
}

export function AiStatusPill({
  hospitalId,
  align = "left",
}: {
  hospitalId: string;
  /** Which edge the details panel lines up with. */
  align?: "left" | "right";
}) {
  const caps = useCapabilities(hospitalId);
  const detailsId = useId();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown, { passive: true });
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!caps) {
    return (
      <span className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[12px] font-semibold bg-surface-low text-text-muted">
        Checking AI…
      </span>
    );
  }

  const on = caps.llm;
  const rows: [string, string][] = [
    [
      "Triage score",
      caps.triage_model.loaded
        ? "Trained model plus safety rules that raise the score when they see danger signs."
        : "Safety rules only. The trained model files are not installed on this server.",
    ],
    ["Early warning scores", "Always on. These are fixed formulas, not AI."],
    [
      "AI drafting",
      on
        ? "On: reasoning, scribe notes, prescription ideas and patient summaries. Check every draft."
        : "Off. Those cards say what is off and what still works.",
    ],
    ["Reading ID and insurance photos", caps.ocr ? "On." : "Off. Patients can type their details or use the sample card."],
    ["Text messages", caps.sms ? "On." : "Off. The screen shows the text that would be sent."],
  ];

  return (
    <div ref={wrapRef} className="relative inline-block" data-tour="ai-status">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={detailsId}
        className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[12px] font-semibold ring-1 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
          on
            ? // #3B5D51 on the green container is 5.7:1 (text-success there is only 3.6:1).
              "bg-success-container text-[#3B5D51] ring-success/30"
            : "bg-surface-low text-text-muted ring-line hover:text-ink"
        }`}
      >
        <span
          className={`h-2 w-2 rounded-full ${on ? "bg-success" : "bg-text-muted/60"}`}
          aria-hidden="true"
        />
        {pillLabel(caps)}
        <Info size={12} aria-hidden="true" />
      </button>
      {open && (
        <div
          id={detailsId}
          role="region"
          aria-label="What is running on this server"
          className={`absolute z-50 mt-2 w-[min(20rem,calc(100vw-2rem))] rounded-xl bg-surface-lowest ring-1 ring-line shadow-lifted p-3.5 ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          <div className="text-sm font-semibold text-ink mb-2">What is running</div>
          <dl className="flex flex-col gap-2">
            {rows.map(([k, v]) => (
              <div key={k}>
                <dt className="text-[12px] font-semibold text-ink">{k}</dt>
                <dd className="text-[12px] text-text-muted leading-snug">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

/** Shown in place of an AI action when the server has no AI key. */
export function AiOffNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-surface-low ring-1 ring-line px-3 py-2.5 text-[13px] text-ink leading-snug">
      <Info size={14} className="mt-0.5 shrink-0 text-text-muted" aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

// Server `source` values that mean an AI wrote the result. Every other value is a
// fallback built without AI ("verbatim_no_ai", "ai_failed", "clinician_note_template", ...).
const AI_SOURCES = new Set(["claude", "ai", "llm", "anthropic", "bedrock"]);

/**
 * Did AI write this result? Reads the server's `source` first, so a fallback is never
 * called an AI draft just because the server has a key. Without a source it falls back
 * to `ai_available`. Null when the server said neither.
 */
export function writtenByAi(source: unknown, aiAvailable?: unknown): boolean | null {
  if (typeof source === "string" && source.trim()) return AI_SOURCES.has(source.trim().toLowerCase());
  if (typeof aiAvailable === "boolean") return aiAvailable;
  return null;
}

/** True when the server tried the AI call and it did not come back ("ai_failed", "verbatim_ai_failed"). */
export function aiCallFailed(source: unknown): boolean {
  return typeof source === "string" && /(^|_)ai_failed$/.test(source.trim().toLowerCase());
}

/** Small tag on a result: written by AI, or built without AI. */
export function AiSourceTag({ ai, label }: { ai: boolean; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold ${
        ai ? "bg-primary-fixed/60 text-primary" : "bg-surface-low text-text-muted ring-1 ring-line"
      }`}
    >
      {ai && <Sparkles size={11} aria-hidden="true" />}
      {label ?? (ai ? "AI draft: check before use" : "No AI used")}
    </span>
  );
}
