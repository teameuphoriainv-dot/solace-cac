import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  GripVertical,
  Lightbulb,
  Monitor,
  PanelLeft,
  PanelLeftClose,
  PanelRight,
  RefreshCw,
  RotateCcw,
  Smartphone,
  X,
} from "lucide-react";
import { apiErrorMessage, loginClinician, resetDemo } from "../lib/api";
import { saveSession } from "../lib/session";
import { useSandboxId } from "../lib/sandbox";
import { ExampleList } from "../components/marketing/ExampleList";
import { DEMO_SIGN_IN, SHOCK_VITALS } from "../components/marketing/site";

// Split screen: the patient check-in (left) and the live clinician dashboard (right),
// each a same-origin iframe of the real routes for this browser's private demo
// hospital. A "What to try" panel on the far left lists tested phrases and the
// vitals that trip the safety floor. On narrow screens everything stacks.
//
// The clinician pane is signed in automatically: this page logs in as a demo
// clinician and saves the session to localStorage, which the same-origin iframe reads.
// ?embed=1 tells the dashboard to drop its sidebar so the queue gets the room.
const PHONE_PX = 420; // default patient pane width: fits a phone frame
const MIN_PATIENT_PX = 340;
const MIN_CLINICIAN_PX = 480;
const PANEL_KEY = "solace.showcase.panel";

// Open by default only when there is room for the tips and both screens.
function readPanelOpen(): boolean {
  const roomy = typeof window !== "undefined" && window.innerWidth >= 1280;
  try {
    const saved = localStorage.getItem(PANEL_KEY);
    return saved ? saved === "open" : roomy;
  } catch {
    return roomy;
  }
}

