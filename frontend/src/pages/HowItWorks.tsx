import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ExternalLink } from "lucide-react";
import { SiteNav } from "../components/marketing/SiteNav";
import { SiteFooter } from "../components/marketing/SiteFooter";
import { Prose, SectionHeading } from "../components/marketing/SectionHeading";
import { PipelineDiagram } from "../components/marketing/PipelineDiagram";
import { EsiChip } from "../components/marketing/EsiChip";
import { StressTest } from "../components/marketing/StressTest";
import { REPORT, of } from "../components/marketing/redFlagReport";
import { AI_DISCLOSURE_PATH, AI_DISCLOSURE_URL, REPO_URL, STRESS_REPORT_PATH } from "../components/marketing/site";
import { CHECKLIST_IDS } from "../components/patient/RedFlagChecklist";
import { useCapabilities, type Capabilities } from "../lib/capabilities";
import { t } from "../lib/i18n";

// Plain-English evidence page: the pipeline, the safety rules, the red-flag stress
// test, an honest model card, and what runs without an AI key.
const RULES_FILE_URL = `${REPO_URL}/blob/main/backend/services/triage_rules.py`;

// The danger signs on the patient's checklist, in English, from the same strings
// the patient screen uses ("None of these" is left out).
const CHECKLIST_SIGNS = CHECKLIST_IDS.filter((id) => id !== "none").map((id) => t(`redflag_${id}` as const, "en"));
const SELF_HARM_LABEL = t("redflag_self_harm", "en");
const BLIND2 = REPORT.sets.find((x) => x.name === "blind2" && x.after_missed !== null) ?? null;
// Word rules shown before "Show all rules".
const RULES_PREVIEW = 5;

