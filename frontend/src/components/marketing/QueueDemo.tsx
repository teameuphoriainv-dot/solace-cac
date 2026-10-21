import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useInView, useReducedMotion } from "framer-motion";
import { Loader2, Pause, Play } from "lucide-react";
import { EsiChip } from "./EsiChip";

type Row = { id: string; esi: number; text: string; waited: string; tag?: string };

// Made-up patients. The arrivals are the same phrases the triage tests pin.
const WAITING: Row[] = [
  { id: "w1", esi: 3, text: "Fever and cough for three days", waited: "26 min" },
  { id: "w2", esi: 4, text: "Cut on my hand, the bleeding has stopped", waited: "41 min" },
  { id: "w3", esi: 4, text: "Twisted my ankle, it's swollen", waited: "18 min" },
  { id: "w4", esi: 5, text: "Need a refill of my blood pressure pills", waited: "52 min" },
];

const ARRIVALS: Row[] = [
  { id: "a1", esi: 2, text: "Crushing chest pain down my left arm and I'm sweating", waited: "now" },
  { id: "a2", esi: 2, text: "My 3 year old has a fever of 104 and is very sleepy", waited: "now" },
  { id: "a3", esi: 2, text: "Me duele mucho el pecho y no puedo respirar", waited: "now", tag: "Spanish" },
];

type Phase = "arriving" | "scored" | "sorted";

// How long each phase lasts before the next one starts.
const HOLD: Record<Phase, number> = { arriving: 1500, scored: 900, sorted: 4600 };

/**
 * The hero picture: a waiting-room queue that re-sorts itself when a new check-in
 * is scored. Runs only while on screen, can be paused, and holds still for people
 * who ask for reduced motion.
 */
export function QueueDemo() {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-40px" });
  const [paused, setPaused] = useState(false);
  const [cycle, setCycle] = useState(0);
  const [phase, setPhase] = useState<Phase>(reduced ? "sorted" : "arriving");

  const running = !reduced && inView && !paused;

  useEffect(() => {
    if (!running) return;
    const t = window.setTimeout(() => {
      if (phase === "arriving") setPhase("scored");
      else if (phase === "scored") setPhase("sorted");
      else {
        setCycle((c) => c + 1);
        setPhase("arriving");
      }
    }, HOLD[phase]);
    return () => window.clearTimeout(t);
  }, [running, phase]);

  const arrival = ARRIVALS[cycle % ARRIVALS.length];
  const rows = useMemo(() => {
    if (phase !== "sorted") return [...WAITING, arrival];
    return [arrival, ...WAITING].sort((a, b) => a.esi - b.esi);
  }, [arrival, phase]);

  const summary = `Example: a patient types "${arrival.text}". Solace scores it ESI ${arrival.esi} and moves them to the top of the waiting list.`;

  return (
    <div ref={ref} className="w-full">
      <div className="rounded-2xl bg-surface-lowest ring-1 ring-line shadow-lifted overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-3 border-b border-line">
          <div className="min-w-0">
            <p className="text-[15px] font-semibold text-ink">Waiting room</p>
            <p className="text-[13px] text-text-muted">Sorted by urgency, most urgent first</p>
          </div>
          {!reduced && (
            <button
              type="button"
              onClick={() => setPaused((p) => !p)}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[13px] font-medium text-text-muted hover:text-ink hover:bg-surface-low focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              aria-pressed={paused}
            >
              {paused ? <Play size={14} aria-hidden /> : <Pause size={14} aria-hidden />}
              {paused ? "Play" : "Pause"}
            </button>
          )}
        </div>

        <p className="sr-only">{summary}</p>
        <ol className="px-3 py-3 flex flex-col gap-1.5" aria-hidden="true">
          <AnimatePresence initial={false}>
            {rows.map((r) => {
              const isNew = r.id === arrival.id;
              const scored = !isNew || phase !== "arriving";
              return (
                <motion.li
                  key={r.id}
                  layout={!reduced}
                  initial={reduced ? false : { opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduced ? undefined : { opacity: 0, transition: { duration: 0.2 } }}
                  transition={{ type: "spring", stiffness: 260, damping: 30 }}
                  className={`flex items-start gap-3 rounded-xl px-3 py-2.5 ${
                    isNew ? "bg-primary-dim ring-1 ring-primary/20" : ""
                  }`}
                >
                  <span className="w-[58px] shrink-0 pt-px">
                    {scored ? (
                      <EsiChip level={r.esi} />
                    ) : (
                      <span className="inline-flex items-center justify-center h-7 w-[52px] rounded-md bg-surface-high text-text-muted">
                        <Loader2 size={14} className="animate-spin" />
                      </span>
                    )}
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[14px] leading-snug text-ink">{r.text}</span>
                    {isNew && (
                      <span className="block mt-0.5 text-[12px] text-primary font-medium">
                        {phase === "arriving"
                          ? "Just checked in, scoring now"
                          : `Just checked in${r.tag ? ` in ${r.tag}` : ""}`}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 pt-1 text-[12px] tabular-nums text-text-muted">{r.waited}</span>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      </div>
      <p className="mt-3 text-[13px] text-text-muted">
        Made-up patients. ESI 1 is the most urgent and ESI 5 is the least urgent.
      </p>
    </div>
  );
}
