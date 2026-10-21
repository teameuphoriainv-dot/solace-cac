/**
 * Open-ended JSON payload for the clinical tool endpoints. The chart context is
 * passed straight through to the backend, so the field set is not fixed; `unknown`
 * still forces a narrow or a cast where a value is used.
 */
export type JsonObject = Record<string, unknown>;

/**
 * Minimal type surface for the Web Speech API. It is not in lib.dom.d.ts on every
 * TypeScript version and is still prefixed on WebKit, so this declares only what the
 * scribe and recorder use.
 */
export type SpeechRecognitionAlternative = {
  transcript: string;
  confidence: number;
};

export type SpeechRecognitionResult = {
  readonly length: number;
  readonly isFinal: boolean;
  [index: number]: SpeechRecognitionAlternative;
};

export type SpeechRecognitionEvent = {
  readonly resultIndex: number;
  readonly results: {
    readonly length: number;
    [index: number]: SpeechRecognitionResult;
  };
};

export type SpeechRecognitionErrorEvent = {
  readonly error: string;
  readonly message?: string;
};

export type SpeechRec = {
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: (e: SpeechRecognitionEvent) => void;
  onerror: (e: SpeechRecognitionErrorEvent) => void;
  onend: () => void;
  continuous: boolean;
  interimResults: boolean;
  lang: string;
};

/** Window as seen by browsers that expose Web Speech, prefixed or not. */
export type SpeechWindow = Window &
  typeof globalThis & {
    SpeechRecognition?: new () => SpeechRec;
    webkitSpeechRecognition?: new () => SpeechRec;
  };

/** Safari still only exposes the prefixed AudioContext constructor. */
export type AudioContextWindow = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

export type ComfortAction = {
  title: string;
  instruction: string;
  icon: string;
};

export type Sex = "male" | "female" | "other";

export type MedicalInfo = {
  age: number | null;
  sex: Sex | null;
  pregnant: boolean | null;
  gestational_weeks: number | null;
  allergies: string[];
  allergy_severity: Record<string, "mild" | "moderate" | "anaphylaxis">;
  medications: string[];
  blood_thinner_name: string | null;
  conditions: string[];
  diabetes_type: "type1" | "type2" | "gestational" | null;
  heart_failure_class: "I" | "II" | "III" | "IV" | null;
  smoker: boolean | null;
};

export type FollowupQuestion =
  | { id: string; question: string; type: "boolean" }
  | { id: string; question: string; type: "choice"; options: string[] }
  | { id: string; question: string; type: "text" };

export type FollowupAnswer = {
  id: string;
  question: string;
  answer: string;
};

export type TranscribeResponse = {
  transcript: string;
  language: string;
  followups: FollowupQuestion[];
  /** Show the red-flag checklist. False only when the rules already put the check-in at ESI 1 or 2. Missing means show it. */
  red_flag_checklist?: boolean;
};

export type IntakeResponse = {
  patient_id: string;
  esi_level: 1 | 2 | 3 | 4 | 5;
  esi_label: string;
  patient_explanation: string;
  /** esi1 | esi2 | esi3 | esi4 | crisis | needs_reading. The screen's i18n key is result_explain_<key>. */
  explanation_key?: string;
  /** Language patient_explanation is written in. */
  explanation_language?: string;
  comfort_protocol: ComfortAction[];
  audio_url: string | null;
  confidence_band: string | null;
  language: string;
  care_recommendation?: {
    destination: "ed_now" | "ed" | "urgent" | "telehealth" | "self_care" | "schedule";
    label: string;
    rationale: string;
    action_cta: string;
    severity: "critical" | "high" | "moderate" | "low";
    /** now | crisis | high | today | wait (services/care_routing.py). The screen's i18n keys are care_<kind>_*. */
    kind?: string;
    /** Language the label, rationale, steps and note are written in. */
    language?: string;
    next_steps?: string[];
    capacity_note?: string;
  };
};

