import { AlertCircle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { DifferentialEntry } from "../../types";
import { useCapabilities } from "../../lib/capabilities";
import { AiSourceTag } from "../workspace/AiStatus";
import { useOptionalPatientWorkspace } from "../workspace/PatientWorkspaceContext";

type Props = {
  entries: DifferentialEntry[];
  /**
   * True when this list was just written by AI, false when it was not. Left out,
   * the tag follows the server: an AI draft when AI is on, otherwise a list that
   * was saved with the record.
   */
  aiDraft?: boolean;
  /** Tag text when the list was not written by AI. */
  noAiLabel?: string;
};

function likelihoodBadge(level: DifferentialEntry["likelihood"]) {
  switch (level) {
    case "high":
      return "bg-error/15 text-error";
    case "moderate":
      return "bg-warning/15 text-warning";
    default:
      return "bg-surface-low text-text-muted";
  }
}

export function DifferentialPanel({ entries, aiDraft, noAiLabel }: Props) {
  const [openIdx, setOpenIdx] = useState<number | null>(0);
  const workspace = useOptionalPatientWorkspace();
  const caps = useCapabilities(aiDraft === undefined ? workspace?.hospitalId : undefined);
  const ai = aiDraft ?? !!caps?.llm;

  if (!entries || entries.length === 0) return null;

  return (
    <section>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="text-[12px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Possible diagnoses
        </div>
        <div className="flex items-center gap-2">
          {(aiDraft !== undefined || caps) && (
            <AiSourceTag ai={ai} label={ai ? undefined : noAiLabel ?? "Saved with this record"} />
          )}
          <span className="text-[12px] text-text-muted">
            {entries.length} {entries.length === 1 ? "idea" : "ideas"}
          </span>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        {entries.map((d, i) => {
          const isOpen = openIdx === i;
          return (
            <div
              key={i}
              className="bg-surface-lowest rounded-lg shadow-soft overflow-hidden"
            >
              <button
                type="button"
                onClick={() => setOpenIdx(isOpen ? null : i)}
                aria-expanded={isOpen}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-surface-low transition-colors"
              >
                {isOpen ? (
                  <ChevronDown size={16} className="text-text-muted shrink-0" aria-hidden="true" />
                ) : (
                  <ChevronRight size={16} className="text-text-muted shrink-0" aria-hidden="true" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold tracking-editorial text-[15px]">
                      {d.diagnosis}
                    </span>
                    {d.must_not_miss && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[12px] font-bold uppercase tracking-wider bg-error text-white">
                        <AlertCircle size={10} aria-hidden="true" /> Do not miss
                      </span>
                    )}
                    <span
                      className={`px-2 py-0.5 rounded-full text-[12px] font-semibold uppercase tracking-wider ${likelihoodBadge(d.likelihood)}`}
                    >
                      {d.likelihood === "high" ? "More likely" : d.likelihood === "moderate" ? "Possible" : "Less likely"}
                    </span>
                    {d.icd10 && (
                      <span className="text-[12px] font-mono text-text-muted">
                        {d.icd10}
                      </span>
                    )}
                  </div>
                </div>
              </button>
              {isOpen && (
                <div className="px-3 pb-3 pt-1 grid grid-cols-1 sm:grid-cols-2 gap-3 border-t border-line">
                  {d.rule_in.length > 0 && (
                    <div>
                      <div className="text-[12px] uppercase tracking-wider text-text-muted mb-1">
                        Points for
                      </div>
                      <ul className="text-[13px] leading-snug list-disc list-inside text-ink space-y-0.5">
                        {d.rule_in.map((x, j) => (
                          <li key={j}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {d.rule_out.length > 0 && (
                    <div>
                      <div className="text-[12px] uppercase tracking-wider text-text-muted mb-1">
                        Points against
                      </div>
                      <ul className="text-[13px] leading-snug list-disc list-inside text-text-muted space-y-0.5">
                        {d.rule_out.map((x, j) => (
                          <li key={j}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
