import { useState } from "react";
import {
  ILLINOIS,
  INSIDE_DISTRICT,
  NEARBY_CITY_ERS,
  formatMinutes,
  type ErSite,
} from "../../lib/il16";

const MAX_MIN = 300;
const TICKS = [0, 60, 120, 180, 240, 300];
const pos = (m: number) => `${(Math.min(m, MAX_MIN) / MAX_MIN) * 100}%`;

type Group = { title: string; rows: { town: string; sites: ErSite[] }[] };

function byTown(sites: ErSite[]) {
  const map = new Map<string, ErSite[]>();
  for (const s of sites) map.set(s.town, [...(map.get(s.town) ?? []), s]);
  return [...map.entries()].map(([town, list]) => ({ town, sites: list }));
}

const GROUPS: Group[] = [
  { title: "Big city ERs just outside the district line", rows: byTown(NEARBY_CITY_ERS) },
  {
    title: "Hospital ERs inside the 16th District",
    rows: byTown([...INSIDE_DISTRICT].sort((a, b) => b.minutes - a.minutes)),
  },
];

function describe(s: ErSite, inside: boolean) {
  const where = inside ? "inside the district" : "just outside the district";
  const left =
    s.leftPct === null
      ? "CMS has no number for patients who left before being seen."
      : `${s.leftPct} in 100 patients left before being seen (Illinois: ${ILLINOIS.leftPct}).`;
  return `${s.town} ER, ${where}: patients sent home spent a median of ${s.minutes} minutes (${formatMinutes(
    s.minutes,
  )}) in the ER. ${left}`;
}

/**
 * Dot plot: one dot per hospital ER, placed by the median time patients who were
 * sent home spent there, against the Illinois figure. Hover, focus or tap a dot
 * for its numbers; the full table sits underneath.
 */
export function Il16Chart() {
  const [active, setActive] = useState<string | null>(null);
  const insideIds = new Set(INSIDE_DISTRICT.map((s) => s.cmsId));
  const activeSite = [...INSIDE_DISTRICT, ...NEARBY_CITY_ERS].find((s) => s.cmsId === active);

  return (
    <figure className="w-full">
      <div className="rounded-2xl bg-surface-lowest ring-1 ring-line p-4 sm:p-6">
        <div className="grid grid-cols-[72px_1fr_76px] sm:grid-cols-[96px_1fr_104px] gap-x-3">
          {/* Illinois reference label, aligned over the track column */}
          <div />
          <div className="relative h-6">
            <span
              className="absolute bottom-0 -translate-x-1/2 whitespace-nowrap text-[12px] font-semibold text-ink"
              style={{ left: pos(ILLINOIS.minutes) }}
            >
              Illinois {ILLINOIS.minutes} min
            </span>
          </div>
          <div />

          {GROUPS.map((g) => (
            <div key={g.title} className="contents">
              <p className="col-span-3 mt-4 mb-1 text-[13px] font-semibold text-text-muted">{g.title}</p>
              {g.rows.map(({ town, sites }) => {
                const lo = Math.min(...sites.map((s) => s.minutes));
                const hi = Math.max(...sites.map((s) => s.minutes));
                return (
                  <div key={town} className="contents">
                    <span className="self-center py-1 text-[14px] leading-tight text-ink">
                      {town}
                      {sites.length > 1 && (
                        <span className="block text-[12px] text-text-muted">{sites.length} ERs</span>
                      )}
                    </span>
                    <div className="relative h-9">
                      {/* gridlines + Illinois line */}
                      {TICKS.map((t) => (
                        <span
                          key={t}
                          aria-hidden
                          className="absolute inset-y-0 w-px bg-surface-high"
                          style={{ left: pos(t) }}
                        />
                      ))}
                      <span
                        aria-hidden
                        className="absolute inset-y-0 w-0.5 -ml-px bg-ink/70"
                        style={{ left: pos(ILLINOIS.minutes) }}
                      />
                      {sites.length > 1 && (
                        <span
                          aria-hidden
                          className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-secondary/40 rounded-full"
                          style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }}
                        />
                      )}
                      {sites.map((s) => {
                        const on = active === s.cmsId;
                        return (
                          <button
                            key={s.cmsId}
                            type="button"
                            aria-label={describe(s, insideIds.has(s.cmsId))}
                            aria-pressed={on}
                            onMouseEnter={() => setActive(s.cmsId)}
                            onFocus={() => setActive(s.cmsId)}
                            onClick={() => setActive(s.cmsId)}
                            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 h-8 w-8 rounded-full flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                            style={{ left: pos(s.minutes) }}
                          >
                            <span
                              className={`block rounded-full ring-2 ring-surface-lowest transition-transform ${
                                on ? "h-4 w-4 bg-ink scale-110" : "h-3 w-3 bg-primary"
                              }`}
                            />
                          </button>
                        );
                      })}
                    </div>
                    <span className="self-center text-right text-[13px] tabular-nums text-text-muted">
                      {lo === hi ? `${hi} min` : `${lo} to ${hi}`}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}

          {/* axis */}
          <div />
          <div className="relative h-6 mt-1">
            {TICKS.map((t) => (
              <span
                key={t}
                className="absolute top-1 -translate-x-1/2 text-[12px] tabular-nums text-text-muted"
                style={{ left: pos(t) }}
              >
                {t === 0 ? "0" : `${t / 60} hr`}
              </span>
            ))}
          </div>
          <div />
        </div>

        <p
          aria-live="polite"
          className="mt-4 min-h-[3rem] rounded-lg bg-surface-low px-3 py-2 text-[14px] leading-snug text-ink"
        >
          {activeSite
            ? describe(activeSite, insideIds.has(activeSite.cmsId))
            : "Point at or tap a dot to see that ER's numbers."}
        </p>
      </div>

      <details className="mt-3 group">
        <summary className="cursor-pointer text-[14px] font-medium text-primary hover:underline w-fit">
          See these numbers as a table
        </summary>
        <div className="mt-3 overflow-x-auto rounded-xl ring-1 ring-line bg-surface-lowest">
          <table className="w-full text-left text-[14px]">
            <thead className="bg-surface-low text-text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Town</th>
                <th scope="col" className="px-3 py-2 font-medium">In the district</th>
                <th scope="col" className="px-3 py-2 font-medium text-right">Minutes in the ER</th>
                <th scope="col" className="px-3 py-2 font-medium text-right">Left before being seen</th>
                <th scope="col" className="px-3 py-2 font-medium">CMS facility id</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {[...NEARBY_CITY_ERS, ...INSIDE_DISTRICT].map((s) => (
                <tr key={s.cmsId}>
                  <td className="px-3 py-2 text-ink">{s.town}</td>
                  <td className="px-3 py-2 text-text-muted">{insideIds.has(s.cmsId) ? "Yes" : "No, next to it"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.minutes}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {s.leftPct === null ? "Not reported" : `${s.leftPct}%`}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-text-muted">{s.cmsId}</td>
                </tr>
              ))}
              <tr className="bg-surface-low">
                <td className="px-3 py-2 font-semibold text-ink">Illinois</td>
                <td className="px-3 py-2 text-text-muted">Whole state</td>
                <td className="px-3 py-2 text-right tabular-nums font-semibold">{ILLINOIS.minutes}</td>
                <td className="px-3 py-2 text-right tabular-nums font-semibold">{ILLINOIS.leftPct}%</td>
                <td className="px-3 py-2 text-text-muted">State file</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
