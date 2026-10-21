import { useEffect, useId, useState } from "react";
import { AlertTriangle, Check, Loader2, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import {
  apiErrorMessage,
  createPrescription,
  listPrescriptions,
  suggestPrescriptions,
  type PrescriptionSafety,
  type SafetyAlert,
  type SuggestionWithSafety,
} from "../../lib/api";
import { useCapabilities } from "../../lib/capabilities";
import { AiOffNote, AiSourceTag } from "../workspace/AiStatus";
import { useOptionalPatientWorkspace } from "../workspace/PatientWorkspaceContext";
import type { MedicalInfo, Prescription, PrescriptionSuggestion } from "../../types";

type Props = {
  hospitalId: string;
  patientId: string;
  medicalInfo?: MedicalInfo | null;
  /** The record's content_flag. Read from the open patient workspace when not passed. */
  contentFlag?: string | null;
};

const CONTENT_FLAG_NOTE =
  "AI prescription ideas are off for this patient. Some of their words matched the filter for instructions aimed at the AI, so nothing from this check-in is sent to the AI. Prescriptions you write above are still checked for allergies and interactions.";

// Quick check while typing, before anything is saved: does the drug name (or its
// family) match an allergy or a medicine the patient reported? The server runs the
// full allergy and interaction check when the prescription is saved.
function checkInteractions(
  drug: string,
  info: MedicalInfo | null | undefined,
): { allergy?: string; med?: string } {
  if (!info || !drug.trim()) return {};
  const norm = drug.trim().toLowerCase();
  const allergies = (info.allergies || []).map((a) => a.toLowerCase()).filter(Boolean);
  const meds = (info.medications || []).map((m) => m.toLowerCase()).filter(Boolean);
  const allergyHit = allergies.find(
    (a) => a !== "none" && (norm.includes(a) || a.includes(norm) || classMatch(norm, a)),
  );
  const medHit = meds.find(
    (m) => m !== "none" && (norm.includes(m) || m.includes(norm) || classMatch(norm, m)),
  );
  return { allergy: allergyHit, med: medHit };
}

// A few common drug families, enough to catch the usual waiting-room cases.
const CLASS_GROUPS: Record<string, string[]> = {
  nsaid: ["ibuprofen", "naproxen", "ketorolac", "aspirin", "diclofenac"],
  opioid: ["morphine", "oxycodone", "hydrocodone", "fentanyl", "tramadol", "codeine"],
  betalactam: ["penicillin", "amoxicillin", "ampicillin", "cephalexin", "ceftriaxone"],
  anticoag: ["warfarin", "apixaban", "rivaroxaban", "heparin", "enoxaparin"],
};

function classMatch(a: string, b: string): boolean {
  for (const group of Object.values(CLASS_GROUPS)) {
    if (group.some((d) => a.includes(d)) && group.some((d) => b.includes(d))) return true;
  }
  return false;
}

type PlainAlert = { severity: string; title: string; text: string };

const SEVERITY_RANK: Record<string, number> = { contraindicated: 4, high: 3, moderate: 2, low: 1 };
const SEVERITY_WORD: Record<string, string> = {
  contraindicated: "Do not give",
  high: "Serious",
  moderate: "Use care",
  low: "Minor",
};

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** Flatten the server's safety result into plain sentences, most serious first. */
function plainAlerts(safety: PrescriptionSafety | null | undefined): PlainAlert[] {
  if (!safety) return [];
  const out: PlainAlert[] = [];
  const push = (list: SafetyAlert[] | undefined, make: (a: SafetyAlert) => { title: string; text: string }) => {
    if (!Array.isArray(list)) return;
    for (const a of list) {
      if (!a || typeof a !== "object") continue;
      const { title, text } = make(a);
      out.push({
        severity: (str(a.severity) || "low").toLowerCase(),
        title,
        text: text.charAt(0).toUpperCase() + text.slice(1),
      });
    }
  };
  push(safety.drug_allergy, (a) => ({
    title: `Allergy: ${str(a.med) || "this medicine"}`,
    text: str(a.reason) || "Matches an allergy the patient reported.",
  }));
  push(safety.drug_drug, (a) => ({
    title: `${str(a.a) || "This medicine"} with ${str(a.b) || "a current medicine"}`,
    text: str(a.reason) || "These two medicines can interact.",
  }));
  push(safety.renal, (a) => ({
    title: `Kidney dosing: ${str(a.med) || "this medicine"}`,
    text: str(a.guidance) || str(a.reason) || "Check the dose for kidney function.",
  }));
  push(safety.hepatic, (a) => ({
    title: `Liver dosing: ${str(a.med) || "this medicine"}`,
    text: str(a.guidance) || str(a.reason) || "Check the dose for liver function.",
  }));
  push(safety.duplicate_therapy, (a) => ({
    title: "Same kind of medicine twice",
    text: str(a.reason) || str(a.guidance) || "The patient may already take a medicine like this.",
  }));
  return out.sort((x, y) => (SEVERITY_RANK[y.severity] ?? 0) - (SEVERITY_RANK[x.severity] ?? 0));
}

/**
 * The alerts saved with a prescription, as sentences like
 * "HIGH: warfarin with ibuprofen. GI bleeding." Used after a reload, when the
 * full safety result from the save is no longer on hand.
 */
function savedAlerts(p: Prescription): PlainAlert[] | null {
  if (!Array.isArray(p.safety_alerts)) return null;
  const out: PlainAlert[] = [];
  for (const raw of p.safety_alerts) {
    if (typeof raw !== "string" || !raw.trim()) continue;
    const m = raw.match(/^\s*([A-Za-z]+)\s*:\s*(.*)$/);
    const sev = m ? m[1].toLowerCase() : (p.safety_highest || "low").toLowerCase();
    const body = (m ? m[2] : raw).trim();
    const dot = body.indexOf(". ");
    const title = (dot > 0 ? body.slice(0, dot) : body).replace(/\.$/, "");
    out.push({
      severity: SEVERITY_RANK[sev] ? sev : "low",
      title: title.charAt(0).toUpperCase() + title.slice(1),
      text: dot > 0 ? body.slice(dot + 2) : "",
    });
  }
  return out.sort((x, y) => (SEVERITY_RANK[y.severity] ?? 0) - (SEVERITY_RANK[x.severity] ?? 0));
}

function AlertList({ alerts, checked }: { alerts: PlainAlert[]; checked: boolean }) {
  if (alerts.length === 0) {
    if (!checked) return null;
    return (
      <div className="flex items-start gap-1.5 text-[12px] text-success font-medium">
        <ShieldCheck size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
        No allergy or interaction problems found with the medicines on file.
      </div>
    );
  }
  return (
    <ul className="flex flex-col gap-1.5" aria-label="Medicine safety alerts">
      {alerts.map((a, i) => {
        const serious = (SEVERITY_RANK[a.severity] ?? 0) >= 3;
        const tone = serious
          ? "bg-error-container text-error"
          : a.severity === "moderate"
            ? "bg-warning-container text-warning"
            : "bg-surface-low text-text-muted";
        return (
          <li key={i} className={`rounded-md px-2.5 py-1.5 text-[12px] leading-snug ${tone}`}>
            <div className="flex items-start gap-1.5">
              <ShieldAlert size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                <span className="font-bold">{SEVERITY_WORD[a.severity] ?? "Note"}. </span>
                <span className="font-semibold">{a.title}.</span>
                {a.text && <> {a.text}</>}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const EMPTY_MANUAL: PrescriptionSuggestion = {
  drug: "",
  dose: "",
  route: "",
  frequency: "",
  duration: "",
  indication: "",
  cautions: "",
};

const SOURCE_LABEL: Record<string, string> = {
  manual: "Written by hand",
  ai_suggested_accepted: "AI idea, accepted",
  ai_suggested: "AI idea",
};

export function PrescriptionPanel({ hospitalId, patientId, medicalInfo, contentFlag }: Props) {
  const caps = useCapabilities(hospitalId);
  const workspace = useOptionalPatientWorkspace();
  // Words that matched the prompt-injection filter at check-in never go to the AI.
  const workspaceFlag = workspace?.patient?.patient_id === patientId ? workspace.patient.content_flag : null;
  const contentFlagged = !!(contentFlag !== undefined ? contentFlag : workspaceFlag);
  const [items, setItems] = useState<Prescription[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionWithSafety[]>([]);
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [suggestNote, setSuggestNote] = useState<string | null>(null);
  const [manualDraft, setManualDraft] = useState<PrescriptionSuggestion>(EMPTY_MANUAL);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // A medicine that matches a reported allergy needs "Prescribe anyway" and a reason.
  const [overrideReason, setOverrideReason] = useState("");
  const overrideId = useId();
  // Safety result for the prescription saved most recently, keyed by its id.
  const [lastSafety, setLastSafety] = useState<{ id: string; alerts: PlainAlert[] } | null>(null);
  // What the server's checker covers, from the last save.
  const [checkerNote, setCheckerNote] = useState<string | null>(null);

  async function refresh() {
    try {
      const list = await listPrescriptions(hospitalId, patientId);
      setItems(list);
      setListError(null);
    } catch (e: unknown) {
      setListError(apiErrorMessage(e, "Could not load prescriptions."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setSuggestions([]);
    setSuggestNote(null);
    setLastSafety(null);
    setCheckerNote(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId]);

  async function fetchSuggestions() {
    setSuggestBusy(true);
    setSuggestNote(null);
    try {
      const r = await suggestPrescriptions(hospitalId, patientId);
      setSuggestions(r.suggestions);
      if (r.ai_available === false) {
        setSuggestNote(r.message || "No AI ideas came back. Write a prescription by hand above; it is still checked for allergies and interactions.");
      } else if (r.suggestions.length === 0) {
        // An empty list says nothing about whether the patient needs a medicine.
        setSuggestNote(
          "No AI ideas came back for this visit. Write a prescription by hand above; it is still checked for allergies and interactions.",
        );
      }
    } catch (e: unknown) {
      setSuggestNote(apiErrorMessage(e, "Could not get suggestions. Write a prescription by hand above."));
    } finally {
      setSuggestBusy(false);
    }
  }

  async function save(body: PrescriptionSuggestion, source: "manual" | "ai_suggested_accepted") {
    setSaving(true);
    setSaveError(null);
    try {
      // Send only the fields the server accepts (it rejects unknown keys).
      const clean: PrescriptionSuggestion = {
        drug: body.drug,
        dose: body.dose || "",
        route: body.route || "",
        frequency: body.frequency || "",
        duration: body.duration || "",
        indication: body.indication || "",
        cautions: body.cautions || "",
      };
      const r = await createPrescription(hospitalId, patientId, { ...clean, source });
      // Only claim "checked" when the server actually sent a safety result back.
      setLastSafety(
        r.prescription?.prescription_id && r.safety
          ? { id: r.prescription.prescription_id, alerts: plainAlerts(r.safety) }
          : null,
      );
      setCheckerNote(typeof r.safety?.note === "string" && r.safety.note.trim() ? r.safety.note : null);
      await refresh();
      return true;
    } catch (e: unknown) {
      setSaveError(apiErrorMessage(e, "Could not save the prescription. Please try again."));
      return false;
    } finally {
      setSaving(false);
    }
  }

  // Where the draft came from: typed by hand, or an AI idea moved into the form for review.
  const [draftSource, setDraftSource] = useState<"manual" | "ai_suggested_accepted">("manual");

  const liveHits = checkInteractions(manualDraft.drug, medicalInfo);
  const needsOverride = !!liveHits.allergy;

  async function saveManual() {
    if (!manualDraft.drug.trim()) return;
    const reason = overrideReason.trim();
    if (needsOverride && !reason) return;
    const body = { ...manualDraft, drug: manualDraft.drug.trim() };
    if (needsOverride) {
      // Saved with the prescription, so the override and its reason stay on the record.
      const why = `Prescribed despite a reported ${liveHits.allergy} allergy. Reason: ${reason}`;
      body.cautions = body.cautions ? `${why}. ${body.cautions}` : why;
    }
    if (await save(body, draftSource)) {
      setManualDraft(EMPTY_MANUAL);
      setOverrideReason("");
      setDraftSource("manual");
    }
  }

  async function accept(s: SuggestionWithSafety) {
    // An AI idea that matches a reported allergy goes into the form, so the same
    // "Prescribe anyway" step applies before it is saved.
    if (checkInteractions(s.drug, medicalInfo).allergy) {
      setManualDraft({
        drug: s.drug,
        dose: s.dose || "",
        route: s.route || "",
        frequency: s.frequency || "",
        duration: s.duration || "",
        indication: s.indication || "",
        cautions: s.cautions || "",
      });
      setDraftSource("ai_suggested_accepted");
      setOverrideReason("");
      setSuggestions((prev) => prev.filter((x) => x !== s));
      return;
    }
    if (await save(s, "ai_suggested_accepted")) {
      setSuggestions((prev) => prev.filter((x) => x !== s));
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <div>
        <div className="text-[12px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Prescriptions
        </div>
        <p className="text-[12px] text-text-muted mt-0.5 leading-snug">
          Demo only. Each one is checked against the allergies and medicines on file when you save it.
        </p>
      </div>

      {/* Manual entry comes first: it works with or without AI. */}
      <div className="bg-surface-lowest rounded-lg p-3 shadow-soft flex flex-col gap-2">
        <ManualField label="Medicine" value={manualDraft.drug} onChange={(v) => setManualDraft({ ...manualDraft, drug: v })} />
        {(liveHits.allergy || liveHits.med) && (
          <div className="flex flex-col gap-1">
            {liveHits.allergy && (
              <div className="text-[12px] text-error flex items-start gap-1 font-semibold">
                <ShieldAlert size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>Possible allergy match: the patient reported {liveHits.allergy}.</span>
              </div>
            )}
            {liveHits.med && (
              <div className="text-[12px] text-warning flex items-start gap-1 font-semibold">
                <ShieldAlert size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>Similar to a medicine they already take: {liveHits.med}.</span>
              </div>
            )}
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <ManualField label="Dose" value={manualDraft.dose} onChange={(v) => setManualDraft({ ...manualDraft, dose: v })} />
          <ManualField label="How it is given" value={manualDraft.route} onChange={(v) => setManualDraft({ ...manualDraft, route: v })} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <ManualField label="How often" value={manualDraft.frequency} onChange={(v) => setManualDraft({ ...manualDraft, frequency: v })} />
          <ManualField label="For how long" value={manualDraft.duration} onChange={(v) => setManualDraft({ ...manualDraft, duration: v })} />
        </div>
        <ManualField label="What it is for" value={manualDraft.indication} onChange={(v) => setManualDraft({ ...manualDraft, indication: v })} />
        {draftSource === "ai_suggested_accepted" && (
          <p className="text-[12px] text-text-muted leading-snug">
            This is an AI idea. Check every field before saving it.
          </p>
        )}
        {needsOverride && (
          <div className="rounded-md bg-error-container/60 p-2.5 flex flex-col gap-1.5">
            <label htmlFor={overrideId} className="text-[12px] font-semibold text-error leading-snug">
              This matches the patient&rsquo;s reported {liveHits.allergy} allergy. To prescribe it anyway,
              say why.
            </label>
            <input
              id={overrideId}
              type="text"
              value={overrideReason}
              maxLength={300}
              onChange={(e) => setOverrideReason(e.target.value)}
              placeholder="For example: allergy was a mild rash years ago, discussed with the patient"
              className="w-full h-10 px-3 rounded-md bg-surface-lowest ring-1 ring-error/40 focus:ring-error focus:ring-2 text-sm outline-none transition-all"
            />
          </div>
        )}
        <div className="flex gap-2 mt-1">
          <button
            type="button"
            onClick={saveManual}
            disabled={!manualDraft.drug.trim() || saving || (needsOverride && !overrideReason.trim())}
            className={`inline-flex items-center gap-1.5 h-9 px-4 rounded-md text-white text-sm font-medium disabled:opacity-50 ${
              needsOverride ? "bg-error" : "bg-primary"
            }`}
          >
            {saving ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
            {needsOverride ? "Prescribe anyway" : "Save and check"}
          </button>
          {manualDraft !== EMPTY_MANUAL && (
            <button
              type="button"
              onClick={() => {
                setManualDraft(EMPTY_MANUAL);
                setOverrideReason("");
                setDraftSource("manual");
              }}
              className="h-9 px-4 rounded-md text-sm text-text-muted hover:text-ink"
            >
              Clear
            </button>
          )}
        </div>
        {saveError && (
          <div className="text-sm text-error" role="alert">
            {saveError}
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-text-muted" role="status">Loading prescriptions…</div>
      ) : listError ? (
        <div className="text-sm text-error" role="alert">{listError}</div>
      ) : items.length === 0 ? (
        <div className="text-sm text-text-muted bg-surface-low rounded-lg p-3">None written yet.</div>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((p) => (
            <PrescriptionCard
              key={p.prescription_id}
              p={p}
              alerts={lastSafety?.id === p.prescription_id ? lastSafety.alerts : savedAlerts(p)}
            />
          ))}
          {checkerNote && <p className="text-[12px] text-text-muted leading-snug">{checkerNote}</p>}
        </div>
      )}

      {/* AI ideas, only when the server has an AI key */}
      {caps && !caps.llm && (
        <AiOffNote>
          AI prescription ideas are off on this server. Prescriptions you write above are still
          checked for allergies and interactions.
        </AiOffNote>
      )}
      {caps?.llm && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={fetchSuggestions}
            disabled={suggestBusy || contentFlagged}
            className="self-start inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-xs font-semibold text-primary bg-primary-fixed/50 hover:bg-primary-fixed disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {suggestBusy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Sparkles size={14} aria-hidden="true" />}
            {suggestBusy ? "Asking AI…" : "Suggest options (AI)"}
          </button>
          {contentFlagged && <AiOffNote>{CONTENT_FLAG_NOTE}</AiOffNote>}
          {suggestNote && !contentFlagged && <AiOffNote>{suggestNote}</AiOffNote>}
          {suggestions.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <AiSourceTag ai label="AI ideas: check every dose before using one" />
              </div>
              {suggestions.map((s, i) => {
                const hits = checkInteractions(s.drug, medicalInfo);
                const alerts = plainAlerts(s.safety);
                return (
                  <div key={i} className="bg-primary-fixed/40 rounded-lg p-3 flex flex-col gap-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-bold tracking-editorial">
                        {s.drug} {s.dose && <span className="text-sm font-normal">{s.dose}</span>}
                      </div>
                      <button
                        type="button"
                        onClick={() => accept(s)}
                        disabled={saving}
                        className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-primary text-white text-xs font-medium disabled:opacity-50"
                      >
                        <Check size={14} aria-hidden="true" /> {hits.allergy ? "Review" : "Accept"}
                      </button>
                    </div>
                    <div className="text-xs text-text-muted">
                      {[s.route, s.frequency, s.duration].filter(Boolean).join(" · ")}
                    </div>
                    {s.indication && <div className="text-sm">{s.indication}</div>}
                    {hits.allergy && (
                      <div className="text-xs text-error flex items-start gap-1 font-semibold">
                        <ShieldAlert size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                        <span>Possible allergy match: {hits.allergy}</span>
                      </div>
                    )}
                    {hits.med && (
                      <div className="text-xs text-warning flex items-start gap-1 font-semibold">
                        <ShieldAlert size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                        <span>Similar to a current medicine: {hits.med}</span>
                      </div>
                    )}
                    <AlertList alerts={alerts} checked={false} />
                    {s.cautions && (
                      <div className="text-xs text-error flex items-start gap-1">
                        <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                        <span>{s.cautions}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PrescriptionCard({ p, alerts }: { p: Prescription; alerts: PlainAlert[] | null }) {
  return (
    <div className="bg-surface-lowest rounded-lg p-3 shadow-soft flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <div className="font-bold tracking-editorial">
          {p.drug} {p.dose && <span className="text-sm font-normal">{p.dose}</span>}
        </div>
        <span className="text-[12px] text-text-muted">{SOURCE_LABEL[p.source] ?? p.source}</span>
      </div>
      <div className="text-xs text-text-muted">
        {[p.route, p.frequency, p.duration].filter(Boolean).join(" · ")}
      </div>
      {p.indication && <div className="text-sm">{p.indication}</div>}
      {p.cautions && (
        <div className="text-xs text-error flex items-start gap-1">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{p.cautions}</span>
        </div>
      )}
      {alerts && <AlertList alerts={alerts} checked />}
      <div className="text-[12px] text-text-muted">
        by {p.prescribed_by} · {new Date(p.prescribed_at).toLocaleTimeString()}
      </div>
    </div>
  );
}

function ManualField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-[12px] uppercase tracking-[0.14em] text-text-muted mb-1">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-10 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none transition-all"
      />
    </div>
  );
}