export default function ShowcaseDemo() {
  const hospitalId = useSandboxId();
  const [ready, setReady] = useState(false);
  const [nonce, setNonce] = useState(0); // bump to remount both iframes
  const [resetting, setResetting] = useState(false);
  // The server's plain reset result (or the error), shown under the header.
  const [flash, setFlash] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  useEffect(() => {
    if (!flash) return;
    const t = window.setTimeout(() => setFlash(null), 8000);
    return () => window.clearTimeout(t);
  }, [flash]);
  const [panelOpen, setPanelOpen] = useState(readPanelOpen);

  // Width of the patient pane in px (wide screens only).
  const [leftPx, setLeftPx] = useState(PHONE_PX);
  const [splitWidth, setSplitWidth] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [isWide, setIsWide] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches,
  );
  const splitRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = "Solace: both sides at once";
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => setIsWide(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Track the split area's width so the patient pane can be clamped to it.
  useEffect(() => {
    const el = splitRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSplitWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const clampLeft = useCallback(
    (px: number) => {
      const max = Math.max(MIN_PATIENT_PX, splitWidth - MIN_CLINICIAN_PX);
      return Math.min(max, Math.max(MIN_PATIENT_PX, px));
    },
    [splitWidth],
  );

  useEffect(() => {
    // Best-effort auto sign-in so the clinician pane is live immediately.
    let cancelled = false;
    setReady(false);
    loginClinician(hospitalId, DEMO_SIGN_IN.name, DEMO_SIGN_IN.pin)
      .then((resp) => {
        if (!cancelled) saveSession(resp);
      })
      .catch(() => {
        /* fall back to the dashboard's own sign-in screen */
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [hospitalId]);

  // Window-level listeners during a drag so the pointer can travel over the
  // iframes (made non-interactive while dragging) without losing it.
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => {
      const rect = splitRef.current?.getBoundingClientRect();
      if (rect) setLeftPx(clampLeft(e.clientX - rect.left));
    };
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [dragging, clampLeft]);

  function togglePanel() {
    setPanelOpen((open) => {
      try {
        localStorage.setItem(PANEL_KEY, open ? "closed" : "open");
      } catch {
        /* remembered for this visit only */
      }
      return !open;
    });
  }

  async function handleReset() {
    if (resetting) return;
    if (!window.confirm("Reset the demo? This removes walk-in patients and restores the 5 example patients.")) return;
    setResetting(true);
    try {
      const r = await resetDemo(hospitalId);
      const failed = (r?.failed_patients?.length ?? 0) > 0;
      const base =
        (typeof r?.message === "string" && r.message.trim()) ||
        "Demo reset. Walk-in patients were removed and the example patients are back.";
      setFlash({
        tone: failed || r?.restored_patients === 0 ? "error" : "ok",
        text: failed ? `${base} Some check-ins could not be removed. Try the reset again.` : base,
      });
    } catch (e: unknown) {
      // The reload below still shows the current state.
      setFlash({ tone: "error", text: apiErrorMessage(e, "Could not reset the demo. Please try again.") });
    } finally {
      setResetting(false);
      setNonce((n) => n + 1);
    }
  }

  const patientWidth = clampLeft(leftPx);
  const leftStyle = isWide && splitWidth > 0 ? { width: `${patientWidth}px` } : undefined;
  const iframeInteractivity = dragging ? ("none" as const) : ("auto" as const);
  const preset = (share: number) => setLeftPx(clampLeft(splitWidth * share));

  return (
    <div className="h-[100dvh] flex flex-col bg-surface-low overflow-hidden">
      <header className="h-14 shrink-0 flex items-center justify-between gap-2 px-3 sm:px-5 bg-surface-lowest border-b border-line">
        <div className="flex items-center gap-3 min-w-0">
          <Link to="/" className="shrink-0 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
            <img src="/solace-logo.png" alt="Solace home" className="h-7 w-auto select-none" draggable={false} />
          </Link>
          <span className="hidden sm:inline text-[14px] text-text-muted border-l border-line pl-3 truncate">
            Both sides at once
          </span>
        </div>
        <div className="flex items-center gap-1 sm:gap-2">
          {isWide && (
            <>
              <button
                type="button"
                onClick={togglePanel}
                aria-expanded={panelOpen}
                aria-controls="what-to-try"
                className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[13px] font-medium text-text-muted hover:text-ink hover:bg-surface-low focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              >
                {panelOpen ? <PanelLeftClose size={15} aria-hidden /> : <Lightbulb size={15} aria-hidden />}
                {panelOpen ? "Hide tips" : "What to try"}
              </button>
              <div className="inline-flex items-center rounded-md bg-surface-low ring-1 ring-line p-0.5">
                <PresetButton label="Bigger patient screen" icon={PanelLeft} onClick={() => preset(0.6)} />
                <PresetButton label="Even split" text="50/50" onClick={() => preset(0.5)} />
                <PresetButton label="Bigger nurse dashboard" icon={PanelRight} onClick={() => setLeftPx(PHONE_PX)} />
              </div>
            </>
          )}
          <button
            type="button"
            onClick={() => setNonce((n) => n + 1)}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[13px] font-medium text-text-muted hover:text-ink hover:bg-surface-low focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            <RefreshCw size={14} aria-hidden /> Reload
          </button>
          <button
            type="button"
            onClick={handleReset}
            disabled={resetting}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[13px] font-medium text-text-muted hover:text-error hover:bg-surface-low disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            <RotateCcw size={14} aria-hidden /> {resetting ? "Resetting" : "Reset demo"}
          </button>
        </div>
      </header>

      {flash && (
        <div
          role="status"
          className={`shrink-0 flex items-start gap-2.5 px-3 sm:px-5 py-2.5 text-sm font-medium border-b border-line ${
            flash.tone === "ok" ? "bg-success-container text-success" : "bg-error-container text-error"
          }`}
        >
          <span className="flex-1">{flash.text}</span>
          <button
            type="button"
            onClick={() => setFlash(null)}
            aria-label="Dismiss message"
            className="h-6 w-6 rounded flex items-center justify-center opacity-70 hover:opacity-100"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row overflow-y-auto lg:overflow-hidden">
        {/* What to try: side panel on wide screens, a fold-out block on narrow ones */}
        {isWide ? (
          panelOpen && (
            <aside
              id="what-to-try"
              aria-label="What to try"
              className="w-[288px] shrink-0 overflow-y-auto border-r border-line bg-surface"
            >
              <TryPanel hospitalId={hospitalId} />
            </aside>
          )
        ) : (
          <details className="shrink-0 border-b border-line bg-surface">
            <summary className="cursor-pointer px-4 py-3 text-[15px] font-semibold text-ink">
              What to try
            </summary>
            <TryPanel hospitalId={hospitalId} />
          </details>
        )}

        <div
          ref={splitRef}
          className={`flex-1 min-w-0 flex flex-col lg:flex-row lg:min-h-0 ${dragging ? "select-none cursor-col-resize" : ""}`}
        >
          {/* Patient, phone-framed on large screens */}
          <section
            aria-label="Patient check-in"
            style={leftStyle}
            className="flex flex-col shrink-0 h-[88dvh] lg:h-auto lg:min-h-0 border-b lg:border-b-0 border-line"
          >
            <PaneLabel icon={Smartphone} title="Patient" subtitle="Waiting-room check-in" />
            <div className="flex-1 min-h-0 bg-surface-low flex justify-center lg:p-4">
              <div className="w-full lg:max-w-[400px] h-full lg:rounded-2xl lg:shadow-card overflow-hidden bg-surface-lowest lg:ring-1 lg:ring-line">
                <iframe
                  key={`patient-${hospitalId}-${nonce}`}
                  src={`/${hospitalId}`}
                  title="Patient check-in"
                  className="w-full h-full border-0"
                  style={{ pointerEvents: iframeInteractivity }}
                  allow="microphone; camera"
                />
              </div>
            </div>
          </section>

          {isWide && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize the two screens"
              onPointerDown={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDoubleClick={() => preset(0.5)}
              className={`relative w-1.5 shrink-0 cursor-col-resize transition-colors ${
                dragging ? "bg-primary" : "bg-line hover:bg-primary/50"
              }`}
              title="Drag to resize. Double-click for an even split."
            >
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-10 w-5 rounded-full bg-surface-lowest ring-1 ring-line shadow-soft flex items-center justify-center">
                <GripVertical size={14} className="text-text-muted" aria-hidden />
              </div>
            </div>
          )}

          {/* Clinician, fills the remaining space */}
          <section aria-label="Nurse dashboard" className="flex flex-col h-[88dvh] lg:h-auto lg:min-h-0 flex-1 min-w-0">
            <PaneLabel icon={Monitor} title="Nurse dashboard" subtitle="Live queue, updates on its own" />
            <div className="flex-1 min-h-0 bg-surface">
              {ready ? (
                <iframe
                  key={`clinician-${hospitalId}-${nonce}`}
                  src={`/${hospitalId}/clinician?embed=1`}
                  title="Nurse dashboard"
                  className="w-full h-full border-0"
                  style={{ pointerEvents: iframeInteractivity }}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-[14px] text-text-muted" role="status">
                  Signing in to the nurse dashboard
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function TryPanel({ hospitalId }: { hospitalId: string }) {
  return (
    <ol className="flex flex-col gap-6 px-4 py-5 text-[14px] leading-relaxed text-text-muted">
      <li>
        <Step n={1} title="Check in on the left" />
        <p className="mt-1">Paste one of these into the symptom box, or tap an example there.</p>
        <div className="mt-3">
          <ExampleList compact />
        </div>
      </li>
      <li>
        <Step n={2} title="Watch the queue on the right" />
        <p className="mt-1">The new patient shows up within a few seconds, sorted by urgency.</p>
      </li>
      <li>
        <Step n={3} title="Test the safety floor" />
        <p className="mt-1">
          Open James (ESI 4, sprained ankle) on the nurse dashboard on the right and enter these
          vital signs:
        </p>
        <dl className="mt-2 grid grid-cols-2 gap-2">
          {SHOCK_VITALS.map((v) => (
            <div key={v.label} className="rounded-lg bg-surface-lowest ring-1 ring-line px-2.5 py-2">
              <dt className="text-[12px] text-text-muted">{v.label}</dt>
              <dd className="text-[17px] font-semibold tabular-nums text-ink">{v.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2">
          The safety rules raise the score to ESI 2 or more urgent, even if the model guessed lower,
          and the screen lists the reasons.
        </p>
      </li>
      <li className="border-t border-line pt-4 text-[13px]">
        The nurse dashboard is signed in as {DEMO_SIGN_IN.name} (PIN {DEMO_SIGN_IN.pin}). Everything
        here happens in your private demo hospital, <span className="font-mono text-ink">{hospitalId}</span>.
      </li>
    </ol>
  );
}

function Step({ n, title }: { n: number; title: string }) {
  return (
    <p className="flex items-center gap-2 text-[15px] font-semibold text-ink">
      <span className="h-6 w-6 shrink-0 rounded-full bg-primary text-white text-[13px] flex items-center justify-center tabular-nums">
        {n}
      </span>
      {title}
    </p>
  );
}

function PaneLabel({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: typeof Smartphone;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="shrink-0 flex items-center gap-2 px-4 py-2 bg-surface-lowest border-b border-line">
      <Icon size={15} className="text-primary shrink-0" aria-hidden />
      <span className="text-[14px] font-semibold text-ink">{title}</span>
      <span className="text-[13px] text-text-muted truncate">{subtitle}</span>
    </div>
  );
}

function PresetButton({
  label,
  icon: Icon,
  onClick,
  text,
}: {
  label: string;
  icon?: typeof PanelLeft;
  onClick: () => void;
  text?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="inline-flex items-center justify-center gap-1 h-8 px-2 rounded text-[12px] font-semibold text-text-muted hover:text-ink hover:bg-surface-lowest focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
    >
      {Icon ? <Icon size={14} aria-hidden /> : null}
      {text ? <span>{text}</span> : null}
    </button>
  );
}
