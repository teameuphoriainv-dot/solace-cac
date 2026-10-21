import { motion } from "framer-motion";
import { ESI_COLORS } from "../../lib/constants";
import { t } from "../../lib/i18n";

type Props = {
  esiLevel: number;
  size?: "sm" | "lg";
  showLabel?: boolean;
  /** The small "Priority" word above the label. Off where a heading already says it. */
  caption?: boolean;
  /** Patient's language for the label. The clinician queue leaves it as English. */
  language?: string;
};

function esiLabel(level: number, lang: string): string {
  if (level >= 1 && level <= 5) {
    return t(`esi_label_${level}` as Parameters<typeof t>[0], lang);
  }
  return ESI_COLORS[level]?.label ?? "Unknown";
}

export function ESIBadge({ esiLevel, size = "sm", showLabel = true, caption = true, language = "en" }: Props) {
  const cfg = ESI_COLORS[esiLevel] || { bg: "#4A5557", label: "Unknown", onDark: true };
  const dim = size === "lg" ? "w-24 h-24 text-4xl" : "w-10 h-10 text-base";
  const label = esiLabel(esiLevel, language);
  return (
    <div className="flex items-center gap-4">
      <motion.div
        key={esiLevel}
        initial={{ scale: 0.7, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 22 }}
        className={`${dim} rounded-full font-bold tracking-editorial-tight rtl:tracking-normal flex items-center justify-center shadow-card ${
          cfg.onDark ? "text-white" : "text-ink"
        }`}
        style={{ background: cfg.bg }}
        role="img"
        aria-label={t("esi_aria", language).replace("{n}", String(esiLevel)).replace("{label}", label)}
      >
        <span aria-hidden="true">{esiLevel}</span>
      </motion.div>
      {showLabel && (
        <div className="flex flex-col leading-tight" aria-hidden="true">
          {caption && (
            // Letter spacing breaks joined scripts such as Arabic apart, so it is off right to left.
            <span className="text-[13px] uppercase tracking-[0.12em] rtl:tracking-normal text-text-muted">
              {t("esi_priority", language)}
            </span>
          )}
          <span className={`font-bold tracking-editorial rtl:tracking-normal ${size === "lg" ? "text-2xl" : "text-sm"}`}>
            {label}
          </span>
        </div>
      )}
    </div>
  );
}
