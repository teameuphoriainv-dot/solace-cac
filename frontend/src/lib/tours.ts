/**
 * Tour registry. Each entry is a self-contained tour definition.
 *
 * Anchor strings here MUST match `data-tour="<anchor>"` attributes on the page.
 * A step whose anchor is not on screen is skipped (see useTour), so the same tour
 * works on a laptop and on a phone, where some panels are folded away.
 */

import type { TourDefinition } from "./tour-types";

/** Started from the "Take the tour" button on the nurse dashboard. */
export const CLINICIAN_DASHBOARD_TOUR: TourDefinition = {
  id: "clinician-dashboard-v2",
  label: "Dashboard tour",
  steps: [
    {
      id: "intro",
      title: "Welcome to the Solace nurse dashboard",
      body: "A one-minute look at the live queue, the bedside re-check and the tools for each patient. Every patient here is fictional.",
    },
    {
      id: "stats",
      title: "The waiting room at a glance",
      body: "How many people are waiting, how many feel-worse alerts are open, the average wait, and how many patients have had their vitals re-checked. It updates every few seconds.",
      anchor: "stat-strip",
      placement: "bottom",
    },
    {
      id: "queue",
      title: "The live queue",
      body: "Everyone who checked in, most urgent first, with the priority score from 1 (most urgent) to 5. Tap a name to open the full chart. Pin keeps a patient on the cards below.",
      anchor: "patient-queue",
      placement: "auto",
    },
    {
      id: "cards",
      title: "Cards for one patient",
      body: "The pinned patient's summary, early warning scores, scribe and reasoning. Add, remove, fold or drag cards to set up your view.",
      anchor: "patient-cards",
      placement: "top",
    },
    {
      id: "recheck",
      title: "The bedside re-check",
      body: "In a patient's chart, enter vitals to re-check the score. A trained model scores them, and safety rules can raise the score when they see danger signs. The queue then shows the new score.",
    },
    {
      id: "ai",
      title: "What the AI is doing",
      body: "This shows whether AI drafting is on. With it off, triage still runs on the model and the safety rules, and every AI card says what is off and what still works.",
      anchor: "ai-status",
      placement: "auto",
    },
    {
      id: "qr",
      title: "Patient check-in",
      body: "Patients scan this code to check in on their own phone. New arrivals appear in the queue on their own.",
      anchor: "checkin-qr",
      placement: "auto",
    },
    {
      id: "help",
      title: "See this again any time",
      body: "Use Take the tour to replay these steps.",
      anchor: "tour-launcher",
      placement: "auto",
    },
  ],
};

/**
 * Patient-side help, opened only from the "?" button on the symptom step (it never
 * opens by itself, so it never covers the box a patient is typing in). Short and
 * modal-only (no anchors): check-in is a focused, full-screen flow on a phone.
 */
export const PATIENT_INTAKE_TOUR: TourDefinition = {
  id: "patient-intake-v1",
  label: "How check-in works",
  steps: [
    {
      id: "voice-or-text",
      title: "Tell us what brings you in",
      body: "You can describe your symptoms by voice or by typing. Take your time and say it in your own words, in your own language.",
    },
    {
      id: "not-a-clinician",
      title: "The care team makes the decisions",
      body: "Solace is a student demo that helps the care team get ready for you. It is not medical advice. If you feel worse while you wait, tell the front desk right away. If you are not at a hospital and this is an emergency, call 911.",
    },
  ],
};

export const TOUR_REGISTRY: Record<string, TourDefinition> = {
  [CLINICIAN_DASHBOARD_TOUR.id]: CLINICIAN_DASHBOARD_TOUR,
  [PATIENT_INTAKE_TOUR.id]: PATIENT_INTAKE_TOUR,
};
