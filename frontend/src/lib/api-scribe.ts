// Typed client for the bedside scribe: POST /api/{hospitalId}/scribe/session/* and
// /scribe/regenerate-section. Uses the shared axios instance so the clinician's
// sign-in token rides along.
import { api } from "./api";

// ---- Shared shapes ---------------------------------------------------------

/** Status a scribe recording session can be in, server-authoritative. */
export type ScribeSessionStatus = "recording" | "paused" | "finalized";

/** One piece of conversation evidence linked to a generated note line. */
export type LinkedEvidence = {
  segment_id: number;
  begin_ms: number;
  end_ms: number;
  speaker: string;
  snippet: string;
};

/** A single generated line within a SOAP section, with its source evidence. */
type ScribeNoteLine = {
  text: string;
  linked_evidence: LinkedEvidence[];
};

/** One SOAP section (Subjective / Objective / Assessment / Plan, etc.). */
export type ScribeSessionSection = {
  name: string;
  lines: ScribeNoteLine[];
  /** 0..1 share of lines in this section that carry at least one evidence link. */
  evidence_coverage: number;
};

/** A diarized chunk of the recorded conversation. */
type ScribeTranscriptSegment = {
  id: number;
  speaker: string;
  begin_ms: number;
  end_ms: number;
  content: string;
};

/**
 * The structured note returned on finalize / regenerate. With no AI key the
 * server returns the words as spoken, and `source` is "verbatim_no_ai".
 */
export type ScribeStructuredNote = {
  sections: ScribeSessionSection[];
  transcript_segments: ScribeTranscriptSegment[];
  session_id: string;
  source?: string;
  error?: string;
};

// ---- Response shapes -------------------------------------------------------

type ScribeSessionStartResponse = {
  session_id: string;
  specialty: string;
  status: "recording";
  ai_available?: boolean;
};

type ScribeSessionStateResponse = {
  session_id: string;
  status: ScribeSessionStatus;
  chunk_count: number;
};

/** `message` is a plain note on how the note was built (for example, AI is off). */
type ScribeFinalizeResponse = {
  structured: ScribeStructuredNote;
  soap_text: string;
  ai_available?: boolean;
  source?: string;
  message?: string;
};

type ScribeRegenerateResponse = ScribeFinalizeResponse;

// ---- Endpoint wrappers -----------------------------------------------------

/** Open a new chunked-recording session (or resume a known session_id). */
export async function startScribeSession(
  hospitalId: string,
  body: { specialty?: string; session_id?: string } = {},
): Promise<ScribeSessionStartResponse> {
  const { data } = await api.post<ScribeSessionStartResponse>(
    `/api/${hospitalId}/scribe/session/start`,
    body,
  );
  return data;
}

/** Append one transcribed chunk of conversation to an active session. */
export async function appendScribeChunk(
  hospitalId: string,
  body: { session_id: string; chunk: string },
): Promise<ScribeSessionStateResponse> {
  const { data } = await api.post<ScribeSessionStateResponse>(
    `/api/${hospitalId}/scribe/session/append`,
    body,
  );
  return data;
}

/** Pause an active session: it stops accepting chunks until resumed. */
export async function pauseScribeSession(
  hospitalId: string,
  sessionId: string,
): Promise<ScribeSessionStateResponse> {
  const { data } = await api.post<ScribeSessionStateResponse>(
    `/api/${hospitalId}/scribe/session/pause`,
    { session_id: sessionId },
  );
  return data;
}

/** Resume a paused session back into the recording state. */
export async function resumeScribeSession(
  hospitalId: string,
  sessionId: string,
): Promise<ScribeSessionStateResponse> {
  const { data } = await api.post<ScribeSessionStateResponse>(
    `/api/${hospitalId}/scribe/session/resume`,
    { session_id: sessionId },
  );
  return data;
}

/** Close the session and generate the structured, evidence-linked SOAP note. */
export async function finalizeScribeSession(
  hospitalId: string,
  sessionId: string,
  refineNote = true,
): Promise<ScribeFinalizeResponse> {
  const { data } = await api.post<ScribeFinalizeResponse>(
    `/api/${hospitalId}/scribe/session/finalize`,
    { session_id: sessionId, refine_note: refineNote },
  );
  return data;
}

/** Regenerate a single SOAP section in place, leaving the rest of the note intact. */
export async function regenerateScribeSection(
  hospitalId: string,
  body: { structured: ScribeStructuredNote; section_name: string; specialty?: string },
): Promise<ScribeRegenerateResponse> {
  const { data } = await api.post<ScribeRegenerateResponse>(
    `/api/${hospitalId}/scribe/regenerate-section`,
    body,
  );
  return data;
}
