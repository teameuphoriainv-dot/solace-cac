import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Stethoscope,
  AlertTriangle,
  ListChecks,
  Loader2,
  Sparkles,
  ShieldAlert,
  Target,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import { AiOffNote, AiSourceTag, aiCallFailed, writtenByAi } from "../AiStatus";
import { DifferentialPanel } from "../../clinician/DifferentialPanel";
import { WorkupPanel } from "../../clinician/WorkupPanel";
import { DispositionPanel } from "../../clinician/DispositionPanel";
import { apiErrorMessage, ddxV2 } from "../../../lib/api";
import type { DdxResult } from "../../../lib/api";
import { useCapabilities } from "../../../lib/capabilities";

/** Map an AI weight (0 to 1) to the panel's likelihood bucket. */
function weightToLikelihood(weight: number): "high" | "moderate" | "low" {
  if (weight >= 0.66) return "high";
  if (weight >= 0.33) return "moderate";
  return "low";
}

/** Shown when the patient's check-in words matched the prompt-injection filter. */
const CONTENT_FLAG_NOTE =
  "AI reasoning is off for this patient. Some of their words matched the filter for instructions aimed at the AI, so nothing from this check-in is sent to the AI. A fixed keyword check for conditions that must not be missed still runs.";

/**
 * Reasoning: possible diagnoses for the patient's own words, plus the workup and
 * next-step suggestions saved at check-in. The diagnosis list needs an AI key.
 * Without one the server still runs a fixed keyword check for conditions that
 * must not be missed, so the card runs that on its own and labels it as no AI.
 * A patient whose words tripped the content filter gets the same no-AI card.
 */
