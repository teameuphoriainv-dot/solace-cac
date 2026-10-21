import { Link } from "react-router-dom";
import { Info, Mic } from "lucide-react";
import type { PatientDetail, RefinedTriage, Vitals } from "../../types";
import { Button } from "../ui/Button";
import { PrescriptionPanel } from "./PrescriptionPanel";
import { NotesPanel } from "./NotesPanel";
import { VitalsPanel } from "./VitalsPanel";
import { DifferentialPanel } from "./DifferentialPanel";
import { WorkupPanel } from "./WorkupPanel";
import { DispositionPanel } from "./DispositionPanel";
import { markSeen } from "../../lib/api";
import { AiSourceTag } from "../workspace/AiStatus";

/** Human-readable wait: 103 → "1h 43m wait", 45 → "45 min wait", 0 → "Just arrived". */
function waitLabel(mins: number | null | undefined): string {
  if (mins == null) return "";
  if (mins <= 0) return "Just arrived";
  if (mins < 60) return `${mins} min wait`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m wait` : `${h}h wait`;
}

/** "ESI 2 to 4 (confidence 99% at ESI 4)" → [2, 4]; null for a single level or no band. */
function bandRange(band: string | null | undefined): [number, number] | null {
  const m = (band || "").match(/^ESI\s+(\d)\s+to\s+(\d)/);
  return m ? [Number(m[1]), Number(m[2])] : null;
}

const MODEL_SURE_TIP =
  "How sure the trained model was about this score. It learned only from made-up practice visits, so this is not how often it is right with real patients.";

/** "model 99% sure", with the reason it is not a real-world accuracy in the tooltip. */
function ModelSure({ p }: { p: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-text-muted" title={MODEL_SURE_TIP}>
      model {(p * 100).toFixed(0)}% sure
      <Info size={12} aria-hidden="true" />
      <span className="sr-only">. {MODEL_SURE_TIP}</span>
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold mb-2">
        {title}
      </div>
      {children}
    </section>
  );
}

function InsRow({
  label,
  value,
  mono = false,
  primary = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  primary?: boolean;
}) {
  return (
    <div>
      <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold">{label}</div>
      <div
        className={`text-sm leading-tight ${mono ? "font-mono" : ""} ${
          primary ? "font-bold text-primary" : "text-ink"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function formatMedicalInfo(info: NonNullable<PatientDetail["medical_info"]>): string {
  const parts: string[] = [];
  if (info.age) parts.push(`${info.age}yo`);
  if (info.sex) parts.push(info.sex);
  if (info.pregnant) {
    parts.push(info.gestational_weeks ? `pregnant ${info.gestational_weeks}w` : "pregnant");
  }
  if (info.smoker) parts.push("smoker");
  const allergies = (info.allergies || []).filter((x) => x.toLowerCase() !== "none");
  if (allergies.length) {
    const labeled = allergies.map((a) => {
      const sev = info.allergy_severity?.[a];
      return sev ? `${a} (${sev})` : a;
    });
    parts.push(`allergies: ${labeled.join(", ")}`);
  }
  const meds = (info.medications || []).filter((x) => x.toLowerCase() !== "none");
  if (meds.length) {
    const labeled = meds.map((m) =>
      m === "Blood thinners" && info.blood_thinner_name ? `${m} (${info.blood_thinner_name})` : m,
    );
    parts.push(`meds: ${labeled.join(", ")}`);
  }
  const conds = (info.conditions || []).filter((x) => x.toLowerCase() !== "none");
  if (conds.length) {
    const labeled = conds.map((c) => {
      if (c === "Diabetes" && info.diabetes_type) return `${c} (${info.diabetes_type})`;
      if (c === "Heart failure" && info.heart_failure_class) return `${c} (NYHA ${info.heart_failure_class})`;
      return c;
    });
    parts.push(`hx: ${labeled.join(", ")}`);
  }
  return parts.join(" · ") || "none reported";
}

function parseJson<T>(raw: string | null | undefined, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** Rebuild the last bedside re-check from the stored patient record (after a reload). */
function refinedFromDetail(d: PatientDetail): RefinedTriage | null {
  if (!d.refined_esi_level) return null;
  const reasons = d.refined_safety_floor_reasons ?? [];
  const modelEsi = d.refined_model_esi_level ?? null;
  return {
    esi_level: d.refined_esi_level,
    confidence: d.refined_confidence ?? null,
    probabilities: parseJson<Record<string, number>>(d.refined_probabilities, {}),
    conformal_set: parseJson<number[]>(d.refined_conformal_set, [d.refined_esi_level]),
    conformal_q_hat: null,
    top_features: parseJson<RefinedTriage["top_features"]>(d.refined_top_features, []),
    source: d.refined_source ?? "",
    model_esi_level: modelEsi,
    model_confidence: d.refined_model_confidence ?? null,
    raised_by_safety_rules: reasons.length > 0 || (modelEsi != null && modelEsi > d.refined_esi_level),
    safety_floor_reasons: reasons,
    safety_rules_agree: d.refined_safety_rules_agree ?? [],
    starting_esi_level: modelEsi ?? d.esi_level,
    intake_esi_level: d.esi_level,
    model_conformal_set: d.refined_model_conformal_set ?? [],
    note: d.refined_note ?? null,
    model_card: d.refined_model_card ?? null,
  };
}

/** Bedside scores from the vitals the nurse entered. null where an input is missing. */
function riskScores(v: Vitals): { label: string; value: string | null }[] {
  const has = (x: number | null | undefined): x is number => typeof x === "number" && !Number.isNaN(x);
  const sbp = v.systolic_bp, hr = v.heart_rate, rr = v.respiratory_rate, t = v.temperature_c, spo2 = v.spo2;
  const altered =
    (has(v.gcs_total) && v.gcs_total < 15) ||
    ["confused", "drowsy", "agitated", "unresponsive"].includes(String(v.mental_status ?? ""));
  const shock = has(hr) && has(sbp) && sbp > 0 ? hr / sbp : null;
  const qsofa = has(sbp) && has(rr) ? Number(sbp <= 100) + Number(rr >= 22) + Number(altered) : null;
  const sirs = has(t) && has(hr) && has(rr) ? Number(t > 38 || t < 36) + Number(hr > 90) + Number(rr > 20) : null;
  const circ =
    has(sbp) && has(hr) && has(spo2) && shock != null
      ? Number(sbp < 90) + Number(hr > 100) + Number(shock > 1) + Number(spo2 < 94)
      : null;
  return [
    { label: "qSOFA (0 to 3)", value: qsofa == null ? null : String(qsofa) },
    { label: "SIRS vitals (0 to 3)", value: sirs == null ? null : String(sirs) },
    { label: "Shock index", value: shock == null ? null : shock.toFixed(2) },
    { label: "Circulation signs (0 to 4)", value: circ == null ? null : String(circ) },
  ];
}

// Rule codes the triage engine stores as clinical flags, in words a nurse reads at a glance.
const FLAG_TEXT: Record<string, string> = {
  "rule.esi1.life_threatening_keywords": "Life-threatening words in the complaint",
  "rule.esi1.catastrophic_trauma": "Severe injury or heavy bleeding described",
  "rule.esi1.stroke_symptoms": "Possible stroke signs described",
  "rule.esi2.high_risk_presentation": "High-risk complaint, such as chest pain or trouble breathing",
  "rule.esi2.crisis": "Suicidal thoughts or self-harm",
  "rule.esi2.chest_pain": "Chest pain or pressure",
  "rule.esi2.breathing": "Cannot breathe or very hard to breathe",
  "rule.esi2.airway_swelling": "Throat, lips, or tongue swelling (allergic reaction)",
  "rule.esi2.heavy_bleeding": "Heavy bleeding or bleeding that will not stop",
  "rule.esi2.pregnancy_bleeding": "Pregnant and bleeding",
  "rule.esi2.syncope": "Fainted, passed out, or collapsed",
  "rule.esi2.head_injury": "Head injury with confusion, vomiting, or passing out",
  "rule.esi2.stiff_neck_fever": "Stiff neck with fever or headache",
  "rule.esi2.child_fever_lethargy": "Child under 5 with fever who is very sleepy or hard to wake",
  "rule.esi2.infant_fever": "Baby under 3 months with a fever",
  "rule.esi2.overdose": "Overdose or poisoning",
  "rule.esi2.overdose_self": "Overdose or poisoning",
  "rule.esi2.seizure": "Seizure",
  "rule.esi2.one_sided_weakness": "One arm or one side weak or numb",
  "rule.esi3.needs_reading": "Written in a language the offline rules cannot fully read",
  needs_interpreter: "Needs someone to read their language",
  "rule.esi5.administrative": "Paperwork or refill request",
  "floor.esi1.unresponsive": "Unresponsive, or GCS 8 or below",
  "floor.esi2.danger_zone_vitals": "Danger-zone vital signs",
};

// The scribe note built without AI (services/scribe.py deterministic_note) starts with this line.
const NO_AI_NOTE_PREFIX = "Auto summary (no AI)";

function flagText(code: string, detail?: PatientDetail): string {
  // The rule that set the check-in score has its plain name stored on the record.
  if (detail?.triage_rule_name && detail.triage_source === `rule:${code}`) return detail.triage_rule_name;
  if (FLAG_TEXT[code]) return FLAG_TEXT[code];
  const m = code.match(/^(?:rule|floor)\.esi(\d)\.(.+)$/);
  const words = (m ? m[2] : code).replace(/[_.]+/g, " ").trim();
  const text = words.charAt(0).toUpperCase() + words.slice(1);
  return m ? `${text} (ESI ${m[1]} rule)` : text;
}

// Older records can still carry raw model context fields; they are never reasons for a score.
const HIDDEN_FACTOR = /^(triage_nurse_id|site_id|arrival_|shift|hour_|is_night|is_weekend|transport_origin|insurance_type|language|miss_|total_missing|num_prior_|ngram)/;

type Props = {
  detail: PatientDetail;
  hospitalId: string;
  authenticated: boolean;
  showScribeLink?: boolean;
  onDetailChange: (updater: (d: PatientDetail | null) => PatientDetail | null) => void;
  onAfterMarkSeen: () => void | Promise<void>;
};

/**
 * The full clinical detail JSX shared between the dashboard drawer and the
 * full-page patient view. Everything inside this component assumes `detail`
 * is loaded.
 */
export function PatientDetailBody({
  detail,
  hospitalId,
  authenticated,
  showScribeLink = true,
  onDetailChange,
  onAfterMarkSeen,
}: Props) {
  const refined = refinedFromDetail(detail);
  const intakeFactors = Object.entries(detail.shap_values ?? {})
    .filter(([name]) => !HIDDEN_FACTOR.test(name))
    .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
    .slice(0, 8);
  const maxFactor = Math.max(...intakeFactors.map(([, v]) => Math.abs(v)), 0) || 1;
  const measuredVitals = detail.measured_vitals ? parseJson<Vitals>(detail.measured_vitals, {}) : null;
  const measuredScores = measuredVitals ? riskScores(measuredVitals) : null;
  const checkinModel = detail.checkin_model_esi_level ?? null;
  const checkinByRules = Boolean(detail.checkin_set_by_rules);
  const checkinNote = checkinByRules
    ? [
        checkinModel != null && checkinModel !== detail.esi_level
          ? `At check-in the model guessed ESI ${checkinModel}.`
          : null,
        detail.checkin_rule_name
          ? `The safety rules set ESI ${detail.esi_level}: ${detail.checkin_rule_name.charAt(0).toLowerCase()}${detail.checkin_rule_name.slice(1)}.`
          : `The safety rules set ESI ${detail.esi_level}.`,
      ]
        .filter(Boolean)
        .join(" ")
    : null;
  const checkinBand = bandRange(detail.confidence_band);
  // The check-in factors explain the model's own pick (SHAP for that score). The
  // rules-only engine instead lists risk factors, which only ever add urgency.
  const factorEsi = checkinModel ?? detail.esi_level;
  const engineFactors = detail.triage_source === "triageist_simulation";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm text-text-muted">
          {waitLabel(detail.waited_minutes)} · {detail.language.toUpperCase()}
        </div>
        {showScribeLink && (
          <Link
            to={`/${hospitalId}/clinician/patient/${detail.patient_id}/scribe`}
            className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md bg-primary text-white text-sm font-semibold hover:opacity-90"
            title="Open the ambient scribe bound to this patient"
          >
            <Mic size={14} /> Open scribe
          </Link>
        )}
      </div>

      {/* Check-in score next to the bedside re-check; the queue acts on the re-check. */}
      <div className="bg-surface-lowest rounded-xl p-4 ring-1 ring-line/45">
        <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold mb-2">
          Triage score
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col gap-0.5">
            <div className="text-[12px] uppercase tracking-wider text-text-muted">At check-in</div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-primary">ESI {detail.esi_level}</span>
              {detail.checkin_set_by_rules ? (
                <span className="text-xs font-medium text-warning" title={detail.checkin_rule_name ?? undefined}>
                  set by safety rules
                </span>
              ) : (
                detail.esi_confidence != null && <ModelSure p={detail.esi_confidence} />
              )}
            </div>
          </div>
          <div className="text-xl text-text-muted mx-1" aria-hidden="true">→</div>
          <div className="flex flex-col gap-0.5">
            <div className="text-[12px] uppercase tracking-wider text-text-muted">
              {refined ? "Bedside re-check" : "Bedside re-check, waiting for vitals"}
            </div>
            <div className="flex items-baseline gap-2">
              {refined ? (
                <>
                  <span className="text-2xl font-bold text-primary">ESI {refined.esi_level}</span>
                  {refined.raised_by_safety_rules ? (
                    <span className="text-xs font-medium text-warning">raised by safety rules</span>
                  ) : (
                    refined.confidence != null && <ModelSure p={refined.confidence} />
                  )}
                </>
              ) : (
                <span className="text-base text-text-muted italic">enter vitals below</span>
              )}
            </div>
          </div>
        </div>
        {checkinNote && <p className="text-[12px] leading-relaxed text-text-muted mt-2">{checkinNote}</p>}
        {!checkinByRules && detail.esi_confidence != null && (
          <p className="text-[12px] leading-relaxed text-text-muted mt-2">
            {checkinBand && checkinBand[0] !== checkinBand[1]
              ? `Likely range: ESI ${checkinBand[0]} to ${checkinBand[1]}. `
              : ""}
            The model&rsquo;s &ldquo;sure&rdquo; number comes from training on made-up visits. It is not
            how often the model is right with real patients.
          </p>
        )}
      </div>

      <div className="bg-primary-fixed/40 rounded-lg p-4">
        <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold mb-1">
          Pre-brief
        </div>
        <div className="text-[15px] leading-relaxed text-ink">{detail.clinician_prebrief}</div>
      </div>

      {detail.clinical_scribe_note && (
        <Section title="Check-in note">
          <div className="mb-2">
            {detail.clinical_scribe_note.trimStart().startsWith(NO_AI_NOTE_PREFIX) ? (
              <AiSourceTag ai={false} label="Built without AI" />
            ) : (
              <AiSourceTag ai />
            )}
          </div>
          <div className="bg-surface-low rounded-lg p-4 text-[14px] leading-relaxed whitespace-pre-wrap text-ink">
            {detail.clinical_scribe_note}
          </div>
        </Section>
      )}

      {detail.clinical_flags.length > 0 && (
        <Section title="Clinical flags">
          <div className="flex flex-wrap gap-2">
            {detail.clinical_flags.map((f) => (
              <span key={f} title={f} className="px-2.5 py-1 rounded-full text-xs font-medium bg-error/10 text-error">
                {flagText(f, detail)}
              </span>
            ))}
          </div>
        </Section>
      )}

      {measuredScores ? (
        <Section title="Risk scores · from measured vitals">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm">
            {measuredScores.map(({ label, value }) => (
              <div key={label} className="bg-surface-lowest rounded-xl p-3 ring-1 ring-line/45">
                <div className="text-[12px] uppercase tracking-wider text-text-muted">{label}</div>
                <div className="text-lg font-bold tracking-editorial text-ink mt-0.5">{value ?? "-"}</div>
              </div>
            ))}
          </div>
          <p className="text-[12px] text-text-muted mt-1.5">A dash means a vital needed for that score was not entered.</p>
        </Section>
      ) : (
        <Section title="Risk scores">
          <div className="bg-surface-lowest rounded-lg p-4 text-[13px] text-text-muted shadow-soft italic">
            Waiting for bedside vitals. Enter heart rate, blood pressure, breathing rate and oxygen level below, then re-check the score.
          </div>
        </Section>
      )}

      {detail.triage_recommendation && (
        <Section title="Recommended next steps">
          <div className="bg-surface-lowest rounded-lg p-4 text-[14px] leading-relaxed shadow-soft">
            {detail.triage_recommendation}
          </div>
        </Section>
      )}

      {detail.differential && detail.differential.length > 0 && (
        <DifferentialPanel entries={detail.differential} />
      )}

      {detail.workup_orders && <WorkupPanel orders={detail.workup_orders} />}

      {detail.disposition && <DispositionPanel disposition={detail.disposition} />}

      <Section title="Patient's words">
        <div className="bg-surface-low rounded-lg p-4 text-[14px] leading-relaxed whitespace-pre-wrap text-ink italic">
          "{detail.transcript}"
        </div>
      </Section>

      {detail.followup_qa.length > 0 && (
        <Section title="Follow-up Q&A">
          <div className="flex flex-col gap-2">
            {detail.followup_qa.map((qa, i) => (
              <div key={i} className="text-sm">
                <span className="text-text-muted">Q: </span>
                <span className="font-medium">{qa.question}</span>
                <br />
                <span className="text-text-muted">A: </span>
                <span className="font-mono">{qa.answer}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {detail.medical_info && (
        <Section title="Reported history">
          <div className="text-sm leading-relaxed text-ink">{formatMedicalInfo(detail.medical_info)}</div>
        </Section>
      )}

      {detail.insurance_info && (
        <Section title="Insurance">
          <div className="bg-surface-lowest rounded-xl p-4 ring-1 ring-line/45 flex flex-col gap-2">
            {detail.insurance_info.provider && <InsRow label="Insurer" value={detail.insurance_info.provider} primary />}
            {detail.insurance_info.plan_name && <InsRow label="Plan" value={detail.insurance_info.plan_name} />}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              {detail.insurance_info.member_id && <InsRow label="Member ID" value={detail.insurance_info.member_id} mono />}
              {detail.insurance_info.group_number && <InsRow label="Group" value={detail.insurance_info.group_number} mono />}
              {detail.insurance_info.name_on_card && <InsRow label="Name on card" value={detail.insurance_info.name_on_card} />}
              {detail.insurance_info.effective_date && <InsRow label="Effective" value={detail.insurance_info.effective_date} mono />}
              {detail.insurance_info.bin && <InsRow label="BIN" value={detail.insurance_info.bin} mono />}
              {detail.insurance_info.pcn && <InsRow label="PCN" value={detail.insurance_info.pcn} mono />}
              {detail.insurance_info.rx_group && <InsRow label="Rx group" value={detail.insurance_info.rx_group} mono />}
              {detail.insurance_info.phone && <InsRow label="Phone" value={detail.insurance_info.phone} mono />}
            </div>
          </div>
        </Section>
      )}

      <VitalsPanel
        hospitalId={hospitalId}
        patientId={detail.patient_id}
        existing={refined}
        initialVitals={measuredVitals}
        onRefined={(r, v) =>
          onDetailChange((d) =>
            d
              ? {
                  ...d,
                  refined_esi_level: r.esi_level,
                  refined_confidence: r.confidence,
                  refined_probabilities: JSON.stringify(r.probabilities),
                  refined_conformal_set: JSON.stringify(r.conformal_set),
                  refined_top_features: JSON.stringify(r.top_features),
                  refined_source: r.source,
                  refined_model_esi_level: r.model_esi_level ?? null,
                  refined_model_confidence: r.model_confidence ?? null,
                  refined_safety_floor_reasons: r.safety_floor_reasons ?? [],
                  refined_safety_rules_agree: r.safety_rules_agree ?? [],
                  refined_model_conformal_set: r.model_conformal_set ?? [],
                  refined_model_card: r.model_card ?? null,
                  refined_note: r.note ?? null,
                  current_esi_level: r.esi_level,
                  measured_vitals: JSON.stringify(
                    Object.fromEntries(Object.entries(v).filter(([, x]) => x != null && x !== "")),
                  ),
                }
              : d,
          )
        }
      />

      <NotesPanel
        hospitalId={hospitalId}
        patientId={detail.patient_id}
        initialNotes={detail.notes}
        initialEducation={detail.patient_education}
        publishedAt={detail.patient_education_published_at}
      />

      <PrescriptionPanel
        hospitalId={hospitalId}
        patientId={detail.patient_id}
        medicalInfo={detail.medical_info}
      />

      {detail.photo_url && (
        <Section title="Photo">
          <img src={detail.photo_url} alt="Injury" className="max-w-full rounded-lg shadow-soft" />
          {detail.photo_analysis?.description && (
            <p className="text-sm text-ink mt-2">{detail.photo_analysis.description}</p>
          )}
        </Section>
      )}

      {intakeFactors.length > 0 && (
        <Section
          title={
            engineFactors
              ? `What raised the check-in score of ESI ${detail.esi_level}`
              : checkinByRules && checkinModel != null && checkinModel !== detail.esi_level
                ? `What made the model's check-in guess of ESI ${checkinModel} more or less likely`
                : `What made the model's check-in score of ESI ${detail.esi_level} more or less likely`
          }
        >
          <div className="flex flex-col gap-1.5 text-[12px]">
            {intakeFactors.map(([feature, value]) => {
              const up = value >= 0;
              const word = engineFactors
                ? up ? "more urgent" : "less urgent"
                : `ESI ${factorEsi} ${up ? "more" : "less"} likely`;
              return (
                <div key={feature} className="flex items-center gap-2" title={`${feature}: ${word} (${value.toFixed(3)})`}>
                  <span className="flex-1 min-w-0 truncate text-ink">{feature}</span>
                  <div className="w-16 sm:w-40 shrink-0 h-3 bg-surface-low rounded-sm relative overflow-hidden">
                    <div
                      className={`h-full rounded-sm ${up ? "bg-primary" : "bg-secondary/50"}`}
                      style={{ width: `${(Math.abs(value) / maxFactor) * 100}%` }}
                    />
                  </div>
                  <span className={`shrink-0 w-[7.5rem] text-right whitespace-nowrap ${up ? "text-primary" : "text-text-muted"}`}>
                    {word}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="text-[12px] text-text-muted mt-2">
            {engineFactors
              ? "Longer bars mattered more. "
              : `Longer bars mattered more. These bars explain the model's guess of ESI ${factorEsi} only: "less likely" does not say whether the patient is more or less urgent, and the safety rules can still raise the score. `}
            Arrival time, site and other paperwork fields are left out because they say nothing about
            the patient.
          </p>
          {detail.triage_source === "heuristic_stub" && (
            <p className="text-xs text-text-muted mt-1 italic">
              These factors are estimated. Bedside vitals will sharpen them.
            </p>
          )}
        </Section>
      )}

      <div className="flex flex-col gap-2">
        <Button
          variant="primary"
          fullWidth
          onClick={async () => {
            if (!authenticated) return;
            await markSeen(hospitalId, detail.patient_id, "Clinician");
            await onAfterMarkSeen();
          }}
        >
          Mark Seen
        </Button>
      </div>
    </div>
  );
}
