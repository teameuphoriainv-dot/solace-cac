import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API needs a secure page; fall back to a hidden text box.
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

/** Small "Copy" button for a phrase. Says "Copied" for two seconds after a click. */
export function CopyButton({
  text,
  label,
  tone = "light",
}: {
  text: string;
  /** Accessible name, e.g. "Copy the chest pain example". */
  label: string;
  tone?: "light" | "dark";
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const t = window.setTimeout(() => setState("idle"), 2000);
    return () => window.clearTimeout(t);
  }, [state]);

  const colors =
    tone === "dark"
      ? "text-primary-fixed hover:text-white hover:bg-white/10 focus-visible:ring-white/60"
      : "text-text-muted hover:text-primary hover:bg-primary-dim focus-visible:ring-primary/40";

  return (
    <button
      type="button"
      onClick={async () => setState((await copyText(text)) ? "copied" : "failed")}
      aria-label={label}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 h-9 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 ${colors}`}
    >
      {state === "copied" ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
      <span aria-live="polite">
        {state === "copied" ? "Copied" : state === "failed" ? "Select and copy" : "Copy"}
      </span>
    </button>
  );
}
