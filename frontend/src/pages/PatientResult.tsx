import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Leaf, Loader2, ShieldCheck } from "lucide-react";
import { AudioPlayer } from "../components/patient/AudioPlayer";
import { CareRecommendationCard, careCopy, crisisCopy, type CareRec } from "../components/patient/CareCard";
import { ComfortProtocol } from "../components/patient/ComfortProtocol";
import { DemoBanner } from "../components/patient/DemoBanner";
import { useSidePaths } from "../lib/paths";
import { ESIBadge } from "../components/patient/ESIBadge";
import { PainEscalateButton } from "../components/patient/PainEscalateButton";
import { PatientLogo } from "../components/patient/PatientLogo";
import { ReadAloud } from "../components/patient/ReadAloud";
import { SmsSelfServe } from "../components/patient/SmsSelfServe";
import { said, withoutSaid, type Said } from "../components/patient/sayOnce";
import { DEMO_SIGN_IN } from "../components/marketing/site";
import { errorStatus, getPublicPatient, liveStatus, type LiveStatus } from "../lib/api-patient";
import { useCapabilities } from "../lib/capabilities";
import { PATIENT_LANG_KEY } from "../lib/constants";
import { LANGUAGES, isRTL, t, useLanguage } from "../lib/i18n";
import { isDemoHospital } from "../lib/sandbox";
import type { ComfortAction, IntakeResponse, PatientEducation, PublicPatient } from "../types";

type Key = Parameters<typeof t>[0];

const POLL_MS = 15_000;

// Comfort guidance and spoken audio are made after the intake response returns,
// so the screen shows the score at once and polls briefly for those two.
const COMFORT_POLL_MS = 3_000;
const COMFORT_POLL_MAX_ATTEMPTS = 15; // ~45s ceiling, then we stop trying.

// Small caps headings. Letter spacing breaks joined scripts such as Arabic apart,
// so it is off right to left.
const CAPS = "text-[13px] uppercase tracking-[0.12em] rtl:tracking-normal font-semibold";

// Plain-language "what this means" for each ESI level, in the patient's own
// language. Written to reassure a stressed patient: it explains the priority
// number without medical jargon and without ever implying their wait is unsafe.
function esiMeaning(level: number, lang: string): { headline: string; body: string } | null {
  if (level < 1 || level > 5) return null;
  return {
    headline: t(`result_esi${level}_headline` as Key, lang),
    body: t(`result_esi${level}_body` as Key, lang),
  };
}

const EXPLAIN_KEYS = new Set(["esi1", "esi2", "esi3", "esi4", "crisis", "needs_reading"]);

// The sentence the server picked for this patient (for example the 988 line, or
// "a nurse will read what you wrote"). Its own words when they are in the
// patient's language, otherwise the translated sentence for the same key.
function explanationText(r: IntakeResponse, lang: string): string | null {
  const key = r.explanation_key;
  if (!key || !EXPLAIN_KEYS.has(key)) return null;
  if (r.patient_explanation && (r.explanation_language || "en") === lang) return r.patient_explanation;
  return t(`result_explain_${key}` as Key, lang);
}

// Rebuild the assessment from the public patient view when the sessionStorage
// seed is gone (refresh, restored tab, another device).
function buildResultFromPublic(p: PublicPatient): IntakeResponse {
  // esi_level is the level to act on now; the check-in level is kept apart.
  const checkin = liveStatus(p).checkinLevel;
  return {
    patient_id: p.patient_id,
    esi_level: (checkin ?? p.esi_level ?? 3) as IntakeResponse["esi_level"],
    esi_label: p.esi_label ?? "",
    patient_explanation: p.patient_explanation ?? "",
    explanation_key: p.explanation_key,
    explanation_language: p.explanation_language,
    comfort_protocol: p.comfort_protocol ?? [],
    audio_url: p.audio_url ?? null,
    confidence_band: null,
    language: p.language ?? "en",
    care_recommendation: p.care_recommendation,
  };
}

