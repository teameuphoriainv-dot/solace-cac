import { Link } from "react-router-dom";
import { AI_DISCLOSURE_PATH, CONTEST, PROVENANCE_URL, REPO_URL, STRESS_REPORT_PATH, TEAM } from "./site";

const linkCls =
  "text-[14px] text-white/80 hover:text-white underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 rounded-sm";

/** Footer for the public pages: who made it, what it is not, and where the code lives. */
export function SiteFooter() {
  return (
    <footer className="bg-ink text-white">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 grid gap-10 md:grid-cols-[1.4fr_1fr]">
        <div className="flex flex-col gap-4 max-w-md">
          <img
            src="/solace-logo.png"
            alt="Solace"
            className="h-8 w-auto self-start select-none brightness-0 invert"
            draggable={false}
          />
          <p className="text-[15px] leading-relaxed text-white/85">
            A student project by {TEAM} for the {CONTEST}.
          </p>
          <p className="text-[14px] leading-relaxed text-white/70">
            Student project, not for real medical use. Every patient in this demo is fictional.
            If you have a medical emergency, call 911.
          </p>
        </div>
        <ul className="flex flex-col gap-3">
          <li>
            <Link to="/how-it-works" className={linkCls}>
              How Solace works
            </Link>
          </li>
          <li>
            <Link to={AI_DISCLOSURE_PATH} className={linkCls}>
              How we used AI to build it
            </Link>
          </li>
          <li>
            <Link to={STRESS_REPORT_PATH} className={linkCls}>
              Full stress test report
            </Link>
          </li>
          <li>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className={linkCls}>
              Source code on GitHub
            </a>
          </li>
          <li>
            <a href={PROVENANCE_URL} target="_blank" rel="noreferrer" className={linkCls}>
              The earlier version this grew from
            </a>
          </li>
        </ul>
      </div>
    </footer>
  );
}
