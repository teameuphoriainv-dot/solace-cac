import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, ShieldOff } from "lucide-react";
import { PatientDetailBody } from "../../clinician/PatientDetailBody";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import type { PatientDetail } from "../../../types";

// Safety-rule ids (backend/services/triage_rules.py) in words a nurse reads at a glance.
const RULE_TEXT: Record<string, string> = {
  "rule.esi1.not_breathing_or_unresponsive": "Not breathing, not waking up, or turning blue",
  "rule.esi1.life_threatening_keywords": "Words that point to a life-threatening emergency",
  "rule.esi1.catastrophic_trauma": "Severe injury or heavy blood loss",
  "rule.esi1.stroke_symptoms": "Possible stroke signs",
  "rule.esi2.chest_pain": "Chest pain or pressure",
  "rule.esi2.breathing": "Trouble breathing",
  "rule.esi2.airway_swelling": "Throat, lips, or tongue swelling",
  "rule.esi2.heavy_bleeding": "Heavy bleeding",
  "rule.esi2.pregnancy_bleeding": "Pregnant with bleeding or severe pain",
  "rule.esi2.syncope": "Fainted or passed out",
  "rule.esi2.head_injury": "Head injury with confusion, vomiting, or passing out",
  "rule.esi2.stiff_neck_fever": "Stiff neck with fever or headache",
  "rule.esi2.child_fever_lethargy": "Young child with a fever who is very sleepy",
  "rule.esi2.infant_fever": "Baby under 3 months with a fever",
  "rule.esi2.crisis": "Suicidal thoughts or self-harm",
  "rule.esi2.overdose": "Overdose or poisoning",
  "rule.esi2.overdose_self": "Overdose, possible self-harm",
  "rule.esi2.seizure": "Seizure",
  "rule.esi2.one_sided_weakness": "One side of the body weak or numb",
  "rule.esi2.high_risk_presentation": "High-risk complaint",
  "rule.esi5.administrative": "Paperwork or refill request",
  "floor.esi1.unresponsive": "Not responding (very low alertness)",
  "floor.esi2.danger_zone_vitals": "Danger-zone vital signs",
};

/** Plain text for a clinical flag; anything that is not a rule id passes through. */
function plainFlag(flag: string): string {
  if (RULE_TEXT[flag]) return RULE_TEXT[flag];
  const m = flag.match(/^(?:rule|floor)\.esi\d\.(.+)$/);
  if (m) {
    const words = m[1].replace(/[_.]+/g, " ").trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  return flag;
}

// The same kinds of wording the server's prompt-injection filter looks for
// (backend/lib/content_guard.py). Used only to pick which sentence to show.
const INSTRUCTION_LIKE = [
  /ignore\s+(?:all\s+|the\s+|any\s+)?(?:previous|prior|above)\s+(?:instruction|prompt|message|rule|system)/i,
  /(?:you\s+are\s+now|you're\s+now|from\s+now\s+on\s+you)\b/i,
  /(?:forget|disregard|override)\s+(?:your\s+|the\s+|all\s+)?(?:instructions?|prompt|system\s+message|rules?|training)/i,
  /you\s+must\s+(?:ignore|override|bypass)\b/i,
  /(?:reveal|print|leak|expose)\s+(?:your\s+)?(?:system\s+prompt|hidden\s+prompt|instructions|api\s+key)/i,
  /\[\/?(?:INST|SYS|SYSTEM|HUMAN|ASSISTANT)\]|<\|[^|]*\|>/i,
];

/**
 * For a flagged check-in, the patient's health words without the sentences that read
 * like instructions to the AI. Prefers a complaint the server picked, when it sends one.
 */
function clinicalWords(p: PatientDetail): string | null {
  const fromServer = (p as PatientDetail & { clinical_complaint?: unknown; chief_complaint?: unknown });
  for (const v of [fromServer.clinical_complaint, fromServer.chief_complaint]) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  const text = (p.transcript || p.transcript_english || "").trim();
  if (!text) return null;
  const sentences = text.match(/[^.!?\n]+[.!?]*/g) ?? [text];
  const kept = sentences.map((x) => x.trim()).filter((x) => x && !INSTRUCTION_LIKE.some((re) => re.test(x)));
  if (kept.length === 0 || kept.length === sentences.length) return null;
  return kept.join(" ");
}

/** Banner for a check-in whose words matched the prompt-injection filter. */
function ContentFlagBanner({ patient }: { patient: PatientDetail }) {
  const words = clinicalWords(patient);
  return (
    <div role="note" className="mb-5 flex items-start gap-2.5 rounded-lg bg-warning-container px-4 py-3 text-ink">
      <ShieldOff size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="text-[14px] leading-relaxed">
        <p className="font-semibold">
          This check-in&rsquo;s words looked like an instruction to the AI, so AI features are off for
          this patient.
        </p>
        <p className="mt-0.5">
          The safety rules, the checklist, the trained model, the early warning scores and the
          bedside re-check still work. Nothing from this check-in is sent to the AI.
        </p>
        {words && (
          <p className="mt-1.5">
            <span className="font-semibold">Health complaint, without the flagged words: </span>
            &ldquo;{words}&rdquo;
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Overview tab: the full record for the workspace patient (summary, vitals,
 * notes, prescriptions). Shared by the patient page and the dashboard card.
 */
export default function OverviewTab() {
  const { hospitalId, patient, loading, error, reloadPatient, updatePatient } = usePatientWorkspace();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const shown = useMemo<PatientDetail | null>(
    () =>
      patient
        ? {
            ...patient,
            clinical_flags: Array.from(
              new Set((patient.clinical_flags || []).map((f) => plainFlag(String(f)))),
            ),
          }
        : null,
    [patient],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm" role="status">
        <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
        Loading patient record…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 rounded-md bg-error-container text-error text-sm" role="alert">{error}</div>
    );
  }

  if (!shown) {
    return <div className="text-text-muted text-sm py-8">No patient record available.</div>;
  }

  return (
    <>
    {shown.content_flag && <ContentFlagBanner patient={shown} />}
    <PatientDetailBody
      detail={shown}
      hospitalId={hospitalId}
      authenticated
      showScribeLink={false}
      onDetailChange={(updater) => {
        // Show the change now, then confirm it from the server in the background.
        updatePatient(updater);
        reloadPatient();
      }}
      onAfterMarkSeen={() => {
        navigate(`/${hospitalId}/clinician${searchParams.get("embed") === "1" ? "?embed=1" : ""}`);
      }}
    />
    </>
  );
}
