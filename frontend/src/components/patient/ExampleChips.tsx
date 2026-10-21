import { t } from "../../lib/i18n";

type Key = Parameters<typeof t>[0];

// The exact phrases the triage tests pin (backend tests, contract C9), so a judge
// who taps one lands on a tested path. The phrase itself stays in English or
// Spanish on purpose: a translated phrase would be a different, untested input.
// Other languages get a short translated label above it.
export const EXAMPLE_PHRASES: Array<{ text: string; lang: "en" | "es"; label: Key }> = [
  { text: "Crushing chest pain down my left arm and I'm sweating", lang: "en", label: "example_label_chest" },
  { text: "I twisted my ankle playing soccer and it's swollen", lang: "en", label: "example_label_ankle" },
  { text: "Me duele mucho el pecho y no puedo respirar", lang: "es", label: "example_label_chest_es" },
  { text: "My 3 year old has a fever of 104 and is very sleepy", lang: "en", label: "example_label_child" },
  { text: "I need a refill of my blood pressure pills", lang: "en", label: "example_label_refill" },
];

type Props = {
  lang: string;
  onPick: (text: string) => void;
  disabled?: boolean;
};

export function ExampleChips({ lang, onPick, disabled }: Props) {
  // A Spanish speaker sees the Spanish example first.
  const examples =
    lang === "es"
      ? [...EXAMPLE_PHRASES].sort((a, b) => Number(b.lang === "es") - Number(a.lang === "es"))
      : EXAMPLE_PHRASES;
  const showLabels = lang !== "en";
  return (
    <div className="flex flex-col gap-2" role="group" aria-labelledby="examples-title">
      <div>
        <div id="examples-title" className="text-sm font-semibold text-ink">
          {t("examples_title", lang)}
        </div>
        <div className="text-[13px] text-text-muted">
          {t("examples_hint", lang)}
          {lang !== "en" && lang !== "es" && <> {t("examples_hint_other", lang)}</>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {examples.map((ex) => {
          const showLabel = showLabels && ex.lang !== lang;
          return (
            <button
              key={ex.text}
              type="button"
              disabled={disabled}
              onClick={() => onPick(ex.text)}
              className="text-start min-h-[44px] px-3 py-2 rounded-lg text-[14px] leading-snug bg-surface-lowest text-ink ring-1 ring-line hover:ring-primary/40 transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
            >
              {showLabel && <span className="block font-semibold">{t(ex.label, lang)}</span>}
              <span lang={ex.lang} dir="ltr" className={showLabel ? "block text-[13px] text-text-muted" : "block"}>
                {ex.text}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
