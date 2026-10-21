import { useEffect, useRef, useState } from "react";
import { CheckCircle2, IdCard, ImagePlus, Loader2, RefreshCw, X, UserCheck } from "lucide-react";
import { InAppCamera } from "../ui/InAppCamera";
import {
  errorStatus,
  identityLookup,
  scanID,
  scanIdSample,
  type IdFields,
  type IdScanResult,
  type IdentityLookupResult,
} from "../../lib/api-patient";
import { isRTL, t } from "../../lib/i18n";

type Props = {
  hospitalId: string;
  onMatched: (result: IdentityLookupResult) => void;
  onSkip: () => void;
  language: string;
  /** Card reading is switched on for this server (capabilities.ocr). */
  ocrOn: boolean;
  /**
   * Offer the made-up sample ID even when card reading is on. Demo hospitals set
   * it, so a visitor never needs a real license to try this step.
   */
  offerSample?: boolean;
};

type Stage = "capture" | "scanning" | "looking-up" | "matched" | "no-match";

function hasGetUserMedia(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

const sideButton =
  "w-full min-h-12 px-4 rounded-md font-semibold text-[15px] text-primary bg-surface-lowest ring-1 ring-line shadow-soft hover:ring-primary/40 transition-all active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2";
const primaryButton =
  "w-full min-h-12 px-4 rounded-md bg-primary text-white font-semibold text-[15px] shadow-soft hover:bg-primary-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2";
const iconButton =
  "bg-surface-lowest/90 backdrop-blur w-11 h-11 rounded-full flex items-center justify-center shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60";

/**
 * Optional first step: scan a driver's license, then look for a returning
 * patient's record so the medical form arrives filled in. When card reading is
 * off (no AI key), the patient can use the made-up sample ID instead, or skip.
 */
export function IdScanner({ hospitalId, onMatched, onSkip, language, ocrOn, offerSample = false }: Props) {
  const [cameraOpen, setCameraOpen] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<IdFields | null>(null);
  const [lookup, setLookup] = useState<IdentityLookupResult | null>(null);
  const [stage, setStage] = useState<Stage>("capture");
  // Starts from the server's answer; also flips on if a real scan reports it is off.
  const [ocrOff, setOcrOff] = useState(!ocrOn);
  const [usedSample, setUsedSample] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const L = (key: Parameters<typeof t>[0]) => t(key, language);

  useEffect(() => setOcrOff(!ocrOn), [ocrOn]);

  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  // Shared by the real scan and the sample: read fields, then look for a record.
  async function applyScan(resp: IdScanResult) {
    if (!resp.success || !resp.fields) {
      setFields(null);
      setStage("capture");
      if (resp.error === "ocr_unavailable" || resp.error === "anthropic_key_missing") {
        setPhoto(null);
        setOcrOff(true);
        return;
      }
      setError(L(resp.error === "not_an_id_card" ? "id_err_not_id" : "id_err_unreadable"));
      return;
    }
    setFields(resp.fields);
    setStage("looking-up");
    const lk = await identityLookup(hospitalId, {
      first_name: resp.fields.first_name,
      last_name: resp.fields.last_name,
      dob: resp.fields.dob,
      license_number: resp.fields.license_number,
      issuing_state: resp.fields.issuing_state,
    });
    setLookup(lk);
    setStage(lk.matched ? "matched" : "no-match");
  }

  async function handleCapture(file: File) {
    setCameraOpen(false);
    setPhoto(file);
    setError(null);
    setUsedSample(false);
    setStage("scanning");
    try {
      const { resizeImageIfNeeded } = await import("../../lib/image");
      const sized = await resizeImageIfNeeded(file);
      await applyScan(await scanID(hospitalId, sized));
    } catch (e) {
      const status = errorStatus(e);
      setError(L(status === 415 ? "photo_err_format" : status === 413 ? "photo_err_size" : "photo_err_send"));
      setStage("capture");
    }
  }

  async function handleSample() {
    setError(null);
    setPhoto(null);
    setUsedSample(true);
    setStage("scanning");
    try {
      await applyScan(await scanIdSample(hospitalId));
    } catch {
      setError(L("scan_sample_failed"));
      setStage("capture");
    }
  }

  function openCamera() {
    if (hasGetUserMedia()) setCameraOpen(true);
    else fileInputRef.current?.click();
  }

  function reset() {
    setPhoto(null);
    setPreview(null);
    setFields(null);
    setLookup(null);
    setError(null);
    setUsedSample(false);
    setStage("capture");
  }

  const prefill = lookup?.prefill;
  const recordLines: Array<[string, string[]]> = [
    [L("form_allergies"), prefill?.allergies ?? []],
    [L("form_medications"), prefill?.medications ?? []],
    [L("form_conditions"), prefill?.conditions ?? []],
  ].filter(([, items]) => (items as string[]).length > 0) as Array<[string, string[]]>;

  return (
    <div className="flex flex-col gap-4" dir={isRTL(language) ? "rtl" : "ltr"}>
      {stage === "capture" && !ocrOff && (
        <>
          <button
            type="button"
            onClick={openCamera}
            className="w-full rounded-lg bg-surface-low hover:bg-primary-fixed transition-colors py-8 flex flex-col items-center gap-2 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
          >
            <div className="w-14 h-14 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
              <IdCard size={26} aria-hidden="true" />
            </div>
            <div className="font-semibold">{L("id_title")}</div>
            <div className="text-[13px] text-text-muted px-6 text-center">{L("id_desc")}</div>
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="self-center inline-flex items-center gap-1 text-sm text-text-muted underline underline-offset-2 px-3 min-h-[44px] rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          >
            <ImagePlus size={14} aria-hidden="true" /> {L("upload_photo")}
          </button>
          {offerSample ? (
            <>
              <p className="text-[14px] text-text-muted leading-snug text-center">{L("id_sample_hint")}</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <button type="button" onClick={handleSample} className={sideButton}>
                  {L("id_use_sample")}
                </button>
                <button type="button" onClick={onSkip} className={sideButton}>
                  {L("skip_step")}
                </button>
              </div>
            </>
          ) : (
            <button type="button" onClick={onSkip} className={sideButton}>
              {L("skip_step")}
            </button>
          )}
        </>
      )}

      {stage === "capture" && ocrOff && (
        <div className="rounded-lg bg-surface-low p-5 flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 shrink-0 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
              <IdCard size={22} aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <div className="font-semibold">{L("id_title")}</div>
              <p className="text-[15px] text-ink font-medium">{L("scan_off_note")}</p>
              <p className="text-[14px] text-text-muted leading-snug">{L("id_sample_hint")}</p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button type="button" onClick={handleSample} className={sideButton}>
              {L("id_use_sample")}
            </button>
            <button type="button" onClick={onSkip} className={sideButton}>
              {L("skip_step")}
            </button>
          </div>
        </div>
      )}

      {(stage === "scanning" || stage === "looking-up") && (
        <div
          className="w-full rounded-lg bg-primary-fixed/40 py-10 flex flex-col items-center gap-3"
          role="status"
          aria-live="polite"
        >
          <Loader2 size={32} className="animate-spin text-primary" aria-hidden="true" />
          <div className="text-sm text-primary font-medium">
            {L(stage === "scanning" ? "id_reading" : "id_looking_up")}
          </div>
        </div>
      )}

      {preview && stage !== "capture" && stage !== "scanning" && (
        <div className="relative">
          <img src={preview} alt={L("id_preview_alt")} className="w-full rounded-lg shadow-soft" />
          <div className="absolute top-3 right-3 flex gap-2">
            <button type="button" onClick={reset} className={iconButton} aria-label={L("scan_again")}>
              <RefreshCw size={18} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => {
                setPhoto(null);
                setPreview(null);
                onSkip();
              }}
              className={iconButton}
              aria-label={L("cancel_button")}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="p-3 rounded-md bg-error-container text-error text-sm">
          {error}
        </div>
      )}

      {stage === "matched" && lookup?.matched && lookup.ehr_record && fields && (
        <div className="rounded-lg bg-primary-fixed/60 ring-2 ring-primary p-5 flex flex-col gap-3">
          {usedSample && (
            <span className="self-start text-[13px] font-semibold text-ink bg-warning-container rounded px-2 py-0.5">
              {L("id_sample_badge")}
            </span>
          )}
          <div className="flex items-center gap-2 text-primary">
            <UserCheck size={20} aria-hidden="true" />
            <div className="font-bold tracking-tight rtl:tracking-normal text-lg">
              {L("id_welcome_back").replace("{name}", fields.first_name)}
            </div>
          </div>
          <p className="text-[14px] leading-relaxed text-ink">{L("id_found_record")}</p>
          {recordLines.length > 0 && (
            <dl className="text-[14px] leading-snug text-ink flex flex-col gap-1">
              {recordLines.map(([label, items]) => (
                <div key={label}>
                  <dt className="inline font-semibold">{label}: </dt>
                  <dd className="inline">{items.join(", ")}</dd>
                </div>
              ))}
            </dl>
          )}
          <div className="flex gap-2 flex-wrap">
            <button type="button" onClick={() => onMatched(lookup)} className={`${primaryButton} flex-1 w-auto`}>
              {L("id_use_record")}
            </button>
            <button
              type="button"
              onClick={() => onSkip()}
              className="min-h-12 px-4 rounded-md text-sm text-ink bg-surface-lowest ring-1 ring-line hover:ring-error/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
            >
              {L("id_not_me")}
            </button>
          </div>
        </div>
      )}

      {stage === "no-match" && fields && (
        <div className="rounded-lg bg-surface-low p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-ink">
            <CheckCircle2 size={18} aria-hidden="true" />
            <div className="font-semibold tracking-tight rtl:tracking-normal">{L("id_no_record_title")}</div>
          </div>
          <div className="text-[14px] leading-relaxed text-ink">
            <span className="font-semibold">
              {fields.first_name} {fields.last_name}
            </span>
            {fields.dob && (
              <>
                {". "}
                {L("id_dob")}: <span className="font-mono">{fields.dob}</span>
              </>
            )}
            . {L("id_no_record_body")}
          </div>
          <button
            type="button"
            onClick={() => onMatched({ matched: false })}
            className={primaryButton}
          >
            {L("continue_button")}
          </button>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleCapture(f);
        }}
      />

      {cameraOpen && (
        <InAppCamera
          label={L("id_title")}
          aspectHint="card"
          language={language}
          onCapture={handleCapture}
          onClose={() => setCameraOpen(false)}
        />
      )}
    </div>
  );
}
