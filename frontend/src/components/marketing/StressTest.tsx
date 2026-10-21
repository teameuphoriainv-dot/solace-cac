import { useState } from "react";
import { Link } from "react-router-dom";
import { Prose } from "./SectionHeading";
import { REPO_URL, STRESS_REPORT_PATH, STRESS_REPORT_URL } from "./site";
import {
  BLIND2_DETAIL,
  detailMatches,
  languageName,
  of,
  type Blind1Run,
  type RedFlagResults,
  type RedFlagSet,
} from "./redFlagReport";

// The "Stress test" section of the How it works page: the blind test 2 headline,
// every other test set, and our own phrases one by one (numbers from ./redFlagReport).

const RED_FLAG_TESTS_URL = `${REPO_URL}/blob/main/backend/tests/test_red_flags.py`;

const SET_TEXT: Record<string, { title: string; about: string }> = {
  pinned: {
    title: "Our own phrases",
    about: "The phrases in our tests. We fixed the rules until every one passed.",
  },
  regression: {
    title: "Red-team phrases",
    about: "Written to break the rules: typos, slang, someone typing for a person who collapsed, all 20 languages. We fixed the rules using them.",
  },
  heldout: {
    title: "Held-out phrases",
    about: "Written by the red teams after the first fixes, and never used to tune the rules.",
  },
  diagnostic_blind1: {
    title: "Blind test 1, now a diagnostic set",
    about: "Written and run blind. We then used its misses to fix general gaps, like denials (“no chest pain”), “not breathing”, swallowed poisons and batteries, and suicide plans, so it is no longer blind.",
  },
};


