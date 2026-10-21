import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Activity, Loader2, RefreshCw, TrendingUp } from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import { AiSourceTag } from "../AiStatus";
import { apiErrorMessage, deteriorationIndex, sepsisEws } from "../../../lib/api";
import type { EwsContribution, EwsResult, SepsisEwsResult } from "../../../lib/api";
import type { Vitals } from "../../../types";

/**
 * Early warning scores for the patient in front of you.
 *
 * Two fixed formulas (no AI): a sepsis warning score and a deterioration index.
 * Vitals start from the chart and can be changed here for this score only; the
 * card also asks for the things a chart cannot know (lab values, oxygen,
 * suspected infection). Missing inputs are listed rather than filled with normal
 * values, so a score built on blanks never looks more certain than it is.
 */

/** `measured_vitals` is stored as a JSON string of the Vitals shape. */
function parseVitals(raw: string | null | undefined): Vitals | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Vitals;
    return v && typeof v === "object" ? v : null;
  } catch {
    return null;
  }
}

type VitalKey = "hr" | "rr" | "sbp" | "spo2" | "temp_c" | "gcs";

const VITAL_FIELDS: { key: VitalKey; label: string; chart: keyof Vitals; step: string }[] = [
  { key: "hr", label: "Heart rate", chart: "heart_rate", step: "1" },
  { key: "rr", label: "Breathing rate", chart: "respiratory_rate", step: "1" },
  { key: "sbp", label: "Blood pressure, top number", chart: "systolic_bp", step: "1" },
  { key: "spo2", label: "Oxygen level (%)", chart: "spo2", step: "1" },
  { key: "temp_c", label: "Temperature (°C)", chart: "temperature_c", step: "0.1" },
  { key: "gcs", label: "Alertness (GCS 3 to 15)", chart: "gcs_total", step: "1" },
];

// Plain names for the factors each formula reports.
const FACTOR_LABEL: Record<string, string> = {
  hr: "Heart rate",
  hr_abs: "Very fast heart rate",
  hr_trend: "Heart rate rising",
  rr: "Breathing rate",
  spo2: "Low oxygen level",
  oxygen: "On extra oxygen",
  on_o2: "On extra oxygen",
  new_o2: "Newly needs oxygen",
  sbp: "Blood pressure",
  sbp_abs: "Low blood pressure",
  sbp_trend: "Blood pressure falling",
  temp: "Temperature",
  mental_status: "Alertness",
  wbc: "White blood cell count",
  wbc_trend: "White blood cell count changing",
  lactate: "Lactate",
  arrhythmia: "New irregular heartbeat",
  nursing_signals: "Nursing concerns",
  aki_creatinine: "Kidney function worse",
};

function factorLabel(feature: string): string {
  return FACTOR_LABEL[feature] ?? feature.replace(/_/g, " ");
}

const BAND_TONE: Record<string, string> = {
  low: "bg-success/15 text-success ring-success/30",
  moderate: "bg-warning/15 text-warning ring-warning/30",
  medium: "bg-warning/15 text-warning ring-warning/30",
  elevated: "bg-warning/15 text-warning ring-warning/30",
  high: "bg-error/15 text-error ring-error/30",
  critical: "bg-error text-white ring-error",
};

function bandTone(band: string): string {
  return BAND_TONE[(band || "").toLowerCase()] || "bg-surface-low text-ink ring-line";
}

