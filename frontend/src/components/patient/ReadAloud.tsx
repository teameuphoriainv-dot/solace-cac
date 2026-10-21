import { useEffect, useState } from "react";
import { Square, Volume2 } from "lucide-react";
import { t } from "../../lib/i18n";
import { speechLangTag } from "../../hooks/useAudioRecorder";

type Props = {
  /** What to read, already in the patient's language. */
  text: string;
  lang: string;
};

function getSynth(): SpeechSynthesis | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  return window.speechSynthesis;
}

function pickVoice(voices: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  const tag = speechLangTag(lang).toLowerCase();
  const base = tag.split("-")[0];
  const norm = (v: SpeechSynthesisVoice) => v.lang.toLowerCase().replace("_", "-");
  return (
    voices.find((v) => norm(v) === tag) ||
    voices.find((v) => norm(v).split("-")[0] === base) ||
    null
  );
}

// Chrome goes quiet partway through one long utterance, so speak sentence by sentence.
function sentences(text: string): string[] {
  const parts = text.match(/[^.!?。！？।]+[.!?。！？।]*/g) || [text];
  return parts.map((p) => p.trim()).filter(Boolean);
}

/**
 * "Read this to me" using the browser's own speech voices. Needs no server or key.
 * Renders nothing when the browser has no voice for the patient's language, so a
 * Spanish page is never read in an English voice.
 */
export function ReadAloud({ text, lang }: Props) {
  const synth = getSynth();
  const [voice, setVoice] = useState<SpeechSynthesisVoice | null>(null);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    if (!synth) return;
    const load = () => setVoice(pickVoice(synth.getVoices(), lang));
    load();
    synth.addEventListener?.("voiceschanged", load);
    return () => {
      synth.removeEventListener?.("voiceschanged", load);
      synth.cancel();
    };
  }, [synth, lang]);

  if (!synth || !voice || !text.trim()) return null;

  function start() {
    if (!synth || !voice) return;
    synth.cancel();
    const parts = sentences(text);
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      u.voice = voice;
      u.lang = voice.lang;
      u.rate = 0.95;
      u.onerror = () => setSpeaking(false);
      if (i === parts.length - 1) u.onend = () => setSpeaking(false);
      synth.speak(u);
    });
    setSpeaking(true);
  }

  function stop() {
    synth?.cancel();
    setSpeaking(false);
  }

  return (
    <button
      type="button"
      onClick={speaking ? stop : start}
      aria-pressed={speaking}
      className="self-start inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full text-[15px] font-semibold text-primary bg-primary-fixed/60 hover:bg-primary-fixed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
    >
      {speaking ? <Square size={16} aria-hidden="true" /> : <Volume2 size={18} aria-hidden="true" />}
      {t(speaking ? "read_aloud_stop" : "read_aloud", lang)}
    </button>
  );
}
