import { Mic, Square } from "lucide-react";
import { t } from "../../lib/i18n";

type Props = {
  isRecording: boolean;
  elapsed: number;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
  language?: string;
};

export function MicButton({ isRecording, elapsed, disabled, onStart, onStop, language = "en" }: Props) {
  return (
    <div className="flex flex-col items-center gap-4">
      <button
        type="button"
        disabled={disabled}
        onClick={isRecording ? onStop : onStart}
        className={`w-28 h-28 rounded-full flex items-center justify-center text-white shadow-lifted transition-transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/50 focus-visible:ring-offset-2 ${
          isRecording
            ? "bg-error animate-pulse-ring"
            : "bg-primary-gradient hover:brightness-110"
        }`}
        aria-label={t(isRecording ? "mic_stop_aria" : "mic_start_aria", language)}
      >
        {isRecording ? <Square size={40} fill="white" aria-hidden="true" /> : <Mic size={40} aria-hidden="true" />}
      </button>
      <div className="text-sm text-text-muted tracking-wide rtl:tracking-normal" aria-live="polite">
        {isRecording
          ? t("mic_listening", language).replace("{s}", String(elapsed))
          : t("mic_tap_to_speak", language)}
      </div>
    </div>
  );
}
