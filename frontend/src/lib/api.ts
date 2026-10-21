import axios from "axios";
import { clearSession, hasStoredSession, notifySessionExpired } from "./session";
import type {
  ClinicianNote,
  JsonObject,
  MedicalInfo,
  PatientDetail,
  PatientEducation,
  PatientSummary,
  Prescription,
  PrescriptionSuggestion,
  RefinedTriage,
  Vitals,
} from "../types";

// Server calls for the nurse side. The patient's phone uses ./api-patient, which
// shares this axios instance.
//
// If VITE_API_BASE_URL is empty, axios uses relative URLs: same origin, either the
// FastAPI server that also serves the built app or Vite's dev proxy.
const BASE_URL =
  import.meta.env.VITE_API_BASE_URL !== undefined && import.meta.env.VITE_API_BASE_URL !== ""
    ? import.meta.env.VITE_API_BASE_URL
    : "";

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 120_000,
});

// Attach the clinician's Bearer token on every request. localStorage is the main
// store; sessionStorage is read for sessions saved by older builds.
api.interceptors.request.use((config) => {
  try {
    const raw =
      localStorage.getItem("solace.session.v1") ??
      sessionStorage.getItem("solace.session.v1");
    if (raw) {
      const sess = JSON.parse(raw);
      if (sess?.token) {
        config.headers = config.headers ?? {};
        (config.headers as Record<string, string>).Authorization = `Bearer ${sess.token}`;
      }
    }
  } catch {
    /* ignore */
  }
  return config;
});

// The PIN sign-in endpoint answers a wrong PIN with 401, and the sign-in form shows
// "Incorrect name or PIN". Treating that 401 as an expired session would clear the
// form it came from, so it is the one path the handler below skips.
const AUTH_CHALLENGE_PATH = /\/auth\/login(\?|$)/;

// One place reacts to an expired token: it clears the session and tells the
// clinician shell to show the sign-in screen.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const url: string = error?.config?.url ?? "";
    // Only meaningful if the request went out as a signed-in clinician.
    if (status === 401 && hasStoredSession() && !AUTH_CHALLENGE_PATH.test(url)) {
      clearSession();
      notifySessionExpired();
    }
    // Always re-reject: callers keep their own catch blocks and error UI.
    return Promise.reject(error);
  },
);

/**
 * A plain-English message for any thrown request error.
 *
 * FastAPI returns `detail` as a string for our own errors but as a list of
 * objects for validation errors, and React cannot render an object. This always
 * returns a string, so it is safe to drop straight into JSX.
 */
export function apiErrorMessage(e: unknown, fallback: string): string {
  const err = e as { response?: { data?: { detail?: unknown; message?: unknown } } };
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) =>
        typeof d === "string"
          ? d
          : d && typeof d === "object" && "msg" in d
            ? String((d as { msg: unknown }).msg)
            : "",
      )
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const m = (detail as { message: unknown }).message;
    if (typeof m === "string" && m.trim()) return m;
  }
  const message = err?.response?.data?.message;
  if (typeof message === "string" && message.trim()) return message;
  if (axios.isAxiosError(e) && !e.response) {
    return "Could not reach the server. Check the connection and try again.";
  }
  return fallback;
}

// ---- Clinician sign-in and the demo ------------------------------------------------

export async function loginClinician(
  hospitalId: string,
  clinicianName: string,
  pin: string
): Promise<{
  token: string;
  clinician_id: string;
  name: string;
  role: string;
  hospital_id: string;
  expires_at: number;
}> {
  const { data } = await api.post(`/api/${hospitalId}/auth/login`, {
    clinician_name: clinicianName,
    pin,
  });
  return data;
}

/** `message` is a plain sentence about what was removed and restored. */
type ResetDemoResult = {
  success?: boolean;
  message?: string;
  restored_patients?: number;
  deleted_test_patients?: string[];
  cleared_canonical_patients?: string[];
  failed_patients?: string[];
};

export async function resetDemo(hospitalId: string): Promise<ResetDemoResult> {
  const { data } = await api.post<ResetDemoResult>(`/api/${hospitalId}/admin/reset-demo`, {});
  return data;
}

// ---- Queue and patient record ------------------------------------------------------

export async function getPatients(
  hospitalId: string,
  status: "waiting" | "all" = "waiting"
): Promise<{ patients: PatientSummary[] }> {
  const { data } = await api.get(`/api/${hospitalId}/patients`, {
    params: { status },
  });
  return data;
}

export async function getPatientDetail(
  hospitalId: string,
  patientId: string,
): Promise<PatientDetail> {
  const { data } = await api.get<PatientDetail>(`/api/${hospitalId}/patients/${patientId}`);
  return data;
}

export async function markSeen(
  hospitalId: string,
  patientId: string,
  clinicianName: string
): Promise<void> {
  await api.patch(
    `/api/${hospitalId}/patients/${patientId}/resolve`,
    { clinician_name: clinicianName },
  );
}

export async function acknowledgePainFlag(
  hospitalId: string,
  patientId: string,
): Promise<void> {
  await api.post(
    `/api/${hospitalId}/pain-flag/acknowledge`,
    { patient_id: patientId },
  );
}

export async function refineTriage(
  hospitalId: string,
  patientId: string,
  vitals: Vitals,
): Promise<RefinedTriage> {
  const { data } = await api.post<{ success: boolean; refinement: RefinedTriage; applied_at: string }>(
    `/api/${hospitalId}/patients/${patientId}/refine-triage`,
    vitals,
  );
  return data.refinement;
}

