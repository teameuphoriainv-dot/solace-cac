import { useEffect, useId, useRef, useState } from "react";
import { CheckCircle2, CreditCard, ImagePlus, Loader2, RefreshCw, X } from "lucide-react";
import { InAppCamera } from "../ui/InAppCamera";
import {
  errorStatus,
  scanInsurance,
  scanInsuranceSample,
  type InsuranceScanResult,
} from "../../lib/api-patient";
import { t } from "../../lib/i18n";
import type { InsuranceFields } from "../../types";

type Props = {
  hospitalId: string;
  value: InsuranceFields | null;
  onChange: (fields: InsuranceFields | null) => void;
  onSkip?: () => void;
  language?: string;
  /** Card reading is switched on for this server (capabilities.ocr). */
  ocrOn: boolean;
  /**
   * Offer the made-up sample card even when card reading is on. Demo hospitals set
   * it, so a visitor never needs a real insurance card to try this step.
   */
  offerSample?: boolean;
};

const EMPTY: InsuranceFields = {
  provider: null,
  plan_name: null,
  member_id: null,
  group_number: null,
  name_on_card: null,
  bin: null,
  pcn: null,
  rx_group: null,
  effective_date: null,
  phone: null,
};

// "anthropic_key_missing" is the older code for the same thing.
const OFF_CODES = new Set(["ocr_unavailable", "anthropic_key_missing"]);

