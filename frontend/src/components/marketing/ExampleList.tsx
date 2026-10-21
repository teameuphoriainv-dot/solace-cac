import { CopyButton } from "./CopyButton";
import { EXAMPLES } from "./site";

/** The tested check-in phrases with what to expect, each with a Copy button. */
export function ExampleList({ compact = false }: { compact?: boolean }) {
  return (
    <ul className={`flex flex-col ${compact ? "gap-2" : "divide-y divide-line"}`}>
      {EXAMPLES.map((ex) => (
        <li
          key={ex.text}
          className={
            compact
              ? "rounded-lg bg-surface-lowest ring-1 ring-line px-3 py-2.5"
              : "flex flex-col sm:flex-row sm:items-start gap-2 sm:gap-6 py-4"
          }
        >
          <div className="flex-1 min-w-0">
            <p
              className={`text-ink ${compact ? "text-[13px] leading-snug" : "text-[17px] leading-snug"}`}
              lang={ex.lang}
            >
              &ldquo;{ex.text}&rdquo;
            </p>
            {ex.note && (
              <p className={`mt-0.5 text-text-muted ${compact ? "text-[12px]" : "text-[13px]"}`}>{ex.note}</p>
            )}
            <p className={`mt-1 text-text-muted ${compact ? "text-[12px]" : "text-[14px]"}`}>
              <span className="font-semibold text-ink">Expect:</span> {ex.expect}
            </p>
          </div>
          <div className={compact ? "mt-1 -ml-2" : "sm:pt-0.5 -ml-2.5 sm:ml-0"}>
            <CopyButton text={ex.text} label={`Copy the phrase: ${ex.text}`} />
          </div>
        </li>
      ))}
    </ul>
  );
}
