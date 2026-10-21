// Lightweight i18n for the patient screens. No library, which keeps the bundle small.
// Languages chosen so Whisper STT + ElevenLabs multilingual_v2 + Claude all support them.
// English ships with the app. Each other language is its own file in ./i18n/ and loads
// when the patient picks it. Until it arrives, and for any key it lacks, t() shows English.

import { useEffect, useSyncExternalStore } from "react";
import en from "./i18n/en";
import type { Dict, Key } from "./i18n/types";

export type { Key as I18nKey } from "./i18n/types";

export type LangCode =
  | "en" | "es" | "zh" | "hi" | "ar" | "fr" | "pt" | "ru" | "ja" | "ko"
  | "vi" | "de" | "it" | "tr" | "pl" | "fa" | "ur" | "id" | "tl" | "bn";

export type LanguageOption = {
  code: LangCode;
  english: string;
  native: string;
  flag: string;
  rtl?: boolean;
};

export const LANGUAGES: LanguageOption[] = [
  { code: "en", english: "English",    native: "English",       flag: "🇺🇸" },
  { code: "es", english: "Spanish",    native: "Español",       flag: "🇪🇸" },
  { code: "zh", english: "Chinese",    native: "中文",          flag: "🇨🇳" },
  { code: "hi", english: "Hindi",      native: "हिन्दी",          flag: "🇮🇳" },
  { code: "ar", english: "Arabic",     native: "العربية",        flag: "🇸🇦", rtl: true },
  { code: "fr", english: "French",     native: "Français",      flag: "🇫🇷" },
  { code: "pt", english: "Portuguese", native: "Português",     flag: "🇧🇷" },
  { code: "ru", english: "Russian",    native: "Русский",       flag: "🇷🇺" },
  { code: "ja", english: "Japanese",   native: "日本語",         flag: "🇯🇵" },
  { code: "ko", english: "Korean",     native: "한국어",         flag: "🇰🇷" },
  { code: "vi", english: "Vietnamese", native: "Tiếng Việt",    flag: "🇻🇳" },
  { code: "de", english: "German",     native: "Deutsch",       flag: "🇩🇪" },
  { code: "it", english: "Italian",    native: "Italiano",      flag: "🇮🇹" },
  { code: "tr", english: "Turkish",    native: "Türkçe",        flag: "🇹🇷" },
  { code: "pl", english: "Polish",     native: "Polski",        flag: "🇵🇱" },
  { code: "fa", english: "Persian",    native: "فارسی",          flag: "🇮🇷", rtl: true },
  { code: "ur", english: "Urdu",       native: "اردو",           flag: "🇵🇰", rtl: true },
  { code: "id", english: "Indonesian", native: "Bahasa Indonesia", flag: "🇮🇩" },
  { code: "tl", english: "Filipino",   native: "Filipino",      flag: "🇵🇭" },
  { code: "bn", english: "Bengali",    native: "বাংলা",         flag: "🇧🇩" },
];

export function isRTL(lang: string): boolean {
  return LANGUAGES.find((l) => l.code === lang)?.rtl === true;
}

// Full translations. Short, plain sentences beat elegant ones here: patients are
// often in pain or scared. Spanish uses usted, Italian Lei, Turkish siz, Persian shoma.
// Each import() is its own small file in the build, fetched only when needed.
const LOADERS: Record<Exclude<LangCode, "en">, () => Promise<{ default: Dict }>> = {
  es: () => import("./i18n/es"),
  zh: () => import("./i18n/zh"),
  hi: () => import("./i18n/hi"),
  ar: () => import("./i18n/ar"),
  fr: () => import("./i18n/fr"),
  pt: () => import("./i18n/pt"),
  ru: () => import("./i18n/ru"),
  ja: () => import("./i18n/ja"),
  ko: () => import("./i18n/ko"),
  vi: () => import("./i18n/vi"),
  de: () => import("./i18n/de"),
  it: () => import("./i18n/it"),
  tr: () => import("./i18n/tr"),
  pl: () => import("./i18n/pl"),
  fa: () => import("./i18n/fa"),
  ur: () => import("./i18n/ur"),
  id: () => import("./i18n/id"),
  tl: () => import("./i18n/tl"),
  bn: () => import("./i18n/bn"),
};

const loaded: Partial<Record<LangCode, Dict>> = { en };
const inFlight = new Map<string, Promise<boolean>>();
const listeners = new Set<() => void>();

function hasLoader(lang: string): lang is Exclude<LangCode, "en"> {
  return Object.prototype.hasOwnProperty.call(LOADERS, lang);
}

/** True when t() can already answer in this language. Unknown codes count as ready (English). */
export function isLanguageLoaded(lang: string): boolean {
  return !hasLoader(lang) || loaded[lang] !== undefined;
}

/**
 * Fetches one language's strings. Safe to call many times: one request per language.
 * Resolves true once t() can use them, or false if the file could not be fetched
 * (then the screens stay in English and a later call tries again).
 */
export function loadLanguage(lang: string): Promise<boolean> {
  if (!hasLoader(lang)) return Promise.resolve(lang === "en");
  if (loaded[lang]) return Promise.resolve(true);
  let p = inFlight.get(lang);
  if (!p) {
    p = LOADERS[lang]()
      .then((mod) => {
        loaded[lang] = mod.default;
        listeners.forEach((fn) => fn());
        return true;
      })
      .catch(() => false)
      .finally(() => inFlight.delete(lang));
    inFlight.set(lang, p);
  }
  return p;
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

const RETRY_MS = [1500, 4000, 10000];

/**
 * Loads the language and re-renders the calling screen when it arrives, so a
 * page that calls t(key, lang) switches from English to the patient's language
 * by itself. Returns true once the language is ready.
 */
export function useLanguage(lang: string): boolean {
  const ready = useSyncExternalStore(subscribe, () => isLanguageLoaded(lang), () => isLanguageLoaded(lang));
  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    let timer: number | undefined;
    const attempt = (n: number) => {
      void loadLanguage(lang).then((ok) => {
        if (!ok && !cancelled && n < RETRY_MS.length) timer = window.setTimeout(() => attempt(n + 1), RETRY_MS[n]);
      });
    };
    attempt(0);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [lang, ready]);
  return ready;
}

export function t(key: Key, lang: string): string {
  const v = loaded[lang as LangCode]?.[key];
  return v ? v : en[key];
}
