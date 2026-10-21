import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { PATIENT_LANG_KEY } from "./lib/constants";
import { loadLanguage } from "./lib/i18n";
import { loadRuntimeConfig } from "./lib/runtime-config";
import "./index.css";

// A patient who reloads their result page already picked a language. Fetch it
// alongside the config so the first paint is usually in that language, but never
// hold the page for more than a moment: English shows if it is slow.
function patientLanguageReady(): Promise<unknown> {
  let lang: string | null = null;
  try {
    if (/^\/[^/]+\/result\//.test(window.location.pathname)) lang = sessionStorage.getItem(PATIENT_LANG_KEY);
  } catch {
    /* storage blocked: English until the page loads it */
  }
  if (!lang || lang === "en") return Promise.resolve();
  return Promise.race([loadLanguage(lang), new Promise((r) => setTimeout(r, 1200))]);
}

// Fetch runtime config before first render so API calls use the right URL.
// Falls back to baked env vars if /config.json isn't present.
Promise.allSettled([loadRuntimeConfig(), patientLanguageReady()]).finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </BrowserRouter>
    </React.StrictMode>
  );
});