function readSeed(patientId: string): IntakeResponse | null {
  try {
    const raw = sessionStorage.getItem(`intake:${patientId}`);
    return raw ? (JSON.parse(raw) as IntakeResponse) : null;
  } catch {
    return null;
  }
}

// The checklist rows this patient tapped on the check-in screen (this tab only).
function readTappedFlags(patientId: string): string[] {
  try {
    const raw = sessionStorage.getItem(`intake:${patientId}:red_flags`);
    const v: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function storedLang(): string {
  try {
    return sessionStorage.getItem(PATIENT_LANG_KEY) || "en";
  } catch {
    return "en";
  }
}

function waitText(minutes: number | null, fallback: string | null, lang: string): string | null {
  if (minutes == null || !Number.isFinite(minutes)) return fallback;
  if (minutes <= 5) return t("result_wait_under5", lang);
  return t("result_wait_range", lang)
    .replace("{lo}", String(Math.max(5, minutes - 5)))
    .replace("{hi}", String(minutes + 5));
}

function sentence(s: string): string {
  const v = s.trim();
  return !v || /[.!?。！？।۔؟]$/.test(v) ? v : `${v}.`;
}

const NO_LIVE: LiveStatus = {
  level: null, checkinLevel: null, rechecked: false, serverRebuilds: false, raised: false, waitKind: null,
};

function sameLive(a: LiveStatus, b: LiveStatus): boolean {
  return (Object.keys(a) as Array<keyof LiveStatus>).every((k) => a[k] === b[k]);
}

export default function PatientResult() {
  const { hospitalId = "demo", patientId = "" } = useParams<{ hospitalId: string; patientId: string }>();
  const sidePaths = useSidePaths();
  const caps = useCapabilities(hospitalId);
  const seedRef = useRef<IntakeResponse | null>(readSeed(patientId));
  const [selfHarmTapped] = useState(() => readTappedFlags(patientId).includes("self_harm"));
  const [result, setResult] = useState<IntakeResponse | null>(seedRef.current);
  const [notFound, setNotFound] = useState(false);
  const [education, setEducation] = useState<PatientEducation | null>(null);
  const [educationPublishedAt, setEducationPublishedAt] = useState<string | null>(null);
  const [waitMinutes, setWaitMinutes] = useState<number | null>(null);
  const [waitRange, setWaitRange] = useState<string | null>(null);
  const [careRec, setCareRec] = useState<CareRec | null>(seedRef.current?.care_recommendation ?? null);
  // The score the queue acts on now, and whether a nurse re-checked it.
  const [live, setLive] = useState<LiveStatus>(NO_LIVE);
  // Deferred comfort/audio: pending until the backend worker fills them in.
  const [comfortPending, setComfortPending] = useState(
    !(seedRef.current?.comfort_protocol && seedRef.current.comfort_protocol.length > 0)
  );
  const [audioFailed, setAudioFailed] = useState(false);

  const lang = result?.language || storedLang();
  // Re-renders this screen when the patient's language finishes loading (main.tsx
  // starts it early on a reload). Until then the words, and so dir and lang, are English.
  const shownLang = useLanguage(lang) ? lang : "en";

  useEffect(() => {
    document.title = "Check in: Solace";
  }, []);

  // The intake page resets <html dir/lang> when it unmounts, so set them again here,
  // before paint, so the words and their direction change in the same frame.
  useLayoutEffect(() => {
    document.documentElement.setAttribute("dir", isRTL(shownLang) ? "rtl" : "ltr");
    document.documentElement.setAttribute("lang", shownLang);
    return () => {
      document.documentElement.setAttribute("dir", "ltr");
      document.documentElement.setAttribute("lang", "en");
    };
  }, [shownLang]);

  // What every poll reads: the current score, a re-check, and the server's card.
  // When a re-check raised the priority, the server rebuilt the explanation, the
  // comfort cards and the card for it (and dropped the audio made for the old one).
  function applyLive(p: PublicPatient) {
    const next = liveStatus(p);
    setLive((prev) => (sameLive(prev, next) ? prev : next));
    const rec = p.care_recommendation;
    if (rec) setCareRec((prev) => (prev && JSON.stringify(prev) === JSON.stringify(rec) ? prev : rec));
    if (next.raised) {
      setResult((prev) => {
        if (!prev) return prev;
        const fresh = {
          ...prev,
          patient_explanation: p.patient_explanation ?? "",
          explanation_key: p.explanation_key,
          explanation_language: p.explanation_language,
          comfort_protocol: p.comfort_protocol ?? [],
          audio_url: p.audio_url ?? null,
        };
        return JSON.stringify(fresh) === JSON.stringify(prev) ? prev : fresh;
      });
    }
  }

  // Short, capped poll for the deferred comfort guidance + audio. Stops as soon
  // as comfort arrives, the cap is hit, or the server no longer has this patient.
  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    let stopped = false;
    let timer: number | null = null;
    let attempts = 0;

    async function tick() {
      attempts += 1;
      try {
        const p = await getPublicPatient(hospitalId, patientId);
        if (cancelled) return;
        if (p.esi_level) {
          setResult((prev) => prev ?? buildResultFromPublic(p));
        }
        applyLive(p);
        const ready = (p.comfort_protocol && p.comfort_protocol.length > 0) || p.comfort_ready;
        const failed = p.artifacts_status === "failed";
        if (ready || failed) {
          setResult((prev) =>
            prev
              ? { ...prev, comfort_protocol: p.comfort_protocol ?? [], audio_url: p.audio_url ?? null }
              : prev
          );
          setComfortPending(false);
          stopped = true;
        }
      } catch (e) {
        if (cancelled) return;
        if (errorStatus(e) === 404) {
          // The server lost this check-in (in-memory demo storage restarted).
          stopped = true;
          setComfortPending(false);
          if (!seedRef.current) setNotFound(true);
        }
        // anything else: retry on the next tick, within the cap
      } finally {
        if (!cancelled && !stopped && attempts < COMFORT_POLL_MAX_ATTEMPTS) {
          timer = window.setTimeout(tick, COMFORT_POLL_MS);
        } else if (!cancelled && !stopped) {
          setComfortPending(false);
        }
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [hospitalId, patientId]);

  // Slow poll for what the care team publishes, a re-check, and the live wait estimate.
  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    let stopped = false;
    let timer: number | null = null;

    async function tick() {
      try {
        const p = await getPublicPatient(hospitalId, patientId);
        if (cancelled) return;
        if (p.patient_education) {
          setEducation(p.patient_education);
          setEducationPublishedAt(p.patient_education_published_at);
        }
        // Null for priority 1 or 2: the screen shows a sentence instead of minutes.
        setWaitMinutes(typeof p.wait_estimate_minutes === "number" ? p.wait_estimate_minutes : null);
        setWaitRange(p.wait_estimate_range || null);
        applyLive(p);
      } catch (e) {
        if (!cancelled && errorStatus(e) === 404) stopped = true;
      } finally {
        if (!cancelled && !stopped) timer = window.setTimeout(tick, POLL_MS);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [hospitalId, patientId]);

  if (!result && notFound) {
    return (
      <div className="min-h-[100dvh] flex flex-col bg-surface">
        <DemoBanner lang={lang} />
        <main className="flex-1 flex flex-col items-center justify-center gap-4 px-6 py-10 text-center max-w-md mx-auto">
          <PatientLogo hospitalId={hospitalId} lang={lang} className="h-12" />
          <h1 className="text-2xl font-bold tracking-tight rtl:tracking-normal">{t("result_not_found_title", lang)}</h1>
          <p className="text-[15px] text-text-muted leading-relaxed">{t("result_not_found_body", lang)}</p>
          <Link
            to={sidePaths.patient}
            className="inline-flex items-center justify-center min-h-12 px-6 rounded-md bg-primary text-white font-semibold shadow-soft hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
          >
            {t("result_start_new", lang)}
          </Link>
        </main>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="min-h-[100dvh] flex flex-col bg-surface">
        <DemoBanner lang={lang} />
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center" role="status" aria-live="polite">
          <Loader2 size={28} className="animate-spin text-primary" aria-hidden="true" />
          <div className="text-[15px] font-semibold text-ink">{t("result_preparing_title", lang)}</div>
          <div className="text-sm text-text-muted">{t("result_preparing_subtitle", lang)}</div>
        </div>
      </div>
    );
  }

  // The score shown is the one to act on now: a nurse's re-check can make it more urgent.
  const level = live.level ?? result.esi_level;
  // An older server keeps the check-in words after a re-check changed the score, so
  // this screen drops them itself. A current server rewrites them for the new score.
  const levelChanged = live.rechecked && !live.serverRebuilds && level !== result.esi_level;
  const recheckText = live.rechecked ? t("result_rechecked", lang).replace("{n}", String(level)) : "";
  const meaning = esiMeaning(level, lang);
  const serverCare = careRec ? careCopy(careRec, lang, level, levelChanged) : null;
  // The server answers a tapped self-harm row with its 988 card. If it did not
  // (an older server), show that same card's text anyway. ESI 1 keeps "get help now".
  const care = selfHarmTapped && level >= 2 && serverCare?.kind !== "crisis" ? crisisCopy(lang) : serverCare;
  // The server's sentence for esi1..esi4 and crisis says what the care card
  // below already says, so it only replaces the "what this means" text when it
  // adds something: "a nurse will read what you wrote", or crisis with no card.
  // After a re-check changed the score it describes the old score, so it is not used.
  const explained = levelChanged ? null : explanationText(result, lang);
  const key = result.explanation_key;
  const useExplained = !!explained && (key === "needs_reading" || (key === "crisis" && !care));
  const meaningBody = (useExplained ? explained : meaning?.body) ?? "";
  // Older servers sent only a sentence in English, with no key.
  const showExplanation =
    !explained && !levelChanged && !!result.patient_explanation && (lang === "en" || caps?.llm === true);
  const languageName = LANGUAGES.find((l) => l.code === lang)?.native ?? lang;
  const hasAudio = !!result.audio_url && !audioFailed;
  // Priority 1 or 2 (or the 988 card): a sentence, not minutes. Older servers do not say, so follow the score.
  const waitNow = live.waitKind
    ? live.waitKind === "now"
    : level <= 2 || care?.kind === "crisis" || care?.kind === "now";
  const wait = waitNow ? t("result_wait_now", lang) : waitText(waitMinutes, waitRange, lang);

  // Say each instruction once: "what this means" and the care card's words come
  // first, the comfort cards drop what those already said, the care card's steps
  // drop what any of them said, and the footer drops what the screen already said.
  const firstSaid: Said = said(meaningBody, showExplanation ? result.patient_explanation : "", care?.body);
  const comfort: ComfortAction[] = [];
  let comfortSaid: Said = [];
  for (const action of result.comfort_protocol ?? []) {
    const instruction = withoutSaid(action.instruction, [...firstSaid, ...comfortSaid]);
    if (!instruction.trim()) continue;
    comfort.push(instruction === action.instruction ? action : { ...action, instruction });
    comfortSaid = comfortSaid.concat(said(instruction));
  }
  const steps: string[] = [];
  for (const step of care?.steps ?? []) {
    const before = [...firstSaid, ...(education ? [] : comfortSaid), ...said(...steps)];
    const kept = withoutSaid(step, before);
    if (kept.trim()) steps.push(kept);
  }
  const careShown = care ? { ...care, steps } : null;
  const footer = withoutSaid(
    t("result_footer_disclaimer", lang),
    [...firstSaid, ...(education ? [] : comfortSaid), ...said(...steps, care?.note, waitNow && !education ? wait : "")],
  );

  const readText = [
    recheckText,
    meaning?.headline,
    meaningBody,
    showExplanation ? result.patient_explanation : "",
    care?.title,
    care?.body,
    ...steps,
    care?.note,
    waitNow && !education ? wait : "",
    ...(education
      ? [education.headline, education.what_we_are_doing, ...(education.things_to_do_at_home ?? []), education.when_to_come_back]
      : comfort.flatMap((a) => [a.title, a.instruction])),
  ]
    .filter((s): s is string => !!s && !!s.trim())
    .map(sentence)
    .join(" ");

  let publishedTime = "";
  if (educationPublishedAt) {
    try {
      publishedTime = new Date(educationPublishedAt).toLocaleTimeString(lang, { hour: "numeric", minute: "2-digit" });
    } catch {
      publishedTime = new Date(educationPublishedAt).toLocaleTimeString();
    }
  }

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <DemoBanner lang={lang} />
      <div className="flex-1 px-5 pb-32 max-w-lg w-full mx-auto flex flex-col gap-8">
        <header className="flex items-start justify-between gap-3 pt-5">
          <PatientLogo hospitalId={hospitalId} lang={lang} className="h-12 sm:h-16" />
          {lang !== "en" && (
            <span
              className="text-[13px] text-text-muted bg-surface-low px-2 py-1 rounded"
              aria-label={t("result_language_aria", lang).replace("{language}", languageName)}
            >
              {languageName}
            </span>
          )}
        </header>

        <section className="flex flex-col gap-4">
          <div>
            <h1 className={`${CAPS} text-text-muted mb-2`}>{t("result_your_priority", lang)}</h1>
            {/* The heading already says "priority", so the badge shows only its label. */}
            <ESIBadge esiLevel={level} size="lg" caption={false} language={lang} />
            <div aria-live="polite">
              {recheckText && (
                <p className="mt-3 rounded-md bg-primary-fixed/60 px-3 py-2 text-[15px] font-semibold leading-snug text-ink">
                  {recheckText}
                </p>
              )}
            </div>
            <p className="mt-3 text-[14px] text-text-muted">{t("result_scale_note", lang)}</p>
          </div>

          {meaning && (
            <div className="rounded-xl bg-surface-lowest shadow-soft p-4 flex flex-col gap-1">
              <h2 className={`${CAPS} text-text-muted`}>{t("result_what_this_means", lang)}</h2>
              <div className="text-[16px] font-bold tracking-editorial rtl:tracking-normal leading-snug text-ink">
                {meaning.headline}
              </div>
              <p className="text-[15px] leading-relaxed text-ink/90">{meaningBody}</p>
            </div>
          )}

          {showExplanation && (
            <p className="text-[17px] leading-relaxed text-ink/90">{result.patient_explanation}</p>
          )}

          {!hasAudio && <ReadAloud text={readText} lang={lang} />}
        </section>

        {careShown && <CareRecommendationCard copy={careShown} lang={lang} />}

        <PainEscalateButton hospitalId={hospitalId} patientId={patientId} language={lang} />

        {/* Waits for capabilities so the button never offers a send that cannot happen. */}
        {caps && <SmsSelfServe hospitalId={hospitalId} patientId={patientId} lang={lang} smsOn={caps.sms} />}

        {education ? (
          <motion.section
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col gap-3 bg-surface-lowest rounded-xl p-5 shadow-soft"
          >
            <div className="flex items-center gap-2 text-primary">
              <ShieldCheck size={16} aria-hidden="true" />
              <h2 className={CAPS}>
                {t("result_from_care_team", lang)}
                {publishedTime && (
                  <span className="ms-1 text-text-muted normal-case tracking-normal font-normal">
                    ({publishedTime})
                  </span>
                )}
              </h2>
            </div>
            <h3 className="text-xl font-bold tracking-editorial rtl:tracking-normal leading-snug">{education.headline}</h3>
            <p className="text-[15px] leading-relaxed">{education.what_we_are_doing}</p>
            {education.things_to_do_at_home?.length > 0 && (
              <div>
                <div className={`${CAPS} text-text-muted mt-1 mb-1`}>
                  {/* The no-AI summary carries waiting-room steps; the server says which heading fits. */}
                  {education.steps_heading === "while_you_wait"
                    ? t("result_while_you_wait", lang)
                    : t("result_at_home", lang)}
                </div>
                <ul className="text-[15px] leading-relaxed list-disc ms-5 flex flex-col gap-1">
                  {education.things_to_do_at_home.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <div className={`${CAPS} text-text-muted mt-1 mb-1`}>{t("result_come_back_if", lang)}</div>
              <p className="text-[15px] leading-relaxed">{education.when_to_come_back}</p>
            </div>
            {education.closing && (
              <p className="text-[14px] italic text-text-muted">{education.closing}</p>
            )}
          </motion.section>
        ) : (
          <section className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-text-muted">
              <Leaf size={14} strokeWidth={1.5} aria-hidden="true" />
              <h2 className={CAPS}>{t("result_while_you_wait", lang)}</h2>
            </div>
            {wait && (
              <div className="rounded-lg bg-surface-lowest px-4 py-3 shadow-soft">
                {waitNow ? (
                  <div className="text-[17px] font-bold leading-snug text-primary">{wait}</div>
                ) : (
                  <>
                    <div className={`${CAPS} text-text-muted`}>{t("result_estimated_wait", lang)}</div>
                    <div className="text-xl font-bold tracking-editorial rtl:tracking-normal text-primary mt-0.5">{wait}</div>
                    <div className="text-[13px] text-text-muted mt-0.5">{t("result_wait_updates", lang)}</div>
                  </>
                )}
              </div>
            )}
            {comfortPending && comfort.length === 0 ? (
              <div
                className="flex items-center gap-2 rounded-lg bg-surface-lowest px-4 py-4 shadow-soft text-text-muted"
                aria-live="polite"
                aria-busy="true"
              >
                <Loader2 size={16} className="animate-spin text-primary" aria-hidden="true" />
                <span className="text-[14px]">{t("result_preparing_guidance", lang)}</span>
              </div>
            ) : comfort.length > 0 ? (
              <ComfortProtocol actions={comfort} />
            ) : (result.comfort_protocol ?? []).length === 0 ? (
              <p className="rounded-lg bg-surface-lowest px-4 py-4 shadow-soft text-[15px] text-ink leading-relaxed">
                {t("result_comfort_empty", lang)}
              </p>
            ) : null}
          </section>
        )}

        {isDemoHospital(hospitalId) && !sidePaths.bare && (
          // Only on demo hospitals reached by id ("/patient" stays patient-only): the next stop for a visitor trying both sides.
          <nav className="flex flex-col gap-1 rounded-lg bg-surface-low px-4 py-3 text-[14px] leading-snug">
            <Link
              to={`/${hospitalId}/clinician`}
              className="inline-flex items-center gap-1.5 min-h-[44px] font-semibold text-primary underline underline-offset-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
            >
              <span>
                {t("result_demo_dashboard", lang)
                  .replace("{name}", DEMO_SIGN_IN.name)
                  .replace("{pin}", DEMO_SIGN_IN.pin)}
              </span>
              <ArrowRight size={14} aria-hidden="true" className="shrink-0 rtl:rotate-180" />
            </Link>
            <Link
              to="/"
              className="inline-flex items-center min-h-[44px] text-text-muted underline underline-offset-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
            >
              {t("result_demo_home", lang)}
            </Link>
          </nav>
        )}

        <footer
          className="text-[13px] text-text-muted leading-relaxed pt-2"
          style={{ paddingBottom: "calc(0.5rem + env(safe-area-inset-bottom, 0px))" }}
        >
          {footer}
        </footer>
      </div>

      {hasAudio ? (
        <AudioPlayer audioUrl={result.audio_url} language={lang} onFailed={() => setAudioFailed(true)} />
      ) : comfortPending && caps?.tts ? (
        <div
          className="mx-4 mb-4 flex items-center gap-2 rounded-lg bg-surface-low px-4 py-3 text-sm text-text-muted"
          aria-live="polite"
          aria-busy="true"
        >
          <Loader2 size={14} className="animate-spin text-primary" aria-hidden="true" />
          {t("result_preparing_audio", lang)}
        </div>
      ) : null}
    </div>
  );
}