export type PatientSummary = {
  patient_id: string;
  name: string;
  esi_level: 1 | 2 | 3 | 4 | 5;
  esi_label: string;
  esi_confidence: number | null;
  confidence_band: string | null;
  clinician_prebrief: string;
  language: string;
  pain_flagged: boolean;
  pain_flagged_at: string | null;
  pain_flag_acknowledged_at?: string | null;
  pain_flag_acknowledged_by?: string | null;
  status: "waiting" | "seen";
  seen_by: string | null;
  seen_at: string | null;
  created_at: string;
  waited_minutes: number;
  refined_esi_level?: number | null;
  refined_confidence?: number | null;
  refined_at?: string | null;
  /** The score the queue acts on: the bedside re-check when there is one. */
  current_esi_level?: number | null;
  /** What the bedside model said before the safety rules (queue chip). */
  refined_model_esi_level?: number | null;
  refined_safety_floor_reasons?: string[] | null;
  /** The check-in model's own top pick (null when no model ran at check-in). */
  checkin_model_esi_level?: number | null;
  /** True when a safety rule, not the model, set the check-in score. esi_confidence is then null. */
  checkin_set_by_rules?: boolean;
  /** Plain name of that rule, e.g. "Chest pain or pressure". */
  checkin_rule_name?: string | null;
};

export type InsuranceFields = {
  provider: string | null;
  plan_name: string | null;
  member_id: string | null;
  group_number: string | null;
  name_on_card: string | null;
  bin: string | null;
  pcn: string | null;
  rx_group: string | null;
  effective_date: string | null;
  phone: string | null;
};

export type Prescription = {
  prescription_id: string;
  patient_id: string;
  hospital_id: string;
  drug: string;
  dose: string;
  route: string;
  frequency: string;
  duration: string;
  indication: string;
  cautions: string;
  prescribed_by: string;
  prescribed_at: string;
  source: "manual" | "ai_suggested_accepted" | "ai_suggested";
  /** Saved allergy and interaction check: the worst severity, and one sentence per alert. */
  safety_highest?: string;
  safety_alerts?: string[];
};

export type PrescriptionSuggestion = Omit<
  Prescription,
  "prescription_id" | "patient_id" | "hospital_id" | "prescribed_at" | "prescribed_by" | "source"
>;

export type ClinicianNote = {
  note_id: string;
  patient_id: string;
  hospital_id: string;
  text: string;
  author: string;
  created_at: string;
};

export type PatientEducation = {
  headline: string;
  what_we_are_doing: string;
  things_to_do_at_home: string[];
  when_to_come_back: string;
  closing: string;
  /** False when the summary is the clinician's note without AI rewording. */
  ai_available?: boolean;
  source?: string;
  /** Which heading fits things_to_do_at_home: the no-AI summary carries the waiting-room steps. */
  steps_heading?: "at_home" | "while_you_wait";
};

export type Vitals = {
  systolic_bp?: number | null;
  diastolic_bp?: number | null;
  heart_rate?: number | null;
  respiratory_rate?: number | null;
  temperature_c?: number | null;
  spo2?: number | null;
  gcs_total?: number | null;
  pain_score?: number | null;
  mental_status?: string | null;
  weight_kg?: number | null;
  height_cm?: number | null;
  news2_score?: number | null;
};

export type RefinedTriage = {
  esi_level: number;
  /** Null when the safety rules raised the score or no model is installed. */
  confidence: number | null;
  probabilities: Record<string, number>;
  conformal_set: number[];
  conformal_q_hat: number | null;
  top_features: {
    /** Plain label, e.g. "Heart rate over 100". */
    feature: string;
    value: number;
    shap?: number;
    direction?: "increases" | "decreases";
    weight?: number;
    /** The model's own feature name. */
    code?: string;
    kind?: "measure" | "flag" | "category" | "text";
  }[];
  source: string;
  model_metrics?: { oof_qwk?: number; oof_accuracy?: number };
  dataset?: string;
  training_data_note?: string;
  /** The model's own pick before the safety rules (null in rules-only mode). */
  model_esi_level?: number | null;
  model_confidence?: number | null;
  raised_by_safety_rules?: boolean;
  /** Plain reasons the safety rules raised the score, e.g. "heart rate over 100". */
  safety_floor_reasons?: string[];
  /** Rules that fired at the same level when nothing was raised (they agree with the score). */
  safety_rules_agree?: string[];
  /** Where the safety rules started: the model's pick, or the check-in score in rules-only mode. */
  starting_esi_level?: number | null;
  intake_esi_level?: number | null;
  model_conformal_set?: number[];
  conformal_note?: string | null;
  /** Set when the model is not installed and only the safety rules ran. */
  note?: string | null;
  model_card?: ModelCard | null;
};

export type ModelCard = {
  name: string;
  dataset: string;
  accuracy_note: string;
  range_note: string;
  technical: string[];
};

export type DifferentialEntry = {
  diagnosis: string;
  icd10: string;
  likelihood: "high" | "moderate" | "low";
  rule_in: string[];
  rule_out: string[];
  must_not_miss: boolean;
};