function hasGetUserMedia(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

const sideButton =
  "w-full min-h-12 px-4 rounded-md font-semibold text-[15px] text-primary bg-surface-lowest ring-1 ring-line shadow-soft hover:ring-primary/40 transition-all active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2";
const iconButton =
  "bg-surface-lowest/90 backdrop-blur w-11 h-11 rounded-full flex items-center justify-center shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60";
const linkButton =
  "inline-flex items-center gap-1 min-h-[44px] px-3 text-sm text-text-muted underline underline-offset-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60";

export function InsuranceScanner({
  hospitalId, value, onChange, onSkip, language = "en", ocrOn, offerSample = false,
}: Props) {
  const [cameraOpen, setCameraOpen] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  function applyScan(resp: InsuranceScanResult) {
    if (resp.success && resp.fields) {
      onChange({ ...EMPTY, ...resp.fields });
      return;
    }
    if (resp.error && OFF_CODES.has(resp.error)) {
      setPhoto(null);
      setOcrOff(true);
      onChange(null);
      return;
    }
    // Unreadable: open the empty fields so the patient can type them.
    setError(L(resp.error === "not_an_insurance_card" ? "ins_err_not_card" : "ins_err_unreadable"));
    onChange({ ...EMPTY });
  }

  async function handleCapture(file: File) {
    setCameraOpen(false);
    setPhoto(file);
    setBusy(true);
    setError(null);
    setUsedSample(false);
    try {
      const { resizeImageIfNeeded } = await import("../../lib/image");
      const sized = await resizeImageIfNeeded(file);
      applyScan(await scanInsurance(hospitalId, sized));
    } catch (e) {
      const status = errorStatus(e);
      setError(L(status === 415 ? "photo_err_format" : status === 413 ? "photo_err_size" : "photo_err_send"));
      onChange({ ...EMPTY });
    } finally {
      setBusy(false);
    }
  }

  async function handleSample() {
    setBusy(true);
    setError(null);
    setPhoto(null);
    try {
      const resp = await scanInsuranceSample(hospitalId);
      if (resp.success && resp.fields) {
        setUsedSample(true);
        onChange({ ...EMPTY, ...resp.fields });
      } else {
        setError(L("scan_sample_failed"));
      }
    } catch {
      setError(L("scan_sample_failed"));
    } finally {
      setBusy(false);
    }
  }

  function openPrimaryCamera() {
    if (hasGetUserMedia()) {
      setCameraOpen(true);
    } else {
      fileInputRef.current?.click();
    }
  }

  function clearCard() {
    setPhoto(null);
    setUsedSample(false);
    setError(null);
    onChange(null);
  }

  function update<K extends keyof InsuranceFields>(key: K, val: string) {
    onChange({ ...(value || EMPTY), [key]: val || null });
  }

  const scanned = !!value;

  return (
    <div className="flex flex-col gap-4">
      {!scanned && !busy && !ocrOff && (
        <>
          <button
            type="button"
            onClick={openPrimaryCamera}
            className="w-full rounded-lg bg-surface-low hover:bg-primary-dim transition-colors py-8 flex flex-col items-center gap-2 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
          >
            <div className="w-14 h-14 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
              <CreditCard size={26} aria-hidden="true" />
            </div>
            <div className="font-semibold tracking-editorial rtl:tracking-normal">{L("ins_scan_title")}</div>
            <div className="text-[13px] text-text-muted px-6 text-center">{L("ins_scan_desc")}</div>
          </button>
          <button type="button" onClick={() => fileInputRef.current?.click()} className={`self-center ${linkButton}`}>
            <ImagePlus size={14} aria-hidden="true" /> {L("upload_photo")}
          </button>
          {offerSample && (
            <>
              <p className="text-[14px] text-text-muted leading-snug text-center">{L("ins_sample_hint")}</p>
              <button type="button" onClick={handleSample} className={sideButton}>
                {L("ins_use_sample")}
              </button>
            </>
          )}
        </>
      )}

      {!scanned && !busy && ocrOff && (
        <div className="rounded-lg bg-surface-low p-5 flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 shrink-0 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
              <CreditCard size={22} aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <div className="font-semibold">{L("ins_scan_title")}</div>
              <p className="text-[15px] text-ink font-medium">{L("scan_off_note")}</p>
              <p className="text-[14px] text-text-muted leading-snug">{L("ins_sample_hint")}</p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button type="button" onClick={handleSample} className={sideButton}>
              {L("ins_use_sample")}
            </button>
            {onSkip && (
              <button type="button" onClick={onSkip} className={sideButton}>
                {L("skip_step")}
              </button>
            )}
          </div>
          <button type="button" onClick={() => onChange({ ...EMPTY })} className={`self-center ${linkButton}`}>
            {L("ins_type_instead")}
          </button>
        </div>
      )}

      {busy && (
        <div
          className="w-full rounded-lg bg-primary-fixed/40 py-10 flex flex-col items-center gap-3"
          role="status"
          aria-live="polite"
        >
          <Loader2 size={32} className="animate-spin text-primary" aria-hidden="true" />
          <div className="text-sm text-primary font-medium">{L("ins_reading")}</div>
        </div>
      )}

      {preview && !busy && (
        <div className="relative">
          <img src={preview} alt={L("ins_preview_alt")} className="w-full rounded-lg shadow-soft" />
          <div className="absolute top-3 right-3 flex gap-2">
            {!ocrOff && (
              <button type="button" onClick={openPrimaryCamera} className={iconButton} aria-label={L("scan_again")}>
                <RefreshCw size={18} aria-hidden="true" />
              </button>
            )}
            <button type="button" onClick={clearCard} className={iconButton} aria-label={L("ins_clear")}>
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {error && !busy && (
        <div role="alert" className="p-3 rounded-md bg-error-container text-error text-sm">
          {error}
        </div>
      )}

      {scanned && !busy && (
        <div className="flex flex-col gap-3">
          {usedSample && (
            <span className="self-start text-[13px] font-semibold text-ink bg-warning-container rounded px-2 py-0.5">
              {L("ins_sample_badge")}
            </span>
          )}
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 text-sm text-primary font-medium">
              <CheckCircle2 size={16} aria-hidden="true" /> {L("ins_confirm")}
            </div>
            {!ocrOff && (
              <button
                type="button"
                onClick={openPrimaryCamera}
                className="inline-flex items-center gap-1 min-h-[44px] px-2 text-sm text-primary font-medium hover:text-primary-hover rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              >
                <RefreshCw size={14} aria-hidden="true" /> {L("scan_again")}
              </button>
            )}
          </div>
          <Row label={L("ins_provider")} value={value!.provider} onChange={(v) => update("provider", v)} />
          <Row label={L("ins_plan")} value={value!.plan_name} onChange={(v) => update("plan_name", v)} />
          <Row label={L("ins_member_id")} value={value!.member_id} onChange={(v) => update("member_id", v)} />
          <Row label={L("ins_group")} value={value!.group_number} onChange={(v) => update("group_number", v)} />
          <Row label={L("ins_name_on_card")} value={value!.name_on_card} onChange={(v) => update("name_on_card", v)} />
          <button type="button" onClick={clearCard} className={`self-start ${linkButton} px-0`}>
            {L("ins_clear")}
          </button>
        </div>
      )}

      {!scanned && !busy && !ocrOff && onSkip && (
        <button type="button" onClick={onSkip} className={sideButton}>
          {L("skip_step")}
        </button>
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
          label={L("ins_scan_title")}
          aspectHint="card"
          language={language}
          onCapture={handleCapture}
          onClose={() => setCameraOpen(false)}
        />
      )}
    </div>
  );
}

function Row({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-[13px] font-semibold text-text-muted mb-1">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-11 px-3 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
      />
    </div>
  );
}
