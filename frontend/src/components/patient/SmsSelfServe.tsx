import { useState } from "react";
import { Check, Loader2, MessageSquare } from "lucide-react";
import { errorStatus, sendCareInstructions } from "../../lib/api-patient";
import { isRTL, t } from "../../lib/i18n";

// Arabic, Persian, Urdu and Hebrew letters.
const RTL_LETTER = /[֐-ࣿיִ-﷿ﹰ-﻿]/;

/**
 * The text message, one line per block. Each line takes its own direction, so a
 * line written in Arabic reads right to left and an English line (a name, a
 * hospital, the opt-out footer) keeps its period at the end.
 */
function SmsBubble({ text, lang }: { text: string; lang: string }) {
  return (
    <div
      dir={isRTL(lang) ? "rtl" : "ltr"}
      className="self-start max-w-[92%] rounded-2xl rounded-es-sm bg-surface-high px-4 py-3 text-[15px] leading-relaxed text-ink shadow-soft"
    >
      {text.split("\n").map((line, i) =>
        line.trim() ? (
          <p key={i} dir={RTL_LETTER.test(line) ? "rtl" : "ltr"} className="whitespace-pre-wrap text-start">
            {line}
          </p>
        ) : (
          <div key={i} className="h-3" aria-hidden="true" />
        ),
      )}
    </div>
  );
}

export function SmsSelfServe({
  hospitalId,
  patientId,
  lang,
  smsOn,
}: {
  hospitalId: string;
  patientId: string;
  lang: string;
  /** Real texting is configured. Without it the patient sees the exact text instead. */
  smsOn: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const digits = phone.replace(/\D/g, "");

  async function request(to: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await sendCareInstructions(hospitalId, patientId, to);
      if (r.sent) setDone(true);
      // The preview stands in for the text only when texting is off. A real send
      // that failed is an error, not a preview.
      else if (r.preview && (r.reason === "sms_off" || !smsOn)) setPreview(r.preview);
      else setError(t("result_sms_failed", lang));
    } catch (e) {
      setError(t(smsOn && errorStatus(e) === 400 ? "result_sms_bad_phone" : "result_sms_failed", lang));
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setOpen(false);
    setPreview(null);
    setError(null);
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setOpen(true);
          // Texting is off: nothing to send, so go straight to the preview.
          if (!smsOn) request("");
        }}
        className="inline-flex items-center justify-center gap-1.5 min-h-[44px] rounded-md text-sm font-semibold text-primary bg-primary-fixed/40 hover:bg-primary-fixed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
      >
        <MessageSquare size={14} aria-hidden="true" /> {t(smsOn ? "result_sms_cta" : "result_sms_preview_cta", lang)}
      </button>
    );
  }
  if (done) {
    return (
      <div
        role="status"
        className="inline-flex items-center justify-center gap-1.5 min-h-[44px] rounded-md text-sm font-semibold text-ink bg-success/15"
      >
        <Check size={14} className="text-success" aria-hidden="true" /> {t("result_sms_sent", lang)}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 bg-surface-lowest rounded-lg p-4 shadow-soft">
      <h2 className="text-[13px] uppercase tracking-wider rtl:tracking-normal text-text-muted font-semibold">
        {t(smsOn ? "result_sms_title" : "result_sms_preview_title", lang)}
      </h2>
      {preview ? (
        <div className="flex flex-col gap-2" role="status">
          <p className="text-[14px] text-ink leading-snug">{t("result_sms_off_note", lang)}</p>
          <SmsBubble text={preview} lang={lang} />
        </div>
      ) : smsOn ? (
        <div className="flex gap-2">
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder={t("result_sms_phone_placeholder", lang)}
            aria-label={t("result_sms_aria", lang)}
            className="flex-1 min-w-0 h-11 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none"
            dir="ltr"
            autoFocus
          />
          <button
            type="button"
            onClick={() => request(phone)}
            disabled={busy || digits.length < 7}
            className="h-11 px-4 rounded-md bg-primary text-white font-semibold text-sm disabled:opacity-50 inline-flex items-center gap-1.5 shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
          >
            {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <MessageSquare size={14} aria-hidden="true" />}
            {t("result_sms_send", lang)}
          </button>
        </div>
      ) : (
        busy && (
          <div className="flex items-center gap-2 text-[14px] text-text-muted" role="status" aria-live="polite">
            <Loader2 size={14} className="animate-spin text-primary" aria-hidden="true" />
            {t("result_preparing_subtitle", lang)}
          </div>
        )
      )}
      {error && (
        <div role="alert" className="text-[14px] text-error">
          {error}
        </div>
      )}
      <button
        type="button"
        onClick={close}
        className="text-[14px] text-text-muted underline self-start min-h-[44px] rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      >
        {t(preview ? "result_sms_hide" : "result_sms_cancel", lang)}
      </button>
    </div>
  );
}