/** How a workup or disposition suggestion was made. "pending" means nobody has examined the patient yet. */
export type SuggestionMeta = {
  status?: "pending" | "suggested";
  basis?: "ai_draft" | "rules" | "none";
  /** "AI draft, for the clinician to decide", "Rule-based suggestion, ..." or "Pending". */
  label?: string;
  ai_available?: boolean;
  /** True when no vitals or notes exist yet. */
  before_exam?: boolean;
};

export type WorkupContraindication = {
  order: string;
  section: string;
  severity: "critical" | "warning" | "info";
  reason: string;
};

export type WorkupOrders = SuggestionMeta & {
  labs: string[];
  imaging: string[];
  monitoring: string[];
  consults: string[];
  rationale: string;
  contraindications?: WorkupContraindication[];
};

export type Disposition = SuggestionMeta & {
  disposition: "admit" | "observe" | "discharge" | "transfer" | "";
  level_of_care: string;
  expected_los_hours: number;
  rationale: string;
  discharge_criteria: string[];
  return_precautions: string[];
  consult_services?: string[];
};

export type PatientDetail = PatientSummary & {
  transcript: string;
  /** English translation the rules and model read (null when none was made). */
  transcript_english?: string | null;
  /** True when the patient wrote in a language the offline rules could not read. */
  needs_reading?: boolean;
  /** Plain name of the safety rule that set the check-in score, e.g. "Chest pain or pressure". */
  triage_rule_name?: string | null;
  /** Plain reasons the check-in safety rules gave. */
  safety_floor_reasons?: string[];
  /** Red-flag checklist ids the patient tapped (null when the checklist was not shown). */
  red_flags_checked?: string[] | null;
  /** What the AI red-flag check found (null when it did not run). It can only raise the score to ESI 2. */
  ai_red_flags?: { source: "ai_red_flag"; ids: string[] } | null;
  /** Set when the patient's words matched the prompt-injection filter, so AI was off for this check-in. */
  content_flag?: string | null;
  photo_url: string | null;
  photo_analysis: { description?: string; severity_indicators?: string[]; triage_observations?: string[] } | null;
  shap_values: Record<string, number> | null;
  comfort_protocol: ComfortAction[];
  patient_explanation: string;
  audio_url: string | null;
  triage_source: string | null;
  clinical_flags: string[];
  composites: { qsofa?: number; sirs?: number; shock_index?: number; cv_risk?: number };
  triage_recommendation: string;
  probabilities: number[];
  medical_info: MedicalInfo | null;
  followup_qa: FollowupAnswer[];
  insurance_info: InsuranceFields | null;
  prescriptions: Prescription[];
  clinical_scribe_note: string;
  differential: DifferentialEntry[];
  workup_orders: WorkupOrders;
  disposition: Disposition;
  notes: ClinicianNote[];
  patient_education: PatientEducation | null;
  patient_education_published_at: string | null;
  refined_esi_level?: number | null;
  refined_confidence?: number | null;
  refined_probabilities?: string | null;
  refined_conformal_set?: string | null;
  refined_top_features?: string | null;
  refined_source?: string | null;
  refined_at?: string | null;
  measured_vitals?: string | null;
  refined_model_confidence?: number | null;
  refined_model_conformal_set?: number[] | null;
  refined_model_card?: ModelCard | null;
  refined_note?: string | null;
  refined_safety_rules_agree?: string[] | null;
};

export type PublicPatient = {
  patient_id: string;
  esi_level?: 1 | 2 | 3 | 4 | 5;
  esi_label?: string;
  language?: string;
  patient_explanation: string;
  explanation_key?: string;
  explanation_language?: string;
  comfort_protocol: ComfortAction[];
  audio_url: string | null;
  // Deferred-artifact lifecycle for the patient-facing comfort + audio. The
  // result screen polls until comfort_ready is true (or a cap is hit) and shows
  // a loading state for those sections meanwhile.
  artifacts_status?: "pending" | "ready" | "failed" | null;
  comfort_ready?: boolean;
  patient_education: PatientEducation | null;
  patient_education_published_at: string | null;
  status: "waiting" | "seen";
  wait_estimate_minutes?: number;
  wait_estimate_range?: string;
  care_recommendation?: {
    destination: "ed_now" | "ed" | "urgent" | "telehealth" | "self_care" | "schedule";
    label: string;
    rationale: string;
    action_cta: string;
    severity: "critical" | "high" | "moderate" | "low";
    kind?: string;
    language?: string;
    next_steps?: string[];
    capacity_note?: string;
  };
};
