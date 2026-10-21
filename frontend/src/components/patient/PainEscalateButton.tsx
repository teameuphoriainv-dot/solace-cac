import { useEffect, useState } from "react";
import { AlertCircle, Check, Loader2 } from "lucide-react";
import { postPainFlag } from "../../lib/api-patient";
import { t } from "../../lib/i18n";

type Props = { hospitalId: string; patientId: string; language?: string };

const COOLDOWN_S = 30;

/**
 * "I feel worse": raises the flag on the nurse dashboard (the API still calls it
 * pain_flag). Covers pain, breathing, bleeding, or feeling faint. If the call
 * fails the patient is told to go to the desk, never left guessing.
 */
export function PainEscalateButton({ hospitalId, patientId, language = "en" }: Props) {
  const [sending, setSending] = useState(false);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [cooldownLeft, setCooldownLeft] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!sentAt) return;
    const tick = () => {
      const left = Math.max(0, COOLDOWN_S - Math.floor((Date.now() - sentAt) / 1000));
      setCooldownLeft(left);
      if (left === 0) setSentAt(null);
    };
    tick();
    const id = window.setInterval(tick, 500);
    return () => window.clearInterval(id);
  }, [sentAt]);

  const sent = sentAt !== null;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={sending || cooldownLeft > 0}
        onClick={async () => {
          setSending(true);
          setFailed(false);
          try {
            await postPainFlag(hospitalId, patientId);
            setSentAt(Date.now());
          } catch {
            setFailed(true);
          } finally {
            setSending(false);
          }
        }}
        className={`w-full min-h-14 px-4 py-3 rounded-md font-semibold text-white transition-all shadow-soft tracking-editorial rtl:tracking-normal focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-error/40 focus-visible:ring-offset-2 disabled:cursor-default ${
          sent ? "bg-secondary text-base leading-snug" : "bg-error hover:brightness-110 text-lg"
        }`}
      >
        <span className="inline-flex items-center justify-center gap-2 text-center">
          {sending ? (
            <Loader2 size={22} className="animate-spin shrink-0" aria-hidden="true" />
          ) : sent ? (
            <Check size={22} className="shrink-0" aria-hidden="true" />
          ) : (
            <AlertCircle size={22} className="shrink-0" aria-hidden="true" />
          )}
          {sent ? t("worse_sent", language) : t("worse_button", language)}
        </span>
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        {sent ? t("worse_sent", language) : ""}
      </span>
      {failed ? (
        <div role="alert" className="p-3 rounded-md bg-error-container text-error text-[15px] font-semibold">
          {t("worse_error", language)}
        </div>
      ) : (
        !sent && <p className="text-[13px] text-text-muted text-center">{t("worse_help", language)}</p>
      )}
    </div>
  );
}
