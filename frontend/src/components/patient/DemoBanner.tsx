import { t } from "../../lib/i18n";

type Props = {
  lang: string;
  /** Pad for the phone's notch. Turn off when the banner is not at the very top. */
  safeTop?: boolean;
};

/** Slim strip at the top of every patient screen: this is a student demo, not real care. */
export function DemoBanner({ lang, safeTop = true }: Props) {
  return (
    <div
      role="note"
      className="w-full bg-warning-container text-ink text-[13px] font-medium leading-snug text-center px-4 pb-1.5"
      style={{ paddingTop: safeTop ? "calc(0.375rem + env(safe-area-inset-top, 0px))" : "0.375rem" }}
    >
      {t("demo_banner", lang)}
    </div>
  );
}
