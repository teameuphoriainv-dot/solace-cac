import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ChevronDown, Info, Loader2, ShieldAlert, ShieldOff, TriangleAlert } from "lucide-react";
import { loadSessionFor, type Session } from "../lib/session";
import { ESI_COLORS } from "../lib/constants";
import {
  PatientWorkspaceProvider,
  usePatientWorkspace,
} from "../components/workspace/PatientWorkspaceContext";
import { AiStatusPill } from "../components/workspace/AiStatus";

const OverviewTab = lazy(() => import("../components/workspace/tabs/OverviewTab"));
const EarlyWarningTab = lazy(() => import("../components/workspace/tabs/EarlyWarningTab"));
const ScribeTab = lazy(() => import("../components/workspace/tabs/ScribeTab"));
const ReasoningTab = lazy(() => import("../components/workspace/tabs/ReasoningTab"));

type TabDef = {
  id: string;
  label: string;
  Component: React.LazyExoticComponent<() => React.JSX.Element>;
};

const TABS: TabDef[] = [
  { id: "overview", label: "Summary", Component: OverviewTab },
  { id: "early-warning", label: "Early warning", Component: EarlyWarningTab },
  { id: "scribe", label: "Scribe", Component: ScribeTab },
  { id: "reasoning", label: "Reasoning", Component: ReasoningTab },
];

/** Small priority pill used in the sticky header (1 is most urgent, 5 least). */
function EsiPill({ label, level }: { label: string; level: number | null | undefined }) {
  if (level == null) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold bg-surface-low text-text-muted">
        {label}: not yet
      </span>
    );
  }
  const cfg = ESI_COLORS[level] || { bg: "#4A5557", onDark: true };
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold"
      style={{ background: cfg.bg, color: cfg.onDark ? "#fff" : "#1A1A1A" }}
    >
      {label}: {level}
    </span>
  );
}

