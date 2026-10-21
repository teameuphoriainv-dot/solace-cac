/**
 * Every server call the patient's phone makes: check-in (with the red-flag
 * checklist), result polling, card scans, "I feel worse", and texting the
 * instructions.
 *
 * Shares the axios instance from ./api (same base URL and interceptors).
 */
import { api } from "./api";
import type {
  InsuranceFields,
  IntakeResponse,
  PublicPatient,
  TranscribeResponse,
} from "../types";

type Multipart = { headers: { "Content-Type": "multipart/form-data" } };
const multipart: Multipart = { headers: { "Content-Type": "multipart/form-data" } };

// --- Check-in -------------------------------------------------------------------

export async function startIntake(
  hospitalId: string,
): Promise<{ token: string; expires_at: number }> {
  const { data } = await api.post(`/api/${hospitalId}/start-intake`);
  return data;
}

export async function postTranscribe(hospitalId: string, form: FormData): Promise<TranscribeResponse> {
  const { data } = await api.post<TranscribeResponse>(`/api/${hospitalId}/transcribe`, form, multipart);
  return data;
}

// --- Red-flag checklist ---------------------------------------------------------

/** The checklist ids, in screen order. The server knows the same ids. */
export const RED_FLAG_IDS = [
  "breathing", "chest", "faint", "confusion", "bleeding",
  "self_harm", "ingestion", "pregnancy", "stroke", "infant_fever", "none",
] as const;

export type RedFlagId = (typeof RED_FLAG_IDS)[number];

/** Adds the patient's checklist taps to the intake form as a JSON array of known ids. */
export function appendRedFlags(form: FormData, flags: readonly string[]): void {
  const clean = RED_FLAG_IDS.filter((id) => flags.includes(id));
  if (clean.length > 0) form.append("red_flags", JSON.stringify(clean));
}

export async function postIntake(hospitalId: string, form: FormData): Promise<IntakeResponse> {
  const { data } = await api.post<IntakeResponse>(`/api/${hospitalId}/intake`, form, multipart);
  return data;
}

export async function getPublicPatient(hospitalId: string, patientId: string): Promise<PublicPatient> {
  const { data } = await api.get<PublicPatient>(`/api/${hospitalId}/public-patients/${patientId}`);
  return data;
}

/** What the result screen follows after check-in: the score the queue acts on now. */
export type LiveStatus = {
  /** The priority to act on now, 1 to 5 (never less urgent than at check-in). Null when the server did not say. */
  level: number | null;
  /** The priority the patient was given at check-in. Null when the server did not say. */
  checkinLevel: number | null;
  /** A nurse re-checked this patient after check-in. */
  rechecked: boolean;
  /**
   * The server rebuilds the explanation, the care card and the comfort cards for a
   * raised priority itself (it sends raised_by_recheck). Older servers do not.
   */
  serverRebuilds: boolean;
  /** The re-check made the priority more urgent (and the server rebuilt the screen for it). */
  raised: boolean;
  /** "now" means show a sentence instead of minutes (priority 1 or 2, or crisis). Null when the server did not say. */
  waitKind: string | null;
};

function levelOf(v: unknown): number | null {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
}

/**
 * Reads the live fields from a public patient answer (routers/patients.py
 * get_public_patient: esi_level is the level to act on now, checkin_esi_level what
 * the patient was told at check-in, rechecked_by_nurse, raised_by_recheck,
 * wait_kind). Older servers send none of them, so every field is optional.
 */
export function liveStatus(p: PublicPatient): LiveStatus {
  const r = p as PublicPatient & Record<string, unknown>;
  const refined = levelOf(r.refined_esi_level);
  const checkinLevel = levelOf(r.checkin_esi_level);
  const level = levelOf(r.current_esi_level) ?? (checkinLevel === null ? refined : null) ?? levelOf(r.esi_level);
  const flag = r.rechecked_by_nurse ?? r.rechecked;
  const rechecked =
    typeof flag === "boolean" ? flag : refined !== null || (typeof r.rechecked_at === "string" && !!r.rechecked_at);
  const kind = typeof r.wait_kind === "string" && r.wait_kind.trim() ? r.wait_kind.trim() : null;
  return {
    level,
    checkinLevel,
    rechecked,
    serverRebuilds: typeof r.raised_by_recheck === "boolean",
    raised: r.raised_by_recheck === true,
    waitKind: kind,
  };
}

