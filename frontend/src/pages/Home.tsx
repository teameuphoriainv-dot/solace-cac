import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Columns2, QrCode, RotateCcw, Smartphone, Stethoscope, type LucideIcon } from "lucide-react";
import { SiteNav } from "../components/marketing/SiteNav";
import { SiteFooter } from "../components/marketing/SiteFooter";
import { SectionHeading } from "../components/marketing/SectionHeading";
import { QueueDemo } from "../components/marketing/QueueDemo";
import { ExampleList } from "../components/marketing/ExampleList";
import { Il16Chart } from "../components/marketing/Il16Chart";
import { CONTEST, DEMO_SIGN_IN, SHOCK_VITALS, TEAM } from "../components/marketing/site";
import { ILLINOIS, IL16_SOURCE } from "../lib/il16";
import { startFreshSandbox, useSandboxId } from "../lib/sandbox";
import { clearSession } from "../lib/session";

// Front door for the Congressional App Challenge build. A judge lands here and has
// three ways into the same working app, all inside their own private demo hospital.

type Entry = {
  to: string;
  icon: LucideIcon;
  title: string;
  body: string;
  detail?: ReactNode;
  primary?: boolean;
};

const STEPS = [
  {
    title: "The patient describes it",
    body: "On their own phone, by typing or speaking. The screens come in 20 languages.",
  },
  {
    title: "Safety rules and a checklist",
    body: "Rules catch emergency words like chest pain. If nothing looks urgent yet, the patient taps any danger sign from a short list, in any language. The most urgent answer wins.",
  },
  {
    title: "A nurse adds vital signs",
    body: "A model trained on about 80,000 made-up ER visits re-checks the score at the bedside.",
  },
  {
    title: "The safety floor has the last word",
    body: "Dangerous vital signs can only raise the urgency, never lower it, and the screen says why.",
  },
];