export default function ReasoningTab() {
  const { hospitalId, patientId, patient, loading, error } = usePatientWorkspace();
  const caps = useCapabilities(hospitalId);

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [ddx, setDdx] = useState<DdxResult | null>(null);
  // The patient the no-AI checklist last ran for, so it runs once per patient.
  const autoRanFor = useRef<string | null>(null);

  const transcript = patient?.transcript || "";
  const medicalInfo = patient?.medical_info ?? undefined;
  // The server needs at least a short sentence to reason about.
  const canRun = transcript.trim().length >= 10;
  // Words that matched the prompt-injection filter at check-in never go to the AI.
  const contentFlagged = !!patient?.content_flag;

  // A late answer for a patient the nurse already left is dropped.
  const currentPid = useRef(patientId);
  currentPid.current = patientId;

  const runReasoning = useCallback(async () => {
    const pid = patientId;
    setRunning(true);
    setRunError(null);
    try {
      // patient_id lets the server check the record's content flag as well.
      const body = { transcript, medical_info: medicalInfo, patient_id: pid };
      const result = await ddxV2(hospitalId, body);
      if (currentPid.current === pid) setDdx(result);
    } catch (e: unknown) {
      if (currentPid.current === pid) {
        setRunError(apiErrorMessage(e, "Could not get possible diagnoses. Please try again."));
      }
    } finally {
      setRunning(false);
    }
  }, [hospitalId, patientId, transcript, medicalInfo]);

  // A different patient starts clean.
  useEffect(() => {
    setDdx(null);
    setRunError(null);
  }, [patientId]);

  // With AI off the checklist is a quick fixed check, so run it without a click.
  useEffect(() => {
    if (!caps || (caps.llm && !contentFlagged) || !patient || !canRun) return;
    if (autoRanFor.current === patient.patient_id) return;
    autoRanFor.current = patient.patient_id;
    void runReasoning();
  }, [caps, contentFlagged, patient, canRun, runReasoning]);

  // Prefer a fresh list; otherwise show whatever the record already carries.
  const differential = useMemo(() => {
    if (ddx && ddx.differential.length > 0) {
      return ddx.differential.map((d) => ({
        diagnosis: d.diagnosis,
        icd10: d.icd10,
        likelihood: weightToLikelihood(d.weight),
        rule_in: d.rule_in ?? [],
        rule_out: d.rule_out ?? [],
        must_not_miss: d.must_not_miss,
      }));
    }
    return patient?.differential ?? [];
  }, [ddx, patient]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16" role="status">
        <Loader2 size={22} className="animate-spin text-text-muted" aria-hidden="true" />
        <span className="sr-only">Loading patient…</span>
      </div>
    );
  }

  if (error || !patient) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <AlertTriangle size={26} className="mx-auto mb-3 text-error" aria-hidden="true" />
          <h2 className="text-lg font-bold tracking-tight">Reasoning</h2>
          <p className="text-text-muted text-sm mt-1">
            {error || "Patient record is unavailable."}
          </p>
        </div>
      </div>
    );
  }

  const hasDifferential = differential.length > 0;
  const hasWorkup =
    !!patient.workup_orders &&
    ((patient.workup_orders.labs?.length ?? 0) > 0 ||
      (patient.workup_orders.imaging?.length ?? 0) > 0 ||
      (patient.workup_orders.monitoring?.length ?? 0) > 0 ||
      (patient.workup_orders.consults?.length ?? 0) > 0);
  const hasDisposition = !!patient.disposition && !!patient.disposition.disposition;
  const aiOn = !!caps?.llm;
  // AI is on for this server and allowed for this patient.
  const aiUsable = aiOn && !contentFlagged;
  const ddxSource = (ddx as { source?: unknown } | null)?.source;
  // AI wrote this run only when the server says so ("claude"); a fallback never counts.
  const ranWithoutAi = !!ddx && writtenByAi(ddxSource, ddx.ai_available) !== true;
  const ranButAiFailed = !!ddx && aiCallFailed(ddxSource);
  // The AI list itself, without the fixed do-not-miss items the server folds in.
  const aiItems = ddx && !ranWithoutAi ? ddx.differential.filter((d) => !isFixedListItem(d)) : [];
  // Only a fresh run says for sure whether AI wrote the list on screen.
  const freshList = !!ddx && ddx.differential.length > 0;

  return (
    <div className="flex flex-col gap-5 max-w-3xl mx-auto py-2">
      <div className="bg-surface-lowest rounded-xl shadow-card p-4 flex items-start gap-3">
        <div className="rounded-lg bg-primary/10 p-2 shrink-0">
          <Stethoscope size={18} className="text-primary" aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-base font-bold tracking-tight">Reasoning</h2>
          <p className="text-text-muted text-[13px] mt-0.5 leading-snug">
            Possible diagnoses for {patient.name}, worked out from what they said at check-in.
            A clinician decides; these are only ideas.
          </p>

          {caps === null ? null : aiUsable ? (
            <>
              <button
                type="button"
                onClick={runReasoning}
                disabled={running || !canRun}
                className="mt-3 inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-[13px] font-semibold bg-primary text-white transition-colors hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {running ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles size={14} aria-hidden="true" />
                )}
                {running ? "Thinking…" : ddx ? "Run again" : "Suggest possible diagnoses (AI)"}
              </button>
              {!canRun && (
                <p className="text-text-muted text-[12px] mt-1.5">
                  The patient did not say enough at check-in for the AI to work with.
                </p>
              )}
            </>
          ) : (
            <div className="mt-3 flex flex-col gap-2">
              <AiOffNote>
                {contentFlagged
                  ? CONTENT_FLAG_NOTE
                  : ddx?.message ||
                    "AI reasoning is off on this server, so no list of possible diagnoses is drafted. Nothing is made up to fill the gap. A fixed keyword check for conditions that must not be missed still runs."}{" "}
                The early warning scores and the bedside re-check also work without AI.
              </AiOffNote>
              {canRun ? (
                <button
                  type="button"
                  onClick={runReasoning}
                  disabled={running}
                  className="self-start inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-[13px] font-semibold bg-surface-low ring-1 ring-line text-ink transition-colors hover:bg-surface-high focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
                >
                  {running ? (
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <ListChecks size={14} aria-hidden="true" />
                  )}
                  {running ? "Checking…" : ddx ? "Check again" : "Check for do-not-miss conditions"}
                </button>
              ) : (
                <p className="text-text-muted text-[12px]">
                  The patient did not say enough at check-in to check against the list.
                </p>
              )}
            </div>
          )}
          {runError && (
            <p className="text-error text-[13px] mt-1.5" role="alert">
              {runError}
            </p>
          )}
          {ddx && ranWithoutAi && aiUsable && (
            <div className="mt-2">
              <AiOffNote>
                {ddx.message ||
                  (ranButAiFailed
                    ? "The AI did not answer, so no list of possible diagnoses was drafted. Try again later."
                    : "AI reasoning is not available right now, so no list was drafted.")}
              </AiOffNote>
            </div>
          )}
          {ddx && !ranWithoutAi && aiItems.length === 0 && ddx.differential.length > 0 && (
            <div className="mt-2">
              <AiOffNote>
                {ddx.message ||
                  "The AI did not return any possible diagnoses. The list below is only the fixed do-not-miss check, not AI."}
              </AiOffNote>
            </div>
          )}
          {ddx && ranWithoutAi && !running && ddx.red_flags.length === 0 && (
            <p className="text-text-muted text-[12px] mt-2" role="status">
              No do-not-miss conditions matched the patient's words. This is a fixed keyword
              check, so it can miss things: use your own judgment.
            </p>
          )}
          {ddx && !ranWithoutAi && ddx.differential.length === 0 && ddx.red_flags.length === 0 && (
            <div className="mt-2">
              <AiOffNote>
                {ddx.message || "No suggestions returned for this patient. Try again, or use the early warning scores."}
              </AiOffNote>
            </div>
          )}
        </div>
      </div>

      {/* Conditions that must be ruled out, from the latest run */}
      {ddx && ddx.red_flags.length > 0 && (
        <section className="bg-error/5 border border-error/30 rounded-xl p-4">
          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
            <ShieldAlert size={14} className="text-error" aria-hidden="true" />
            <div className="text-[12px] uppercase tracking-[0.14em] text-error font-semibold">
              Do not miss
            </div>
            <span className="ml-auto">
              {/* The server's red_flags always come from its fixed keyword list, never the AI. */}
              <AiSourceTag ai={false} label="From a fixed checklist, no AI" />
            </span>
          </div>
          <ul className="flex flex-col gap-1.5">
            {ddx.red_flags.map((rf, i) => (
              <li key={i} className="flex items-center gap-2 text-[13px] text-ink">
                <AlertTriangle size={12} className="text-error shrink-0" aria-hidden="true" />
                <span className="font-medium">{rf.diagnosis}</span>
                {rf.icd10 && (
                  <span className="text-[12px] font-mono text-text-muted">{rf.icd10}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Shortlists the AI expects the answer to be in */}
      {ddx && !ranWithoutAi && aiItems.length > 0 && (ddx.conformal.set_90.length > 0 || ddx.conformal.set_95.length > 0) && (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-4">
          <div className="flex items-center gap-1.5 mb-1">
            <Target size={14} className="text-primary" aria-hidden="true" />
            <div className="text-[12px] uppercase tracking-[0.14em] text-text-muted font-semibold">
              Shortlists
            </div>
          </div>
          <p className="text-[12px] text-text-muted mb-2 leading-snug">
            The smallest groups of ideas the answer is expected to be in, at two levels of certainty.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { label: "Shortlist (90%)", items: ddx.conformal.set_90 },
              { label: "Wider shortlist (95%)", items: ddx.conformal.set_95 },
            ].map((set) => (
              <div key={set.label}>
                <div className="text-[12px] uppercase tracking-wider text-text-muted mb-1">
                  {set.label}
                </div>
                {set.items.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {set.items.map((dx, j) => (
                      <span
                        key={j}
                        className="inline-flex items-center px-2 h-6 rounded-md text-[12px] font-medium bg-surface-low text-ink"
                      >
                        {dx}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-[12px] text-text-muted italic">None</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {hasDifferential ? (
        <DifferentialPanel
          entries={differential}
          aiDraft={freshList ? !ranWithoutAi && aiItems.length > 0 : undefined}
          noAiLabel={freshList ? "From a fixed checklist, no AI" : undefined}
        />
      ) : (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-5 text-center">
          <p className="text-text-muted text-[13px]">
            {aiUsable
              ? "No diagnosis list yet. Use the button above to ask for one."
              : contentFlagged
                ? "No diagnosis list on file. AI is off for this patient, so none is drafted."
                : "No diagnosis list on file. One is only drafted when AI is on."}
          </p>
        </section>
      )}

      {hasWorkup ? (
        <WorkupPanel orders={patient.workup_orders} />
      ) : (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-5 text-center">
          <p className="text-text-muted text-[13px]">No suggested tests on file.</p>
        </section>
      )}

      {hasDisposition ? (
        <DispositionPanel disposition={patient.disposition} />
      ) : (
        <section className="bg-surface-lowest rounded-xl shadow-soft p-5 text-center">
          <p className="text-text-muted text-[13px]">No next-step suggestion on file.</p>
        </section>
      )}
    </div>
  );
}

ReasoningTab.displayName = "ReasoningTab";

/** A do-not-miss item the server adds from its fixed keyword list, not from the AI. */
function isFixedListItem(d: DdxResult["differential"][number]): boolean {
  const first = (d.rule_in ?? [])[0] ?? "";
  return /^red-flag keyword match/i.test(first);
}
