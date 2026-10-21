import type { ReactElement } from "react";

// The path from a patient's words to a final urgency score, drawn as inline SVG.
// Wide screens get one row; phones get a column. Both come from the same list.

type Node = { title: [string, string]; sub: [string, string]; tone?: "floor" | "final" };

const STAGES = ["At check-in, on the patient's phone", "At the bedside, with a nurse"];
/** How many nodes happen at check-in; the rest happen at the bedside. */
const CHECK_IN_NODES = 4;

function nodes(modelLoaded: boolean): Node[] {
  return [
    { title: ["Patient's", "words"], sub: ["Typed or spoken", "on their phone"] },
    modelLoaded
      ? { title: ["Rules and", "model"], sub: ["Most urgent", "answer wins"] }
      : { title: ["Safety", "word rules"], sub: ["No model here:", "rules only"] },
    { title: ["Red-flag", "checklist"], sub: ["Any tap: ESI 2", "or more urgent"], tone: "floor" },
    { title: ["First", "score"], sub: ["ESI 1 to 5, in", "the queue"] },
    { title: ["Nurse takes", "vitals"], sub: ["Pulse, oxygen,", "blood pressure"] },
    modelLoaded
      ? { title: ["Trained", "model"], sub: ["5 LightGBM", "models guess"] }
      : { title: ["Trained", "model"], sub: ["Not installed", "here: skipped"] },
    { title: ["Safety", "floor"], sub: ["Can only raise", "the urgency"], tone: "floor" },
    { title: ["Final", "score"], sub: ["Shown with", "the reasons"], tone: "final" },
  ];
}

const C = {
  card: "#FFFFFF",
  stroke: "rgba(74, 85, 87, 0.28)",
  ink: "#1A2023",
  muted: "#4A5557",
  arrow: "#406372",
  floor: "#2A474E",
  floorSub: "#CBE3E9",
  final: "#D8ECF0",
};

function fills(n: Node) {
  if (n.tone === "floor") return { bg: C.floor, stroke: C.floor, title: "#FFFFFF", sub: C.floorSub };
  if (n.tone === "final") return { bg: C.final, stroke: C.floor, title: C.ink, sub: C.muted };
  return { bg: C.card, stroke: C.stroke, title: C.ink, sub: C.muted };
}

function Arrowhead({ id }: { id: string }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill={C.arrow} />
      </marker>
    </defs>
  );
}

function Wide({ list }: { list: Node[] }) {
  const W = 128, G = 16, H = 114, Y = 4;
  const x = (i: number) => i * (W + G);
  const total = x(list.length - 1) + W;
  const split = CHECK_IN_NODES;
  const bracket = (from: number, to: number, label: string) => {
    const x1 = x(from), x2 = x(to) + W, yb = Y + H + 18;
    return (
      <g key={label}>
        <path d={`M${x1} ${yb - 8} V${yb} H${x2} V${yb - 8}`} fill="none" stroke={C.stroke} strokeWidth="1.5" />
        <text x={(x1 + x2) / 2} y={yb + 23} textAnchor="middle" fontSize="15" fontWeight="600" fill={C.muted}>
          {label}
        </text>
      </g>
    );
  };
  return (
    <svg viewBox={`0 0 ${total} ${Y + H + 54}`} className="w-full h-auto" aria-hidden="true" fontFamily="inherit">
      <Arrowhead id="pipe-arrow-wide" />
      {list.map((n, i) => {
        const f = fills(n);
        return (
          <g key={i}>
            <rect x={x(i)} y={Y} width={W} height={H} rx="14" fill={f.bg} stroke={f.stroke} strokeWidth="1.5" />
            <text x={x(i) + 12} y={Y + 28} fontSize="16" fontWeight="700" fill={f.title}>
              <tspan x={x(i) + 12}>{n.title[0]}</tspan>
              <tspan x={x(i) + 12} dy="19">{n.title[1]}</tspan>
            </text>
            <text x={x(i) + 12} y={Y + 78} fontSize="13" fill={f.sub}>
              <tspan x={x(i) + 12}>{n.sub[0]}</tspan>
              <tspan x={x(i) + 12} dy="16">{n.sub[1]}</tspan>
            </text>
            {i < list.length - 1 && (
              <line
                x1={x(i) + W + 3}
                y1={Y + H / 2}
                x2={x(i + 1) - 3}
                y2={Y + H / 2}
                stroke={C.arrow}
                strokeWidth="1.75"
                markerEnd="url(#pipe-arrow-wide)"
              />
            )}
          </g>
        );
      })}
      {bracket(0, split - 1, STAGES[0])}
      {bracket(split, list.length - 1, STAGES[1])}
    </svg>
  );
}

