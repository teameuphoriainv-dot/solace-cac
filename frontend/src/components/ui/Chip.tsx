type Props = {
  label: string;
  selected: boolean;
  onToggle: () => void;
  disabled?: boolean;
};

export function Chip({ label, selected, onToggle, disabled }: Props) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      disabled={disabled}
      className={`min-h-[44px] px-4 rounded-full text-sm font-medium transition-all active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
        selected
          ? "bg-primary text-white shadow-soft"
          : "bg-surface-lowest text-ink ring-1 ring-line hover:ring-primary/40"
      }`}
    >
      {label}
    </button>
  );
}