/** Raises the "feels worse" flag on the nurse dashboard. The API field is still called pain_flag. */
export async function postPainFlag(hospitalId: string, patientId: string): Promise<void> {
  await api.post(`/api/${hospitalId}/pain-flag`, { patient_id: patientId });
}

/** HTTP status of a failed axios call, or undefined for a network error. */
export function errorStatus(e: unknown): number | undefined {
  return (e as { response?: { status?: number } })?.response?.status;
}

/** The plain-string `detail` the backend puts on 4xx/5xx responses. */
export function errorDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "";
}

/** True when the backend does not know this hospital id (a mistyped or old link). */
export function isUnknownHospital(e: unknown): boolean {
  return errorStatus(e) === 404 && /unknown hospital/i.test(errorDetail(e));
}

// --- ID and insurance cards -----------------------------------------------------

export type IdFields = {
  first_name: string;
  last_name: string;
  dob: string;
  license_number: string;
  issuing_state: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  expiry: string;
  sex: string;
};

/** error is "ocr_unavailable" when card reading is off (no AI key). */
export type IdScanResult = { success: boolean; fields?: IdFields; error?: string; ai_available?: boolean };
export type InsuranceScanResult = {
  success: boolean;
  fields?: InsuranceFields;
  error?: string;
  ai_available?: boolean;
};

export async function scanID(hospitalId: string, imageFile: File): Promise<IdScanResult> {
  const form = new FormData();
  form.append("image_file", imageFile);
  const { data } = await api.post(`/api/${hospitalId}/scan-id`, form, multipart);
  return data;
}

export async function scanInsurance(
  hospitalId: string,
  imageFile: File,
  consentGranted = true,
): Promise<InsuranceScanResult> {
  const form = new FormData();
  form.append("image_file", imageFile);
  form.append("consent_granted", consentGranted ? "true" : "false");
  const { data } = await api.post(`/api/${hospitalId}/scan-insurance`, form, multipart);
  return data;
}

/** The made-up sample ID from the demo records. No photo, no AI. */
export async function scanIdSample(hospitalId: string): Promise<IdScanResult> {
  const { data } = await api.post(`/api/${hospitalId}/scan-id/sample`);
  return data;
}

/** The made-up sample insurance card from the demo records. No photo, no AI. */
export async function scanInsuranceSample(hospitalId: string): Promise<InsuranceScanResult> {
  const { data } = await api.post(`/api/${hospitalId}/scan-insurance/sample`);
  return data;
}

export type IdentityLookupResult = {
  matched: boolean;
  match_method?: string;
  reason?: string;
  ehr_record?: {
    name: string;
    mrn: string;
    dob: string;
    sex: string;
    fhir_id?: string;
    allergies?: string[];
    medications?: string[];
    conditions?: string[];
    insurance?: string;
    primary_care_provider?: string;
    source?: string;
  };
  prefill?: {
    age: number | null;
    sex: "male" | "female" | "other" | null;
    allergies: string[];
    medications: string[];
    conditions: string[];
    insurance_hint?: string;
    emergency_contact?: string;
    primary_care_provider?: string;
    prior_visits_count?: number;
  };
};

export type IdentityLookupBody = {
  first_name?: string;
  last_name?: string;
  dob?: string;
  license_number?: string;
  issuing_state?: string;
  insurance_member_id?: string;
  insurance_provider?: string;
};

/** Looks for a returning patient in the demo hospital's made-up records. */
export async function identityLookup(
  hospitalId: string,
  body: IdentityLookupBody,
): Promise<IdentityLookupResult> {
  const { data } = await api.post<IdentityLookupResult>(`/api/${hospitalId}/identity/lookup`, body);
  return data;
}

// --- Texting the care instructions ------------------------------------------------

export type CareTextResult = {
  /** A real text went out. Only possible when texting is configured on the server. */
  sent: boolean;
  /** The exact message body that was (or would have been) sent. */
  preview: string;
  reason?: string;
};

export async function sendCareInstructions(
  hospitalId: string,
  patientId: string,
  phone: string,
): Promise<CareTextResult> {
  const { data } = await api.post(`/api/${hospitalId}/sms/care-instructions`, {
    patient_id: patientId,
    phone,
  });
  // Older servers answered {success, reason} with no preview.
  return {
    sent: Boolean(data?.sent ?? data?.success),
    preview: typeof data?.preview === "string" ? data.preview : "",
    reason: data?.reason || undefined,
  };
}
