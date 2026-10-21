import { useEffect, useId, useRef, useState } from "react";
import {
  Mic, Square, Loader2, AlertTriangle, ClipboardCheck, Pause, Play,
  RefreshCw, Quote, Info, Plus,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import { AiOffNote, AiSourceTag, aiCallFailed, writtenByAi } from "../AiStatus";
import { apiErrorMessage } from "../../../lib/api";
import { useCapabilities } from "../../../lib/capabilities";
import {
  startScribeSession, appendScribeChunk, pauseScribeSession, resumeScribeSession,
  finalizeScribeSession, regenerateScribeSection,
  type ScribeSessionStatus, type ScribeStructuredNote, type ScribeSessionSection,
  type LinkedEvidence,
} from "../../../lib/api-scribe";

/**
 * Scribe tab: a bedside note for the workspace patient.
 *
 * The clinician starts a session, the browser turns speech into text (or the
 * clinician types lines), the text is saved to the server in small parts, and
 * finishing the session builds a SOAP note whose lines link back to what was
 * said. With an AI key the note is drafted by AI. Without one the server keeps
 * the words as spoken and leaves the assessment and plan to the clinician.
 */
export default function ScribeTab() {
  const { hospitalId, patient, loading, error } = usePatientWorkspace();
  const caps = useCapabilities(hospitalId);
  const typedId = useId();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<ScribeSessionStatus | null>(null);
  const [chunkCount, setChunkCount] = useState(0);
  const [finalNote, setFinalNote] = useState<ScribeStructuredNote | null>(null);
  const [finalSoapText, setFinalSoapText] = useState("");
  const [finalUsedAi, setFinalUsedAi] = useState<boolean | null>(null);
  // Why the note was built without AI: the server has no key, the AI call failed,
  // or the words looked like instructions to the AI.
  const [finalSource, setFinalSource] = useState<string>("");
  const [finalMessage, setFinalMessage] = useState<string | null>(null);
  const [regenSection, setRegenSection] = useState<string | null>(null);
  // A plain line after a redo that did not change anything, and whether redo is off now.
  const [regenNote, setRegenNote] = useState<string | null>(null);
  const [regenOff, setRegenOff] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<LinkedEvidence | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [listening, setListening] = useState(false);

  // Web Speech recognizer + chunk-flush plumbing for the live session.
  const sessionRecRef = useRef<SpeechRecognitionLike | null>(null);
  const sessionStreamRef = useRef<MediaStream | null>(null);
  const pendingChunkRef = useRef<string>("");
  const flushTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sessionStatusRef = useRef<ScribeSessionStatus | null>(null);

  const speechSupported = typeof window !== "undefined" && !!(
    (window as unknown as SpeechWindow).SpeechRecognition
    || (window as unknown as SpeechWindow).webkitSpeechRecognition
  );

  // Tear down capture if the tab unmounts mid-encounter.
  useEffect(() => {
    return () => {
      if (flushTimerRef.current) clearInterval(flushTimerRef.current);
      try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // Push whatever text has built up to the server as one part. Runs on a timer
  // while recording, and once more on pause and finish.
  const flushChunk = async () => {
    const sid = sessionIdRef.current;
    const text = pendingChunkRef.current.trim();
    if (!sid || sessionStatusRef.current !== "recording" || !text) return;
    pendingChunkRef.current = "";
    try {
      const r = await appendScribeChunk(hospitalId, { session_id: sid, chunk: text });
      setChunkCount(r.chunk_count);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
    } catch (e: unknown) {
      // Put the text back so the next flush retries instead of losing it.
      pendingChunkRef.current = (text + " " + pendingChunkRef.current).trim();
      setErrorMsg(humanizeError(apiErrorMessage(e, "")));
    }
  };

  // Start a recognizer that adds each finished phrase to the pending text.
  const attachSessionRecognizer = () => {
    const SpeechCtor = (window as unknown as SpeechWindow).SpeechRecognition
      || (window as unknown as SpeechWindow).webkitSpeechRecognition;
    if (!SpeechCtor || !sessionStreamRef.current) return;
    try {
      const sr = new SpeechCtor();
      sr.continuous = true;
      sr.interimResults = true;
      sr.lang = "en-US";
      sr.onresult = (e: SpeechResultEvent) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const seg = e.results[i];
          if (seg.isFinal) pendingChunkRef.current += (seg[0]?.transcript || "") + " ";
        }
      };
      sr.onerror = () => { /* the flush timer keeps going; typing still works */ };
      // Browsers stop listening on their own after a while; keep going while recording.
      sr.onend = () => {
        if (sessionStatusRef.current === "recording") {
          try { sr.start(); } catch { /* ignore double-start */ }
        }
      };
      sessionRecRef.current = sr;
      sr.start();
      setListening(true);
    } catch {
      sessionRecRef.current = null;
      setListening(false);
    }
  };

  const startSession = async () => {
    setBusy("Starting…");
    setErrorMsg(null);
    setNotice(null);
    setFinalNote(null);
    setFinalSoapText("");
    setFinalUsedAi(null);
    setFinalSource("");
    setFinalMessage(null);
    setRegenNote(null);
    setRegenOff(false);
    setActiveEvidence(null);
    // The microphone is optional: without it (or without speech support) the
    // clinician can still type what was said.
    if (speechSupported && navigator.mediaDevices?.getUserMedia) {
      try {
        sessionStreamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e: unknown) {
        sessionStreamRef.current = null;
        const err = e as { name?: string };
        setNotice(
          err?.name === "NotAllowedError"
            ? "The microphone is blocked, so the scribe cannot hear the room. You can still type what was said below."
            : "No microphone was found. You can still type what was said below.",
        );
      }
    } else {
      setNotice("This browser cannot turn speech into text. Type what was said below, or open this page in Chrome or Edge.");
    }
    try {
      const r = await startScribeSession(hospitalId, {
        specialty: "ed",
        session_id: sessionId || undefined,
      });
      setSessionId(r.session_id);
      sessionIdRef.current = r.session_id;
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(0);
      pendingChunkRef.current = "";
      attachSessionRecognizer();
      // Save the built-up speech every 6 seconds so the count stays live.
      flushTimerRef.current = setInterval(() => { void flushChunk(); }, 6000);
    } catch (e: unknown) {
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
      sessionStreamRef.current = null;
      setErrorMsg(humanizeError(apiErrorMessage(e, "")));
    } finally {
      setBusy(null);
    }
  };

  const addTyped = async () => {
    const line = typed.trim();
    if (!line || sessionStatusRef.current !== "recording") return;
    pendingChunkRef.current = (pendingChunkRef.current + " " + line).trim() + " ";
    setTyped("");
    await flushChunk();
  };

  const stopListening = () => {
    try { sessionRecRef.current?.stop(); } catch { /* ignore */ }
    sessionRecRef.current = null;
    setListening(false);
  };

  const pauseSession = async () => {
    if (!sessionId) return;
    await flushChunk();
    setBusy("Pausing…");
    try {
      sessionStatusRef.current = "paused";
      stopListening();
      const r = await pauseScribeSession(hospitalId, sessionId);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(r.chunk_count);
    } catch (e: unknown) {
      setErrorMsg(humanizeError(apiErrorMessage(e, "")));
    } finally {
      setBusy(null);
    }
  };

  const resumeSession = async () => {
    if (!sessionId) return;
    setBusy("Resuming…");
    try {
      const r = await resumeScribeSession(hospitalId, sessionId);
      setSessionStatus(r.status);
      sessionStatusRef.current = r.status;
      setChunkCount(r.chunk_count);
      attachSessionRecognizer();
    } catch (e: unknown) {
      setErrorMsg(humanizeError(apiErrorMessage(e, "")));
    } finally {
      setBusy(null);
    }
  };

  const finalizeSession = async () => {
    if (!sessionId) return;
    await flushChunk();
    setBusy("Building the note…");
    try {
      sessionStatusRef.current = "finalized";
      stopListening();
      if (flushTimerRef.current) { clearInterval(flushTimerRef.current); flushTimerRef.current = null; }
      sessionStreamRef.current?.getTracks().forEach((t) => t.stop());
      sessionStreamRef.current = null;
      const r = await finalizeScribeSession(hospitalId, sessionId, true);
      const note = normalizeNote(r.structured, sessionId);
      setFinalNote(note);
      setFinalSoapText(r.soap_text || "");
      setFinalUsedAi(noteUsedAi(r.structured, r.source, r.ai_available));
      setFinalSource(String(r.source || r.structured?.source || ""));
      setFinalMessage(noteMessage(r.structured, r.message));
      setSessionStatus("finalized");
      sessionStatusRef.current = "finalized";
    } catch (e: unknown) {
      // Still open on the server (for example nothing was captured): keep going.
      sessionStatusRef.current = sessionStatus;
      if (sessionStatus === "recording") attachSessionRecognizer();
      setErrorMsg(humanizeError(apiErrorMessage(e, "")));
    } finally {
      setBusy(null);
    }
  };

  const regenerate = async (sectionName: string) => {
    if (!finalNote) return;
    setRegenSection(sectionName);
    setRegenNote(null);
    try {
      const r = await regenerateScribeSection(hospitalId, {
        structured: finalNote,
        section_name: sectionName,
        specialty: "ed",
      });
      const label = sectionName.replace(/_/g, " ").toLowerCase();
      const msg = noteMessage(r.structured, r.message);
      // The rest of the note is still the AI draft; only this redo did not happen.
      if (r.ai_available === false || aiCallFailed(r.source)) {
        // Only a server with AI off disables redo; one failed call should not.
        setRegenOff(r.ai_available === false && !aiCallFailed(r.source));
        setRegenNote(
          msg ??
            (r.ai_available === false
              ? `AI is off right now, so the ${label} section was not redone. Edit the note text yourself.`
              : `The AI did not answer, so the ${label} section was not redone. Try again later, or edit it yourself.`),
        );
        return;
      }
      setFinalNote(normalizeNote(r.structured, finalNote.session_id));
      setFinalSoapText(r.soap_text || "");
      // A message with a normal answer means the section came back unchanged.
      setRegenNote(msg ?? `The ${label} section was redone. Check it before using the note.`);
    } catch (e: unknown) {
      setErrorMsg(humanizeError(apiErrorMessage(e, "")));
    } finally {
      setRegenSection(null);
    }
  };

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

  if (!patient) {
    return <div className="text-text-muted text-sm py-8">No patient record available.</div>;
  }

  const recording = sessionStatus === "recording";
  const paused = sessionStatus === "paused";
  const verbatim = finalUsedAi === false;
  // Redo needs AI on this server and a note the AI actually drafted.
  const canRedo = !verbatim && !regenOff && !!caps?.llm;
  const partsLabel = `${chunkCount} part${chunkCount === 1 ? "" : "s"} saved`;

  return (
    <div className="space-y-3">
      <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
        <div className="flex items-center gap-2">
          <Mic size={16} className="text-primary shrink-0" aria-hidden="true" />
          <div className="text-xs uppercase tracking-wide text-text-muted font-medium">
            Scribe
          </div>
        </div>
        <h2 className="text-lg font-bold tracking-editorial mt-1">Bedside note for {patient.name}</h2>
        <p className="text-text-muted text-sm mt-0.5">
          Start a session, talk with the patient (or type what was said), then finish to get a
          note. Each line links back to the words it came from.
        </p>
        {caps && !caps.llm && (
          <div className="mt-3">
            <AiOffNote>
              AI drafting is off on this server, so the note keeps the words as they were said and
              leaves the assessment and plan for you to write.
            </AiOffNote>
          </div>
        )}
      </div>

      <div role="status" aria-live="polite" aria-atomic="true">
        {recording && (
          <div className="flex items-center gap-2 rounded-lg bg-error-container px-4 py-2 text-sm text-error">
            <span className="w-2.5 h-2.5 rounded-full bg-error animate-pulse shrink-0" aria-hidden="true" />
            {listening ? "Listening." : "Recording (typing only)."} {partsLabel}. Pause any time; finish when the visit ends.
          </div>
        )}
        {paused && (
          <div className="flex items-center gap-2 rounded-lg bg-warning-container px-4 py-2 text-sm text-warning">
            <Pause size={14} aria-hidden="true" className="shrink-0" />
            Paused. {partsLabel} so far. Resume to keep going.
          </div>
        )}
        {busy && (
          <div className="flex items-center gap-2 rounded-lg bg-primary-dim px-4 py-2 text-sm text-primary">
            <Loader2 size={16} className="animate-spin" aria-hidden="true" />{busy}
          </div>
        )}
      </div>

      {notice && (
        <div className="flex items-start gap-2 rounded-lg bg-surface-low ring-1 ring-line px-4 py-2 text-sm text-ink">
          <Info size={16} className="mt-0.5 shrink-0 text-text-muted" aria-hidden="true" />
          <div className="flex-1">{notice}</div>
        </div>
      )}

      {errorMsg && (
        <div role="alert" className="flex items-start gap-2 rounded-lg bg-error-container px-4 py-2 text-sm text-error">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            aria-label="Dismiss error"
            className="rounded text-xs font-semibold uppercase tracking-wide text-error/70 hover:text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/50"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-xs uppercase tracking-wide text-text-muted font-medium">
            Session
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-text-muted">Parts saved</span>
            <span className="inline-flex items-center justify-center min-w-8 h-7 px-2 rounded-md bg-surface-low font-mono font-semibold text-ink tabular-nums">
              {chunkCount}
            </span>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {(!sessionStatus || sessionStatus === "finalized") && (
            <button
              type="button"
              onClick={startSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-error text-surface-lowest text-sm font-medium hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/50 focus-visible:ring-offset-2 transition-opacity"
            >
              <Mic size={16} aria-hidden="true" />
              {sessionStatus === "finalized" ? "Start a new session" : "Start session"}
            </button>
          )}
          {recording && (
            <button
              type="button"
              onClick={pauseSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-warning-container text-warning text-sm font-medium hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warning/50 focus-visible:ring-offset-2 transition-opacity"
            >
              <Pause size={16} aria-hidden="true" /> Pause
            </button>
          )}
          {paused && (
            <button
              type="button"
              onClick={resumeSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-success-container text-success text-sm font-medium hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success/50 focus-visible:ring-offset-2 transition-opacity"
            >
              <Play size={16} aria-hidden="true" /> Resume
            </button>
          )}
          {(recording || paused) && (
            <button
              type="button"
              onClick={finalizeSession}
              disabled={!!busy}
              className="flex items-center gap-2 h-11 px-4 rounded-md bg-primary text-surface-lowest text-sm font-medium hover:bg-primary-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 transition-colors"
            >
              <Square size={16} aria-hidden="true" /> Finish note
            </button>
          )}
        </div>

        {recording && (
          <div className="mt-4">
            <label htmlFor={typedId} className="block text-xs uppercase tracking-wide text-text-muted font-medium mb-1.5">
              Type what was said
            </label>
            <div className="flex gap-2">
              <input
                id={typedId}
                type="text"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void addTyped();
                  }
                }}
                placeholder="For example: Pain started two hours ago, worse when walking."
                className="flex-1 min-w-0 h-10 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-2 focus:ring-primary text-sm outline-none transition-all"
              />
              <button
                type="button"
                onClick={() => void addTyped()}
                disabled={!typed.trim()}
                className="inline-flex items-center gap-1 h-10 px-3 rounded-md bg-surface-low ring-1 ring-line text-sm font-medium text-ink hover:bg-surface-high disabled:opacity-50"
              >
                <Plus size={14} aria-hidden="true" /> Add
              </button>
            </div>
          </div>
        )}

        {!sessionStatus && (
          <div className="mt-3 text-xs text-text-muted">
            No session yet. Start one to capture the visit.
          </div>
        )}
      </div>

      {finalNote && (
        <>
          <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <ClipboardCheck size={16} className="text-success" aria-hidden="true" />
              <div className="text-xs uppercase tracking-wide text-text-muted font-medium">
                {verbatim ? "Note: the words as spoken" : "Finished note: each line links to what was said"}
              </div>
              <span className="ml-auto">
                <AiSourceTag
                  ai={!verbatim}
                  label={verbatim ? (aiCallFailed(finalSource) ? "No AI used: the AI did not answer" : "No AI used") : undefined}
                />
              </span>
            </div>
            {verbatim && (
              <div className="mb-3">
                <AiOffNote>
                  {finalMessage ||
                    "AI drafting is off, so nothing was reworded or added. Write the assessment and plan yourself before using this note."}
                </AiOffNote>
              </div>
            )}
            {!verbatim && finalMessage && (
              <div className="mb-3">
                <AiOffNote>{finalMessage}</AiOffNote>
              </div>
            )}
            {!verbatim && caps && (regenOff || !caps.llm) && (
              <div className="mb-3">
                <AiOffNote>AI is off right now, so sections cannot be redone. Edit the note text yourself.</AiOffNote>
              </div>
            )}
            {regenNote && (
              <p role="status" className="mb-3 text-[13px] text-text-muted leading-snug">
                {regenNote}
              </p>
            )}
            {finalNote.sections.length === 0 ? (
              <div className="text-sm text-text-muted italic">
                The note came back empty. Start a new session and try again.
              </div>
            ) : (
              finalNote.sections.map((sec) => (
                <SessionNoteSection
                  key={sec.name}
                  section={sec}
                  regenerating={regenSection === sec.name}
                  disabled={!!regenSection || !!busy}
                  canRegenerate={canRedo}
                  onRegenerate={() => regenerate(sec.name)}
                  onPickEvidence={setActiveEvidence}
                />
              ))
            )}
          </div>

          {activeEvidence && (
            <div className="bg-secondary-container rounded-lg p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-secondary font-medium">
                  <Quote size={14} aria-hidden="true" /> Where this line came from
                </div>
                <button
                  type="button"
                  onClick={() => setActiveEvidence(null)}
                  aria-label="Close source detail"
                  className="rounded text-xs font-semibold uppercase tracking-wide text-secondary/70 hover:text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/50"
                >
                  Close
                </button>
              </div>
              {(activeEvidence.begin_ms > 0 || activeEvidence.end_ms > 0) && (
                <div className="mt-1.5 text-xs text-secondary/80">
                  {speakerLabelOf(activeEvidence.speaker)} · {fmtMs(activeEvidence.begin_ms)} to {fmtMs(activeEvidence.end_ms)}
                </div>
              )}
              <div className="mt-1 text-sm text-ink">"{activeEvidence.snippet}"</div>
            </div>
          )}

          {finalSoapText && (
            <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
              <label htmlFor="scribe-final-soap" className="block text-xs uppercase tracking-wide text-text-muted font-medium mb-2">
                Note text to copy
              </label>
              <textarea
                id="scribe-final-soap"
                value={finalSoapText}
                readOnly
                rows={10}
                className="w-full px-3 py-2 rounded-md bg-surface-low font-mono text-sm leading-relaxed text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              />
            </div>
          )}

          {finalNote.transcript_segments.length > 0 && (
            <div className="bg-surface-lowest rounded-lg shadow-soft p-4">
              <div className="text-xs uppercase tracking-wide text-text-muted font-medium mb-2">
                What was said
              </div>
              <div className="text-sm space-y-1 max-h-64 overflow-auto">
                {finalNote.transcript_segments.map((s) => {
                  const label = speakerLabelOf(s.speaker);
                  const isHL = activeEvidence?.segment_id === s.id;
                  return (
                    <div key={s.id} className={`px-2 py-1 rounded transition-colors ${isHL ? "bg-warning-container" : ""}`}>
                      {label && (
                        <span className={`text-xs font-medium mr-2 ${label === "Clinician" ? "text-secondary" : "text-success"}`}>
                          {label}:
                        </span>
                      )}
                      <span className="text-ink">{s.content}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * True only when the server says AI drafted the note. Any fallback ("verbatim_no_ai",
 * "verbatim_ai_failed", "verbatim_guard", "ai_failed") keeps the words as spoken.
 */
function noteUsedAi(
  n: ScribeStructuredNote | null | undefined,
  topSource: string | undefined,
  aiAvailable: boolean | undefined,
): boolean {
  const byAi = writtenByAi(topSource || n?.source, aiAvailable);
  return byAi === true;
}

/** A plain message from the server about how the note was built, if any. */
function noteMessage(n: ScribeStructuredNote | null | undefined, topLevel: unknown): string | null {
  if (typeof topLevel === "string" && topLevel.trim()) return topLevel;
  const inner = (n as { message?: unknown } | null | undefined)?.message;
  if (typeof inner === "string" && inner.trim()) return inner;
  if (n?.error && /key|not configured|unavailable/i.test(n.error)) {
    return "AI drafting is off on this server, so the note could not be written for you.";
  }
  return null;
}

// Minimal Web Speech typings: the API is not in the default lib.dom yet.
type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechResultEvent = {
  resultIndex: number;
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
};
type SpeechWindow = {
  SpeechRecognition?: { new (): SpeechRecognitionLike };
  webkitSpeechRecognition?: { new (): SpeechRecognitionLike };
};

// Small UI helpers, kept inline so the tab stays self-contained.

/** Coerce a finalize/regenerate payload into a full note so a missing or
 *  malformed field from the server can never crash the render. */
function normalizeNote(
  n: ScribeStructuredNote | null | undefined,
  sessionId: string,
): ScribeStructuredNote {
  const sections = n && Array.isArray(n.sections) ? n.sections : [];
  const segments = n && Array.isArray(n.transcript_segments) ? n.transcript_segments : [];
  return {
    session_id: n?.session_id ?? sessionId,
    sections,
    transcript_segments: segments,
    source: n?.source,
    error: n?.error,
  };
}

/** Turn a backend / network error string into something a clinician can read. */
function humanizeError(raw: string): string {
  if (!raw) return "Something went wrong. Please try again.";
  const s = String(raw);
  if (/could not reach the server|network|timeout/i.test(s)) return "The connection dropped. Check it and try again.";
  if (/rate.?limit|too many requests|429/i.test(s)) return "Too many requests in a row. Please wait a moment and try again.";
  if (/Consent required/i.test(s)) return "The patient has to agree before their voice is processed.";
  if (/no transcript|empty transcript|returned empty|empty_session/i.test(s)) {
    return "Nothing was captured yet. Speak near the microphone or type a line, then finish the note.";
  }
  if (/unknown scribe session/i.test(s)) return "This session is no longer open. Start a new session to keep going.";
  if (/permission/i.test(s)) return s; // already user-friendly
  if (s.length > 220) return "The system couldn't complete that request. Please try again.";
  return s;
}

/** Turn a raw speaker tag into a label. Untagged text (typed or no AI) gets none. */
function speakerLabelOf(speaker: string): string {
  const s = (speaker || "").toLowerCase();
  if (s.includes("clinic") || s.includes("doctor") || s.includes("nurse")) return "Clinician";
  if (s.includes("patient")) return "Patient";
  return "";
}

/** Format a millisecond offset into a compact m:ss timestamp. */
function fmtMs(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * One section of the finished note: each line with chips that jump to the words
 * it came from, a bar for how many lines are linked, and (with AI) a redo button.
 */
function SessionNoteSection({
  section,
  regenerating,
  disabled,
  canRegenerate,
  onRegenerate,
  onPickEvidence,
}: {
  section: ScribeSessionSection;
  regenerating: boolean;
  disabled: boolean;
  canRegenerate: boolean;
  onRegenerate: () => void;
  onPickEvidence: (e: LinkedEvidence) => void;
}) {
  const coveragePct = Math.round((section.evidence_coverage || 0) * 100);
  // Green when most lines are linked, amber when some are, red when few are.
  const tone =
    coveragePct >= 80 ? { bar: "bg-success", text: "text-success" } :
    coveragePct >= 50 ? { bar: "bg-warning", text: "text-warning" } :
    { bar: "bg-error", text: "text-error" };
  const sectionLabel = (section.name || "section").replace(/_/g, " ").toLowerCase();
  const lines = section.lines || [];
  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm font-semibold text-ink capitalize">{sectionLabel}</div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5" title="Share of lines linked to something that was said">
            <div className="w-20 h-1.5 rounded bg-surface-high overflow-hidden">
              <div className={`h-full ${tone.bar}`} style={{ width: `${Math.min(100, coveragePct)}%` }} />
            </div>
            <span className={`text-xs font-medium tabular-nums ${tone.text}`}>{coveragePct}% linked</span>
          </div>
          {canRegenerate && (
            <button
              type="button"
              onClick={onRegenerate}
              disabled={disabled}
              aria-label={`Redo the ${sectionLabel} section with AI`}
              className="flex items-center gap-1 h-8 px-2 rounded text-xs font-medium bg-surface-low text-text-muted hover:bg-surface-high disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 transition-colors"
            >
              {regenerating
                ? <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                : <RefreshCw size={12} aria-hidden="true" />}
              {regenerating ? "Redoing" : "Redo"}
            </button>
          )}
        </div>
      </div>
      <div className="mt-1.5 space-y-2">
        {lines.length === 0 && (
          <div className="text-sm text-text-muted italic">Nothing captured for this section.</div>
        )}
        {lines.map((line, i) => {
          const evidence = line.linked_evidence || [];
          return (
          <div key={i} className="text-sm">
            <div className="text-ink">{line.text}</div>
            {evidence.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {evidence.map((ev, j) => {
                  const who = speakerLabelOf(ev.speaker);
                  const timed = ev.begin_ms > 0 || ev.end_ms > 0;
                  return (
                    <button
                      key={`${ev.segment_id}-${j}`}
                      type="button"
                      onClick={() => onPickEvidence(ev)}
                      title={ev.snippet}
                      aria-label={`Show where this line came from: ${ev.snippet}`}
                      className="inline-flex items-center gap-1 max-w-full px-1.5 py-0.5 rounded border border-secondary/40 bg-secondary-container text-[12px] text-secondary hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/50 transition-opacity"
                    >
                      <Quote size={10} className="shrink-0" aria-hidden="true" />
                      <span className="font-medium">{who || `Part ${ev.segment_id + 1}`}</span>
                      {timed && <span className="tabular-nums opacity-70">{fmtMs(ev.begin_ms)}</span>}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="mt-1 inline-flex items-center gap-1 text-[12px] text-warning">
                <AlertTriangle size={10} aria-hidden="true" />
                Not linked to anything that was said: check it before using the note.
              </div>
            )}
          </div>
          );
        })}
      </div>
    </div>
  );
}
