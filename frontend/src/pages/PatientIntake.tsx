import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight, CheckCircle2, Keyboard, Loader2, Mic, X as XIcon } from "lucide-react";
import { MicButton } from "../components/patient/MicButton";
import { MedicalInfoForm } from "../components/patient/MedicalInfoForm";
import { PhotoCapture } from "../components/patient/PhotoCapture";
import { FollowupQuestions, toAnswerList } from "../components/patient/FollowupQuestions";
import { InsuranceScanner } from "../components/patient/InsuranceScanner";
import { LanguageGate } from "../components/patient/LanguageGate";
import { IdScanner } from "../components/patient/IdScanner";
import { DemoBanner } from "../components/patient/DemoBanner";
import { useSidePaths } from "../lib/paths";
import { PatientLogo } from "../components/patient/PatientLogo";
import { ExampleChips } from "../components/patient/ExampleChips";
import { RedFlagChecklist, appendChecklistFlags, type ChecklistId } from "../components/patient/RedFlagChecklist";
import { Button } from "../components/ui/Button";
import { ProgressDots } from "../components/ui/ProgressDots";
import { TourLauncher } from "../components/tour/TourLauncher";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import {
  errorDetail,
  errorStatus,
  identityLookup,
  isUnknownHospital,
  postIntake,
  postTranscribe,
  startIntake,
  type IdentityLookupResult,
} from "../lib/api-patient";
import { useCapabilities } from "../lib/capabilities";
import { PATIENT_LANG_KEY } from "../lib/constants";
import { isRTL, t, useLanguage, type LangCode } from "../lib/i18n";
import { isDemoHospital } from "../lib/sandbox";
import type { FollowupQuestion, InsuranceFields, MedicalInfo } from "../types";

type Step =
  | "language" | "id-scan" | "welcome" | "medical" | "insurance" | "record" | "redflags" | "followups" | "submitting";

const emptyMedical: MedicalInfo = {
  age: null,
  sex: null,
  pregnant: null,
  gestational_weeks: null,
  allergies: [],
  allergy_severity: {},
  medications: [],
  blood_thinner_name: null,
  conditions: [],
  diabetes_type: null,
  heart_failure_class: null,
  smoker: null,
};

const stepOrder: Step[] = [
  "language", "id-scan", "welcome", "medical", "insurance", "record", "redflags", "followups", "submitting",
];