export default function HowItWorks() {
  // Capabilities are the same for every hospital on a server, so ask the shared demo
  // hospital instead of creating a private one just to read this page.
  const caps = useCapabilities("demo");

  useEffect(() => {
    document.title = "How Solace works";
  }, []);

  const modelLoaded = caps ? caps.triage_model.loaded : true;
  const [allRules, setAllRules] = useState(false);
  const shownRules = allRules ? REPORT.rules : REPORT.rules.slice(0, RULES_PREVIEW);

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <div className="bg-surface-lowest border-b border-line">
        <SiteNav />
        <header className="mx-auto max-w-3xl px-4 sm:px-6 pt-6 pb-12 sm:pt-12 sm:pb-16">
          <h1 className="font-display font-normal text-[38px] sm:text-[52px] leading-[1.05] tracking-editorial-tight text-ink">
            How Solace works
          </h1>
          <p className="mt-5 text-[17px] sm:text-[18px] leading-relaxed text-text-muted">
            Solace gives each patient in an ER waiting room an urgency score from 1 (most urgent) to
            5 (least urgent). It uses the same 1 to 5 scale many ERs use, called the Emergency
            Severity Index, or ESI. This page shows how the score is made, how we tested it, and what
            it cannot do yet.
          </p>
          <ServerStatus caps={caps} />
          {BLIND2 && <HeadlineNumbers />}
        </header>
      </div>

      <main className="flex-1">
        <Section id="pipeline" title="From a patient's words to a score">
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <div className="rounded-2xl bg-surface-lowest ring-1 ring-line p-4 sm:p-6">
              <PipelineDiagram modelLoaded={modelLoaded} />
            </div>
          </div>
          <Prose>
            <p>
              <strong>At check-in,</strong> the patient types or says what is wrong on their own phone.
              Safety word rules look for emergencies, like chest pain, trouble breathing or heavy
              bleeding, and the trained model makes its own guess from the words. If they disagree, the
              more urgent answer wins.
            </p>
            <p>
              <strong>Then the red-flag checklist.</strong> Unless the rules already found an emergency,
              the patient sees &ldquo;Is any of this happening right now?&rdquo; and taps any of ten
              danger signs that apply, like &ldquo;Hard to breathe&rdquo; or &ldquo;Swallowed something
              dangerous, like pills, poison or a battery&rdquo;. Tapping works the same in every
              language, so it can catch an emergency the word rules cannot read. Any tap moves the
              patient up to ESI 2. With an AI key, an AI check also reads the patient&rsquo;s words for the same danger
              signs. It can only raise the score, and the nurse sees it labeled as an AI check. That
              first score puts the patient in the queue right away.
            </p>
            <p>
              <strong>At the bedside,</strong> a nurse enters vital signs. A trained model looks at the
              vital signs and the patient&rsquo;s words together and makes its own guess.
            </p>
            <p>
              <strong>Then the safety floor checks that guess.</strong> If a vital sign is in a danger
              zone, like oxygen under 92% or an adult heart rate over 100, the score goes up. The floor
              can only make a patient more urgent, never less, and the screen tells the nurse which rule
              raised it.
            </p>
          </Prose>
        </Section>

        <Section id="rules" title="The safety rules" tone="low">
          <Prose>
            <p>
              These rules are plain pattern checks, written in code, that run in a split second with
              no AI. Each one sets the least urgent score a patient can get when it matches. The
              paperwork rule is the exception: it can mark a visit ESI 5 only when nothing else is
              urgent.
            </p>
          </Prose>
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 flex flex-col gap-8">
            <TableCard caption="Red-flag checklist (tapped by the patient at check-in)">
              <thead className="bg-surface-low text-text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium w-[88px]">Score</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">When the patient taps</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {CHECKLIST_SIGNS.map((label) => (
                  <tr key={label}>
                    <td className="px-4 py-3"><EsiChip level={2} /></td>
                    <td className="px-4 py-3 text-ink">
                      {label}
                      {label === SELF_HARM_LABEL && (
                        <span className="text-text-muted"> (also shows the 988 crisis line)</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </TableCard>
            {REPORT.rules.length > 0 ? (
              <div>
              <TableCard caption={`Word rules (checked at check-in and at the bedside), ${REPORT.rules.length} in all`}>
                <thead className="bg-surface-low text-text-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-medium w-[88px]">Score</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Rule</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Example phrases</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {shownRules.map((r) => (
                    <tr key={`${r.esi}-${r.name}`} className="align-top">
                      <td className="px-4 py-3"><EsiChip level={r.esi} /></td>
                      <td className="px-4 py-3 text-ink font-medium">{r.name}</td>
                      <td className="px-4 py-3 text-text-muted">
                        {(r.examples ?? []).map((e) => `"${e}"`).join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </TableCard>
              {REPORT.rules.length > RULES_PREVIEW && (
                <button
                  type="button"
                  onClick={() => setAllRules((v) => !v)}
                  aria-expanded={allRules}
                  className="mt-3 text-[15px] font-medium text-primary underline underline-offset-4 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                >
                  {allRules ? "Show fewer rules" : `Show all ${REPORT.rules.length} rules`}
                </button>
              )}
              </div>
            ) : (
              <p className="text-[15px] text-text-muted">
                The full rule list is in{" "}
                <a className="text-primary underline underline-offset-2" href={RULES_FILE_URL} target="_blank" rel="noreferrer">
                  triage_rules.py
                </a>
                .
              </p>
            )}

            {REPORT.vital_floor.length > 0 && (
              <TableCard caption="Vital sign floor (checked at the bedside)">
                <thead className="bg-surface-low text-text-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-medium w-[88px]">Score</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">When this is true</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {REPORT.vital_floor.map((v) => (
                    <tr key={`${v.esi}-${v.check}`}>
                      <td className="px-4 py-3"><EsiChip level={v.esi} /></td>
                      <td className="px-4 py-3 text-ink">{v.check}</td>
                    </tr>
                  ))}
                </tbody>
              </TableCard>
            )}
          </div>
        </Section>

        <Section id="stress-test" title="Stress test: can it miss an emergency?">
          <StressTest report={REPORT} />
        </Section>

        <Section id="model" title="The trained model, honestly" tone="low">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
            <dl className="rounded-2xl bg-surface-lowest ring-1 ring-line divide-y divide-line">
              <Fact term="What it is">
                Five LightGBM models, a kind of decision tree model. Each one learned from a different
                80% of the data, and their answers are averaged.
              </Fact>
              <Fact term="What it learned from">
                About 80,000 synthetic (made-up) ER visits from a Kaggle competition called
                Triagegeist. No real patients.
              </Fact>
              <Fact term="What it looks at">
                561 inputs: vital signs, age, medical history, and the words of the complaint (450 of the
                inputs come from the words).
              </Fact>
              <Fact term="How it scored">
                Almost perfect on made-up visits it had not trained on (each of the five models was
                checked on the part of the data it did not learn from): an agreement score of 0.999
                out of 1 (quadratic weighted kappa) and 99.9% exactly right. That mostly tells us the
                made-up data is too clean. How well it would do with real patients is unknown.
              </Fact>
              <Fact term="A known problem">
                The training data includes details that should not matter medically, like which nurse
                did triage and which hospital site a visit came from, and the model was allowed to use
                them. A real version should be retrained without them.
              </Fact>
              <Fact term="Why we still use it">
                It never gets the last word. The safety rules and the checklist can raise its score,
                and a nurse always makes the real decision.
              </Fact>
              {caps && !caps.triage_model.loaded && (
                <Fact term="On this server">
                  The model files are not installed here, so every score comes from the safety rules
                  alone.
                </Fact>
              )}
            </dl>
          </div>
        </Section>

        <Section id="keys" title="What works without an AI key">
          <Prose>
            <p>
              Solace runs with no paid AI service at all, which is how most people will run it on a
              laptop. A few optional features use Claude, an AI model made by Anthropic, when a key is
              set. When a feature is off, the screen says so and offers the next best thing.
            </p>
          </Prose>
          <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
            <KeyTable caps={caps} />
          </div>
        </Section>

        <Section id="ai" title="How we used AI to build this" tone="low">
          <Prose>
            <p>
              We used Claude Code, an AI coding assistant made by Anthropic, to write and rewrite
              large parts of this code while we directed it. It also wrote our test phrases, the
              red-team, held-out and blind test sets, and the translations of the patient screens. Our AI
              disclosure lists, part by part, where AI helped and what we did ourselves.
            </p>
            <p>
              That is separate from the AI features inside the app, which are optional. Everything in
              the &ldquo;With no key&rdquo; column of the table above runs inside Solace itself, with no
              AI service and no key.
            </p>
            <p className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <Link
                to={AI_DISCLOSURE_PATH}
                className="inline-flex items-center gap-1.5 font-medium text-primary underline underline-offset-4"
              >
                Read the AI disclosure <ArrowRight size={15} aria-hidden />
              </Link>
              <a
                href={AI_DISCLOSURE_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-[15px] text-text-muted underline underline-offset-4 hover:text-ink"
              >
                Same file on GitHub <ExternalLink size={14} aria-hidden />
              </a>
            </p>
          </Prose>
        </Section>

        <Section id="limits" title="Limits, and what version 2.0 needs">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 grid gap-6 sm:grid-cols-2">
            <ListCard
              title="What Solace cannot do yet"
              items={[
                "It has not been tested with real patients, nurses or doctors.",
                "The model learned only from made-up data.",
                "No doctor has reviewed the safety rules or the test phrases, and no native speaker has checked the translations.",
                BLIND2
                  ? `Word rules miss many new ways of describing an emergency: ${BLIND2.after_missed} of ${BLIND2.urgent} in our newest blind test, and ${BLIND2.checklist_missed ?? "some"} even with honest checklist answers.`
                  : "Word rules miss many new ways of describing an emergency.",
                "The checklist only helps when the emergency is on its list and the patient taps it. It can never fix a score that is too urgent.",
                "It is a demo: patients are stored in memory and disappear when the server restarts.",
              ]}
            />
            <ListCard
              title="What version 2.0 needs"
              items={[
                "ER nurses and doctors review the rules and check the scores on real visits, with names removed and with permission.",
                "Triage nurses try the dashboard on a real shift so we can fix what slows them down.",
                "Retrain the model without non-medical inputs and measure it on real data.",
                "Interpreters check every rule written for another language.",
                "A secure database and real hospital sign-in.",
              ]}
            />
          </div>
        </Section>
      </main>

      <SiteFooter />
    </div>
  );
}

function Section({
  id,
  title,
  tone,
  children,
}: {
  id: string;
  title: string;
  tone?: "low";
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-title`} className={`py-14 sm:py-20 ${tone === "low" ? "bg-surface-low" : ""}`}>
      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 mb-8">
        <SectionHeading id={`${id}-title`} title={title} />
      </div>
      <div className="flex flex-col gap-8">{children}</div>
    </section>
  );
}

function TableCard({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-surface-lowest ring-1 ring-line">
      <table className="w-full text-left text-[15px]">
        <caption className="text-left px-4 pt-4 pb-3 text-[15px] font-semibold text-ink">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[180px_1fr] sm:gap-6 px-5 py-4">
      <dt className="text-[15px] font-semibold text-ink">{term}</dt>
      <dd className="text-[15px] leading-relaxed text-text-muted">{children}</dd>
    </div>
  );
}

function ListCard({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-2xl bg-surface-lowest ring-1 ring-line p-5">
      <h3 className="text-[17px] font-semibold text-ink">{title}</h3>
      <ul className="mt-3 flex flex-col gap-2.5 text-[15px] leading-relaxed text-text-muted list-disc pl-5 marker:text-primary">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  );
}

function ServerStatus({ caps }: { caps: Capabilities | null }) {
  const pills: { label: string; on: boolean | null }[] = caps
    ? [
        { label: caps.llm ? "AI features are on for this server" : "AI features are off on this server", on: caps.llm },
        {
          label: caps.triage_model.loaded
            ? `Trained model installed (${caps.triage_model.folds} models)`
            : "Trained model not installed, rules only",
          on: caps.triage_model.loaded,
        },
      ]
    : [{ label: "Checking this server", on: null }];
  return (
    <ul className="mt-6 flex flex-wrap gap-2" aria-label="This server right now">
      {pills.map((p) => (
        <li
          key={p.label}
          className="inline-flex items-center gap-2 rounded-full bg-surface-low ring-1 ring-line px-3 h-9 text-[14px] text-ink"
        >
          <span
            aria-hidden
            className={`h-2.5 w-2.5 rounded-full ${
              p.on === null ? "bg-surface-high" : p.on ? "bg-success" : "bg-text-muted"
            }`}
          />
          {p.label}
        </li>
      ))}
    </ul>
  );
}

/** The three blind test 2 numbers, right under the intro, read from the report file. */
function HeadlineNumbers() {
  if (!BLIND2) return null;
  const stats = [
    { value: of(BLIND2.after_missed ?? 0, BLIND2.urgent), label: "emergencies missed from the words alone" },
    ...(BLIND2.checklist_missed !== null
      ? [{ value: of(BLIND2.checklist_missed, BLIND2.urgent), label: "missed when the patient also answers the checklist" }]
      : []),
    { value: of(BLIND2.after_over, BLIND2.everyday), label: "everyday check-ins shown too urgent (false alarms)" },
  ];
  return (
    <section aria-labelledby="headline-title" className="mt-8 rounded-2xl bg-primary text-white p-5 sm:p-6">
      <h2 id="headline-title" className="text-[17px] font-semibold text-white">
        Our honest numbers, from a blind test
      </h2>
      <p className="mt-1 text-[15px] leading-relaxed text-primary-fixed">
        {BLIND2.cases.toLocaleString("en-US")} new check-ins written after our last fix and never used
        to change the rules, run with no AI key.
      </p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-3">
        {stats.map((s) => (
          <li key={s.label} className="rounded-xl bg-white/10 px-4 py-3 flex flex-col gap-1">
            <span className="text-[26px] leading-none font-semibold tabular-nums">{s.value}</span>
            <span className="text-[14px] leading-snug text-primary-fixed">{s.label}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-[15px]">
        <a href="#stress-test-title" className="font-medium text-white underline underline-offset-4">
          How we tested
        </a>
        <Link to={STRESS_REPORT_PATH} className="font-medium text-white underline underline-offset-4">
          Full report, with every miss
        </Link>
      </p>
    </section>
  );
}

type CapKey = "llm" | "ocr" | "transcription" | "tts" | "sms" | null;

const KEY_ROWS: { feature: string; without: string; withKey: string; cap: CapKey; offNote?: string }[] = [
  {
    feature: "Check-in and urgency score",
    without: "Works. Safety word rules, the red-flag checklist and the trained model.",
    withKey:
      "Same rules, checklist and model. A check-in in another language is first translated to English by AI so they can read it, so its score can differ. AI also writes the follow-up questions and comfort tips.",
    cap: null,
  },
  {
    feature: "AI red-flag check",
    without: "Off. The checklist the patient taps still works.",
    withKey:
      "Reads the patient's words, in any language, for the checklist danger signs. It can only raise the score, and the nurse sees it labeled as an AI check.",
    cap: "llm",
  },
  {
    feature: "Nurse dashboard queue, vital signs re-check, early warning scores",
    without: "Works. No AI involved.",
    withKey: "Same.",
    cap: null,
  },
  {
    feature: "Speaking instead of typing",
    without: "Uses the browser's built-in dictation, where the browser has it.",
    withKey: "Also works in browsers without dictation.",
    cap: "transcription",
    offNote: "uses the browser's own dictation",
  },
  {
    feature: "Reading the guidance aloud",
    without: "Uses the browser's own voice.",
    withKey: "A more natural voice from the server.",
    cap: "tts",
    offNote: "uses the browser's own voice",
  },
  {
    feature: "ID and insurance cards",
    without: "Try the steps with a sample card.",
    withKey: "Reads a photo of a real card.",
    cap: "ocr",
  },
  {
    feature: "Visit notes (scribe)",
    without: "Keeps what was said, word for word. The clinician writes the rest.",
    withKey: "AI drafts the note for the clinician to edit.",
    cap: "llm",
  },
  {
    feature: "Possible causes (reasoning)",
    without: "The AI list is off, and the screen says so. Fixed rules still flag must-not-miss conditions that match the complaint.",
    withKey: "AI lists possibilities for the clinician to consider.",
    cap: "llm",
  },
  {
    feature: "Tests and next steps (workup, admit or send home)",
    without: "A plain rule-based starting point from the score and vital signs, labeled as rules.",
    withKey: "An AI draft, re-checked against the current score and vital signs.",
    cap: "llm",
  },
  {
    feature: "Prescriptions",
    without: "Typed prescriptions are checked for allergies and drug interactions.",
    withKey: "AI suggestions too, checked the same way.",
    cap: "llm",
  },
  {
    feature: "Summary for the patient",
    without: "Built from the clinician's own note.",
    withKey: "AI rewrites it in plain language.",
    cap: "llm",
  },
  {
    feature: "Text messages",
    without: "Shows exactly what the text would say.",
    withKey: "Sends a real text, if texting is set up.",
    cap: "sms",
  },
];

function KeyTable({ caps }: { caps: Capabilities | null }) {
  const status = (cap: CapKey, offNote?: string): { text: string; note?: string; on: boolean | null } => {
    if (cap === null) return { text: "On here", note: "no key needed", on: true };
    if (!caps) return { text: "Checking", on: null };
    return caps[cap] ? { text: "On here", on: true } : { text: "Off here", note: offNote, on: false };
  };
  return (
    <div className="overflow-x-auto rounded-2xl bg-surface-lowest ring-1 ring-line">
      <table className="w-full min-w-[720px] text-left text-[15px]">
        <thead className="bg-surface-low text-text-muted">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium w-[22%]">Feature</th>
            <th scope="col" className="px-4 py-3 font-medium">With no key</th>
            <th scope="col" className="px-4 py-3 font-medium">With a key</th>
            <th scope="col" className="px-4 py-3 font-medium w-[150px]">On this server</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {KEY_ROWS.map((r) => {
            const s = status(r.cap, r.offNote);
            return (
              <tr key={r.feature} className="align-top">
                <th scope="row" className="px-4 py-3 font-semibold text-ink">{r.feature}</th>
                <td className="px-4 py-3 text-text-muted">{r.without}</td>
                <td className="px-4 py-3 text-text-muted">{r.withKey}</td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-2 text-[14px] text-ink whitespace-nowrap">
                    <span
                      aria-hidden
                      className={`h-2.5 w-2.5 rounded-full ${
                        s.on === null ? "bg-surface-high" : s.on ? "bg-success" : "bg-text-muted"
                      }`}
                    />
                    {s.text}
                  </span>
                  {s.note && <span className="block mt-0.5 pl-[18px] text-[13px] text-text-muted">({s.note})</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
