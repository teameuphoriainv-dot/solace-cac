import { Component, lazy, Suspense, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Activity,
  BookOpen,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Link2,
  Loader2,
  Mic,
  Pin,
  PinOff,
  Plus,
  Search,
  Sparkles,
  TrendingUp,
  Users2,
  X,
} from "lucide-react";
import { PatientWorkspaceProvider } from "../workspace/PatientWorkspaceContext";
import { ESIBadge } from "../patient/ESIBadge";
import type { PatientSummary } from "../../types";
import { useSidePaths } from "../../lib/paths";

// The dashboard board: the live queue plus cards for one patient at a time.
//
// The nurse pins patients (from the queue or the search box) and picks which
// cards to show: add, remove, fold, or drag to reorder. Every card is the same
// tab component the full patient page uses, fed by one PatientWorkspaceProvider,
// so nothing is written twice. The card layout is saved per clinician in
// localStorage; the pinned patients last for the browser tab (sessionStorage).

type LazyTab = React.LazyExoticComponent<() => React.JSX.Element>;

const OverviewTab = lazy(() => import("../workspace/tabs/OverviewTab"));
const ScribeTab = lazy(() => import("../workspace/tabs/ScribeTab"));
const ReasoningTab = lazy(() => import("../workspace/tabs/ReasoningTab"));
const EarlyWarningTab = lazy(() => import("../workspace/tabs/EarlyWarningTab"));

type Feature = {
  id: string;
  label: string;
  icon: typeof Mic;
  kind: "queue" | "tab";
  Component?: LazyTab;
};

const FEATURES: Feature[] = [
  { id: "queue", label: "Queue", icon: Users2, kind: "queue" },
  { id: "overview", label: "Patient summary", icon: Activity, kind: "tab", Component: OverviewTab },
  { id: "early-warning", label: "Early warning", icon: TrendingUp, kind: "tab", Component: EarlyWarningTab },
  { id: "scribe", label: "Scribe", icon: Mic, kind: "tab", Component: ScribeTab },
  { id: "reasoning", label: "Reasoning", icon: BookOpen, kind: "tab", Component: ReasoningTab },
];
const FEATURE_MAP: Record<string, Feature> = Object.fromEntries(FEATURES.map((f) => [f.id, f]));
const DEFAULT_CARDS = ["queue", "overview", "early-warning", "scribe"];

const storageKey = (clinicianId: string) => `solace-board-${clinicianId}`;
const pinsKey = (clinicianId: string) => `solace-board-pins-${clinicianId}`;

type Board = { cards: string[]; collapsed: Record<string, boolean> };

const validCards = (arr: unknown[]): string[] =>
  arr.filter((id): id is string => typeof id === "string" && !!FEATURE_MAP[id]);

// Loads the saved card layout. Unknown card ids are dropped, and any problem
// (corrupt or blocked storage) falls back to the default board.
function loadBoard(clinicianId: string): Board {
  try {
    const raw = localStorage.getItem(storageKey(clinicianId));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.cards)) {
        const cards = validCards(parsed.cards);
        const safeCards = cards.length ? cards : DEFAULT_CARDS;
        const collapsed: Record<string, boolean> = {};
        const src = parsed.collapsed;
        if (src && typeof src === "object") {
          for (const [id, v] of Object.entries(src)) {
            if (FEATURE_MAP[id] && safeCards.includes(id) && typeof v === "boolean") collapsed[id] = v;
          }
        }
        return { cards: safeCards, collapsed };
      }
    }
  } catch {
    /* ignore corrupt layout */
  }
  return { cards: DEFAULT_CARDS, collapsed: {} };
}

type Pins = { ids: string[]; active: string | null };

function loadPins(clinicianId: string): Pins {
  try {
    const raw = sessionStorage.getItem(pinsKey(clinicianId));
    if (raw) {
      const parsed = JSON.parse(raw);
      const ids = Array.isArray(parsed?.ids) ? parsed.ids.filter((x: unknown) => typeof x === "string") : [];
      const active = typeof parsed?.active === "string" && ids.includes(parsed.active) ? parsed.active : null;
      return { ids, active };
    }
  } catch {
    /* ignore */
  }
  return { ids: [], active: null };
}

