// The red-flag stress test numbers for the How it works page, read from
// frontend/src/data/red-flag-results.json (written by scripts/red_flag_report.py),
// plus the blind test 2 details the report script does not store.

export type RedFlagCase = {
  text: string;
  language: string;
  expected_max_esi: number;
  before_esi: number | null;
  after_esi: number | null;
};

/** One test set from the report. Counts are of emergencies unless they say everyday. */
export type RedFlagSet = {
  name: string;
  cases: number;
  urgent: number;
  everyday: number;
  /** Shown less urgent than expected by the scoring before our fix. Null when not run. */
  before_under: number | null;
  /** Shown less urgent than expected now. An expected ESI 1 shown at ESI 2 counts. */
  after_under: number;
  /** Shown at ESI 3 or calmer now. Null in older reports. */
  after_missed: number | null;
  /** Everyday check-ins shown at ESI 1 or 2 now. */
  after_over: number;
  checklist_under: number | null;
  checklist_missed: number | null;
  /** True when the rules were fixed using this set, so its numbers are not a fair test. */
  tuned: boolean;
};

// Sets the rules were fixed with, for reports written before the "tuned" field existed.
const TUNED_BY_NAME = new Set(["pinned", "regression", "diagnostic_blind1"]);

/** Blind test 1 as it ran blind, before its misses were used to fix the rules. */
export type Blind1Run = { urgent: number; everyday: number; missed: number; over: number; checklist_missed: number };

export type RedFlagResults = {
  generated_at: string;
  summary: { cases: number; languages: string[]; before_under_triaged: number; after_under_triaged: number };
  cases: RedFlagCase[];
  sets: RedFlagSet[];
  blind1_run: Blind1Run | null;
  rules: { esi: number; name: string; examples: string[] }[];
  vital_floor: { esi: number; check: string }[];
};

// Loaded with a glob so the page still builds and renders if the report has not been made yet.
const reportFiles = import.meta.glob("../../data/red-flag-results.json", { eager: true, import: "default" });
export const REPORT = parseReport(Object.values(reportFiles)[0]);

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function parseReport(raw: unknown): RedFlagResults {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const cases = (Array.isArray(r.cases) ? r.cases : []).filter(
    (c): c is RedFlagCase => !!c && typeof (c as RedFlagCase).text === "string",
  );
  const s = (r.summary ?? {}) as Partial<RedFlagResults["summary"]>;
  const sets = (Array.isArray(r.sets) ? r.sets : [])
    .filter((x): x is Record<string, unknown> => !!x && typeof (x as { name?: unknown }).name === "string")
    .map((x) => ({
      name: x.name as string,
      cases: num(x.cases) ?? 0,
      urgent: num(x.urgent) ?? 0,
      everyday: num(x.everyday) ?? 0,
      before_under: num(x.before_under),
      after_under: num(x.after_under) ?? 0,
      after_missed: num(x.after_missed),
      after_over: num(x.after_over) ?? 0,
      checklist_under: num(x.checklist_under),
      checklist_missed: num(x.checklist_missed),
      tuned: typeof x.tuned === "boolean" ? x.tuned : TUNED_BY_NAME.has(x.name as string),
    }));
  const b1 = (r.blind1_run ?? null) as Record<string, unknown> | null;
  const blind1 =
    b1 && num(b1.missed) !== null && num(b1.over) !== null
      ? {
          urgent: num(b1.urgent) ?? 160,
          everyday: num(b1.everyday) ?? 80,
          missed: num(b1.missed)!,
          over: num(b1.over)!,
          checklist_missed: num(b1.checklist_missed) ?? 0,
        }
      : null;
  return {
    generated_at: typeof r.generated_at === "string" ? r.generated_at : "",
    summary: {
      cases: num(s.cases) ?? cases.length,
      languages: Array.isArray(s.languages) ? s.languages : [],
      before_under_triaged: num(s.before_under_triaged) ?? 0,
      after_under_triaged: num(s.after_under_triaged) ?? 0,
    },
    cases,
    sets,
    blind1_run: blind1,
    rules: Array.isArray(r.rules) ? (r.rules as RedFlagResults["rules"]) : [],
    vital_floor: Array.isArray(r.vital_floor) ? (r.vital_floor as RedFlagResults["vital_floor"]) : [],
  };
}

/**
 * Blind test 2 by language, and its ESI 1 and checklist counts. The report script keeps only
 * the totals, so these come from the run itself (2026-10-19, case file sha256 8277960b...,
 * two identical runs). The page shows them only while they add up to the report's totals.
 */
export const BLIND2_DETAIL = {
  esi1Expected: 41,
  esi1AtOne: 16,
  /** With honest checklist answers, the other expected ESI 1 emergencies were all shown at ESI 2. */
  esi1AtTwoWithChecklist: 25,
  checklistShownUrgent: 43,
  checklistShownEveryday: 76,
  languages: [
    { code: "en", urgent: 100, everyday: 50, missed: 26, missedChecklist: 12, over: 3 },
    { code: "es", urgent: 12, everyday: 6, missed: 2, missedChecklist: 0, over: 0 },
    { code: "zh", urgent: 12, everyday: 6, missed: 4, missedChecklist: 2, over: 0 },
    { code: "hi", urgent: 12, everyday: 6, missed: 5, missedChecklist: 1, over: 0 },
    { code: "ar", urgent: 12, everyday: 6, missed: 3, missedChecklist: 1, over: 0 },
    { code: "vi", urgent: 12, everyday: 6, missed: 3, missedChecklist: 1, over: 1 },
  ],
};

export function detailMatches(b2: RedFlagSet): boolean {
  const sum = (k: "urgent" | "everyday" | "missed" | "missedChecklist" | "over") =>
    BLIND2_DETAIL.languages.reduce((n, l) => n + l[k], 0);
  return (
    BLIND2_DETAIL.esi1AtOne + BLIND2_DETAIL.esi1AtTwoWithChecklist === BLIND2_DETAIL.esi1Expected &&
    sum("urgent") === b2.urgent &&
    sum("everyday") === b2.everyday &&
    sum("missed") === b2.after_missed &&
    sum("missedChecklist") === b2.checklist_missed &&
    sum("over") === b2.after_over
  );
}

export const languageName = (() => {
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames(["en"], { type: "language" });
  } catch {
    names = null;
  }
  return (code: string) => {
    try {
      return names?.of(code) ?? code;
    } catch {
      return code;
    }
  };
})();

export const of = (n: number, total: number) => `${n.toLocaleString("en-US")} of ${total.toLocaleString("en-US")}`;
