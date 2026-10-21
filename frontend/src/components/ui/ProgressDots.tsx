type Props = {
  total: number;
  current: number; // 1-based
  /** Spoken description, e.g. "Step 2 of 5" in the patient's language. */
  label?: string;
};

export function ProgressDots({ total, current, label }: Props) {
  const text = label ?? `Step ${current} of ${total}`;
  return (
    <div
      className="flex items-center gap-1.5"
      role="progressbar"
      aria-valuemin={1}
      aria-valuemax={total}
      aria-valuenow={current}
      aria-valuetext={text}
      aria-label={text}
    >
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          aria-hidden="true"
          className={`h-1 rounded-full transition-all ${
            i < current ? "bg-primary w-8" : "bg-surface-high w-4"
          }`}
        />
      ))}
    </div>
  );
}