export default function Home() {
  const sandbox = useSandboxId();

  useEffect(() => {
    document.title = "Solace: ER check-in that sorts by urgency";
  }, []);

  const entries: Entry[] = [
    {
      to: `/${sandbox}`,
      icon: Smartphone,
      title: "Check in as a patient",
      body: "Describe what is wrong by typing or speaking. Solace scores how urgent it is and tells you, in plain words, what to do while you wait.",
      detail: "The screens come in 20 languages.",
      primary: true,
    },
    {
      to: `/${sandbox}/clinician`,
      icon: Stethoscope,
      title: "Open the nurse dashboard",
      body: "The live queue the care team sees, most urgent first. Open a patient and enter vital signs to re-check the score.",
      detail: (
        <>
          Sign in as <span className="font-semibold text-ink">{DEMO_SIGN_IN.name}</span> with PIN{" "}
          <span className="font-mono font-semibold text-ink tracking-wider">{DEMO_SIGN_IN.pin}</span>
        </>
      ),
    },
    {
      to: "/showcase",
      icon: Columns2,
      title: "Watch both sides at once",
      body: "A patient phone next to the live queue, so you can watch a check-in land on the nurse dashboard.",
      detail: "Best on a laptop. The nurse dashboard signs in for you.",
    },
  ];

  function startFresh() {
    try {
      clearSession(); // the old sign-in belongs to the old demo hospital
    } catch {
      /* storage is blocked, so there is no saved sign-in to clear */
    }
    startFreshSandbox();
  }

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <div className="bg-surface-lowest">
        <SiteNav />
        <section
          aria-labelledby="home-title"
          className="mx-auto max-w-6xl px-4 sm:px-6 pt-6 pb-10 sm:pt-12 lg:pb-16 grid gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:items-center"
        >
          <div className="flex flex-col gap-6">
            <h1
              id="home-title"
              className="font-display font-normal text-[34px] leading-[1.1] sm:text-[44px] lg:text-[48px] lg:leading-[1.06] tracking-editorial-tight text-ink"
            >
              Solace sorts ER waiting-room patients by urgency, from their own phones.
            </h1>
            <p className="text-[18px] sm:text-[20px] leading-relaxed text-ink max-w-2xl">
              It is built so the sickest person is less likely to be missed. Safety rules can only raise
              a score, and a nurse always makes the real decision.
            </p>
            <p className="text-[16px] sm:text-[17px] leading-relaxed text-text-muted">
              Made by <span className="text-ink font-medium">{TEAM}</span>
              <br />
              {CONTEST}
            </p>
          </div>
          <div className="hidden lg:block">
            <QueueDemo />
          </div>
        </section>
      </div>

      <main className="flex-1">
        {/* Three ways in */}
        <section aria-label="Ways into the demo" className="mx-auto max-w-6xl px-4 sm:px-6 -mt-2 pt-0 lg:-mt-6">
          <ul className="grid gap-3 md:grid-cols-3">
            {entries.map((e) => (
              <li key={e.title}>
                <EntryLink entry={e} />
              </li>
            ))}
          </ul>
          <p className="mt-4 text-[14px]">
            <Link
              to={`/${sandbox}/qr`}
              className="inline-flex items-center gap-1.5 font-medium text-primary hover:underline underline-offset-4 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              <QrCode size={15} aria-hidden /> Show a QR code to check in from your phone
            </Link>
          </p>
          <div className="mt-4 rounded-xl bg-surface-lowest ring-1 ring-line px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3 sm:justify-between">
            <p className="text-[14px] leading-relaxed text-text-muted">
              You have your own private demo hospital,{" "}
              <span className="font-mono text-ink">{sandbox}</span>. You only see the five example
              patients and anyone you check in yourself.
            </p>
            <button
              type="button"
              onClick={startFresh}
              className="inline-flex shrink-0 items-center justify-center gap-1.5 h-10 px-4 rounded-md text-[14px] font-medium text-primary ring-1 ring-line hover:ring-primary/40 hover:bg-surface-low focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              <RotateCcw size={15} aria-hidden /> Start fresh
            </button>
          </div>
        </section>

        {/* The queue picture, for phones and tablets (desktop shows it in the hero) */}
        <section aria-label="Example waiting room" className="lg:hidden mx-auto max-w-xl px-4 sm:px-6 pt-12">
          <QueueDemo />
        </section>

        {/* Try these */}
        <section aria-labelledby="try-title" className="mx-auto max-w-6xl px-4 sm:px-6 pt-16 sm:pt-24">
          <div className="grid gap-8 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
            <SectionHeading
              id="try-title"
              title="Try these check-ins"
              sub="Paste one into the patient check-in, or tap it as an example there. Each of these exact phrases is in our automated tests, so you can see if the app gets it right."
            />
            <ExampleList />
          </div>
          <div className="mt-8 rounded-2xl bg-primary text-white p-5 sm:p-7 grid gap-5 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
            <div>
              <h3 className="font-display text-[24px] sm:text-[28px] leading-tight tracking-editorial">
                Then test the safety floor
              </h3>
              <p className="mt-2 text-[15px] leading-relaxed text-primary-fixed">
                Open James (ESI 4, sprained ankle) on the nurse dashboard and enter these vital
                signs. Whatever the trained model guesses, the safety rules raise the score to ESI 2
                or more urgent, and the screen lists the reasons.
              </p>
            </div>
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 self-center">
              {SHOCK_VITALS.map((v) => (
                <div key={v.label} className="rounded-xl bg-white/10 px-3 py-3">
                  <dt className="text-[13px] text-primary-fixed">{v.label}</dt>
                  <dd className="mt-0.5 text-[24px] font-semibold tabular-nums">{v.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* IL-16 */}
        <section aria-labelledby="il16-title" className="mx-auto max-w-6xl px-4 sm:px-6 pt-16 sm:pt-24">
          <div className="grid gap-8 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
            <div className="flex flex-col gap-4">
              <SectionHeading id="il16-title" title="Why this matters in Illinois's 16th District" />
              <div className="flex flex-col gap-3 text-[16px] leading-relaxed text-text-muted max-w-xl">
                <p>
                  The 16th District is mostly small towns, plus parts of Rockford and Peoria. Its own
                  small ERs mostly move faster than the state as a whole. The big city ERs in Rockford
                  and Peoria sit just outside the district line, and that is where patients spend the
                  longest.
                </p>
                <p>
                  At 5 of those 6 ERs, patients who were sent home spent longer in the ER than the
                  Illinois typical time of {ILLINOIS.minutes} minutes, up to 286 minutes. At two of
                  them, 6 in every 100 patients left before being seen, twice the Illinois rate.
                </p>
                <p className="text-ink">
                  People who wait a long time without knowing where they stand are the people Solace
                  is built for.
                </p>
              </div>
            </div>
            <div>
              <Il16Chart />
              <p className="mt-4 text-[13px] leading-relaxed text-text-muted">
                Source: Centers for Medicare and Medicaid Services, Timely and Effective Care,{" "}
                <a className="underline underline-offset-2 hover:text-ink" href={IL16_SOURCE.datasetUrl} target="_blank" rel="noreferrer">
                  hospital file
                </a>{" "}
                and{" "}
                <a className="underline underline-offset-2 hover:text-ink" href={IL16_SOURCE.stateDatasetUrl} target="_blank" rel="noreferrer">
                  state file
                </a>
                , updated {IL16_SOURCE.updated}, downloaded {IL16_SOURCE.downloaded}. Time in the ER
                is measure {IL16_SOURCE.timeMeasure} (the median for patients sent home,{" "}
                {IL16_SOURCE.timePeriod}). Left before being seen is measure {IL16_SOURCE.leftMeasure} (
                {IL16_SOURCE.leftPeriod}). District lines come from the {IL16_SOURCE.districtCheck}.
              </p>
            </div>
          </div>
        </section>

        {/* How it works teaser */}
        <section aria-labelledby="how-title" className="mx-auto max-w-6xl px-4 sm:px-6 pt-16 sm:pt-24 pb-20 sm:pb-28">
          <SectionHeading
            id="how-title"
            title="How it works"
            sub="Two checks, one at check-in and one at the bedside. Safety rules guard both and can only raise a score. They still miss some emergencies, and our test results show how many."
          />
          <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex flex-col gap-2 border-t-2 border-primary pt-4">
                <span className="text-[14px] font-semibold text-primary tabular-nums">Step {i + 1}</span>
                <h3 className="text-[17px] font-semibold text-ink leading-snug">{s.title}</h3>
                <p className="text-[15px] leading-relaxed text-text-muted">{s.body}</p>
              </li>
            ))}
          </ol>
          <Link
            to="/how-it-works"
            className="mt-10 inline-flex items-center gap-2 h-12 px-6 rounded-full bg-primary text-white font-medium hover:bg-primary-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
          >
            See how it works, with our test results <ArrowRight size={16} aria-hidden />
          </Link>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}

