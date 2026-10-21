/**
 * Which optional features are switched on for this server.
 *
 * Solace runs fully without API keys: triage rules, the bedside model, the queue and
 * the early-warning scores are all local. Features that need an AI key (reading an ID
 * card, drafting notes, suggesting prescriptions) or a paid service (sending a text)
 * read this so the screen can explain what is off instead of failing.
 *
 * Served by GET /api/{hospitalId}/capabilities. Fetched once and shared by every caller.
 */
import { useEffect, useState } from "react";
import { api } from "./api";

export type Capabilities = {
  /** Claude is configured: notes, reasoning, prescription ideas, card reading, comfort text. */
  llm: boolean;
  /** ID and insurance card photos can be read (needs llm). */
  ocr: boolean;
  /** Server-side speech to text for browsers without live dictation. */
  transcription: boolean;
  /** Server-side spoken audio of the guidance. The browser read-aloud works without it. */
  tts: boolean;
  /** Real text messages can be sent. Without it the app shows a preview of the text. */
  sms: boolean;
  triage_model: {
    /** The trained bedside model is installed (scripts/fetch_models.sh). */
    loaded: boolean;
    /** "lgbm_5fold" when loaded, "rules_only" when the model files are missing. */
    mode: string;
    folds: number;
  };
};

/** Safe default while loading or if the request fails: assume nothing optional is on. */
export const NO_CAPABILITIES: Capabilities = {
  llm: false,
  ocr: false,
  transcription: false,
  tts: false,
  sms: false,
  triage_model: { loaded: false, mode: "rules_only", folds: 0 },
};

const pending = new Map<string, Promise<Capabilities>>();

export function fetchCapabilities(hospitalId: string): Promise<Capabilities> {
  let p = pending.get(hospitalId);
  if (!p) {
    p = api
      .get<Capabilities>(`/api/${hospitalId}/capabilities`)
      .then((r) => ({ ...NO_CAPABILITIES, ...r.data }))
      .catch(() => {
        pending.delete(hospitalId); // let a later call retry
        return NO_CAPABILITIES;
      });
    pending.set(hospitalId, p);
  }
  return p;
}

/** Returns null until the first answer arrives, then the server's capabilities. */
export function useCapabilities(hospitalId: string | undefined): Capabilities | null {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  useEffect(() => {
    if (!hospitalId) return;
    let live = true;
    fetchCapabilities(hospitalId).then((c) => live && setCaps(c));
    return () => {
      live = false;
    };
  }, [hospitalId]);
  return caps;
}