function Tall({ list }: { list: Node[] }) {
  const W = 340, H = 64, GAP = 24, LABEL = 46;
  const cx = W / 2;
  const items: ReactElement[] = [];
  let y = 0;
  const stageLabel = (label: string, top: number) => (
    <text key={label} x={cx} y={top + 18} textAnchor="middle" fontSize="14" fontWeight="600" fill={C.muted}>
      {label}
    </text>
  );
  items.push(stageLabel(STAGES[0], y));
  y += 30;
  list.forEach((n, i) => {
    const f = fills(n);
    items.push(
      <g key={`n${i}`}>
        <rect x={1} y={y} width={W - 2} height={H} rx="14" fill={f.bg} stroke={f.stroke} strokeWidth="1.5" />
        <text x={16} y={y + 27} fontSize="16" fontWeight="700" fill={f.title}>
          {n.title.join(" ")}
        </text>
        <text x={16} y={y + 48} fontSize="13" fill={f.sub}>
          {n.sub.join(" ")}
        </text>
      </g>,
    );
    const bottom = y + H;
    if (i === list.length - 1) {
      y = bottom;
      return;
    }
    if (i === CHECK_IN_NODES - 1) {
      // The bedside stage starts here: arrow, label, arrow.
      items.push(
        <line key={`a${i}`} x1={cx} y1={bottom + 3} x2={cx} y2={bottom + 14} stroke={C.arrow} strokeWidth="1.75" />,
      );
      items.push(stageLabel(STAGES[1], bottom + 14));
      items.push(
        <line
          key={`b${i}`}
          x1={cx}
          y1={bottom + 14 + 26}
          x2={cx}
          y2={bottom + LABEL + 14 - 3}
          stroke={C.arrow}
          strokeWidth="1.75"
          markerEnd="url(#pipe-arrow-tall)"
        />,
      );
      y = bottom + LABEL + 14;
    } else {
      items.push(
        <line
          key={`a${i}`}
          x1={cx}
          y1={bottom + 3}
          x2={cx}
          y2={bottom + GAP - 3}
          stroke={C.arrow}
          strokeWidth="1.75"
          markerEnd="url(#pipe-arrow-tall)"
        />,
      );
      y = bottom + GAP;
    }
  });
  return (
    <svg viewBox={`0 0 ${W} ${y + 2}`} className="w-full max-w-[400px] h-auto mx-auto" aria-hidden="true" fontFamily="inherit">
      <Arrowhead id="pipe-arrow-tall" />
      {items}
    </svg>
  );
}

export function PipelineDiagram({ modelLoaded = true }: { modelLoaded?: boolean }) {
  const list = nodes(modelLoaded);
  const description = list
    .map((n, i) => `${i + 1}. ${n.title.join(" ")}: ${n.sub.join(" ")}.`)
    .join(" ");
  return (
    <figure role="img" aria-label={`How Solace scores urgency. ${description}`} className="w-full">
      <div className="hidden xl:block">
        <Wide list={list} />
      </div>
      <div className="xl:hidden">
        <Tall list={list} />
      </div>
    </figure>
  );
}