/** Queue wait label: 0 → "Just arrived", 45 → "45 min wait", 103 → "1h 43m wait". */
function waitLabel(mins: number | null | undefined): string {
  if (mins == null) return "";
  if (mins <= 0) return "Just arrived";
  if (mins < 60) return `${mins} min wait`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m wait` : `${h}h wait`;
}

/** The score the queue acts on: the bedside re-check when there is one. */
function effectiveEsi(p: PatientSummary): number {
  const v = p.current_esi_level ?? p.refined_esi_level ?? p.esi_level;
  return typeof v === "number" && v >= 1 && v <= 5 ? v : 5;
}

/** Small chip after a bedside re-check: plain "Re-checked", or raised by the safety rules. */
function recheckChip(p: PatientSummary): { label: string; raised: boolean; detail: string } | null {
  if (p.refined_esi_level == null) return null;
  const reasons = Array.isArray(p.refined_safety_floor_reasons)
    ? p.refined_safety_floor_reasons.filter((r) => typeof r === "string" && r.trim())
    : [];
  const model = p.refined_model_esi_level;
  const raised =
    typeof model === "number"
      ? p.refined_esi_level < model
      : reasons.length > 0 && p.refined_esi_level < p.esi_level;
  if (raised) {
    return {
      label: "Raised by safety rules",
      raised: true,
      detail:
        (typeof model === "number" ? `The model said ${model}; the safety rules raised it to ${p.refined_esi_level}. ` : "") +
        reasons.join("; "),
    };
  }
  return {
    label: "Re-checked",
    raised: false,
    detail: `Re-checked with bedside vitals: priority ${p.refined_esi_level} (it was ${p.esi_level} at check-in).`,
  };
}

function hasActiveAlert(p: PatientSummary): boolean {
  if (!p.pain_flagged || !p.pain_flagged_at) return false;
  if (!p.pain_flag_acknowledged_at) return true;
  return p.pain_flag_acknowledged_at < p.pain_flagged_at;
}

export function StudioBoard({
  hospitalId,
  patients,
  loading,
  authenticated,
  clinicianId,
  onOpenPatient,
}: {
  hospitalId: string;
  patients: PatientSummary[];
  loading: boolean;
  authenticated: boolean;
  clinicianId: string;
  /** Opens the full chart for a patient. */
  onOpenPatient?: (patientId: string) => void;
}) {
  const [cards, setCards] = useState<string[]>(() => loadBoard(clinicianId).cards);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => loadBoard(clinicianId).collapsed);
  const [query, setQuery] = useState("");
  const [tagIds, setTagIds] = useState<string[]>(() => loadPins(clinicianId).ids);
  const [activeId, setActiveId] = useState<string | null>(() => loadPins(clinicianId).active);
  const [adding, setAdding] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);

  // One write carries both card order and folded state.
  useEffect(() => {
    try {
      localStorage.setItem(storageKey(clinicianId), JSON.stringify({ v: 2, cards, collapsed }));
    } catch {
      /* storage full or blocked: not fatal */
    }
  }, [cards, collapsed, clinicianId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(pinsKey(clinicianId), JSON.stringify({ ids: tagIds, active: activeId }));
    } catch {
      /* storage full or blocked: not fatal */
    }
  }, [tagIds, activeId, clinicianId]);

  const toggleCollapse = (id: string) => setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  function removeCard(id: string) {
    setCards((prev) => prev.filter((c) => c !== id));
    setCollapsed((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  const sorted = useMemo(
    () =>
      [...patients].sort(
        (a, b) => effectiveEsi(a) - effectiveEsi(b) || (a.created_at || "").localeCompare(b.created_at || ""),
      ),
    [patients],
  );
  const byId = useMemo(
    () => Object.fromEntries(patients.map((p) => [p.patient_id, p])) as Record<string, PatientSummary>,
    [patients],
  );
  const tagged = tagIds.map((id) => byId[id]).filter(Boolean) as PatientSummary[];
  // A pinned patient who left the list (seen, or the demo was reset) is not active.
  const liveActiveId = activeId && byId[activeId] ? activeId : null;
  const activePatient = liveActiveId ? byId[liveActiveId] : null;
  const results = query.trim()
    ? sorted.filter((p) => p.name?.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 6)
    : [];
  const available = FEATURES.filter((f) => !cards.includes(f.id));

  function pinPatient(p: PatientSummary) {
    setTagIds((prev) => (prev.includes(p.patient_id) ? prev : [...prev, p.patient_id]));
    setActiveId(p.patient_id);
    setQuery("");
  }
  function untag(id: string) {
    setTagIds((prev) => prev.filter((x) => x !== id));
    setActiveId((cur) => (cur === id ? null : cur));
  }
  function togglePin(p: PatientSummary) {
    if (tagIds.includes(p.patient_id)) untag(p.patient_id);
    else pinPatient(p);
  }
  function openPatient(p: PatientSummary) {
    // Pin too, so the cards show this patient when the nurse comes back.
    pinPatient(p);
    onOpenPatient?.(p.patient_id);
  }
  // Live reorder: when the dragged card enters another card, move it into that
  // slot right away so the board makes room under the cursor.
  function reorder(targetId: string) {
    if (!dragId || dragId === targetId) return;
    setCards((prev) => {
      if (prev.indexOf(dragId) === -1) return prev;
      const idx = prev.indexOf(targetId);
      if (idx === -1) return prev;
      const next = prev.filter((c) => c !== dragId);
      next.splice(next.indexOf(targetId), 0, dragId);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Find and pin patients */}
      <div className="card-clean rounded-2xl p-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search patients by name"
            placeholder="Find a patient by name"
            className="w-full h-11 pl-9 pr-3 rounded-xl bg-surface-low text-sm text-ink ring-1 ring-line/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 placeholder:text-text-muted/70"
          />
          {query.trim() !== "" && (
            <div className="absolute z-20 left-0 right-0 mt-1 rounded-xl bg-surface-lowest ring-1 ring-line shadow-card overflow-hidden">
              {results.length === 0 ? (
                <div className="px-3 py-2.5 text-sm text-text-muted">No patient by that name in this list.</div>
              ) : (
                results.map((p) => (
                  <div key={p.patient_id} className="flex items-center gap-2 px-2 py-1.5 hover:bg-surface-low transition-colors">
                    <button
                      type="button"
                      onClick={() => pinPatient(p)}
                      className="flex-1 min-w-0 flex items-center gap-3 px-1 py-0.5 text-left"
                    >
                      <ESIBadge esiLevel={effectiveEsi(p)} size="sm" showLabel={false} />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold truncate">{p.name}</span>
                        <span className="block text-[12px] text-text-muted">
                          {waitLabel(p.waited_minutes)} · tap to pin
                        </span>
                      </span>
                    </button>
                    {onOpenPatient && (
                      <button
                        type="button"
                        onClick={() => openPatient(p)}
                        className="shrink-0 inline-flex items-center gap-0.5 h-8 px-2 rounded-md text-[12px] font-semibold text-primary hover:bg-primary-fixed/50"
                      >
                        Chart <ChevronRight size={14} aria-hidden="true" />
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        {tagged.length > 0 && (
          <div className="mt-2.5">
            <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold mb-1.5">
              Pinned patients
            </div>
            <div className="flex flex-wrap gap-2">
              {tagged.map((p) => {
                const active = liveActiveId === p.patient_id;
                return (
                  <span
                    key={p.patient_id}
                    className={`inline-flex items-center rounded-full text-[12px] font-semibold ring-1 transition-colors ${
                      active ? "bg-primary text-white ring-primary" : "bg-surface-low text-ink ring-line/60"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setActiveId(p.patient_id)}
                      aria-pressed={active}
                      className="pl-3 pr-1.5 py-1"
                      title="Show this patient on the cards"
                    >
                      {p.name}
                    </button>
                    <button
                      type="button"
                      onClick={() => untag(p.patient_id)}
                      aria-label={`Unpin ${p.name}`}
                      className={`pr-2 pl-0.5 py-1 rounded-r-full ${active ? "hover:text-white/70" : "text-text-muted hover:text-error"}`}
                    >
                      <X size={12} aria-hidden="true" />
                    </button>
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Board header */}
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-editorial">Patient cards</h2>
          <p className="text-sm text-text-muted sm:truncate">
            {activePatient ? `Showing ${activePatient.name}` : "Pin a patient from the queue to fill these cards."}
          </p>
        </div>
        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            aria-expanded={adding}
            className="inline-flex items-center gap-1.5 h-10 px-4 rounded-full bg-primary text-white text-sm font-semibold hover:brightness-110 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
          >
            <Plus size={16} aria-hidden /> Add a card
          </button>
          {adding && (
            <div className="absolute right-0 z-20 mt-2 w-60 rounded-xl bg-surface-lowest ring-1 ring-line shadow-card overflow-hidden py-1">
              {available.length === 0 ? (
                <div className="px-3 py-2.5 text-sm text-text-muted">Every card is already on the board.</div>
              ) : (
                available.map((f) => {
                  const Icon = f.icon;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => {
                        setCards((prev) => (prev.includes(f.id) ? prev : [...prev, f.id]));
                        setAdding(false);
                      }}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm font-medium text-ink hover:bg-surface-low transition-colors"
                    >
                      <Icon size={15} className="text-primary" aria-hidden /> {f.label}
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>

      {/* One provider feeds every patient card */}
      <PatientWorkspaceProvider hospitalId={hospitalId} patientId={liveActiveId || ""} authenticated={authenticated}>
        <div className="grid grid-cols-1 xl:grid-cols-2 auto-rows-min gap-5 items-start" data-tour="patient-cards">
          {cards.map((id) => {
            const f = FEATURE_MAP[id];
            if (!f) return null;
            const Comp = f.Component;
            return (
              <FeatureCard
                key={id}
                feature={f}
                collapsed={!!collapsed[id]}
                onToggleCollapse={() => toggleCollapse(id)}
                dragging={dragId === id}
                onDragStart={() => setDragId(id)}
                onDragEnd={() => setDragId(null)}
                onDragEnter={() => reorder(id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => setDragId(null)}
                onRemove={() => removeCard(id)}
              >
                <CardErrorBoundary key={`${id}-${liveActiveId ?? "none"}`} label={f.label}>
                  {f.kind === "queue" ? (
                    <QueueCardBody
                      hospitalId={hospitalId}
                      patients={sorted}
                      loading={loading}
                      activeId={liveActiveId}
                      pinnedIds={tagIds}
                      onOpen={openPatient}
                      onTogglePin={togglePin}
                    />
                  ) : liveActiveId && Comp ? (
                    <Suspense fallback={<CardSpinner />}>
                      <Comp />
                    </Suspense>
                  ) : (
                    <CardEmpty label={f.label} />
                  )}
                </CardErrorBoundary>
              </FeatureCard>
            );
          })}
        </div>
      </PatientWorkspaceProvider>
    </div>
  );
}

function FeatureCard({
  feature,
  children,
  collapsed,
  onToggleCollapse,
  onRemove,
  onDragStart,
  onDragEnd,
  onDragEnter,
  onDragOver,
  onDrop,
  dragging,
}: {
  feature: Feature;
  children: React.ReactNode;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onRemove: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragEnter: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: () => void;
  dragging: boolean;
}) {
  const Icon = feature.icon;
  const reduce = useReducedMotion();
  return (
    <motion.section
      // layout="position" glides the card to its new slot while dragging without
      // animating its size (the body below owns the fold animation). Off under
      // reduced motion.
      layout={reduce ? false : "position"}
      transition={{ layout: { duration: reduce ? 0 : 0.22, ease: [0.4, 0, 0.2, 1] } }}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDrop={onDrop}
      aria-label={feature.label}
      className={`card-clean rounded-2xl overflow-hidden flex flex-col min-w-0 transition-[opacity,box-shadow] ${
        dragging ? "opacity-40 ring-2 ring-primary/50" : ""
      } ${collapsed ? "xl:col-span-2" : ""}`}
    >
      <header
        draggable
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        className="flex items-center gap-2 px-4 py-2.5 border-b border-line/50 bg-surface-low/40 cursor-grab active:cursor-grabbing select-none"
      >
        <GripVertical size={14} className="text-text-muted shrink-0 hidden sm:block" aria-hidden />
        <Icon size={15} className="text-primary shrink-0" aria-hidden />
        <span className="text-sm font-semibold truncate">{feature.label}</span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse();
            }}
            aria-expanded={!collapsed}
            aria-label={collapsed ? `Open ${feature.label}` : `Fold ${feature.label}`}
            className="h-7 w-7 rounded-md flex items-center justify-center text-text-muted hover:text-ink hover:bg-surface-low transition-colors"
          >
            <ChevronDown size={15} className={`transition-transform ${collapsed ? "" : "rotate-180"}`} aria-hidden />
          </button>
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove the ${feature.label} card`}
            className="h-7 w-7 rounded-md flex items-center justify-center text-text-muted hover:text-error hover:bg-surface-low transition-colors"
          >
            <X size={15} aria-hidden />
          </button>
        </div>
      </header>
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.22, ease: [0.4, 0, 0.2, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className="p-3 sm:p-4 max-h-[560px] overflow-auto">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

function QueueCardBody({
  hospitalId,
  patients,
  loading,
  activeId,
  pinnedIds,
  onOpen,
  onTogglePin,
}: {
  hospitalId: string;
  patients: PatientSummary[];
  loading: boolean;
  activeId: string | null;
  pinnedIds: string[];
  onOpen: (p: PatientSummary) => void;
  onTogglePin: (p: PatientSummary) => void;
}) {
  if (loading && !patients.length) return <CardSpinner />;
  if (!patients.length) return <QueueEmpty hospitalId={hospitalId} />;
  return (
    <div data-tour="patient-queue">
      <p className="text-[12px] text-text-muted mb-2">
        Most urgent first. Priority 1 is the most urgent, 5 the least. Tap a name to open the chart.
      </p>
      <ul className="flex flex-col gap-1.5">
        {patients.map((p) => {
          const active = activeId === p.patient_id;
          const pinned = pinnedIds.includes(p.patient_id);
          const chip = recheckChip(p);
          const alert = hasActiveAlert(p);
          const snippet = (p.clinician_prebrief || "").trim();
          return (
            <li
              key={p.patient_id}
              className={`flex items-center gap-1 rounded-xl transition-colors ${
                active ? "bg-primary-fixed/50 ring-1 ring-primary/30" : "hover:bg-surface-low"
              }`}
            >
              <button
                type="button"
                onClick={() => onOpen(p)}
                className="flex-1 min-w-0 text-left flex items-center gap-3 px-3 py-2"
                aria-label={`Open the chart for ${p.name}, priority ${effectiveEsi(p)}`}
              >
                <ESIBadge esiLevel={effectiveEsi(p)} size="sm" showLabel={false} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-sm font-semibold truncate">{p.name}</span>
                    {chip && (
                      <span
                        title={chip.detail}
                        className={`inline-flex items-center rounded-full px-1.5 py-px text-[12px] font-semibold ${
                          chip.raised ? "bg-error/10 text-error" : "bg-surface-low text-text-muted ring-1 ring-line"
                        }`}
                      >
                        {chip.label}
                      </span>
                    )}
                    {alert && (
                      <span className="inline-flex items-center rounded-full px-1.5 py-px text-[12px] font-semibold bg-error text-white">
                        Feels worse
                      </span>
                    )}
                    {p.status === "seen" && (
                      <span className="inline-flex items-center rounded-full px-1.5 py-px text-[12px] font-semibold bg-surface-low text-text-muted">
                        Seen
                      </span>
                    )}
                  </span>
                  <span className="block text-[12px] text-text-muted">
                    {waitLabel(p.waited_minutes)} · {(p.language || "en").toUpperCase()}
                  </span>
                  {snippet && <span className="block text-[12px] text-text-muted truncate">{snippet}</span>}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onTogglePin(p)}
                aria-pressed={pinned}
                aria-label={pinned ? `Unpin ${p.name}` : `Pin ${p.name} to the cards`}
                title={pinned ? "Unpin" : "Pin to the cards"}
                className={`shrink-0 mr-1.5 h-9 w-9 rounded-lg flex items-center justify-center transition-colors ${
                  pinned ? "text-primary bg-primary-fixed/60" : "text-text-muted hover:text-primary hover:bg-surface-lowest"
                }`}
              >
                {pinned ? <PinOff size={15} aria-hidden="true" /> : <Pin size={15} aria-hidden="true" />}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The queue with nobody in it. Instead of a dead end, it offers the check-in
 * link to hand out and a way to walk through check-in as a patient.
 */
function QueueEmpty({ hospitalId }: { hospitalId: string }) {
  const [copied, setCopied] = useState(false);
  const path = useSidePaths().bare ? "/patient" : `/${hospitalId}`;
  const intakeUrl = `${window.location.origin}${path}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(intakeUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked: the link is on screen to copy by hand */
    }
  };

  return (
    <div className="py-6 flex flex-col gap-4" data-tour="patient-queue">
      <div className="text-center">
        <Users2 size={22} className="mx-auto text-text-muted" aria-hidden />
        <div className="mt-2 text-sm font-semibold text-ink">No one is waiting right now</div>
        <p className="mx-auto mt-1 max-w-xs text-sm text-text-muted leading-relaxed">
          Patients appear here as soon as they check in. Share the check-in link, or check in
          yourself as a pretend patient.
        </p>
      </div>

      <div className="rounded-lg bg-surface-low p-3">
        <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold">
          Patient check-in link
        </div>
        <div className="mt-1 font-mono text-xs text-ink break-all">{intakeUrl}</div>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-surface-lowest text-xs font-semibold text-ink shadow-soft hover:shadow-card transition-shadow"
          >
            <Link2 size={13} aria-hidden />
            {copied ? "Copied" : "Copy link"}
          </button>
          <a
            href={path}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-xs font-semibold text-white hover:brightness-110 transition-all"
          >
            <Sparkles size={13} aria-hidden />
            Open check-in
          </a>
        </div>
      </div>

      <p className="text-center text-xs text-text-muted leading-relaxed">
        Each patient's details fill in here as soon as they finish check-in.
      </p>
    </div>
  );
}

function CardEmpty({ label }: { label: string }) {
  return (
    <div className="text-sm text-text-muted py-8 text-center leading-relaxed">
      Pin a patient from the queue to use <span className="font-semibold text-ink">{label}</span>.
    </div>
  );
}

function CardSpinner() {
  return (
    <div className="flex items-center justify-center py-10 text-text-muted text-sm" role="status">
      <Loader2 size={18} className="animate-spin mr-2" aria-hidden /> Loading…
    </div>
  );
}

// Keeps one broken card from taking down the whole board.
class CardErrorBoundary extends Component<
  { label: string; children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error("Dashboard card crashed:", error);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="text-sm text-text-muted py-8 text-center leading-relaxed" role="alert">
          The <span className="font-semibold text-ink">{this.props.label}</span> card hit a problem and
          stopped. Pick another patient, or remove this card and add it again.
        </div>
      );
    }
    return this.props.children;
  }
}
