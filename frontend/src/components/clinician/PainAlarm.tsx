import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, ArrowRight, BellOff, Loader2, VolumeX, Volume2 } from "lucide-react";
import { acknowledgePainFlag, apiErrorMessage } from "../../lib/api";
import type { AudioContextWindow, PatientSummary } from "../../types";

type Props = {
  hospitalId: string;
  patients: PatientSummary[];
  onOpenPatient: (patientId: string) => void;
  onAfterAck?: () => void;        // refetch hook so the row updates immediately
};

/**
 * An alert is active when the patient pressed "I feel worse" and no one has
 * acknowledged it since. The same patient can raise it again later; the server
 * resets the acknowledgement on every new press.
 */
function isActive(p: PatientSummary): boolean {
  if (!p.pain_flagged || !p.pain_flagged_at) return false;
  if (!p.pain_flag_acknowledged_at) return true;
  return p.pain_flag_acknowledged_at < p.pain_flagged_at;
}

export function PainAlarm({ hospitalId, patients, onOpenPatient, onAfterAck }: Props) {
  const active = useMemo(() => patients.filter(isActive), [patients]);
  const [muted, setMuted] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem("solace.alarm.muted") === "1";
    } catch {
      return false;
    }
  });
  const [pendingAck, setPendingAck] = useState<Record<string, boolean>>({});
  const [ackError, setAckError] = useState<string | null>(null);

  // Remember mute so a page refresh does not suddenly start beeping.
  useEffect(() => {
    try {
      sessionStorage.setItem("solace.alarm.muted", muted ? "1" : "0");
    } catch {
      /* storage blocked: mute just lasts for this page */
    }
  }, [muted]);

  // ---- audio --------------------------------------------------------------
  // WebAudio gives us a controlled tone with no asset to ship + works offline.
  // The beep loop only runs while at least one alarm is active.
  const ctxRef = useRef<AudioContext | null>(null);
  const oscRef = useRef<OscillatorNode | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  // Own ref for the pulse timer. This used to be parked on the GainNode behind
  // an `as any` cast, which hid it from the type system for no benefit.
  const beepIntervalRef = useRef<number | null>(null);
  const userPrimedRef = useRef<boolean>(false);

  // Mark the audio context as primed after any user gesture — autoplay rules
  // require this to start tones at all.
  useEffect(() => {
    const prime = () => {
      userPrimedRef.current = true;
      window.removeEventListener("click", prime);
      window.removeEventListener("keydown", prime);
    };
    window.addEventListener("click", prime, { passive: true });
    window.addEventListener("keydown", prime);
    return () => {
      window.removeEventListener("click", prime);
      window.removeEventListener("keydown", prime);
    };
  }, []);

  useEffect(() => {
    const shouldBeep = active.length > 0 && !muted;
    if (!shouldBeep) {
      stopBeep();
      return;
    }
    if (!userPrimedRef.current) {
      // Browser will reject playback until the clinician interacts with the
      // page once. The banner is still visible, so they'll see it.
      return;
    }
    startBeep();
    return stopBeep;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.length, muted]);

  function startBeep() {
    if (oscRef.current) return; // already running
    try {
      const ctx = ctxRef.current ?? new (window.AudioContext ?? (window as AudioContextWindow).webkitAudioContext!)();
      ctxRef.current = ctx;
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      // Two-tone alarm — A5 + E5 alternation, gated so it pulses ~2x/sec.
      osc.type = "sine";
      osc.frequency.value = 880;
      gain.gain.value = 0;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      oscRef.current = osc;
      gainRef.current = gain;

      let on = false;
      const intervalId = window.setInterval(() => {
        if (!gainRef.current || !oscRef.current || !ctxRef.current) return;
        on = !on;
        oscRef.current.frequency.setValueAtTime(on ? 880 : 660, ctxRef.current.currentTime);
        // ramp to avoid clicks
        gainRef.current.gain.cancelScheduledValues(ctxRef.current.currentTime);
        gainRef.current.gain.linearRampToValueAtTime(
          on ? 0.18 : 0,
          ctxRef.current.currentTime + 0.04
        );
      }, 320);
      beepIntervalRef.current = intervalId;
    } catch (e) {
      console.warn("alarm beep failed to start", e);
    }
  }

  function stopBeep() {
    try {
      if (beepIntervalRef.current !== null) {
        window.clearInterval(beepIntervalRef.current);
        beepIntervalRef.current = null;
      }
      if (oscRef.current) {
        oscRef.current.stop();
        oscRef.current.disconnect();
      }
      if (gainRef.current) gainRef.current.disconnect();
    } catch {
      /* noop */
    }
    oscRef.current = null;
    gainRef.current = null;
  }

  async function handleAcknowledge(patientId: string) {
    setPendingAck((prev) => ({ ...prev, [patientId]: true }));
    setAckError(null);
    try {
      await acknowledgePainFlag(hospitalId, patientId);
      onAfterAck?.();
    } catch (e) {
      setAckError(apiErrorMessage(e, "Could not mark the alert as seen. Please try again."));
    } finally {
      setPendingAck((prev) => {
        const next = { ...prev };
        delete next[patientId];
        return next;
      });
    }
  }

  if (active.length === 0) return null;

  return (
    <AnimatePresence>
      <motion.div
        key="pain-alarm"
        initial={{ y: -32, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: -32, opacity: 0 }}
        transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
        className="sticky top-0 z-40 mb-4"
      >
        <div className="rounded-lg bg-error text-white shadow-lifted overflow-hidden ring-2 ring-error/60 motion-safe:animate-pulse">
          <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
            <div className="h-9 w-9 rounded-full bg-white/20 flex items-center justify-center shrink-0">
              <AlertTriangle size={18} aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0" role="alert">
              <div className="text-[12px] uppercase tracking-[0.18em] font-bold">
                Feel-worse alert
              </div>
              <div className="text-sm font-semibold tracking-editorial">
                {active.length === 1
                  ? `${active[0].name || active[0].patient_id.slice(0, 8)} says they feel worse. Check on them now.`
                  : `${active.length} patients say they feel worse. Check on them now.`}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setMuted((m) => !m)}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-white/15 hover:bg-white/25 text-xs font-medium transition-colors"
              title={muted ? "Unmute alarm sound" : "Mute alarm sound"}
            >
              {muted ? <VolumeX size={14} aria-hidden="true" /> : <Volume2 size={14} aria-hidden="true" />}
              {muted ? "Sound off" : "Mute"}
            </button>
          </div>
          <div className="bg-white/[0.07] border-t border-white/15">
            {active.map((p) => {
              const minutesAgo = p.pain_flagged_at
                ? Math.max(0, Math.floor((Date.now() - new Date(p.pain_flagged_at).getTime()) / 60000))
                : 0;
              const isPending = !!pendingAck[p.patient_id];
              return (
                <div
                  key={p.patient_id}
                  className="flex items-center gap-3 px-4 py-2.5 border-t border-white/10 first:border-t-0"
                >
                  <button
                    type="button"
                    onClick={() => onOpenPatient(p.patient_id)}
                    className="flex-1 text-left flex items-center gap-3 min-w-0 hover:bg-white/10 -mx-2 px-2 py-1 rounded-md"
                  >
                    <div
                      className="h-8 w-8 rounded-full bg-white/15 flex items-center justify-center text-sm font-bold shrink-0"
                      aria-label={`Priority ${p.current_esi_level ?? p.refined_esi_level ?? p.esi_level}`}
                    >
                      {p.current_esi_level ?? p.refined_esi_level ?? p.esi_level}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold truncate">{p.name || p.patient_id.slice(0, 8)}</div>
                      <div className="text-[12px] opacity-90 sm:truncate">
                        Pressed {minutesAgo === 0 ? "just now" : `${minutesAgo} min ago`} · waiting {p.waited_minutes} min · {(p.language || "en").toUpperCase()}
                      </div>
                    </div>
                    <ArrowRight size={14} className="opacity-70 shrink-0" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleAcknowledge(p.patient_id)}
                    disabled={isPending}
                    aria-label={`I'm on it: mark the alert for ${p.name || "this patient"} as seen`}
                    className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-white text-error text-xs font-bold uppercase tracking-wider shadow-soft hover:bg-white/90 disabled:opacity-60"
                  >
                    {isPending ? (
                      <Loader2 size={13} className="animate-spin" aria-hidden="true" />
                    ) : (
                      <BellOff size={13} aria-hidden="true" />
                    )}
                    <span className="whitespace-nowrap">I'm on it</span>
                  </button>
                </div>
              );
            })}
          </div>
          {ackError && (
            <div className="px-4 py-2 border-t border-white/15 text-sm font-medium" role="alert">
              {ackError}
            </div>
          )}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
