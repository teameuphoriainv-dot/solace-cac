import { useEffect, useId, useState } from "react";
import { Check, Loader2, Send, StickyNote } from "lucide-react";
import { apiErrorMessage, createNote, publishPatientSummary } from "../../lib/api";
import { useCapabilities } from "../../lib/capabilities";
import { useOptionalPatientWorkspace } from "../workspace/PatientWorkspaceContext";
import { AiSourceTag, writtenByAi } from "../workspace/AiStatus";
import type { ClinicianNote, PatientEducation } from "../../types";

type Props = {
  hospitalId: string;
  patientId: string;
  initialNotes: ClinicianNote[];
  initialEducation: PatientEducation | null;
  publishedAt: string | null;
};

export function NotesPanel({
  hospitalId,
  patientId,
  initialNotes,
  initialEducation,
  publishedAt,
}: Props) {
  const workspace = useOptionalPatientWorkspace();
  const caps = useCapabilities(hospitalId);
  const textareaId = useId();
  const [notes, setNotes] = useState<ClinicianNote[]>(initialNotes);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [education, setEducation] = useState<PatientEducation | null>(initialEducation);
  const [publishedTs, setPublishedTs] = useState<string | null>(publishedAt);
  // null = unknown (an older summary saved before this was recorded). Read from the
  // summary's source, so a word-for-word fallback is never tagged as an AI draft.
  const [summaryUsedAi, setSummaryUsedAi] = useState<boolean | null>(() =>
    writtenByAi(initialEducation?.source, initialEducation?.ai_available),
  );
  // The server's plain note on how the last summary was built, if any.
  const [summaryNote, setSummaryNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setNotes(initialNotes);
    setEducation(initialEducation);
    setPublishedTs(publishedAt);
    const byAi = writtenByAi(initialEducation?.source, initialEducation?.ai_available);
    if (byAi !== null) setSummaryUsedAi(byAi);
  }, [initialNotes, initialEducation, publishedAt, patientId]);

  // A different patient starts with no leftover messages.
  useEffect(() => {
    setSummaryNote(null);
    setStatus(null);
    setError(null);
  }, [patientId]);

  async function saveNote() {
    if (!draft.trim() || saving) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const note = await createNote(hospitalId, patientId, draft.trim());
      if (note) setNotes((prev) => [...prev, note]);
      setDraft("");
      setStatus("Note saved.");
      // Refresh the shared record so the note is still there after switching tabs.
      workspace?.reloadPatient();
    } catch (e: unknown) {
      setError(apiErrorMessage(e, "Could not save the note. Please try again."));
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (publishing) return;
    setPublishing(true);
    setError(null);
    setStatus(null);
    setSummaryNote(null);
    try {
      const r = await publishPatientSummary(hospitalId, patientId);
      if (!r.summary) {
        setError(r.message || "No summary came back. Your notes are saved; try again in a moment.");
        return;
      }
      setEducation(r.summary);
      setPublishedTs(new Date().toISOString());
      setSummaryUsedAi(writtenByAi(r.source || r.summary.source, r.ai_available ?? r.summary.ai_available));
      setSummaryNote(r.message || null);
      setStatus("Sent to the patient's screen.");
      workspace?.reloadPatient();
    } catch (e: unknown) {
      setError(apiErrorMessage(e, "Could not send the summary. Your notes are saved."));
    } finally {
      setPublishing(false);
    }
  }

  const aiOff = caps ? !caps.llm : false;
  // Words that matched the prompt-injection filter at check-in never go to the AI.
  const contentFlagged =
    workspace?.patient?.patient_id === patientId ? !!workspace.patient.content_flag : false;

  return (
    <section>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="text-[12px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Care team notes
        </div>
        {notes.length > 0 && (
          <button
            type="button"
            onClick={publish}
            disabled={publishing}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-white text-xs font-medium disabled:opacity-50"
          >
            {publishing ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Send size={14} aria-hidden="true" />}
            {publishedTs ? "Send updated summary to patient" : "Send summary to patient"}
          </button>
        )}
      </div>

      {notes.length > 0 && (
        <p className="text-[12px] text-text-muted leading-snug mb-2">
          {aiOff
            ? "AI is off, so the patient sees your notes as you wrote them. Write them in plain words."
            : contentFlagged
              ? "AI is off for this patient, so they see your notes as you wrote them. Write them in plain words."
              : "AI turns your notes into plain words for the patient. If the AI does not answer, they get your notes word for word. Read what they see below after sending."}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {notes.length === 0 ? (
          <div className="text-sm text-text-muted bg-surface-low rounded-lg p-3 flex items-start gap-2">
            <StickyNote size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
            No notes yet. Add what you saw, what you are doing next, or what you told the patient.
          </div>
        ) : (
          notes.map((n) => (
            <div key={n.note_id} className="bg-surface-lowest rounded-lg p-3 shadow-soft">
              <div className="text-sm whitespace-pre-wrap leading-relaxed">{n.text}</div>
              <div className="text-[12px] text-text-muted mt-1">
                {n.author} · {new Date(n.created_at).toLocaleTimeString()}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="mt-3">
        <label htmlFor={textareaId} className="sr-only">
          New care team note
        </label>
        <textarea
          id={textareaId}
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a note (what you saw, your plan, what you told the patient)"
          className="w-full p-3 rounded-md bg-surface-lowest ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none transition-all resize-y"
        />
        <div className="flex items-center gap-3 mt-2">
          <button
            type="button"
            onClick={saveNote}
            disabled={!draft.trim() || saving}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-md bg-primary text-white text-sm font-medium disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
            Save note
          </button>
          <span role="status" aria-live="polite" className="text-[12px] text-success font-medium">
            {status}
          </span>
        </div>
      </div>

      {education && (
        <div className="mt-4 bg-primary-fixed/40 rounded-lg p-3">
          <div className="flex items-center justify-between gap-2 flex-wrap mb-1">
            <div className="text-[12px] uppercase tracking-[0.14em] text-primary font-semibold">
              What the patient sees {publishedTs && `· ${new Date(publishedTs).toLocaleTimeString()}`}
            </div>
            {summaryUsedAi !== null && (
              <AiSourceTag ai={summaryUsedAi} label={summaryUsedAi ? undefined : "Your notes, no AI rewording"} />
            )}
          </div>
          {summaryNote && (
            <p className="text-[12px] text-text-muted leading-snug mb-1.5">{summaryNote}</p>
          )}
          <div className="text-sm font-semibold">{education.headline}</div>
          <div className="text-sm mt-1 whitespace-pre-wrap">{education.what_we_are_doing}</div>
          {education.things_to_do_at_home?.length > 0 && (
            <ul className="text-sm mt-2 list-disc ml-5">
              {education.things_to_do_at_home.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          )}
          {education.when_to_come_back && (
            <div className="text-sm mt-2">
              <span className="font-semibold">When to get help: </span>
              {education.when_to_come_back}
            </div>
          )}
          {education.closing && <div className="text-sm italic mt-2 text-text-muted">{education.closing}</div>}
        </div>
      )}

      {error && (
        <div className="mt-3 p-3 rounded-md bg-error-container text-error text-sm" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