// ---- Notes and the patient summary -------------------------------------------------

export async function createNote(
  hospitalId: string,
  patientId: string,
  text: string,
  author = "Clinician"
): Promise<ClinicianNote> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/notes`,
    { text, author },
  );
  return data.note;
}

/**
 * `ai_available` is false when the summary was built from the clinician's own
 * note without AI rewording; `source` then names the template.
 */
type PublishSummaryResult = {
  summary: PatientEducation | null;
  ai_available?: boolean;
  source?: string;
  message?: string;
};

export async function publishPatientSummary(
  hospitalId: string,
  patientId: string,
  noteId?: string
): Promise<PublishSummaryResult> {
  const { data } = await api.post<PublishSummaryResult>(
    `/api/${hospitalId}/patients/${patientId}/publish-summary`,
    noteId ? { note_id: noteId } : {},
  );
  return { ...data, summary: data?.summary ?? null };
}

// ---- Prescriptions -----------------------------------------------------------------

/** One allergy or interaction alert from the server's medicine checker. */
export type SafetyAlert = {
  severity?: string;
  reason?: string;
  guidance?: string;
  med?: string;
  a?: string;
  b?: string;
  [key: string]: unknown;
};

/** Result of checking a prescription against the patient's allergies and medicines. */
export type PrescriptionSafety = {
  any_high?: boolean;
  drug_drug?: SafetyAlert[];
  drug_allergy?: SafetyAlert[];
  renal?: SafetyAlert[];
  hepatic?: SafetyAlert[];
  duplicate_therapy?: SafetyAlert[];
  summary?: { highest_severity?: string };
  /** One plain sentence per alert, most serious first. */
  alerts?: { severity?: string; message?: string }[];
  /** What the checker covers (a built-in list, not every drug). */
  note?: string;
};

export type SuggestionWithSafety = PrescriptionSuggestion & { safety?: PrescriptionSafety | null };

type SuggestResult = {
  suggestions: SuggestionWithSafety[];
  ai_available?: boolean;
  message?: string;
};

export async function listPrescriptions(
  hospitalId: string,
  patientId: string,
): Promise<Prescription[]> {
  const { data } = await api.get(`/api/${hospitalId}/patients/${patientId}/prescriptions`);
  return data.prescriptions || [];
}

export async function suggestPrescriptions(
  hospitalId: string,
  patientId: string,
): Promise<SuggestResult> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/prescriptions/suggest`,
    {},
  );
  return {
    suggestions: Array.isArray(data?.suggestions) ? data.suggestions : [],
    ai_available: data?.ai_available,
    message: typeof data?.message === "string" ? data.message : undefined,
  };
}

export async function createPrescription(
  hospitalId: string,
  patientId: string,
  body: Partial<Prescription> & { drug: string }
): Promise<{ prescription: Prescription; safety: PrescriptionSafety | null }> {
  const { data } = await api.post(
    `/api/${hospitalId}/patients/${patientId}/prescriptions`,
    body,
  );
  return { prescription: data.prescription, safety: data.safety ?? null };
}

// ---- Reasoning (possible diagnoses) ------------------------------------------------

type DdxItem = {
  diagnosis: string;
  icd10: string;
  weight: number;
  rule_in: string[];
  rule_out: string[];
  must_not_miss: boolean;
  next_step: string;
  evidence_quote: string;
};

export type DdxResult = {
  differential: DdxItem[];
  counterfactuals: { if_true: string; would_change: string }[];
  red_flags: { diagnosis: string; icd10: string }[];
  conformal: { set_90: string[]; set_95: string[] };
  /** False when the server has no AI key; `message` then says what is off. */
  ai_available?: boolean;
  message?: string;
};

export async function ddxV2(
  hospitalId: string,
  body: { transcript: string; chief_complaint?: string; specialty?: string; medical_info?: MedicalInfo; vitals?: Vitals }
): Promise<DdxResult> {
  const { data } = await api.post<DdxResult>(`/api/${hospitalId}/ddx/v2`, body);
  return {
    ...data,
    differential: Array.isArray(data?.differential) ? data.differential : [],
    red_flags: Array.isArray(data?.red_flags) ? data.red_flags : [],
    counterfactuals: Array.isArray(data?.counterfactuals) ? data.counterfactuals : [],
    conformal: {
      set_90: data?.conformal?.set_90 ?? [],
      set_95: data?.conformal?.set_95 ?? [],
    },
  };
}

// ---- Early warning scores (no AI, always available) --------------------------------

export type EwsContribution = { feature: string; points: number; why: string; source?: string };

/** Shared head of both early-warning responses (backend/services/early_warning.py). */
export type EwsResult = {
  score: number;
  band: string;
  action: string;
  contributions: EwsContribution[];
};

/** The sepsis score also carries a short note on how it was calibrated. */
export type SepsisEwsResult = EwsResult & { calibration_note: string };

export async function sepsisEws(hospitalId: string, vitals: JsonObject): Promise<SepsisEwsResult> {
  const { data } = await api.post<SepsisEwsResult>(`/api/${hospitalId}/ews/sepsis`, vitals);
  return data;
}

/**
 * Accepts the flat vitals the card sends (hr, rr, sbp, spo2, temp_c, gcs, on_oxygen,
 * wbc) and/or `vitals_now`. The card sends both so it works with either server.
 */
export async function deteriorationIndex(hospitalId: string, body: JsonObject): Promise<EwsResult> {
  const { data } = await api.post<EwsResult>(`/api/${hospitalId}/ews/deterioration`, body);
  return data;
}
