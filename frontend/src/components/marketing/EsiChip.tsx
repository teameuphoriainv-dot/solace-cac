import { ESI_COLORS } from "../../lib/constants";

/** Solid ESI badge using the app's ESI palette (ink text on the light gold level). */
export function EsiChip({ level, className = "" }: { level: number; className?: string }) {
  const c = ESI_COLORS[level] ?? ESI_COLORS[3];
  return (
    <span
      className={`inline-flex items-center justify-center rounded-md px-2 h-7 text-[13px] font-semibold tabular-nums whitespace-nowrap ${className}`}
      style={{ background: c.bg, color: c.onDark ? "#FFFFFF" : "#1A2023" }}
    >
      ESI {level}
    </span>
  );
}
