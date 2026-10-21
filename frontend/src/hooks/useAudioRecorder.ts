import { useCallback, useEffect, useRef, useState } from "react";
import type { SpeechRec, SpeechRecognitionEvent, SpeechWindow } from "../types";

export type UseAudioRecorder = {
  isRecording: boolean;
  audioBlob: Blob | null;
  elapsed: number;
  permissionDenied: boolean;
  // Web Speech API live transcript. Populated in real-time on browsers that
  // support window.SpeechRecognition (iOS Safari 14.1+, Chrome, Edge). When
  // non-empty, callers can skip the server /transcribe round-trip entirely.
  liveTranscript: string;
  webSpeechSupported: boolean;
  start: (langHint?: string) => Promise<void>;
  stop: () => void;
  reset: () => void;
};

// A minute is plenty to describe symptoms, and it keeps an uploaded clip small
// enough for the server to transcribe quickly.
const MAX_SECONDS = 60;

// Map our internal ISO-639-1 codes to BCP-47 tags that SpeechRecognition expects.
const SPEECH_LANG_MAP: Record<string, string> = {
  en: "en-US", es: "es-US", fr: "fr-FR", de: "de-DE",
  pt: "pt-BR", it: "it-IT", vi: "vi-VN", zh: "zh-CN",
  ja: "ja-JP", ko: "ko-KR", ar: "ar-SA", hi: "hi-IN",
  ru: "ru-RU", nl: "nl-NL", pl: "pl-PL", tr: "tr-TR",
  uk: "uk-UA", ur: "ur-PK", bn: "bn-IN", tl: "fil-PH",
  ht: "fr-FR", fa: "fa-IR", gu: "gu-IN", id: "id-ID",
};

/** BCP-47 tag for one of our language codes (speech recognition and read-aloud share it). */
export function speechLangTag(code: string): string {
  return SPEECH_LANG_MAP[(code || "").toLowerCase()] || "en-US";
}

// Safari records audio/mp4, not webm. Let the browser pick when none of these fit.
function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return undefined;
  }
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
}

// Web Speech API surface lives in ../types so the scribe page shares one
// declaration instead of re-deriving it with `any`.
function getSpeechCtor(): (new () => SpeechRec) | null {
  if (typeof window === "undefined") return null;
  const w = window as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useAudioRecorder(): UseAudioRecorder {
  const [isRecording, setIsRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const speechRef = useRef<SpeechRec | null>(null);
  // Accumulated FINAL results from the speech recognizer. Interim results are
  // appended to a separate scratch buffer so the user sees them update live,
  // but only finals are committed to state on stop().
  const finalChunksRef = useRef<string>("");

  const webSpeechSupported = getSpeechCtor() !== null;

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
      try { speechRef.current?.abort(); } catch { /* ignore */ }
    };
  }, []);

  const stopInternal = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
    try { speechRef.current?.stop(); } catch { /* ignore */ }
    setIsRecording(false);
  }, []);

  const start = useCallback(async (langHint?: string) => {
    setAudioBlob(null);
    setElapsed(0);
    setLiveTranscript("");
    finalChunksRef.current = "";
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = pickMimeType();
      const recorder = preferred ? new MediaRecorder(stream, { mimeType: preferred }) : new MediaRecorder(stream);
      const mimeType = recorder.mimeType || preferred || "audio/webm";
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        setAudioBlob(blob);
        stream.getTracks().forEach((t) => t.stop());
      };
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);

      // Spin up the Web Speech recognizer in parallel. It uses its own mic
      // session (independent of MediaRecorder) and emits interim+final
      // transcripts as the patient speaks. Failures are swallowed — the
      // MediaRecorder path remains the canonical fallback.
      const SpeechCtor = getSpeechCtor();
      if (SpeechCtor) {
        try {
          const rec = new SpeechCtor();
          rec.continuous = true;
          rec.interimResults = true;
          rec.lang = speechLangTag(langHint || "");
          rec.onresult = (e: SpeechRecognitionEvent) => {
            let interim = "";
            for (let i = e.resultIndex; i < e.results.length; i++) {
              const segment = e.results[i];
              const txt = segment[0]?.transcript || "";
              if (segment.isFinal) finalChunksRef.current += txt;
              else interim += txt;
            }
            setLiveTranscript((finalChunksRef.current + " " + interim).trim());
          };
          rec.onerror = () => { /* swallow: the recorded clip is still there */ };
          rec.onend = () => { /* allow caller to read liveTranscript */ };
          speechRef.current = rec;
          rec.start();
        } catch {
          // Some browsers throw if called twice or in private mode — ignore.
          speechRef.current = null;
        }
      }

      const startedAt = Date.now();
      timerRef.current = window.setInterval(() => {
        const secs = Math.floor((Date.now() - startedAt) / 1000);
        setElapsed(secs);
        if (secs >= MAX_SECONDS) stopInternal();
      }, 250);
    } catch (err) {
      console.error("Mic permission denied or error:", err);
      setPermissionDenied(true);
    }
  }, [stopInternal]);

  const reset = useCallback(() => {
    setAudioBlob(null);
    setElapsed(0);
    setLiveTranscript("");
    finalChunksRef.current = "";
  }, []);

  return {
    isRecording,
    audioBlob,
    elapsed,
    permissionDenied,
    liveTranscript,
    webSpeechSupported,
    start,
    stop: stopInternal,
    reset,
  };
}
