import { useState } from "react";
import { Activity, Info, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { refineTriage } from "../../lib/api";
import { useCapabilities } from "../../lib/capabilities";
import type { RefinedTriage, Vitals } from "../../types";

type Props = {
  hospitalId: string;
  patientId: string;
  existing?: RefinedTriage | null;
  /** The vitals from the last re-check, so the form starts filled in after a reload. */
  initialVitals?: Vitals | null;
  onRefined?: (r: RefinedTriage, v: Vitals) => void;
};

const FIELDS: { key: keyof Vitals; label: string; placeholder: string; step?: string }[] = [
  { key: "heart_rate", label: "Heart rate (beats per minute)", placeholder: "80", step: "1" },
  { key: "systolic_bp", label: "Blood pressure, top number", placeholder: "120", step: "1" },
  { key: "diastolic_bp", label: "Blood pressure, bottom number", placeholder: "80", step: "1" },
  { key: "respiratory_rate", label: "Breaths per minute", placeholder: "16", step: "1" },
  { key: "temperature_c", label: "Temperature (°C or °F)", placeholder: "37.0", step: "0.1" },
  { key: "spo2", label: "Oxygen level (SpO₂ %)", placeholder: "98", step: "1" },
  { key: "gcs_total", label: "GCS (3 to 15)", placeholder: "15", step: "1" },
  { key: "pain_score", label: "Pain (0 to 10)", placeholder: "3", step: "1" },
];

const MENTAL_STATUS: { value: string; label: string }[] = [
  { value: "alert", label: "Alert" },
  { value: "confused", label: "Confused" },
  { value: "drowsy", label: "Drowsy" },
  { value: "agitated", label: "Agitated" },
  { value: "unresponsive", label: "Unresponsive" },
];

const pct = (p: number | null | undefined) => (p == null ? null : Math.round(p * 100));

/** A temperature over 50 can only be Fahrenheit; the server takes Celsius. */
function toCelsius(t: number | null | undefined): { value: number | null | undefined; fromF: number | null } {
  if (typeof t !== "number" || Number.isNaN(t) || t <= 50) return { value: t, fromF: null };
  return { value: Math.round(((t - 32) * 5) / 9 * 10) / 10, fromF: t };
}

/** The sentence that explains the final score. Never puts a percentage next to a score the model did not pick. */
function Verdict({ r }: { r: RefinedTriage }) {
  const reasons = r.safety_floor_reasons ?? [];
  const rulesOnly = r.model_esi_level == null;
  const raised = r.raised_by_safety_rules ?? (reasons.length > 0 || (r.model_esi_level ?? r.esi_level) > r.esi_level);
  const modelPct = pct(r.model_confidence ?? r.confidence);

  if (raised) {
    const start = rulesOnly
      ? `The check-in score was ESI ${r.starting_esi_level ?? r.intake_esi_level ?? "?"}.`
      : `The model guessed ESI ${r.model_esi_level}${modelPct != null ? ` (model ${modelPct}% sure, trained on made-up data)` : ""}.`;
    return (
      <div className="flex gap-2.5 rounded-lg bg-warning-container/70 p-3 text-[13px] leading-relaxed text-ink">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        <p>
          {start} Safety rules raised it to <strong>ESI {r.esi_level}</strong>
          {reasons.length > 0 ? <> because: {reasons.join("; ")}.</> : "."}
        </p>
      </div>
    );
  }
  const agree = r.safety_rules_agree ?? [];
  const agreeText = agree.length > 0 ? ` The safety rules agree with ESI ${r.esi_level}: ${agree.join("; ")}.` : "";
  if (rulesOnly) {
    return (
      <p className="text-[13px] leading-relaxed text-text-muted">
        {agree.length > 0
          ? `The check-in score was ESI ${r.esi_level}, and the safety rules keep it there: ${agree.join("; ")}.`
          : `No safety rule raised the check-in score of ESI ${r.esi_level}.`}
      </p>
    );
  }
  return (
    <p className="text-[13px] leading-relaxed text-text-muted">
      The model picked ESI {r.esi_level}
      {modelPct != null ? ` (model ${modelPct}% sure, trained on made-up data)` : ""}
      {agree.length > 0 ? "." : ", and no safety rule raised it."}
      {agreeText}
    </p>
  );
}

function ProbabilityTiles({ r }: { r: RefinedTriage }) {
  const modelPick = r.model_esi_level ?? r.esi_level;
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-text-muted">How sure the model was about each score</div>
      <div className="grid grid-cols-5 gap-1">
        {[1, 2, 3, 4, 5].map((esi) => {
          const p = r.probabilities[String(esi)] ?? 0;
          const isModel = esi === modelPick;
          const isFinal = esi === r.esi_level && !isModel;
          return (
            <div
              key={esi}
              className={`rounded-md p-2 text-center text-xs ${
                isModel ? "bg-primary text-white" : "bg-surface-low text-text-muted"
              } ${isFinal ? "ring-2 ring-warning" : ""}`}
            >
              <div className="font-semibold">ESI {esi}</div>
              <div className="mt-0.5 font-mono">{(p * 100).toFixed(1)}%</div>
              {(isModel || isFinal) && (
                <div className="mt-0.5 text-[12px] font-medium">{isModel ? "model's pick" : "final"}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Factors({ r }: { r: RefinedTriage }) {
  const items = r.top_features.slice(0, 5);
  if (items.length === 0) return null;
  const modelPick = r.model_esi_level ?? r.esi_level;
  const maxAbs = Math.max(...items.map((f) => Math.abs(f.shap ?? f.weight ?? 0))) || 1;
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-text-muted">
        What made the model&rsquo;s guess of ESI {modelPick} more or less likely
      </div>
      <ul className="space-y-1.5">
        {items.map((f) => {
          const val = f.shap ?? f.weight ?? 0;
          const toward = f.direction ? f.direction === "increases" : val > 0;
          const showValue = f.kind === "measure";
          const word = `ESI ${modelPick} ${toward ? "more" : "less"} likely`;
          return (
            <li key={f.code ?? f.feature} className="flex items-center gap-2" title={`${f.feature}: ${word}`}>
              <span className="min-w-0 flex-1 truncate text-[12px] text-ink">
                {f.feature}
                {showValue && <span className="text-text-muted">: {Number(f.value.toFixed(1))}</span>}
              </span>
              <div className="relative h-2 w-14 sm:w-28 shrink-0 overflow-hidden rounded bg-surface-low">
                <div
                  className={`absolute left-0 top-0 h-full rounded ${toward ? "bg-primary" : "bg-secondary/50"}`}
                  style={{ width: `${(Math.abs(val) / maxAbs) * 100}%` }}
                />
              </div>
              <span className={`shrink-0 w-[7.5rem] whitespace-nowrap text-right text-[12px] ${toward ? "text-primary" : "text-text-muted"}`}>
                {word}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[12px] leading-relaxed text-text-muted">
        These bars explain the model&rsquo;s guess only. &ldquo;Less likely&rdquo; does not say more or
        less urgent, and the safety rules above can still raise the score.
      </p>
    </div>
  );
}

function ModelCardDetails({ r }: { r: RefinedTriage }) {
  const card = r.model_card;
  if (!card) {
    // Rules-only re-check: say what ran instead of a model card.
    return (
      <details className="rounded-lg bg-surface-low/60 p-3">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-[12px] font-semibold text-primary">
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          About this re-check
        </summary>
        <p className="mt-2.5 text-[12px] leading-relaxed text-text-muted">
          The safety rules are fixed checks taken from the ESI triage handbook. For example, a heart
          rate over 100, a top blood pressure number under 90, or an oxygen level under 92% makes the
          score at least ESI 2. They can raise the score, never lower it. No trained model ran.
        </p>
      </details>
    );
  }
  const range = r.model_conformal_set ?? [];
  return (
    <details className="rounded-lg bg-surface-low/60 p-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[12px] font-semibold text-primary">
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
        About this model
      </summary>
      <div className="mt-2.5 space-y-2 text-[12px] leading-relaxed text-text-muted">
        <p>
          <span className="font-semibold text-ink">Trained on:</span> {card.dataset}
        </p>
        <p>{card.accuracy_note}</p>
        <details>
          <summary className="cursor-pointer text-[12px] font-medium text-primary">Technical details</summary>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12px]">
            {card.technical.map((t) => (
              <li key={t}>{t}</li>
            ))}
            {range.length > 0 && (
              <li>
                Likely range for this patient: ESI {range.join(", ")}.{card.range_note ? ` ${card.range_note}` : ""}
              </li>
            )}
            <li>Result source: {r.source}</li>
          </ul>
        </details>
      </div>
    </details>
  );
}

function startingVitals(v: Vitals | null | undefined): Vitals {
  const numbers: Vitals = { ...(v ?? {}) };
  delete numbers.mental_status; // has its own select
  return numbers;
}

export function VitalsPanel({ hospitalId, patientId, existing, initialVitals, onRefined }: Props) {
  const caps = useCapabilities(hospitalId);
  const [vitals, setVitals] = useState<Vitals>(() => startingVitals(initialVitals));
  const [mentalStatus, setMentalStatus] = useState<string>(initialVitals?.mental_status || "alert");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [converted, setConverted] = useState<string | null>(null);
  const [result, setResult] = useState<RefinedTriage | null>(existing ?? null);

  function update<K extends keyof Vitals>(key: K, raw: string) {
    const num = raw === "" ? null : Number(raw);
    setVitals((v) => ({ ...v, [key]: isNaN(num as number) ? null : num }));
  }

  async function submit() {
    setLoading(true);
    setError(null);
    setConverted(null);
    try {
      const temp = toCelsius(vitals.temperature_c);
      const payload: Vitals = { ...vitals, temperature_c: temp.value, mental_status: mentalStatus };
      const refined = await refineTriage(hospitalId, patientId, payload);
      if (temp.fromF != null) {
        setVitals((v) => ({ ...v, temperature_c: temp.value }));
        setConverted(`Converted ${temp.fromF} °F to ${temp.value} °C.`);
      }
      setResult(refined);
      onRefined?.(refined, payload);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(
        typeof detail === "string" && detail
          ? detail
          : "The re-check did not go through. Check the numbers and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  const modelMissing = caps != null && !caps.triage_model.loaded;
  const rulesOnlyResult = result != null && result.model_esi_level == null;

  return (
    <div className="rounded-2xl bg-surface-lowest p-5 shadow-soft">
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-primary">
        <Activity className="h-4 w-4" aria-hidden="true" />
        Bedside vitals and re-check
      </div>
      <p className="mb-3 text-[12px] leading-relaxed text-text-muted">
        {modelMissing
          ? "The trained model is not installed on this server, so the re-check uses the safety rules only. They start from the check-in score and can raise it, never lower it."
          : "The trained model makes a guess from these vitals, then the safety rules get the last word. They can raise the score, never lower it."}
      </p>

      <div className="grid grid-cols-2 gap-3">
        {FIELDS.map(({ key, label, placeholder, step }) => (
          <label key={key} className="flex flex-col gap-1 text-xs text-text-muted">
            <span>{label}</span>
            <input
              type="number"
              inputMode="decimal"
              step={step || "any"}
              placeholder={placeholder}
              value={(vitals[key] as number | null | undefined) ?? ""}
              onChange={(e) => update(key, e.target.value)}
              className="rounded-md border border-line bg-surface-low px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
        ))}
        <label className="col-span-2 flex flex-col gap-1 text-xs text-text-muted">
          <span>Mental status</span>
          <select
            value={mentalStatus}
            onChange={(e) => setMentalStatus(e.target.value)}
            className="rounded-md border border-line bg-surface-low px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-primary/30"
          >
            {MENTAL_STATUS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <button
        onClick={submit}
        disabled={loading}
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-primary-hover disabled:opacity-60"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
        {loading ? "Checking…" : result ? "Re-check again" : "Re-check the score"}
      </button>

      {error && (
        <p className="mt-3 text-xs text-error" role="alert">
          {error}
        </p>
      )}
      {converted && !error && <p className="mt-2 text-[12px] text-text-muted">{converted}</p>}

      {result && (
        <div className="mt-5 space-y-4 border-t border-line pt-4" aria-live="polite">
          <div className="flex items-baseline gap-3">
            <div className="text-3xl font-semibold tracking-tight text-primary">ESI {result.esi_level}</div>
            <div className="text-sm text-text-muted">
              {rulesOnlyResult ? "from the safety rules (model not installed)" : "bedside score"}
            </div>
          </div>

          <Verdict r={result} />

          {rulesOnlyResult && result.note && (
            <p className="text-[12px] leading-relaxed text-text-muted">{result.note}</p>
          )}

          {Object.keys(result.probabilities).length > 0 && <ProbabilityTiles r={result} />}
          <Factors r={result} />
          <ModelCardDetails r={result} />
        </div>
      )}
    </div>
  );
}