/** Sticky patient header: name, scores and tabs, from the workspace context. */
function WorkspaceHeader({
  hospitalId,
  activeTab,
  onSelectTab,
  tablistId,
}: {
  hospitalId: string;
  activeTab: string;
  onSelectTab: (id: string) => void;
  tablistId: string;
}) {
  const { patient, loading, error, prefilledFromRecord } = usePatientWorkspace();
  // Inside the /showcase pane, going back keeps the compact dashboard.
  const [searchParams] = useSearchParams();
  const queuePath = `/${hospitalId}/clinician${searchParams.get("embed") === "1" ? "?embed=1" : ""}`;
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  // Record details stay behind "More info" so the header reads clean.
  const [showMore, setShowMore] = useState(false);

  const info = patient?.medical_info;
  const ageSex = [
    info?.age != null ? `${info.age}yo` : null,
    info?.sex || null,
  ]
    .filter(Boolean)
    .join(" ");
  const shortId = patient?.patient_id ? patient.patient_id.slice(0, 8) : "-";
  const modelEsi = patient?.refined_model_esi_level;
  const raisedByRules =
    patient?.refined_esi_level != null && typeof modelEsi === "number" && patient.refined_esi_level < modelEsi;
  const alertActive =
    !!patient?.pain_flagged &&
    !!patient.pain_flagged_at &&
    (!patient.pain_flag_acknowledged_at || patient.pain_flag_acknowledged_at < patient.pain_flagged_at);
  // The check-in words matched the prompt-injection filter, so AI is off for this patient.
  const contentFlagged = !!patient?.content_flag;

  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    else return;
    e.preventDefault();
    const id = TABS[next].id;
    onSelectTab(id);
    tabRefs.current[id]?.focus();
  };

  return (
    <header
      className="border-b border-line bg-surface-lowest sticky top-0 z-30"
      style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
    >
      <div className="px-4 sm:px-5 pt-2.5 flex items-center justify-between gap-3">
        <Link
          to={queuePath}
          className="inline-flex items-center gap-1.5 rounded text-text-muted hover:text-ink text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
        >
          <ArrowLeft size={16} aria-hidden="true" /> Back to queue
        </Link>
        <AiStatusPill hospitalId={hospitalId} align="right" />
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 pt-2">
        <div className="min-w-0">
          <div className="text-[12px] uppercase tracking-wider text-text-muted font-semibold">
            Patient chart
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-bold tracking-tight truncate">
              {patient?.name || (loading ? "Loading…" : error ? "Patient" : "-")}
            </h1>
            {ageSex && <span className="text-sm text-text-muted">{ageSex}</span>}
          </div>

          <div className="flex items-center gap-2 flex-wrap mt-1.5">
            {patient && (
              <>
                <EsiPill label="Check-in priority" level={patient.esi_level} />
                <EsiPill label="Bedside re-check" level={patient.refined_esi_level} />
                {raisedByRules && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold bg-error/10 text-error">
                    <ShieldAlert size={12} aria-hidden="true" />
                    Raised by safety rules (model said {modelEsi})
                  </span>
                )}
                {alertActive && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold bg-error text-white">
                    <TriangleAlert size={12} aria-hidden="true" />
                    Says they feel worse
                  </span>
                )}
                {contentFlagged && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold bg-warning-container text-ink"
                    title={patient.content_flag ?? undefined}
                  >
                    <ShieldOff size={12} aria-hidden="true" />
                    AI off for this patient
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setShowMore((v) => !v)}
                  aria-expanded={showMore}
                  className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-semibold bg-surface-low text-text-muted hover:text-ink transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                >
                  <Info size={12} aria-hidden="true" />
                  {showMore ? "Less" : "More info"}
                  <ChevronDown
                    size={12}
                    aria-hidden="true"
                    className={`transition-transform ${showMore ? "rotate-180" : ""}`}
                  />
                </button>
                {showMore && (
                  <>
                    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold bg-surface-low text-text-muted">
                      Demo record (fictional patient)
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] bg-surface-low text-text-muted">
                      Patient ID {shortId}
                    </span>
                    {prefilledFromRecord && (
                      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold bg-primary-fixed/50 text-primary">
                        History filled from a sample record
                      </span>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>

        {/* Tab bar */}
        <div
          role="tablist"
          id={tablistId}
          aria-label="Patient chart sections"
          className="flex items-center gap-1 mt-3 -mb-px overflow-x-auto"
        >
          {TABS.map((t, i) => {
            const selected = t.id === activeTab;
            return (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                role="tab"
                id={`${tablistId}-tab-${t.id}`}
                aria-selected={selected}
                aria-controls={`${tablistId}-panel-${t.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => onSelectTab(t.id)}
                onKeyDown={(e) => onTabKeyDown(e, i)}
                className={`whitespace-nowrap rounded-t-md px-3 py-2 text-sm font-semibold border-b-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 ${
                  selected
                    ? "border-primary text-primary"
                    : "border-transparent text-text-muted hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>
    </header>
  );
}

function WorkspaceBody({ hospitalId, tablistId }: { hospitalId: string; tablistId: string }) {
  const [activeTab, setActiveTab] = useState<string>(TABS[0].id);
  // A tab stays mounted (just hidden) once opened, so a scribe session keeps
  // recording and typed vitals survive a trip to another tab.
  const [visited, setVisited] = useState<Set<string>>(() => new Set([TABS[0].id]));
  const selectTab = (id: string) => {
    setActiveTab(id);
    setVisited((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  };

  return (
    <div className="min-h-screen bg-surface-lowest">
      <WorkspaceHeader
        hospitalId={hospitalId}
        activeTab={activeTab}
        onSelectTab={selectTab}
        tablistId={tablistId}
      />
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
        {TABS.map((t) => {
          const selected = t.id === activeTab;
          const { Component } = t;
          return (
            <div
              key={t.id}
              role="tabpanel"
              id={`${tablistId}-panel-${t.id}`}
              aria-labelledby={`${tablistId}-tab-${t.id}`}
              hidden={!selected}
            >
              {visited.has(t.id) && (
                <Suspense
                  fallback={
                    <div className="flex items-center justify-center py-16 text-text-muted text-sm">
                      <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
                      Loading…
                    </div>
                  }
                >
                  <Component />
                </Suspense>
              )}
            </div>
          );
        })}
      </main>
    </div>
  );
}

export default function PatientDetailPage() {
  const { hospitalId = "demo", patientId = "" } = useParams<{
    hospitalId?: string;
    patientId?: string;
  }>();
  const [session] = useState<Session | null>(() => loadSessionFor(hospitalId));
  const tablistId = useId();

  useEffect(() => {
    document.title = "Patient chart: Solace";
  }, []);

  if (!session?.token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-low">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <h1 className="text-xl font-bold mb-2">Sign in required</h1>
          <p className="text-text-muted text-sm mb-4">
            Open the nurse dashboard to sign in first.
          </p>
          <Link
            to={`/${hospitalId}/clinician`}
            className="inline-flex items-center gap-1.5 h-11 px-4 rounded-md bg-primary text-white text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
          >
            Go to the dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <PatientWorkspaceProvider
      hospitalId={hospitalId}
      patientId={patientId}
      authenticated={!!session?.token}
    >
      <WorkspaceBody hospitalId={hospitalId} tablistId={tablistId} />
    </PatientWorkspaceProvider>
  );
}
