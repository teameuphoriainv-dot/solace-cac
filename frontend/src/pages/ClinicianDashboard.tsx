import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { motion } from "framer-motion";
import {
  X,
  ShieldCheck,
  Activity,
  Clock3,
  Bell,
  AlertCircle,
  HelpCircle,
  QrCode,
  RotateCcw,
  Loader2,
  LogOut,
} from "lucide-react";
import { PainAlarm } from "../components/clinician/PainAlarm";
import { StudioBoard } from "../components/clinician/StudioBoard";
import { AiStatusPill } from "../components/workspace/AiStatus";
import { TourOverlay } from "../components/tour/TourOverlay";
import { Button } from "../components/ui/Button";
import { usePollingPatients } from "../hooks/usePollingPatients";
import { useTour } from "../hooks/useTour";
import { apiErrorMessage, loginClinician, resetDemo } from "../lib/api";
import { getRuntimeConfig } from "../lib/runtime-config";
import { getSandboxId, isDemoHospital } from "../lib/sandbox";
import { CLINICIAN_DASHBOARD_TOUR } from "../lib/tours";
import {
  bumpActivity,
  clearSession,
  isIdleExpired,
  loadSessionFor,
  onSessionExpired,
  roleLabel,
  saveSession,
  signedInElsewhere,
  type Session,
} from "../lib/session";

const DEMO_CLINICIANS = ["Dr. Chen", "Dr. Patel", "Dr. Kim"];