function EntryLink({ entry }: { entry: Entry }) {
  const { to, icon: Icon, title, body, detail, primary } = entry;
  return (
    <Link
      to={to}
      className={`group h-full flex flex-col gap-3 rounded-2xl p-5 sm:p-6 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-primary/50 ${
        primary
          ? "bg-primary text-white hover:bg-primary-hover"
          : "bg-surface-lowest ring-1 ring-line hover:ring-primary/40"
      }`}
    >
      <span
        className={`h-11 w-11 rounded-xl flex items-center justify-center ${
          primary ? "bg-white/15 text-white" : "bg-primary-dim text-primary"
        }`}
      >
        <Icon size={20} aria-hidden />
      </span>
      <span className={`flex items-center gap-2 text-[18px] font-semibold ${primary ? "text-white" : "text-ink"}`}>
        {title}
        <ArrowRight
          size={17}
          aria-hidden
          className={`transition-transform group-hover:translate-x-0.5 ${primary ? "text-primary-fixed" : "text-text-muted group-hover:text-primary"}`}
        />
      </span>
      <span className={`text-[15px] leading-relaxed ${primary ? "text-primary-fixed" : "text-text-muted"}`}>{body}</span>
      {detail && (
        <span
          className={`mt-auto pt-3 border-t text-[14px] ${
            primary ? "border-white/15 text-white" : "border-line text-text-muted"
          }`}
        >
          {detail}
        </span>
      )}
    </Link>
  );
}