/** The browser heard nothing and the server cannot transcribe audio (no key). */
class VoiceNotCaught extends Error {}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export default function PatientIntake() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const sidePaths = useSidePaths();
  const navigate = useNavigate();
  const recorder = useAudioRecorder();
  const caps = useCapabilities(hospitalId);

  const [step, setStep] = useState<Step>("language");
  const [name, setName] = useState("");
  const [medical, setMedical] = useState<MedicalInfo>(emptyMedical);
  const [insurance, setInsurance] = useState<InsuranceFields | null>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const [textFallback, setTextFallback] = useState("");
  const [inputMode, setInputMode] = useState<"voice" | "type">("voice");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalidLink, setInvalidLink] = useState(false);

  const [transcript, setTranscript] = useState<string>("");
  const [, setLanguage] = useState<string>("en");
  const [preferredLanguage, setPreferredLanguage] = useState<LangCode>("en");
  const [followups, setFollowups] = useState<FollowupQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  // The red-flag checklist. The server skips it when the words already show an emergency.
  const [showChecklist, setShowChecklist] = useState(false);
  const [redFlags, setRedFlags] = useState<ChecklistId[]>([]);
  const [intakeToken, setIntakeToken] = useState<string | null>(null);
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());
  const [consentGranted, setConsentGranted] = useState(false);
  const CONSENT_VERSION = "1.0";
  const voiceMissesRef = useRef(0);
  // An example chip fills the box; don't pop the phone keyboard over it.
  const [focusTextBox, setFocusTextBox] = useState(true);

  const lang = preferredLanguage;
  // English is built in; any other language loads when picked (the gate starts it),
  // and this re-renders every step once it arrives.
  const langReady = useLanguage(lang);
  // What the screen is showing right now: English until the patient's language arrives.
  const shownLang = langReady ? lang : "en";
  const ocrOn = caps?.ocr === true;
  // Demo hospitals always offer the made-up sample ID and card, so nobody needs a real one.
  const demo = isDemoHospital(hospitalId);
  // Speaking needs either live dictation in this browser or server transcription.
  const voiceUnavailable = caps !== null && !caps.transcription && !recorder.webSpeechSupported;
  const typing = inputMode === "type" || recorder.permissionDenied || voiceUnavailable;
  // Until capabilities arrive, describe the AI services in the consent text (the cautious choice).
  const aiOn = caps === null || caps.llm || caps.transcription || caps.tts || caps.ocr;

  // Returning-patient match, from the ID scan or the insurance card. The banner
  // stays up for the rest of the intake so the patient knows why fields are filled.
  const [ehrMatched, setEhrMatched] = useState<IdentityLookupResult | null>(null);
  const [ehrBannerDismissed, setEhrBannerDismissed] = useState(false);
  const ehrAttemptedInsuranceRef = useRef(false);

  const applyEhrMatch = (result: IdentityLookupResult) => {
    if (!result.matched || !result.prefill) return;
    setMedical((cur) => ({
      ...cur,
      age: result.prefill?.age ?? cur.age,
      sex: result.prefill?.sex ?? cur.sex,
      allergies: result.prefill?.allergies ?? cur.allergies,
      medications: result.prefill?.medications ?? cur.medications,
      conditions: result.prefill?.conditions ?? cur.conditions,
    }));
    if (result.ehr_record?.name && !name) {
      setName(result.ehr_record.name.split(" ")[0]);
    }
    setEhrMatched(result);
  };

  // No match from the ID (or no ID)? An insurance member ID is often enough to
  // find the record.
  useEffect(() => {
    if (ehrMatched || ehrAttemptedInsuranceRef.current) return;
    const memberId = (insurance?.member_id || "").trim();
    if (!memberId) return;
    ehrAttemptedInsuranceRef.current = true;
    identityLookup(hospitalId, {
      first_name: "",
      last_name: "",
      dob: "",
      insurance_member_id: memberId,
      insurance_provider: insurance?.provider || "",
    })
      .then((r) => {
        if (r.matched) applyEhrMatch(r);
      })
      .catch(() => { /* silent: patient flow continues either way */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [insurance?.member_id, ehrMatched, hospitalId]);

  // Mirror the shown language onto <html dir> so RTL scripts (Arabic/Persian/Urdu)
  // flow correctly without reshuffling the whole layout module. It follows the
  // words on screen, so English text is never laid out right to left while the
  // patient's language is still loading. A layout effect, so it lands before paint.
  useLayoutEffect(() => {
    const dir = isRTL(shownLang) ? "rtl" : "ltr";
    document.documentElement.setAttribute("dir", dir);
    document.documentElement.setAttribute("lang", shownLang);
    return () => {
      document.documentElement.setAttribute("dir", "ltr");
      document.documentElement.setAttribute("lang", "en");
    };
  }, [shownLang]);

  useEffect(() => {
    document.title = "Check in: Solace";
  }, []);

  // Also our early check that the link points at a real hospital.
  useEffect(() => {
    startIntake(hospitalId)
      .then((r) => setIntakeToken(r.token))
      .catch((e) => {
        if (errorStatus(e) === 404) setInvalidLink(true);
        /* anything else: submit will surface a clean error */
      });
  }, [hospitalId]);

  useEffect(() => {
    if (voiceUnavailable) setInputMode("type");
  }, [voiceUnavailable]);

  // Progress dots count the user-visible intake steps. Excludes the language gate
  // and id-scan (both full-screen pre-steps that own their own UI) and submitting
  // (a spinner, no dots).
  const userSteps = stepOrder.filter(
    (s) => s !== "language" && s !== "id-scan" && s !== "submitting"
  );
  const currentUserStep = userSteps.indexOf(step as (typeof userSteps)[number]);

  // Slide forward or back depending on which way the step moved.
  const reduce = useReducedMotion();
  const curIdx = stepOrder.indexOf(step);
  const prevIdxRef = useRef(curIdx);
  const direction = curIdx >= prevIdxRef.current ? 1 : -1;
  useEffect(() => {
    prevIdxRef.current = curIdx;
  }, [curIdx]);
  const stepVariants = {
    enter: (dir: number) => ({ opacity: 0, x: dir >= 0 ? 28 : -28 }),
    center: { opacity: 1, x: 0 },
    exit: (dir: number) => ({ opacity: 0, x: dir >= 0 ? -28 : 28 }),
  };

  function canAdvance(): boolean {
    if (step === "language") return true;
    if (step === "welcome") return name.trim().length > 0 && consentGranted;
    if (step === "medical") return medical.age !== null && !!medical.sex;
    if (step === "insurance") return true;
    if (step === "record") {
      if (typing) return textFallback.trim().length > 3;
      return !!recorder.audioBlob;
    }
    if (step === "redflags") return redFlags.length > 0;
    if (step === "followups") return followups.every((q) => answers[q.id]?.trim());
    return false;
  }

  async function transcribeWithRetry(): Promise<void> {
    const form = new FormData();
    const usingVoice = !typing && !!recorder.audioBlob;
    // The browser's live dictation is the main voice path: it sends text, so it
    // needs no server speech service. The recorded clip is only uploaded when the
    // browser heard nothing and the server can transcribe it.
    const liveTxt = (recorder.liveTranscript || "").trim();
    if (usingVoice && liveTxt.length >= 3) {
      form.append("pre_transcribed_text", liveTxt);
    } else if (usingVoice && recorder.audioBlob) {
      if (caps && !caps.transcription) throw new VoiceNotCaught();
      const ext = recorder.audioBlob.type.includes("mp4") ? "m4a" : "webm";
      form.append("audio_file", recorder.audioBlob, `intake.${ext}`);
    } else {
      form.append("pre_transcribed_text", textFallback.trim());
    }
    form.append("medical_info", JSON.stringify(medical));
    form.append("preferred_language", preferredLanguage);
    form.append("consent_granted", consentGranted ? "true" : "false");

    let attempt = 0;
    while (true) {
      try {
        const resp = await postTranscribe(hospitalId, form);
        setTranscript(resp.transcript);
        setLanguage(resp.language);
        setFollowups(resp.followups);
        // Older servers do not send the flag, so missing means show the checklist.
        const checklist = resp.red_flag_checklist !== false;
        setShowChecklist(checklist);
        if (checklist) {
          setStep("redflags");
        } else if (resp.followups.length === 0) {
          await finalize(resp.transcript, [], [], "record");
        } else {
          setStep("followups");
        }
        return;
      } catch (e) {
        const status = errorStatus(e);
        // A 503 that says the service is off will not clear on a retry.
        const permanent = status === 503 && /not set|is off|turned off|unavailable|not configured/i.test(errorDetail(e));
        if (attempt < 1 && !permanent && (status === 429 || status === 503 || status === 502 || status === 504)) {
          attempt += 1;
          await sleep(1500);
          continue;
        }
        throw e;
      }
    }
  }

  async function handleNext() {
    if (!canAdvance() || busy) return;
    setError(null);

    if (step === "language") return setStep("id-scan");
    if (step === "id-scan") return setStep("welcome");
    if (step === "welcome") return setStep("medical");
    if (step === "medical") return setStep("insurance");
    if (step === "insurance") return setStep("record");

    if (step === "record") {
      setBusy(true);
      try {
        await transcribeWithRetry();
      } catch (e) {
        if (e instanceof VoiceNotCaught) {
          // Nothing was heard and the server cannot listen to the clip. Let the
          // patient try once more, then move them to typing.
          voiceMissesRef.current += 1;
          recorder.reset();
          if (recorder.webSpeechSupported && voiceMissesRef.current < 2) {
            setError(t("error_voice_not_caught", lang));
          } else {
            setInputMode("type");
            setError(t("error_transcription_down", lang));
          }
          return;
        }
        if (isUnknownHospital(e)) {
          setInvalidLink(true);
          return;
        }
        const status = errorStatus(e);
        const detail = errorDetail(e);
        const isTranscriptionDown =
          /transcription/i.test(detail) || /whisper/i.test(detail) || status === 503;
        // No status plus a network/timeout message means the request never got an
        // answer. The clip and text are still here, so tapping again resends them.
        const isGatewayTimeout =
          status === 502 || status === 504 ||
          (!status && /network|fetch|abort|timeout/i.test((e as Error)?.message || ""));
        if (isTranscriptionDown && !typing) {
          setInputMode("type");
          setError(t("error_transcription_down", lang));
        } else if (status === 429) {
          setError(t("error_rate_limited", lang));
        } else if (isGatewayTimeout) {
          setError(t("error_network", lang));
        } else {
          // Never show raw server or JavaScript error text to the patient.
          setError(t("error_generic", lang));
        }
      } finally {
        setBusy(false);
      }
      return;
    }

    if (step === "redflags") {
      // A tapped danger sign means ESI 2 or higher, and the follow-up questions are
      // skipped at that level (services/followups.py), so the result comes at once.
      const urgent = redFlags.some((f) => f !== "none");
      if (urgent || followups.length === 0) {
        await finalize(transcript, [], redFlags, "redflags");
      } else {
        setStep("followups");
      }
      return;
    }

    if (step === "followups") {
      await finalize(transcript, toAnswerList(followups, answers), showChecklist ? redFlags : [], "followups");
    }
  }

  async function buildIntakeForm(
    transcriptText: string,
    followupAnswers: { id: string; question: string; answer: string }[],
    flags: ChecklistId[],
    tokenOverride?: string
  ): Promise<FormData> {
    const form = new FormData();
    form.append("patient_name", name.trim());
    form.append("pre_transcribed_text", transcriptText);
    form.append("medical_info", JSON.stringify(medical));
    form.append("followup_qa", JSON.stringify(followupAnswers));
    if (insurance) form.append("insurance_info", JSON.stringify(insurance));
    const tok = tokenOverride ?? intakeToken;
    if (tok) form.append("intake_token", tok);
    form.append("idempotency_key", idempotencyKeyRef.current);
    form.append("consent_granted", consentGranted ? "true" : "false");
    form.append("consent_version", CONSENT_VERSION);
    form.append("preferred_language", preferredLanguage);
    appendChecklistFlags(form, flags);
    // Carry the matched record id so the nurse's screen opens the same record.
    if (ehrMatched?.matched && ehrMatched.ehr_record) {
      const fhirId = ehrMatched.ehr_record.fhir_id || ehrMatched.ehr_record.mrn || "";
      if (fhirId) {
        form.append("ehr_fhir_id", fhirId);
        form.append("ehr_match_source", ehrMatched.ehr_record.source || "fhir");
      }
    }
    if (photo) {
      const { resizeImageIfNeeded } = await import("../lib/image");
      const sized = await resizeImageIfNeeded(photo);
      form.append("image_file", sized);
    }
    return form;
  }

  async function finalize(
    transcriptText: string,
    followupAnswers: { id: string; question: string; answer: string }[],
    // The checklist taps to send (none when the checklist was not shown).
    flags: ChecklistId[],
    // Where the patient lands if sending fails, so they can tap again.
    returnTo: Step
  ) {
    setStep("submitting");
    setBusy(true);
    try {
      const form = await buildIntakeForm(transcriptText, followupAnswers, flags);
      let result;
      try {
        result = await postIntake(hospitalId, form);
      } catch (e) {
        const isNonceFault =
          errorStatus(e) === 403 && /intake token|scan the QR/i.test(errorDetail(e));
        if (!isNonceFault) throw e;
        const fresh = await startIntake(hospitalId);
        setIntakeToken(fresh.token);
        const retryForm = await buildIntakeForm(transcriptText, followupAnswers, flags, fresh.token);
        result = await postIntake(hospitalId, retryForm);
      }
      try {
        sessionStorage.setItem(`intake:${result.patient_id}`, JSON.stringify(result));
        sessionStorage.setItem(PATIENT_LANG_KEY, preferredLanguage);
        // The result screen keeps the 988 card up for a patient who tapped self-harm.
        if (flags.length > 0) {
          sessionStorage.setItem(`intake:${result.patient_id}:red_flags`, JSON.stringify(flags));
        }
      } catch {
        /* private mode: the result page rebuilds from the server */
      }
      navigate(`${sidePaths.patient}/result/${result.patient_id}`);
    } catch (e) {
      if (isUnknownHospital(e)) {
        setInvalidLink(true);
        return;
      }
      const status = errorStatus(e);
      if (status === 429) {
        setError(t("error_rate_limited", lang));
      } else if (!status && /network|fetch|abort|timeout/i.test((e as Error)?.message || "")) {
        setError(t("error_network", lang));
      } else {
        setError(t("error_generic", lang));
      }
      setStep(returnTo);
    } finally {
      setBusy(false);
    }
  }

  function handleBack() {
    if (step === "redflags") return setStep("record");
    if (step === "followups") return setStep(showChecklist ? "redflags" : "record");
    const idx = stepOrder.indexOf(step);
    if (idx > 0) setStep(stepOrder[idx - 1]);
  }

  function pickExample(text: string) {
    setFocusTextBox(false);
    setInputMode("type");
    setTextFallback(text);
    setError(null);
  }

  if (invalidLink) {
    return (
      <div className="min-h-[100dvh] flex flex-col bg-surface-lowest">
        <DemoBanner lang={lang} />
        <main className="flex-1 flex flex-col items-center justify-center gap-4 px-6 py-10 text-center max-w-md mx-auto">
          <PatientLogo hospitalId={hospitalId} lang={lang} className="h-12" />
          <h1 className="text-2xl font-bold tracking-tight rtl:tracking-normal">{t("invalid_link_title", lang)}</h1>
          <p className="text-[15px] text-text-muted leading-relaxed">{t("invalid_link_body", lang)}</p>
          <Link
            to="/"
            className="inline-flex items-center justify-center min-h-12 px-6 rounded-md bg-primary text-white font-semibold shadow-soft hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
          >
            {t("invalid_link_home", lang)}
          </Link>
        </main>
      </div>
    );
  }

  // The same line every step's footer carries, for the two full-screen pre-steps.
  const preStepFooter = (
    <p
      className="px-4 pt-2 text-[13px] text-text-muted text-center leading-snug max-w-md w-full mx-auto"
      style={{ paddingBottom: "calc(1rem + env(safe-area-inset-bottom, 0px))" }}
    >
      {t("footer_disclaimer", lang)}
    </p>
  );

  // Language gate is its own full-screen layout, without the step header/footer.
  if (step === "language") {
    return (
      <div className="min-h-[100dvh] flex flex-col bg-surface-lowest">
        <DemoBanner lang={lang} />
        <div className="flex-1 flex items-center justify-center">
          <LanguageGate
            hospitalId={hospitalId}
            selected={preferredLanguage}
            onSelect={setPreferredLanguage}
            onContinue={() => setStep("id-scan")}
          />
        </div>
        {preStepFooter}
      </div>
    );
  }

  // ID scan is optional. A returning patient's record fills in the medical form.
  if (step === "id-scan") {
    return (
      <div className="min-h-[100dvh] flex flex-col bg-surface-lowest">
        <DemoBanner lang={lang} />
        <div className="flex-1 flex items-center justify-center px-4 py-8">
          <div className="max-w-md w-full">
            <div className="text-center mb-6">
              <PatientLogo hospitalId={hospitalId} lang={lang} className="h-12 sm:h-16 mx-auto" />
              <h1 className="mt-3 text-xl sm:text-2xl font-bold tracking-tight rtl:tracking-normal">
                {t("welcome_title", lang)}
              </h1>
            </div>
            <IdScanner
              hospitalId={hospitalId}
              language={lang}
              ocrOn={ocrOn}
              offerSample={demo}
              onSkip={() => setStep("welcome")}
              onMatched={(result: IdentityLookupResult) => {
                applyEhrMatch(result);
                setStep("welcome");
              }}
            />
          </div>
        </div>
        {preStepFooter}
      </div>
    );
  }

  const showBack = step !== "welcome" && step !== "submitting";

  return (
    <div className="min-h-[100dvh] flex flex-col">
      {/* The help tour describes the symptom step, and it is written in English. It only
          opens from its "?" button: opening by itself would cover the box the patient types in. */}
      {step === "record" && lang === "en" && (
        <TourLauncher
          tourId="patient-intake-v1"
          subjectId="patient"
          autoStart={false}
          buttonPosition="bottom-right"
          buttonClassName="!bottom-[calc(7.5rem+env(safe-area-inset-bottom,0px))]"
        />
      )}
      <header className="bg-surface-lowest/85 backdrop-blur-xl sticky top-0 z-10 shadow-soft">
        <DemoBanner lang={lang} />
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2 shrink-0">
            {showBack && (
              <button
                onClick={handleBack}
                aria-label={t("back_button", lang)}
                className="w-11 h-11 rounded-full hover:bg-surface-low flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
              >
                <ArrowLeft size={20} aria-hidden="true" className="rtl:rotate-180" />
              </button>
            )}
            {/* Smaller next to the back button on a phone, so it never runs into the progress bar. */}
            <PatientLogo
              hospitalId={hospitalId}
              lang={lang}
              className={`${showBack ? "h-8" : "h-10"} sm:h-14 shrink-0`}
            />
          </div>
          {step !== "submitting" && (
            <div className="min-w-0 flex justify-end overflow-hidden">
              <ProgressDots
                total={userSteps.length}
                current={currentUserStep + 1}
                label={t("progress_label", lang)
                  .replace("{current}", String(currentUserStep + 1))
                  .replace("{total}", String(userSteps.length))}
              />
            </div>
          )}
        </div>
      </header>

      {ehrMatched?.matched && !ehrBannerDismissed && step !== "submitting" && (
        <div className="mx-auto w-full max-w-lg px-4 mt-3">
          <div
            role="status"
            className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 flex items-start gap-3 shadow-soft"
          >
            <CheckCircle2 className="text-emerald-700 mt-0.5 shrink-0" size={18} aria-hidden="true" />
            <div className="flex-1 text-sm">
              <div className="font-semibold text-emerald-900">{t("ehr_found_title", lang)}</div>
              <div className="text-emerald-900 text-[14px] mt-0.5 leading-snug">
                {ehrMatched.ehr_record?.name ? `${ehrMatched.ehr_record.name}. ` : ""}
                {t("ehr_found_body", lang)}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setEhrBannerDismissed(true)}
              aria-label={t("dismiss_button", lang)}
              className="w-11 h-11 -mr-2 -mt-2 flex items-center justify-center rounded-full text-emerald-800 hover:text-emerald-950 shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-700/60 focus-visible:ring-offset-1"
            >
              <XIcon size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {/* overflow-x-clip: the step slides in sideways, and must not widen the page while it does. */}
      <main className="flex-1 px-4 py-6 max-w-lg w-full mx-auto flex flex-col gap-6 overflow-x-clip">
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={step}
            custom={direction}
            variants={stepVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: reduce ? 0 : 0.28, ease: [0.4, 0, 0.2, 1] }}
            className="flex flex-col gap-6"
          >
            {step === "welcome" && (
              <>
                <div>
                  <h1 className="text-3xl font-bold tracking-editorial-tight rtl:tracking-normal mb-2">
                    {t("welcome_title", lang)}
                  </h1>
                  <p className="text-text-muted">{t("welcome_subtitle", lang)}</p>
                </div>
                <div>
                  <label className="text-sm font-semibold block mb-2" htmlFor="name">
                    {t("first_name_label", lang)}
                  </label>
                  <input
                    id="name"
                    type="text"
                    autoComplete="given-name"
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("first_name_placeholder", lang)}
                    className="w-full h-14 px-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-lg outline-none transition-all"
                  />
                </div>

                <button
                  type="button"
                  onClick={() => setStep("language")}
                  className="inline-flex items-center gap-1 text-[14px] text-primary underline self-start min-h-[44px] rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
                >
                  {t("language_gate_title", lang)} <ArrowRight size={14} aria-hidden="true" className="rtl:rotate-180" />
                </button>

                <div className="rounded-lg bg-surface-lowest p-4 border border-[rgba(74,85,87,0.12)]">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={consentGranted}
                      onChange={(e) => setConsentGranted(e.target.checked)}
                      className="mt-0.5 h-5 w-5 shrink-0 rounded border-line accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
                    />
                    <div className="flex-1 text-[14px] leading-relaxed text-ink">
                      <span className="font-semibold">{t("consent_lead", lang)}</span>{" "}
                      {t(aiOn ? "consent_body_ai_on" : "consent_body_ai_off", lang)}
                      <div className="mt-1.5 text-[13px] text-text-muted">
                        {t("consent_decline", lang)} (v{CONSENT_VERSION})
                      </div>
                    </div>
                  </label>
                </div>
              </>
            )}

            {step === "medical" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial rtl:tracking-normal mb-1">
                    {t("medical_title", lang)}
                  </h2>
                  <p className="text-text-muted text-sm">{t("medical_subtitle", lang)}</p>
                </div>
                <MedicalInfoForm value={medical} onChange={setMedical} language={lang} />
              </>
            )}

            {step === "insurance" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial rtl:tracking-normal mb-1">
                    {t("insurance_title", lang)}
                  </h2>
                  <p className="text-text-muted text-sm">
                    {t(ocrOn ? "insurance_subtitle" : "insurance_subtitle_off", lang)}
                  </p>
                </div>
                <InsuranceScanner
                  hospitalId={hospitalId}
                  value={insurance}
                  onChange={setInsurance}
                  onSkip={() => setStep("record")}
                  language={lang}
                  ocrOn={ocrOn}
                  offerSample={demo}
                />
              </>
            )}

            {step === "record" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial rtl:tracking-normal mb-1">
                    {t("record_title", lang)}
                  </h2>
                  <p className="text-text-muted text-sm">
                    {typing ? t("record_subtitle_type", lang) : t("record_subtitle_voice", lang)}
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <div className="inline-flex self-start rounded-md bg-surface-low p-1" role="group">
                    <button
                      type="button"
                      onClick={() => setInputMode("voice")}
                      aria-pressed={!typing}
                      className={`inline-flex items-center gap-1.5 min-h-[40px] px-3 rounded text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
                        !typing ? "bg-surface-lowest text-ink shadow-soft" : "text-text-muted"
                      }`}
                      disabled={recorder.permissionDenied || voiceUnavailable}
                    >
                      <Mic size={14} aria-hidden="true" /> {t("record_voice_tab", lang)}
                    </button>
                    <button
                      type="button"
                      onClick={() => setInputMode("type")}
                      aria-pressed={typing}
                      className={`inline-flex items-center gap-1.5 min-h-[40px] px-3 rounded text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 ${
                        typing ? "bg-surface-lowest text-ink shadow-soft" : "text-text-muted"
                      }`}
                    >
                      <Keyboard size={14} aria-hidden="true" /> {t("record_type_tab", lang)}
                    </button>
                  </div>
                  {voiceUnavailable && (
                    <p className="text-[13px] text-text-muted">{t("record_voice_off", lang)}</p>
                  )}
                </div>

                {typing ? (
                  <div className="flex flex-col gap-2">
                    <label htmlFor="symptoms-text" className="sr-only">
                      {t("record_title", lang)}
                    </label>
                    <textarea
                      id="symptoms-text"
                      value={textFallback}
                      onChange={(e) => setTextFallback(e.target.value)}
                      rows={6}
                      className="w-full p-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
                      placeholder={t("record_textarea_placeholder", lang)}
                      autoFocus={focusTextBox}
                    />
                    {recorder.permissionDenied && (
                      <p className="text-[13px] text-text-muted">{t("record_mic_denied", lang)}</p>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-4 py-8 bg-primary-fixed/40 rounded-lg">
                    <MicButton
                      isRecording={recorder.isRecording}
                      elapsed={recorder.elapsed}
                      onStart={() => {
                        setError(null);
                        recorder.start(preferredLanguage);
                      }}
                      onStop={recorder.stop}
                      language={lang}
                    />
                    {recorder.isRecording && recorder.liveTranscript && (
                      <div className="text-sm text-ink px-4 max-w-md text-center italic leading-snug">
                        "{recorder.liveTranscript}"
                      </div>
                    )}
                    {recorder.audioBlob && !recorder.isRecording && (
                      <div className="text-sm text-primary flex items-center gap-3">
                        {t("record_captured", lang)} ({recorder.elapsed}s)
                        <button
                          type="button"
                          className="text-text-muted underline min-h-[44px] rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
                          onClick={recorder.reset}
                        >
                          {t("record_rerecord", lang)}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                <ExampleChips lang={lang} onPick={pickExample} disabled={recorder.isRecording || busy} />

                <PhotoCapture file={photo} onChange={setPhoto} language={lang} />
              </>
            )}

            {step === "redflags" && (
              <RedFlagChecklist lang={lang} value={redFlags} onChange={setRedFlags} />
            )}

            {step === "followups" && (
              <>
                <div>
                  <h2 className="text-2xl font-bold tracking-editorial rtl:tracking-normal mb-1">
                    {t("followups_title", lang)}
                  </h2>
                  <p className="text-text-muted text-sm">{t("followups_subtitle", lang)}</p>
                </div>
                <FollowupQuestions
                  questions={followups}
                  answers={answers}
                  onAnswer={(id, _q, a) => setAnswers((prev) => ({ ...prev, [id]: a }))}
                  language={lang}
                />
              </>
            )}

            {step === "submitting" && (
              <div
                role="status"
                aria-live="polite"
                className="flex flex-col items-center justify-center py-24 gap-4 text-center"
              >
                <Loader2 size={48} className="animate-spin text-primary" aria-hidden="true" />
                <div className="text-lg font-semibold tracking-editorial rtl:tracking-normal">{t("submitting_title", lang)}</div>
                <div className="text-sm text-text-muted">{t("submitting_subtitle", lang)}</div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        {error && (
          <div role="alert" className="p-3 rounded-md bg-error-container text-error text-sm">
            {error}
          </div>
        )}
      </main>

      {step !== "submitting" && (
        <footer
          className="sticky bottom-0 bg-surface-lowest/95 backdrop-blur-xl px-4 pt-4 shadow-glass"
          style={{ paddingBottom: "calc(1rem + env(safe-area-inset-bottom, 0px))" }}
        >
          <Button variant="primary" fullWidth disabled={!canAdvance() || busy} onClick={handleNext}>
            {busy ? (
              <>
                <Loader2 size={18} className="animate-spin" aria-hidden="true" /> {t("working_button", lang)}
              </>
            ) : step === "record" || step === "redflags" ? (
              <>
                {t("continue_button", lang)} <ArrowRight size={18} aria-hidden="true" className="rtl:rotate-180" />
              </>
            ) : step === "followups" ? (
              t("submit_button", lang)
            ) : (
              <>
                {t("next_button", lang)} <ArrowRight size={18} aria-hidden="true" className="rtl:rotate-180" />
              </>
            )}
          </Button>
          <div className="text-[13px] text-text-muted text-center mt-2 leading-snug">
            {t("footer_disclaimer", lang)}
          </div>
        </footer>
      )}
    </div>
  );
}
