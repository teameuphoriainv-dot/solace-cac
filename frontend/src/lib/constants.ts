// ESI palette aligned with the Clinical Sanctuary system.
// Avoid high-saturation emergency reds; use the `error` token only for ESI 1.
// onDark picks the text color: white on the darker fills, ink on the gold ESI 3
// (white on #B8924A is only 2.9:1; ink is 5.7:1).
// Labels are the plain English fallback; patient screens show t("esi_label_N").
export const ESI_COLORS: Record<number, { bg: string; label: string; onDark: boolean }> = {
  1: { bg: "#BA1A1A", label: "Most urgent", onDark: true },
  2: { bg: "#B05436", label: "Very urgent", onDark: true },
  3: { bg: "#B8924A", label: "Urgent", onDark: false },
  4: { bg: "#406372", label: "Less urgent", onDark: true },
  5: { bg: "#557D6E", label: "Least urgent", onDark: true },
};

export const POLL_INTERVAL_MS = 10_000;

// sessionStorage key for the patient's chosen language, so the result page's
// loading and "not found" screens match the check-in.
export const PATIENT_LANG_KEY = "solace.patient.lang";
