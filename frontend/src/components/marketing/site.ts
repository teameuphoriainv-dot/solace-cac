// Links and names shown on the public pages. Change the repo address here only.
export const REPO_URL = "https://github.com/teameuphoriainv-dot/solace-cac";
/** GitHub copies of the evidence files. The site shows both itself at the routes below. */
export const AI_DISCLOSURE_URL = `${REPO_URL}/blob/main/AI-DISCLOSURE.md`;
export const STRESS_REPORT_URL = `${REPO_URL}/blob/main/docs/evidence/red-flag-stress-test.md`;
/** The same two files, rendered on this site (pages/AiDisclosure.tsx, pages/StressTest.tsx). */
export const AI_DISCLOSURE_PATH = "/ai-disclosure";
export const STRESS_REPORT_PATH = "/stress-test";
/** The earlier repo this build grew out of. */
export const PROVENANCE_URL = "https://github.com/Dhruvjain35/solace-ai";

export const TEAM = "Dhruv Jain and Sriyan Bodla";
export const CONTEST = "2026 Congressional App Challenge, Illinois 16th District";

export const DEMO_SIGN_IN = { name: "Dr. Chen", pin: "224466" };

export type Example = {
  text: string;
  /** What a judge should see, in plain words. */
  expect: string;
  /** Lowest and highest ESI the triage tests accept for this phrase. */
  esi: [number, number];
  /** Language of the phrase when it is not English. */
  lang?: string;
  note?: string;
};

// The check-in phrases the triage tests pin (contract C9).
export const EXAMPLES: Example[] = [
  {
    text: "Crushing chest pain down my left arm and I'm sweating",
    expect: "ESI 1 or 2, at the top of the queue.",
    esi: [1, 2],
  },
  {
    text: "Me duele mucho el pecho y no puedo respirar",
    expect: "ESI 1 or 2. Pick Spanish on the first screen to get the guidance in Spanish.",
    esi: [1, 2],
    lang: "es",
    note: "Spanish for: my chest hurts a lot and I can't breathe.",
  },
  {
    text: "My 3 year old has a fever of 104 and is very sleepy",
    expect: "ESI 1 or 2. A very sleepy small child with a high fever should not wait.",
    esi: [1, 2],
  },
  {
    text: "I twisted my ankle playing soccer and it's swollen",
    expect: "ESI 4 or 5. This patient waits while sicker people go first.",
    esi: [4, 5],
  },
  {
    text: "I need a refill of my blood pressure pills",
    expect: "ESI 4 or 5, the least urgent.",
    esi: [4, 5],
  },
];

/** Bedside vitals that should trip the safety floor (low pressure, fast pulse, low oxygen). */
export const SHOCK_VITALS = [
  { label: "Blood pressure", value: "88/54" },
  { label: "Heart rate", value: "124" },
  { label: "Oxygen (SpO2)", value: "91%" },
  { label: "Breathing rate", value: "24" },
];