function ScoreCard({
  title,
  Icon,
  result,
}: {
  title: string;
  Icon: typeof Activity;
  result: EwsResult | SepsisEwsResult;
}) {
  const contributions = Array.isArray(result.contributions) ? result.contributions : [];
  return (
    <div className="rounded-lg bg-surface-lowest shadow-card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-wider text-text-muted font-semibold">
          <Icon className="w-3.5 h-3.5" aria-hidden />
          {title}
        </div>
        <span
          className={`text-[12px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded ring-1 ${bandTone(result.band)}`}
        >
          {result.band}
        </span>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-bold tracking-editorial text-ink">{result.score}</span>
        <span className="text-xs text-text-muted">points</span>
      </div>

      {result.action && <p className="text-sm text-ink leading-relaxed">{result.action}</p>}

      {contributions.length > 0 ? (
        <div className="divide-y divide-line">
          {contributions.map((c: EwsContribution, i: number) => (
            <div key={i} className="py-1.5 first:pt-0 text-sm">
              <div className="flex justify-between gap-3">
                <span className="text-ink">{factorLabel(c.feature)}</span>
                <span className="font-semibold text-ink shrink-0">+{c.points}</span>
              </div>
              <div className="text-xs text-text-muted mt-0.5">{c.why}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-text-muted">No warning signs in the values given.</p>
      )}

      {"calibration_note" in result && result.calibration_note && (
        <p className="text-[12px] text-text-muted leading-relaxed border-t border-line pt-2">
          {result.calibration_note}
        </p>
      )}
    </div>
  );
}

export default function EarlyWarningTab() {
  const { hospitalId, patientId, patient, loading, error } = usePatientWorkspace();

  // Vitals typed here override the chart for this score only.
  const [edits, setEdits] = useState<Partial<Record<VitalKey, string>>>({});
  const [wbc, setWbc] = useState<string>("");
  const [lactate, setLactate] = useState<string>("");
  const [onOxygen, setOnOxygen] = useState(false);
  const [suspectedInfection, setSuspectedInfection] = useState(false);

  const [sepsis, setSepsis] = useState<SepsisEwsResult | null>(null);
  const [deterioration, setDeterioration] = useState<EwsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [sepsisError, setSepsisError] = useState<string | null>(null);
  const [detError, setDetError] = useState<string | null>(null);

  // A different patient starts clean.
  useEffect(() => {
    setEdits({});
    setWbc("");
    setLactate("");
    setOnOxygen(false);
    setSuspectedInfection(false);
    setSepsis(null);
    setDeterioration(null);
    setSepsisError(null);
    setDetError(null);
  }, [patientId]);

  const chart = useMemo(() => parseVitals(patient?.measured_vitals), [patient?.measured_vitals]);

  const shown = useMemo(() => {
    const out = {} as Record<VitalKey, string>;
    for (const f of VITAL_FIELDS) {
      const typed = edits[f.key];
      const fromChart = chart?.[f.chart];
      out[f.key] = typed ?? (typeof fromChart === "number" ? String(fromChart) : "");
    }
    return out;
  }, [edits, chart]);

  const payload = useMemo(() => {
    const num = (s: string) => {
      if (s.trim() === "") return undefined;
      const n = Number(s);
      return Number.isFinite(n) ? n : undefined;
    };
    const vitals: Partial<Record<VitalKey, number>> = {};
    for (const f of VITAL_FIELDS) {
      const n = num(shown[f.key]);
      if (n !== undefined) vitals[f.key] = n;
    }
    return {
      vitals,
      wbc: num(wbc),
      lactate: num(lactate),
      mental_status: chart?.mental_status ?? undefined,
    };
  }, [shown, wbc, lactate, chart]);

  const hasAnyVital = Object.keys(payload.vitals).length > 0;

  /** Inputs the formulas use that we still have nothing for. */
  const missing = useMemo(() => {
    const labels: [string, boolean][] = [
      ["heart rate", payload.vitals.hr === undefined],
      ["breathing rate", payload.vitals.rr === undefined],
      ["temperature", payload.vitals.temp_c === undefined],
      ["blood pressure", payload.vitals.sbp === undefined],
      ["oxygen level", payload.vitals.spo2 === undefined],
      ["white blood cell count", payload.wbc === undefined],
      ["lactate", payload.lactate === undefined],
    ];
    return labels.filter(([, m]) => m).map(([l]) => l);
  }, [payload]);

  const run = useCallback(async () => {
    setSepsisError(null);
    setDetError(null);
    // A score built on nothing would read as "low risk", so ask for an input first.
    if (!hasAnyVital && payload.wbc === undefined && payload.lactate === undefined) {
      setSepsis(null);
      setDeterioration(null);
      setSepsisError("Enter at least one vital sign or lab value above, then work out the scores.");
      return;
    }
    setBusy(true);
    const flat = {
      ...payload.vitals,
      wbc: payload.wbc,
      lactate: payload.lactate,
      mental_status: payload.mental_status,
      on_oxygen: onOxygen,
    };
    const [s, d] = await Promise.allSettled([
      sepsisEws(hospitalId, { ...flat, suspected_infection: suspectedInfection }),
      hasAnyVital
        ? // Flat fields for the current server, `vitals_now` for older ones.
          deteriorationIndex(hospitalId, { ...flat, vitals_now: payload.vitals, wbc_now: payload.wbc })
        : Promise.reject(new Error("no_vitals")),
    ]);
    if (s.status === "fulfilled") setSepsis(s.value);
    else {
      setSepsis(null);
      setSepsisError(apiErrorMessage(s.reason, "Could not work out the sepsis score. Please try again."));
    }
    if (d.status === "fulfilled") setDeterioration(d.value);
    else {
      setDeterioration(null);
      setDetError(
        hasAnyVital
          ? apiErrorMessage(d.reason, "Could not work out the deterioration score. Please try again.")
          : "Enter at least one vital sign above to score deterioration.",
      );
    }
    setBusy(false);
  }, [hospitalId, payload, onOxygen, suspectedInfection, hasAnyVital]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-10 justify-center text-text-muted text-sm" role="status">
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> Loading patient…
      </div>
    );
  }
  if (error || !patient) {
    return (
      <div className="py-6 text-sm text-error" role="alert">
        {error || "Patient record unavailable."}
      </div>
    );
  }

  const inputClass =
    "w-full h-9 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-2 focus:ring-primary text-sm text-ink outline-none transition-all";
  const labelClass = "text-[12px] uppercase tracking-wider text-text-muted font-semibold";

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface-lowest shadow-card p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className={labelClass}>Inputs</div>
          <AiSourceTag ai={false} label="Fixed formulas, no AI" />
        </div>

        <p className="text-[13px] text-text-muted leading-snug">
          {chart
            ? "Vitals come from the chart. Change a number here to try it in the score; the chart stays the same."
            : "No vitals on the chart yet. Type them here, or record them on the patient summary."}
        </p>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          {VITAL_FIELDS.map((f) => (
            <label key={f.key} className="flex flex-col gap-1">
              <span className={labelClass}>{f.label}</span>
              <input
                type="number"
                inputMode="decimal"
                step={f.step}
                value={shown[f.key]}
                onChange={(e) => setEdits((prev) => ({ ...prev, [f.key]: e.target.value }))}
                placeholder="not taken"
                className={inputClass}
              />
            </label>
          ))}
          <label className="flex flex-col gap-1">
            <span className={labelClass}>White cells (WBC)</span>
            <input
              type="number"
              inputMode="decimal"
              step="0.1"
              value={wbc}
              onChange={(e) => setWbc(e.target.value)}
              placeholder="not drawn"
              className={inputClass}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Lactate</span>
            <input
              type="number"
              inputMode="decimal"
              step="0.1"
              value={lactate}
              onChange={(e) => setLactate(e.target.value)}
              placeholder="not drawn"
              className={inputClass}
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={suspectedInfection}
              onChange={(e) => setSuspectedInfection(e.target.checked)}
            />
            Infection suspected
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={onOxygen}
              onChange={(e) => setOnOxygen(e.target.checked)}
            />
            On extra oxygen
          </label>
        </div>

        {missing.length > 0 && (
          <div className="flex items-start gap-2 rounded-md bg-warning-container/40 p-2.5 text-[12px] text-ink leading-relaxed">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-warning mt-0.5" aria-hidden />
            <span>
              Scoring without {missing.join(", ")}. A missing value adds no points, so treat the
              result as a lowest estimate, not a full check.
            </span>
          </div>
        )}

        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="self-start inline-flex items-center gap-1.5 h-9 px-4 rounded-md bg-primary text-white text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" aria-hidden />
          )}
          {sepsis || deterioration ? "Score again" : "Work out the scores"}
        </button>
      </div>

      {sepsis ? (
        <ScoreCard title="Sepsis warning score" Icon={Activity} result={sepsis} />
      ) : (
        sepsisError && (
          <div className="rounded-lg bg-surface-low ring-1 ring-line text-ink text-sm p-3" role="alert">
            {sepsisError}
          </div>
        )
      )}
      {deterioration ? (
        <ScoreCard title="Deterioration index" Icon={TrendingUp} result={deterioration} />
      ) : (
        detError && (
          <div className="rounded-lg bg-surface-low ring-1 ring-line text-ink text-sm p-3" role="status">
            {detError}
          </div>
        )
      )}
    </div>
  );
}
