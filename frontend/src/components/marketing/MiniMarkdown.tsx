import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { REPO_URL } from "./site";

/**
 * A small Markdown renderer for the repo's own documents (AI-DISCLOSURE.md and the
 * stress test report). It covers what those files use: headings, paragraphs, bullet
 * and numbered lists, tables, block quotes, code blocks, inline code, bold, italic and
 * links. It builds React elements only (no raw HTML), so nothing in a file can run.
 *
 * Links: a repo file that has a page on this site opens that page; any other repo
 * path opens on GitHub; web links open in a new tab.
 */

/** Repo files that have their own page on this site. */
const SITE_PAGES: Record<string, string> = {
  "AI-DISCLOSURE.md": "/ai-disclosure",
  "docs/evidence/red-flag-stress-test.md": "/stress-test",
};

type Props = {
  source: string;
  /** Folder of the file inside the repo ("" for the root, "docs/evidence/"), for relative links. */
  baseDir?: string;
};

export function MiniMarkdown({ source, baseDir = "" }: Props) {
  const blocks = parseBlocks(source);
  return <div className="flex flex-col gap-4">{blocks.map((b, i) => renderBlock(b, i, baseDir))}</div>;
}

// ---- blocks -------------------------------------------------------------------------

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "para"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "quote"; text: string }
  | { kind: "code"; text: string }
  | { kind: "rule" };

const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const FENCE = /^\s*(```|~~~)/;
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    HEADING.test(line) ||
    BULLET.test(line) ||
    NUMBERED.test(line) ||
    FENCE.test(line) ||
    RULE.test(line) ||
    /^\s*>/.test(line) ||
    (line.trim().startsWith("|") && next !== undefined && TABLE_DIVIDER.test(next))
  );
}

function splitRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|") && !t.endsWith("\\|")) t = t.slice(0, -1);
  // Split on bars, keeping a "\|" inside a cell as a literal bar. (No regex
  // lookbehind: older Safari cannot parse it.)
  const cells: string[] = [];
  let cur = "";
  for (let i = 0; i < t.length; i++) {
    if (t[i] === "\\" && t[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (t[i] === "|") {
      cells.push(cur.trim());
      cur = "";
    } else cur += t[i];
  }
  cells.push(cur.trim());
  return cells;
}

function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (FENCE.test(line)) {
      const fence = line.trim().slice(0, 3);
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence)) body.push(lines[i++]);
      i++; // closing fence
      out.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    const h = line.match(HEADING);
    if (h) {
      out.push({ kind: "heading", level: h[1].length, text: h[2] });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      out.push({ kind: "rule" });
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
      const head = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      out.push({ kind: "table", head, rows });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push({ kind: "quote", text: body.join(" ") });
      continue;
    }
    const bullet = BULLET.test(line);
    if (bullet || NUMBERED.test(line)) {
      const re = bullet ? BULLET : NUMBERED;
      const items: string[] = [];
      while (i < lines.length) {
        const l = lines[i];
        const m = l.match(re);
        if (m) {
          items.push(m[1]);
          i++;
        } else if (l.trim() && /^\s{2,}/.test(l) && items.length) {
          // An indented line continues the item above it.
          items[items.length - 1] += " " + l.trim();
          i++;
        } else {
          break;
        }
      }
      out.push({ kind: "list", ordered: !bullet, items });
      continue;
    }
    const body: string[] = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i], lines[i + 1])) body.push(lines[i++].trim());
    out.push({ kind: "para", text: body.join(" ") });
  }
  return out;
}

function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_[\]()]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

const HEADING_CLS: Record<number, string> = {
  1: "font-display font-normal text-[34px] sm:text-[44px] leading-[1.08] tracking-editorial-tight text-ink",
  2: "mt-6 text-[24px] sm:text-[26px] font-semibold leading-tight text-ink",
  3: "mt-3 text-[19px] font-semibold leading-snug text-ink",
  4: "mt-2 text-[17px] font-semibold text-ink",
};

function renderBlock(b: Block, key: number, baseDir: string): ReactNode {
  switch (b.kind) {
    case "heading": {
      const level = Math.min(b.level, 4) as 1 | 2 | 3 | 4;
      const Tag = `h${level}` as "h1" | "h2" | "h3" | "h4";
      return (
        <Tag key={key} id={slug(b.text)} className={`${HEADING_CLS[level]} scroll-mt-6`}>
          {inline(b.text, baseDir)}
        </Tag>
      );
    }
    case "para":
      return (
        <p key={key} className="text-[16px] leading-relaxed text-ink [overflow-wrap:anywhere]">
          {inline(b.text, baseDir)}
        </p>
      );
    case "list": {
      const Tag = b.ordered ? "ol" : "ul";
      return (
        <Tag
          key={key}
          className={`flex flex-col gap-2 pl-6 text-[16px] leading-relaxed text-ink [overflow-wrap:anywhere] ${
            b.ordered ? "list-decimal" : "list-disc marker:text-primary"
          }`}
        >
          {b.items.map((it, j) => (
            <li key={j}>{inline(it, baseDir)}</li>
          ))}
        </Tag>
      );
    }
    case "table":
      return (
        <div key={key} className="overflow-x-auto rounded-xl bg-surface-lowest ring-1 ring-line">
          <table className="w-full text-left text-[14px]">
            <thead className="bg-surface-low text-text-muted">
              <tr>
                {b.head.map((c, j) => (
                  <th key={j} scope="col" className="px-3 py-2 font-medium align-bottom">
                    {inline(c, baseDir)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {b.rows.map((r, j) => (
                <tr key={j} className="align-top">
                  {b.head.map((_, k) => (
                    <td key={k} className="px-3 py-2 text-ink">
                      {inline(r[k] ?? "", baseDir)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "quote":
      return (
        <blockquote key={key} className="border-l-4 border-primary/40 pl-4 text-[16px] leading-relaxed text-text-muted">
          {inline(b.text, baseDir)}
        </blockquote>
      );
    case "code":
      return (
        <pre key={key} className="overflow-x-auto rounded-xl bg-surface-low ring-1 ring-line p-4 text-[13px] leading-relaxed">
          <code className="font-mono text-ink">{b.text}</code>
        </pre>
      );
    case "rule":
      return <hr key={key} className="border-line" />;
  }
}

// ---- inline -------------------------------------------------------------------------

const LINK = /^\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/;

/** Bold, italic, inline code and links inside one block of text. */
function inline(text: string, baseDir: string): ReactNode[] {
  const out: ReactNode[] = [];
  let buf = "";
  let i = 0;
  const flush = () => {
    if (buf) out.push(<Fragment key={out.length}>{buf}</Fragment>);
    buf = "";
  };
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\" && i + 1 < text.length && /[\\`*_[\]()#|]/.test(text[i + 1])) {
      buf += text[i + 1];
      i += 2;
      continue;
    }
    if (ch === "`") {
      const end = text.indexOf("`", i + 1);
      if (end > i) {
        flush();
        out.push(
          <code key={out.length} className="rounded bg-surface-low px-1 py-0.5 font-mono text-[0.9em] text-ink [overflow-wrap:anywhere]">
            {text.slice(i + 1, end)}
          </code>,
        );
        i = end + 1;
        continue;
      }
    }
    if (text.startsWith("**", i)) {
      const end = text.indexOf("**", i + 2);
      if (end > i + 2) {
        flush();
        out.push(
          <strong key={out.length} className="font-semibold">
            {inline(text.slice(i + 2, end), baseDir)}
          </strong>,
        );
        i = end + 2;
        continue;
      }
    }
    if (ch === "[") {
      const m = text.slice(i).match(LINK);
      if (m) {
        flush();
        out.push(<MdLink key={out.length} href={m[2]} baseDir={baseDir}>{inline(m[1], baseDir)}</MdLink>);
        i += m[0].length;
        continue;
      }
    }
    // *italic*, but not a lone star or a star before a space.
    if (ch === "*" && text[i + 1] && text[i + 1] !== " " && text[i + 1] !== "*") {
      const end = text.indexOf("*", i + 1);
      if (end > i + 1 && text[end - 1] !== " ") {
        flush();
        out.push(<em key={out.length}>{inline(text.slice(i + 1, end), baseDir)}</em>);
        i = end + 1;
        continue;
      }
    }
    buf += ch;
    i++;
  }
  flush();
  return out;
}

