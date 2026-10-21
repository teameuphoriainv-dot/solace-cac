import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Check, Clock, HeartHandshake, Hospital } from "lucide-react";
import { t } from "../../lib/i18n";
import type { IntakeResponse } from "../../types";

type Key = Parameters<typeof t>[0];
export type CareRec = NonNullable<IntakeResponse["care_recommendation"]>;

// The server's care kinds (services/care_routing.py). Each has care_<kind>_* text here.
export type CareKind = "now" | "crisis" | "high" | "today" | "wait";
export type CareCopy = { kind: CareKind; title: string; body: string; cta: string; steps: string[]; note: string };

const CARE_KINDS = new Set<string>(["now", "crisis", "high", "today", "wait"]);

// Destinations and wording that would send a patient who is already in the ER
// somewhere else. Older servers could send these; they are never shown.
const OFFSITE = new Set(["telehealth", "self_care", "schedule"]);
const OFFSITE_TEXT = /virtual visit|telehealth|from home|book a|schedule|come back later/i;

/** The card that fits a priority on its own, with no server reason behind it. */
export function kindForLevel(esi: number): CareKind {
  if (esi <= 1) return "now";
  if (esi === 2) return "high";
  if (esi === 3) return "today";
  return "wait";
}

function careKind(rec: CareRec, esi: number): CareKind {
  if (rec.kind && CARE_KINDS.has(rec.kind)) return rec.kind as CareKind;
  // Older servers sent only a destination, so follow the visible score.
  if (/\b988\b/.test(rec.rationale || "")) return "crisis";
  if (rec.destination === "ed_now") return "now";
  return kindForLevel(esi);
}

function translated(kind: CareKind, lang: string, busy: boolean): CareCopy {
  return {
    kind,
    title: t(`care_${kind}_title` as Key, lang),
    body: t(`care_${kind}_body` as Key, lang),
    cta: t(`care_${kind}_cta` as Key, lang),
    steps: [],
    note: busy ? t("care_busy_note", lang) : "",
  };
}

/**
 * The card's words. When the server wrote them in the patient's language (it knows
 * the reason, for example a red-flag phrase) they are shown as is, with its steps.
 * Otherwise the translated text for the same kind is used.
 *
 * When a nurse's re-check changed the priority, the server's card can still describe
 * the old one. Then the card follows the new priority, except the 988 card, which stays.
 */
export function careCopy(rec: CareRec, lang: string, esi: number, levelChanged = false): CareCopy {
  let kind = careKind(rec, esi);
  const stale = levelChanged && kind !== "crisis" && kind !== kindForLevel(esi);
  if (stale) kind = kindForLevel(esi);
  const steps = (rec.next_steps ?? []).filter((s) => typeof s === "string" && s.trim());
  const serverText = [rec.label, rec.rationale, rec.action_cta, ...steps].join(" ");
  const offsite = OFFSITE.has(rec.destination) || OFFSITE_TEXT.test(serverText);
  const serverLang = rec.language || "en";
  if (!stale && serverLang === lang && !offsite && rec.label) {
    return {
      kind,
      title: rec.label,
      body: rec.rationale,
      cta: rec.action_cta || t(`care_${kind}_cta` as Key, lang),
      steps,
      note: rec.capacity_note || "",
    };
  }
  return translated(kind, lang, !!rec.capacity_note);
}

export function crisisCopy(lang: string): CareCopy {
  return translated("crisis", lang, false);
}

const SEVERITY_OF: Record<CareKind, "critical" | "high" | "moderate" | "low"> = {
  now: "critical", crisis: "critical", high: "high", today: "moderate", wait: "low",
};

export function CareRecommendationCard({ copy, lang }: { copy: CareCopy; lang: string }) {
  const [acknowledged, setAcknowledged] = useState(false);
  const severity = SEVERITY_OF[copy.kind];
  const critical = severity === "critical";

  const tone = {
    critical: { bg: "bg-error", fg: "text-white", body: "text-white", Icon: AlertTriangle, ring: "ring-error" },
    high:     { bg: "bg-error/15", fg: "text-error", body: "text-ink", Icon: Hospital, ring: "ring-error/40" },
    moderate: { bg: "bg-warning/15", fg: "text-ink", body: "text-ink", Icon: Clock, ring: "ring-warning/40" },
    low:      { bg: "bg-success/15", fg: "text-ink", body: "text-ink", Icon: Clock, ring: "ring-success/40" },
  }[severity];

  const ack = t(
    copy.kind === "crisis" ? "care_ack_crisis"
      : copy.kind === "now" ? "care_ack_now"
      : copy.kind === "high" ? "care_ack_high"
      : "care_ack_stay",
    lang,
  );
  const ActionIcon = copy.kind === "crisis" ? HeartHandshake : critical || copy.kind === "high" ? Hospital : Check;

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex flex-col gap-3 rounded-xl p-5 shadow-soft ring-2 ${tone.ring} ${tone.bg}`}
    >
      <div className={`flex items-center gap-2 ${critical ? "text-white" : "text-ink"}`}>
        <tone.Icon size={16} strokeWidth={2.5} aria-hidden="true" />
        <h2 className="text-[13px] uppercase tracking-wider rtl:tracking-normal font-bold">{t("result_what_to_do", lang)}</h2>
      </div>
      <div className={`text-2xl font-bold tracking-tight rtl:tracking-normal ${tone.fg}`}>{copy.title}</div>
      {copy.body && <p className={`text-[15px] leading-relaxed ${tone.body}`}>{copy.body}</p>}
      {copy.steps.length > 0 && (
        <ul className={`text-[15px] leading-relaxed list-disc ms-5 flex flex-col gap-1 ${tone.body}`}>
          {copy.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ul>
      )}
      {copy.note && <p className={`text-[14px] font-semibold leading-snug ${tone.body}`}>{copy.note}</p>}
      <div className="mt-1">
        {acknowledged ? (
          <p
            role="status"
            className={`rounded-md px-4 py-3 text-[15px] font-semibold leading-snug ${
              critical ? "bg-white text-error" : "bg-surface-lowest text-ink"
            }`}
          >
            {ack}
          </p>
        ) : (
          // The patient is already here, so this button only confirms they read it.
          <button
            type="button"
            onClick={() => setAcknowledged(true)}
            className={`w-full inline-flex items-center justify-center gap-2 min-h-12 px-4 py-2 rounded-md font-semibold text-[15px] shadow-soft transition-all active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
              critical
                ? "bg-white text-error hover:bg-white/90 focus-visible:ring-white focus-visible:ring-offset-error"
                : "bg-primary text-white hover:bg-primary-hover focus-visible:ring-primary/60"
            }`}
          >
            <ActionIcon size={16} aria-hidden="true" />
            {copy.cta}
          </button>
        )}
      </div>
    </motion.section>
  );
}
