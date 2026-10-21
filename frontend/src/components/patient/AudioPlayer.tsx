import { useEffect, useRef, useState } from "react";
import { Play, Pause } from "lucide-react";
import { t } from "../../lib/i18n";

type Props = {
  audioUrl: string | null;
  language?: string;
  /** Called when the clip cannot play, so the page can offer read-aloud instead. */
  onFailed?: () => void;
};

/** Sticky player for the spoken guidance. Renders nothing when there is no clip. */
export function AudioPlayer({ audioUrl, language = "en", onFailed }: Props) {
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const ref = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    setFailed(false);
    if (!audioUrl) return;
    const timer = window.setTimeout(() => {
      ref.current?.play().catch(() => {
        /* autoplay may be blocked by the browser; user can tap play */
      });
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [audioUrl]);

  function fail() {
    setFailed(true);
    onFailed?.();
  }

  if (!audioUrl || failed) return null;

  return (
    <div className="sticky bottom-0 w-full bg-surface-lowest/85 backdrop-blur-xl p-4 flex items-center gap-4 shadow-glass">
      <button
        type="button"
        className="w-12 h-12 rounded-full bg-primary-gradient text-white flex items-center justify-center shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
        aria-label={t(playing ? "audio_pause_aria" : "audio_play_aria", language)}
        onClick={() => {
          const el = ref.current;
          if (!el) return;
          if (playing) {
            el.pause();
          } else {
            const p = el.play();
            if (p && typeof p.catch === "function") p.catch(fail);
          }
        }}
      >
        {playing ? <Pause size={22} aria-hidden="true" /> : <Play size={22} fill="white" aria-hidden="true" />}
      </button>
      <div className={`flex items-end gap-1 h-8 flex-1 ${playing ? "opacity-100" : "opacity-40"}`} aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className="w-1.5 bg-primary rounded"
            style={{
              height: `${12 + (i % 3) * 8}px`,
              animation: playing ? `pulse 1.2s ease-in-out ${i * 0.15}s infinite` : undefined,
            }}
          />
        ))}
      </div>
      <audio
        ref={ref}
        src={audioUrl}
        preload="auto"
        crossOrigin="anonymous"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={fail}
      />
    </div>
  );
}