/** Resolve "../x.md" against the file's folder; null when it leaves the repo. */
function repoPath(href: string, baseDir: string): string | null {
  const parts = (baseDir + href).split("/");
  const stack: string[] = [];
  for (const p of parts) {
    if (p === "" || p === ".") continue;
    if (p === "..") {
      if (!stack.length) return null;
      stack.pop();
    } else stack.push(p);
  }
  return stack.join("/");
}

const linkCls = "text-primary underline underline-offset-2 hover:text-primary-hover [overflow-wrap:anywhere]";

function MdLink({ href, baseDir, children }: { href: string; baseDir: string; children: ReactNode }) {
  if (/^https?:\/\//i.test(href) || /^mailto:/i.test(href)) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={linkCls}>
        {children}
      </a>
    );
  }
  if (href.startsWith("#")) {
    return (
      <a href={href} className={linkCls}>
        {children}
      </a>
    );
  }
  // Anything with a scheme other than http(s) or mailto (javascript:, data:) is shown as text.
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return <>{children}</>;
  const [pathPart, hash = ""] = href.split("#");
  const path = repoPath(pathPart, baseDir);
  if (path === null) return <>{children}</>;
  const page = SITE_PAGES[path];
  if (page) {
    return (
      <Link to={hash ? `${page}#${hash}` : page} className={linkCls}>
        {children}
      </Link>
    );
  }
  return (
    <a href={`${REPO_URL}/blob/main/${path}${hash ? `#${hash}` : ""}`} target="_blank" rel="noreferrer" className={linkCls}>
      {children}
    </a>
  );
}