export function StressTest({ report }: { report: RedFlagResults }) {
  const [showAll, setShowAll] = useState(false);
  const { summary, cases } = report;

  if (cases.length === 0) {
    return (
      <Prose>
        <p>
          We keep a list of check-in phrases that must always score as urgent, in several languages,
          and the backend tests run every one of them. You can read the list in{" "}
          <a className="text-primary underline underline-offset-2" href={RED_FLAG_TESTS_URL} target="_blank" rel="noreferrer">
            test_red_flags.py
          </a>
          .
        </p>
      </Prose>
    );
  }

  const languages = summary.languages.length ? summary.languages : [...new Set(cases.map((c) => c.language))];
  const shown = showAll ? cases : cases.slice(0, 12);
  const urgent = cases.filter((c) => c.expected_max_esi < 5).length;
  const missed = (esi: number | null, max: number) => esi !== null && esi > max;
  // Older reports have no "sets"; show the pinned phrases alone then.
  const sets: RedFlagSet[] = report.sets.length
    ? report.sets
    : [{
        name: "pinned", cases: summary.cases, urgent, everyday: cases.length - urgent,
        before_under: summary.before_under_triaged, after_under: summary.after_under_triaged,
        after_missed: null, after_over: 0, checklist_under: null, checklist_missed: null, tuned: true,
      }];
  const pinned = sets.find((x) => x.name === "pinned");
  const blind2 = sets.find((x) => x.name === "blind2" && x.after_missed !== null) ?? null;
  const detail = blind2 && detailMatches(blind2) ? BLIND2_DETAIL : null;
  const others = sets.filter((x) => x.name !== "blind2");
  // Sets the rules were fixed with only show that the fixes stuck, so they sit apart, greyed.
  const fair = others.filter((x) => !x.tuned);
  const tuned = others.filter((x) => x.tuned);
  const redTeam = sets.filter((x) => x.name === "regression" || x.name === "heldout").reduce((n, x) => n + x.cases, 0);
  const blindSets = sets.filter((x) => x.name === "diagnostic_blind1" || x.name === "blind2").length;
  const knownMisses = sets.find((x) => x.name === "regression")?.after_under ?? 0;

  return (
    <>
      <Prose>
        <p>
          We count two kinds of mistakes. An emergency is <strong>missed</strong> when it is shown at
          ESI 3 or calmer, so it is not marked as an emergency at all. It is <strong>too calm</strong>{" "}
          when it is shown less urgent than it should be, which also counts an ESI 1 emergency shown
          at ESI 2. All of these numbers were measured with no AI key and the trained model on.
        </p>
        <p>
          <strong>
            {pinned && pinned.after_under > 0
              ? `${pinned.after_under} of our own ${summary.cases} phrases are still too calm.`
              : `Our own ${summary.cases} phrases all pass.`}
          </strong>{" "}
          But that only proved the rules knew the phrases we wrote them for.
          {redTeam > 0 && (
            <>
              {" "}
              So red teams, run with Claude Code agents, wrote {redTeam.toLocaleString("en-US")} new
              check-ins meant to break the rules. Before our fix the word rules scored almost all of
              their emergencies too calm. We patched the rules using the red-team phrases, then
              measured again on held-out phrases written after the first fixes and never used to
              tune them.
            </>
          )}
          {blindSets === 2 && (
            <>
              {" "}
              Then two more Claude Code agents each wrote a blind test without ever opening our rules
              or tests, and ran it through the real app.
            </>
          )}
        </p>
      </Prose>

      {blind2 && <Blind2Card set={blind2} detail={detail} />}

      {fair.length > 0 && (
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
          <h3 className="text-[17px] font-semibold text-ink">Other sets we did not tune on</h3>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2" aria-label="Other test sets we did not tune on">
            {fair.map((x) => (
              <SetCard key={x.name} set={x} blind1={x.name === "diagnostic_blind1" ? report.blind1_run : null} />
            ))}
          </ul>
        </div>
      )}

      {tuned.length > 0 && (
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
          <h3 className="text-[17px] font-semibold text-text-muted">Sets we tuned on (not a fair test)</h3>
          <p className="mt-1.5 text-[15px] leading-relaxed text-text-muted">
            We changed the rules until these passed, so a low number here only shows the fixes stuck.
            It does not show how Solace does on new wording.
          </p>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2" aria-label="Test sets we tuned the rules on">
            {tuned.map((x) => (
              <SetCard key={x.name} set={x} muted blind1={x.name === "diagnostic_blind1" ? report.blind1_run : null} />
            ))}
          </ul>
        </div>
      )}

      <Prose>
        {blind2 && (
          <p>
            <strong>What this means.</strong> Word rules catch the phrases they were written for, but
            on wording nobody had seen yet they still missed {of(blind2.after_missed ?? 0, blind2.urgent)}{" "}
            emergencies. That is why the patient also gets the red-flag checklist: tapping &ldquo;Hard
            to breathe&rdquo; does not depend on how they word it or which language they speak. With
            honest answers, the misses drop to {blind2.checklist_missed ?? "an unmeasured number"}.
            {detail && (
              <>
                {" "}
                The checklist appeared for {of(detail.checklistShownUrgent, blind2.urgent)} emergencies,
                because the rules had already put the others at ESI 1 or 2. Every emergency still missed
                is one that no checklist item describes, like sudden loss of sight, a stroke that shows up as
                dizziness, or a fever after chemotherapy.
              </>
            )}
          </p>
        )}
        {blind2 && blind2.after_over > 0 && (
          <p>
            <strong>False alarms.</strong> Blind test 2 also found {of(blind2.after_over, blind2.everyday)}{" "}
            everyday check-ins shown too urgent.
            {detail && (
              <>
                {" "}
                Three came from denials the rules did not notice. For example, &ldquo;I&rsquo;m not
                having a stroke or anything, my face is fine&rdquo; (about a cold sore) was shown ESI 1.
              </>
            )}{" "}
            The checklist cannot fix those, because it can only raise a score.
          </p>
        )}
        <p>We have not measured how much the AI red-flag check helps.</p>
      </Prose>

      {blind2 && detail && <LanguageTable set={blind2} detail={detail} />}

      <Prose>
        <p>
          <Link className="text-primary underline underline-offset-2" to={STRESS_REPORT_PATH}>
            Read the full report
          </Link>
          , with every missed phrase. It is also on{" "}
          <a className="text-primary underline underline-offset-2" href={STRESS_REPORT_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
          .
        </p>
      </Prose>

      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
        <h3 className="text-[17px] font-semibold text-ink">Our own phrases, one by one</h3>
        <p className="mt-2 mb-4 text-[15px] leading-relaxed text-text-muted">
          Our tests check {summary.cases} check-in phrases in {languages.length}{" "}
          {languages.length === 1 ? "language" : "languages"} ({languages.map(languageName).join(", ")}).
          {urgent < cases.length
            ? ` ${urgent} of them describe something that must never wait, so each has the least urgent score it may get. ${
                cases.length - urgent === 1 ? "The other one is an everyday problem" : `The other ${cases.length - urgent} are everyday problems`
              }, there to check that the rules do not flag everything.`
            : " Each one has the least urgent score it may get."}{" "}
          Claude Code, the AI coding assistant we used, wrote them at our direction, and no native
          speaker has checked the ones in other languages.
        </p>
        <div className="overflow-x-auto rounded-2xl bg-surface-lowest ring-1 ring-line">
          <table className="w-full min-w-[560px] text-left text-[14px]">
            <thead className="bg-surface-low text-text-muted">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Phrase</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Language</th>
                <th scope="col" className="px-4 py-2.5 font-medium text-right">Should be at most</th>
                <th scope="col" className="px-4 py-2.5 font-medium text-right">Before</th>
                <th scope="col" className="px-4 py-2.5 font-medium text-right">After</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((c, i) => (
                <tr key={`${i}-${c.text}`} className="align-top">
                  <td className="px-4 py-2.5 text-ink" lang={c.language}>&ldquo;{c.text}&rdquo;</td>
                  <td className="px-4 py-2.5 text-text-muted">{languageName(c.language)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {c.expected_max_esi < 5 ? `ESI ${c.expected_max_esi}` : "Any"}
                  </td>
                  <ScoreCell esi={c.before_esi} miss={missed(c.before_esi, c.expected_max_esi)} />
                  <ScoreCell esi={c.after_esi} miss={missed(c.after_esi, c.expected_max_esi)} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cases.length > 12 && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="mt-3 text-[15px] font-medium text-primary underline underline-offset-4 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            aria-expanded={showAll}
          >
            {showAll ? "Show fewer" : `Show all ${cases.length} phrases`}
          </button>
        )}
        <p className="mt-3 text-[14px] text-text-muted">
          The backend tests check every one of our own phrases, every red-team phrase and every blind
          test 1 check-in on each run, so a change that brings a miss back fails the tests.
          {knownMisses > 0
            ? ` The ${knownMisses} red-team ${knownMisses === 1 ? "miss" : "misses"} we have not fixed yet ${
                knownMisses === 1 ? "is" : "are"
              } kept in the tests as known failures, and so are the blind test 1 emergencies the rules alone cannot reach.`
            : ""}{" "}
          The held-out set and blind test 2 are only measured, never put in the tests, so nobody tunes
          the rules to them.
          {report.generated_at ? ` Numbers generated ${report.generated_at}.` : ""}
        </p>
      </div>
    </>
  );
}

function Blind2Card({ set, detail }: { set: RedFlagSet; detail: typeof BLIND2_DETAIL | null }) {
  const langs = detail ? ` in ${detail.languages.length} languages` : "";
  return (
    <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
      <section aria-labelledby="blind2-title" className="rounded-2xl bg-primary text-white p-5 sm:p-7 flex flex-col gap-4">
        <div>
          <h3 id="blind2-title" className="text-[18px] font-semibold text-white">
            Blind test 2: our honest number
          </h3>
          <p className="mt-1.5 text-[15px] leading-relaxed text-primary-fixed">
            {set.cases.toLocaleString("en-US")} check-ins{langs}, {set.urgent} of them emergencies,
            written after our last fix and run through the real app. Nothing in it was used to change
            the rules.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Stat value={of(set.after_missed ?? 0, set.urgent)} label="emergencies missed from the words alone" />
          {set.checklist_missed !== null && (
            <Stat value={of(set.checklist_missed, set.urgent)} label="missed when the patient answers the checklist truthfully" />
          )}
        </div>
        <dl className="text-[14px] leading-relaxed text-primary-fixed flex flex-col gap-1">
          <div>
            <dt className="inline">Too calm: </dt>
            <dd className="inline tabular-nums">
              {set.after_under} from the words alone
              {set.checklist_under !== null ? `, ${set.checklist_under} with the checklist` : ""}
            </dd>
          </div>
          {detail && (
            <div>
              <dt className="inline">The most urgent level: </dt>
              <dd className="inline tabular-nums">
                Only {of(detail.esi1AtOne, detail.esi1Expected)} ESI 1 emergencies were shown as ESI 1. With
                the checklist, the other {detail.esi1AtTwoWithChecklist} were shown ESI 2, because the
                checklist can only lift a score to ESI 2.
              </dd>
            </div>
          )}
          <div>
            <dt className="inline">Everyday problems shown too urgent: </dt>
            <dd className="inline tabular-nums">{of(set.after_over, set.everyday)}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <p className="rounded-xl bg-white/10 px-4 py-3 flex flex-col gap-1">
      <span className="text-[30px] leading-none font-semibold tabular-nums">{value}</span>
      <span className="text-[14px] leading-snug text-primary-fixed">{label}</span>
    </p>
  );
}

function SetCard({ set: x, blind1, muted = false }: { set: RedFlagSet; blind1: Blind1Run | null; muted?: boolean }) {
  const text = SET_TEXT[x.name] ?? { title: x.name, about: "" };
  return (
    <li
      className={`rounded-2xl p-5 flex flex-col gap-2 ring-1 ring-line ${
        muted ? "bg-surface-low" : "bg-surface-lowest"
      }`}
    >
      <h4 className={`text-[16px] font-semibold ${muted ? "text-text-muted" : "text-ink"}`}>{text.title}</h4>
      <p className="text-[14px] leading-relaxed text-text-muted">
        {x.cases.toLocaleString("en-US")} check-ins, {x.urgent.toLocaleString("en-US")} of them emergencies. {text.about}
      </p>
      <p
        className={`mt-1 leading-none font-semibold tabular-nums ${
          muted ? "text-[22px] text-text-muted" : "text-[32px] text-ink"
        }`}
      >
        {x.after_missed ?? x.after_under}
        <span className="text-[16px] font-medium text-text-muted">
          {" "}
          of {x.urgent.toLocaleString("en-US")} emergencies {x.after_missed === null ? "too calm" : "missed"} now
        </span>
      </p>
      <dl className="mt-1 text-[14px] leading-relaxed text-text-muted">
        {x.after_missed !== null && (
          <div>
            <dt className="inline">Too calm now: </dt>
            <dd className="inline tabular-nums">{of(x.after_under, x.urgent)}</dd>
          </div>
        )}
        {x.before_under !== null && (
          <div>
            <dt className="inline">Too calm before our fix: </dt>
            <dd className="inline tabular-nums">{of(x.before_under, x.urgent)}</dd>
          </div>
        )}
        {x.everyday > 0 && (
          <div>
            <dt className="inline">Everyday problems shown too urgent now: </dt>
            <dd className="inline tabular-nums">{of(x.after_over, x.everyday)}</dd>
          </div>
        )}
        {blind1 && (
          <div>
            <dt className="inline">When it ran blind: </dt>
            <dd className="inline tabular-nums">
              {of(blind1.missed, blind1.urgent)} missed from the words alone, {of(blind1.over, blind1.everyday)}{" "}
              everyday shown too urgent
            </dd>
          </div>
        )}
      </dl>
    </li>
  );
}

function LanguageTable({ set, detail }: { set: RedFlagSet; detail: typeof BLIND2_DETAIL }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
      <div className="overflow-x-auto rounded-2xl bg-surface-lowest ring-1 ring-line">
        <table className="w-full min-w-[520px] text-left text-[14px]">
          <caption className="text-left px-4 pt-4 pb-3 text-[15px] font-semibold text-ink">
            Blind test 2 by language
          </caption>
          <thead className="bg-surface-low text-text-muted">
            <tr>
              <th scope="col" className="px-4 py-2.5 font-medium">Language</th>
              <th scope="col" className="px-4 py-2.5 font-medium text-right">Emergencies missed, words alone</th>
              <th scope="col" className="px-4 py-2.5 font-medium text-right">With the checklist</th>
              <th scope="col" className="px-4 py-2.5 font-medium text-right">Everyday shown too urgent</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {detail.languages.map((l) => (
              <tr key={l.code}>
                <th scope="row" className="px-4 py-2.5 font-medium text-ink">{languageName(l.code)}</th>
                <td className="px-4 py-2.5 text-right tabular-nums">{of(l.missed, l.urgent)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{of(l.missedChecklist, l.urgent)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{of(l.over, l.everyday)}</td>
              </tr>
            ))}
            <tr className="bg-surface-low">
              <th scope="row" className="px-4 py-2.5 font-semibold text-ink">All</th>
              <td className="px-4 py-2.5 text-right tabular-nums font-semibold">{of(set.after_missed ?? 0, set.urgent)}</td>
              <td className="px-4 py-2.5 text-right tabular-nums font-semibold">{of(set.checklist_missed ?? 0, set.urgent)}</td>
              <td className="px-4 py-2.5 text-right tabular-nums font-semibold">{of(set.after_over, set.everyday)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScoreCell({ esi, miss }: { esi: number | null; miss: boolean }) {
  if (esi === null) return <td className="px-4 py-2.5 text-right text-text-muted">None</td>;
  return (
    <td className="px-4 py-2.5 text-right tabular-nums whitespace-nowrap">
      <span className={miss ? "font-semibold text-error" : "text-ink"}>ESI {esi}</span>
      {miss && <span className="ml-1.5 text-[12px] font-semibold text-error">too calm</span>}
    </td>
  );
}