function initialsOf(name: string): string {
  return name
    .replace(/^Dr\.\s*/i, "")
    .split(" ")
    .map((s) => s[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function ClinicianDashboard() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const navigate = useNavigate();
  const { state: locationState } = useLocation();
  const [searchParams] = useSearchParams();
  // ?embed=1 drops the sidebar for tight frames such as the /showcase pane.
  const embed = searchParams.get("embed") === "1";
  const openPatient = (id: string) =>
    navigate(`/${hospitalId}/clinician/patient/${id}${embed ? "?embed=1" : ""}`);
  // Read synchronously so a signed-in nurse never sees the sign-in form flash.
  const [session, setSession] = useState<Session | null>(() => loadSessionFor(hospitalId));
  const [loginName, setLoginName] = useState(DEMO_CLINICIANS[0]);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  // Signed in, but for another demo hospital (for example the shared one).
  const [elsewhere] = useState(() => signedInElsewhere(hospitalId));
  const [pinChecking, setPinChecking] = useState(false);
  const isDemo = isDemoHospital(hospitalId);
  const [statusFilter, setStatusFilter] = useState<"waiting" | "all">("waiting");
  const [showQr, setShowQr] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [flash, setFlash] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const authenticated = !!session?.token;
  // Names of patients who checked in since the last poll, for a short banner.
  const [newArrivals, setNewArrivals] = useState<string[]>([]);
  const seenIdsRef = useRef<Set<string>>(new Set());

  const tour = useTour(CLINICIAN_DASHBOARD_TOUR, session?.clinician_id || "clinician");

  useEffect(() => {
    document.title = "Nurse dashboard: Solace";
  }, []);

  // Idle timeout + activity listener. Checks every 60s.
  useEffect(() => {
    if (!session) return;
    const onActivity = () => bumpActivity();
    ["mousemove", "keydown", "click", "touchstart"].forEach((evt) =>
      window.addEventListener(evt, onActivity, { passive: true })
    );
    bumpActivity();
    const timer = window.setInterval(() => {
      if (isIdleExpired()) {
        clearSession();
        setSession(null);
        setPinError("Signed out after 15 minutes without activity.");
      }
    }, 60_000);
    return () => {
      clearInterval(timer);
      ["mousemove", "keydown", "click", "touchstart"].forEach((evt) =>
        window.removeEventListener(evt, onActivity)
      );
    };
  }, [session]);

  // Polling every 4 seconds keeps the queue live without a manual refresh.
  const { patients, loading, error, refetch } = usePollingPatients(hospitalId, authenticated, 4_000, statusFilter);

  // Brand-new arrivals between polls show a short banner.
  useEffect(() => {
    if (!patients.length) return;
    const seen = seenIdsRef.current;
    // First load: remember everyone without announcing them.
    if (seen.size === 0) {
      patients.forEach((p) => seen.add(p.patient_id));
      return;
    }
    const fresh = patients.filter((p) => !seen.has(p.patient_id));
    if (fresh.length) {
      fresh.forEach((p) => seen.add(p.patient_id));
      setNewArrivals(fresh.map((p) => p.name || p.patient_id.slice(0, 8)));
      const t = window.setTimeout(() => setNewArrivals([]), 8000);
      return () => window.clearTimeout(t);
    }
  }, [patients]);

  // Token expired or revoked: back to the sign-in form. The api layer already
  // cleared storage, so this only resets local state.
  useEffect(() => {
    return onSessionExpired((reason) => {
      setSession(null);
      setPinError(reason);
    });
  }, []);

  // Arriving from a chart page that hit a 401: the reason rides in router state.
  useEffect(() => {
    const reason = (locationState as { authReason?: string } | null)?.authReason;
    if (reason) setPinError(reason);
  }, [locationState]);

  useEffect(() => {
    if (!flash) return;
    const t = window.setTimeout(() => setFlash(null), 6000);
    return () => window.clearTimeout(t);
  }, [flash]);

  async function submitLogin() {
    if (pinChecking || pinInput.length < 4) return;
    setPinError(null);
    setPinChecking(true);
    try {
      const resp = await loginClinician(hospitalId, loginName, pinInput);
      saveSession(resp);
      setSession(resp);
      setPinInput("");
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setPinError(status === 401 ? "Incorrect name or PIN." : apiErrorMessage(e, "Could not sign in. Please try again."));
      setPinInput("");
    } finally {
      setPinChecking(false);
    }
  }

  function signOut() {
    clearSession();
    setSession(null);
  }

  async function doReset() {
    if (!authenticated || resetting) return;
    if (!window.confirm("Reset the demo? This removes walk-in patients and restores the 5 example patients.")) return;
    setResetting(true);
    try {
      const r = await resetDemo(hospitalId);
      seenIdsRef.current = new Set();
      setNewArrivals([]);
      await refetch();
      const failed = (r?.failed_patients?.length ?? 0) > 0;
      const base =
        (typeof r?.message === "string" && r.message.trim()) ||
        "Demo reset. Walk-in patients were removed and the example patients are back.";
      setFlash({
        tone: failed || r?.restored_patients === 0 ? "error" : "ok",
        text: failed ? `${base} Some check-ins could not be removed. Try the reset again.` : base,
      });
    } catch (e: unknown) {
      setFlash({ tone: "error", text: apiErrorMessage(e, "Could not reset the demo. Please try again.") });
    } finally {
      setResetting(false);
    }
  }

  // Summary numbers for the stat strip, recomputed on every poll. This must stay
  // above the `if (!session)` return so the hook order never changes.
  const statBar = useMemo(() => {
    const waiting = patients.filter((p) => p.status === "waiting");
    const activeAlarms = patients.filter(
      (p) =>
        p.pain_flagged &&
        p.pain_flagged_at &&
        (!p.pain_flag_acknowledged_at ||
          (p.pain_flag_acknowledged_at as string) < (p.pain_flagged_at as string))
    );
    const refined = patients.filter((p) => p.refined_esi_level != null);
    const avgWaitMinutes =
      waiting.length === 0
        ? 0
        : Math.round(
            waiting.reduce((s, p) => s + (p.waited_minutes || 0), 0) / waiting.length
          );
    return {
      waiting: waiting.length,
      alarms: activeAlarms.length,
      refinedPct: patients.length === 0 ? 0 : Math.round((refined.length / patients.length) * 100),
      avgWaitMinutes,
    };
  }, [patients]);

  if (!session) {
    return (
      <div
        className="min-h-screen flex items-center justify-center p-4"
        style={{
          background:
            "radial-gradient(800px 500px at 30% -10%, rgba(203,227,233,0.35) 0%, transparent 55%), " +
            "radial-gradient(600px 400px at 100% 110%, rgba(64,99,114,0.15) 0%, transparent 55%), " +
            "#F3F4F4",
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
          className="w-full max-w-sm bg-surface-lowest rounded-xl shadow-card p-7 flex flex-col gap-5"
        >
          <div>
            <img src="/solace-logo.png" alt="Solace" className="h-9 w-auto mb-3 select-none" draggable={false} />
            <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold mb-1">
              Nurse dashboard
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
            <p className="text-[13px] text-text-muted mt-1.5 leading-snug">
              Pick a demo care team member and enter their PIN. Every patient in this demo is fictional.
            </p>
          </div>

          {elsewhere && (
            <p className="-mt-2 rounded-md bg-surface-low ring-1 ring-line px-3 py-2 text-[13px] text-ink leading-snug" role="status">
              You are signed in to a different demo hospital. Sign in again to see this one.
            </p>
          )}
          {isDemo ? (
            <>
              <label className="flex flex-col gap-1.5 text-[12px] text-text-muted font-semibold uppercase tracking-wider">
                Name
                <select
                  value={loginName}
                  onChange={(e) => setLoginName(e.target.value)}
                  className="h-11 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-sm font-medium text-ink outline-none transition-all"
                >
                  {DEMO_CLINICIANS.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-[12px] text-text-muted font-semibold uppercase tracking-wider">
                PIN
                <input
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  value={pinInput}
                  onChange={(e) => {
                    setPinInput(e.target.value);
                    if (pinError) setPinError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitLogin();
                  }}
                  placeholder="••••••"
                  aria-invalid={!!pinError}
                  className={`h-11 px-4 rounded-md bg-surface-low ring-1 focus:ring-2 text-base font-mono tracking-[0.2em] outline-none transition-all ${
                    pinError ? "ring-error focus:ring-error" : "ring-line focus:ring-primary"
                  }`}
                />
              </label>
              {pinError && (
                <div className="-mt-2 text-sm text-error font-medium" role="alert">{pinError}</div>
              )}
              <div className="-mt-1 rounded-md bg-surface-low ring-1 ring-line px-3 py-2 text-[12px] text-text-muted leading-relaxed">
                <span className="font-semibold text-ink">Demo PINs</span>: Dr. Chen 224466 ·
                Dr. Patel 113355 · Dr. Kim 667788
              </div>
              <Button
                variant="primary"
                fullWidth
                disabled={pinInput.length < 4 || pinChecking}
                onClick={submitLogin}
              >
                {pinChecking ? "Signing in…" : "Sign in"}
              </Button>
            </>
          ) : (
            <p className="text-sm text-ink">
              Sign-in is only set up for the demo hospital.{" "}
              <a href={`/${getSandboxId()}/clinician`} className="font-semibold text-primary underline">
                Open the demo dashboard
              </a>
              .
            </p>
          )}
          <p className="text-[12px] text-text-muted text-center leading-relaxed">
            You are signed out after 15 minutes without activity, or 30 minutes in total.
          </p>
        </motion.div>
      </div>
    );
  }

  const intakeUrl = `${getRuntimeConfig().publicUrl || window.location.origin}/${hospitalId}`;
  const waitingCount = patients.filter((p) => p.status === "waiting").length;

  const filterToggle = (
    <div role="group" aria-label="Which patients to show" className="inline-flex rounded-lg bg-surface-low p-0.5 ring-1 ring-line/60">
      {(["waiting", "all"] as const).map((f) => {
        const active = statusFilter === f;
        return (
          <button
            key={f}
            type="button"
            aria-pressed={active}
            onClick={() => setStatusFilter(f)}
            className={`h-8 px-3 rounded-md text-[13px] font-semibold transition-colors ${
              active ? "bg-surface-lowest text-primary shadow-soft" : "text-text-muted hover:text-ink"
            }`}
          >
            {f === "waiting" ? "Waiting" : "All"}
            {active && (
              <span className="ml-1.5 text-[12px] text-text-muted font-semibold">
                {f === "waiting" ? waitingCount : patients.length}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );

  const tourButton = (
    <button
      type="button"
      onClick={tour.start}
      data-tour="tour-launcher"
      className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-[13px] font-semibold text-text-muted hover:text-primary hover:bg-surface-lowest transition-colors"
    >
      <HelpCircle size={15} aria-hidden="true" /> Take the tour
    </button>
  );

  const resetButton = isDemo ? (
    <button
      type="button"
      onClick={doReset}
      disabled={resetting}
      className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-[13px] font-semibold text-text-muted hover:text-error transition-colors disabled:opacity-60"
      title="Removes walk-in patients and restores the 5 example patients"
    >
      {resetting ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <RotateCcw size={14} aria-hidden="true" />}
      Reset demo
    </button>
  ) : null;

  return (
    <div className={embed ? "min-h-full" : "min-h-full lg:grid lg:grid-cols-[268px_minmax(0,1fr)]"}>
      {!embed && (
        <aside className="hidden lg:flex bg-surface-low p-6 flex-col gap-5 min-h-screen border-r border-line/70">
          <div>
            <img
              src="/solace-logo.png"
              alt="Solace"
              className="h-16 w-auto max-w-full select-none"
              draggable={false}
            />
            <p className="text-[12px] text-text-muted uppercase tracking-wider font-semibold mt-2">
              Nurse dashboard
            </p>
          </div>

          <div className="flex flex-col gap-2.5 bg-surface-lowest rounded-lg p-3 shadow-soft">
            <div className="flex items-center gap-2.5">
              <div
                className="w-9 h-9 rounded-full bg-primary text-white flex items-center justify-center font-semibold text-sm shrink-0"
                aria-hidden
              >
                {initialsOf(session.name)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold truncate">{session.name}</div>
                <div className="text-[12px] text-text-muted">{roleLabel(session.role)}</div>
              </div>
            </div>
            <button
              type="button"
              onClick={signOut}
              className="self-start inline-flex items-center gap-1.5 text-[12px] text-text-muted hover:text-error font-semibold transition-colors"
            >
              <LogOut size={13} aria-hidden="true" /> Sign out
            </button>
          </div>

          <div>
            <AiStatusPill hospitalId={hospitalId} />
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold px-1">
              Show
            </div>
            {filterToggle}
          </div>

          <div className="flex flex-col items-start gap-1">
            {tourButton}
            {resetButton}
          </div>

          <div className="mt-auto flex flex-col items-center gap-2 bg-surface-lowest rounded-lg p-4 shadow-soft" data-tour="checkin-qr">
            <QRCodeSVG value={intakeUrl} size={160} bgColor="#FFFFFF" fgColor="#2A474E" />
            <p className="text-xs text-text-muted text-center tracking-wide">Patients scan to check in</p>
          </div>
        </aside>
      )}

      <div className="min-w-0 bg-surface-lowest">
        {/* Compact top bar for phones, tablets and the /showcase pane */}
        <header className={`${embed ? "" : "lg:hidden"} border-b border-line/70 bg-surface-low px-4 py-3 flex flex-col gap-2.5`}>
          <div className="flex items-center gap-2.5 min-[400px]:gap-3">
            <img src="/solace-logo.png" alt="Solace" className="h-7 min-[400px]:h-8 w-auto shrink-0 select-none" draggable={false} />
            <span className="text-[12px] text-text-muted uppercase tracking-wide font-semibold whitespace-nowrap">
              Nurse dashboard
            </span>
            <div className="ml-auto flex items-center gap-1.5 min-w-0">
              <div className="min-w-0 text-right">
                <div className="text-[13px] font-semibold truncate">{session.name}</div>
                {/* The role is in the sidebar on wide screens; on narrow phones there is no room. */}
                <div className="hidden min-[400px]:block text-[12px] text-text-muted whitespace-nowrap">
                  {roleLabel(session.role)}
                </div>
              </div>
              <button
                type="button"
                onClick={signOut}
                aria-label="Sign out"
                className="h-8 w-8 shrink-0 rounded-md flex items-center justify-center text-text-muted hover:text-error hover:bg-surface-lowest transition-colors"
              >
                <LogOut size={16} aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {filterToggle}
            <AiStatusPill hospitalId={hospitalId} />
            <button
              type="button"
              onClick={() => setShowQr((v) => !v)}
              aria-expanded={showQr}
              data-tour="checkin-qr"
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-[13px] font-semibold text-text-muted hover:text-primary hover:bg-surface-lowest transition-colors"
            >
              <QrCode size={15} aria-hidden="true" /> Check-in code
            </button>
            {tourButton}
            {resetButton}
          </div>
          {showQr && (
            <div className="flex items-center gap-4 rounded-lg bg-surface-lowest p-3 shadow-soft">
              <QRCodeSVG value={intakeUrl} size={120} bgColor="#FFFFFF" fgColor="#2A474E" className="shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">Patients scan this to check in</p>
                <p className="mt-1 text-[12px] text-text-muted break-all">{intakeUrl}</p>
              </div>
            </div>
          )}
        </header>

        <main className="p-4 sm:p-6 lg:p-10 relative">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 mb-6 sm:mb-8" data-tour="stat-strip">
            <StatTile icon={Activity} label="Waiting" value={statBar.waiting} tone="primary" />
            <StatTile
              icon={Bell}
              label="Feel-worse alerts"
              value={statBar.alarms}
              tone={statBar.alarms > 0 ? "error" : "muted"}
            />
            <StatTile icon={Clock3} label="Average wait" value={formatWaitShort(statBar.avgWaitMinutes)} tone="muted" />
            <StatTile icon={ShieldCheck} label="Vitals re-checked" value={`${statBar.refinedPct}%`} tone="muted" />
          </div>

          {flash && (
            <div
              role="status"
              className={`mb-4 flex items-start gap-2.5 p-3 rounded-md text-sm font-medium ${
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

          <PainAlarm
            hospitalId={hospitalId}
            patients={patients}
            onOpenPatient={openPatient}
            onAfterAck={refetch}
          />
          {newArrivals.length > 0 && (
            <div
              role="status"
              className="mb-4 flex items-center gap-3 px-4 py-3 rounded-lg bg-primary text-white shadow-card"
            >
              <span className="h-6 w-6 rounded-full bg-white/15 flex items-center justify-center shrink-0">
                <Bell size={13} aria-hidden />
              </span>
              <span className="hidden sm:inline text-[12px] uppercase tracking-[0.14em] font-bold shrink-0">
                New arrival
              </span>
              <span className="text-sm font-medium truncate">
                {newArrivals.length === 1
                  ? `${newArrivals[0]} just checked in.`
                  : `${newArrivals.length} patients just checked in: ${newArrivals.join(", ")}.`}
              </span>
              <button
                type="button"
                onClick={() => setNewArrivals([])}
                aria-label="Dismiss new arrival notice"
                className="ml-auto h-7 w-7 rounded-md flex items-center justify-center text-white/70 hover:text-white hover:bg-white/10 transition-colors shrink-0"
              >
                <X size={15} aria-hidden />
              </button>
            </div>
          )}
          {error && (
            <div className="mb-4 flex items-start gap-2.5 p-3 rounded-md bg-error-container text-error text-sm" role="alert">
              <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden />
              <span className="font-medium">{error}</span>
            </div>
          )}
          <StudioBoard
            hospitalId={hospitalId}
            patients={patients}
            loading={loading}
            authenticated={authenticated}
            clinicianId={session.clinician_id}
            onOpenPatient={openPatient}
          />
        </main>
      </div>

      <TourOverlay
        active={tour.active}
        step={tour.step}
        rect={tour.rect}
        stepIndex={tour.stepIndex}
        stepCount={tour.stepCount}
        onNext={tour.next}
        onPrev={tour.prev}
        onClose={tour.finish}
      />
    </div>
  );
}

/** Compact wait for the stat strip: 100 becomes "1h 40m", 45 becomes "45m". */
function formatWaitShort(mins: number): string {
  if (!mins || mins <= 0) return "-";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function StatTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Activity;
  label: string;
  value: string | number;
  tone: "primary" | "muted" | "error";
}) {
  const toneClasses = {
    primary: "text-primary bg-primary-fixed",
    muted: "text-text-muted bg-surface-low",
    error: "text-error bg-error-container",
  }[tone];
  return (
    <div className="bg-surface-lowest rounded-xl p-3 sm:p-4 ring-1 ring-line/45 flex items-center gap-3 min-w-0">
      <div className={`h-9 w-9 sm:h-10 sm:w-10 rounded-xl flex items-center justify-center shrink-0 ${toneClasses}`}>
        <Icon size={18} aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold leading-tight">
          {label}
        </div>
        <div className="text-xl sm:text-2xl font-bold tracking-tight text-ink leading-none mt-1">
          {value}
        </div>
      </div>
    </div>
  );
}
