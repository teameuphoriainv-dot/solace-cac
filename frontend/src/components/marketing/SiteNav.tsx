import { Link, NavLink } from "react-router-dom";
import { REPO_URL } from "./site";

const linkCls = ({ isActive }: { isActive: boolean }) =>
  `px-2.5 py-2 rounded-md text-[14px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
    isActive ? "text-ink" : "text-text-muted hover:text-ink"
  }`;

/** Slim top bar for the public pages (home, how it works). */
export function SiteNav() {
  return (
    <header className="relative z-10">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 sm:px-6 h-16"
      >
        <Link to="/" className="shrink-0 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <img src="/solace-logo.png" alt="Solace home" className="h-8 sm:h-9 w-auto select-none" draggable={false} />
        </Link>
        <div className="flex items-center gap-0.5 sm:gap-1">
          <NavLink to="/how-it-works" className={linkCls}>
            How it works
          </NavLink>
          <NavLink to="/showcase" className={(s) => `${linkCls(s)} hidden md:inline-flex`}>
            Both sides at once
          </NavLink>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className={linkCls({ isActive: false })}>
            Code
          </a>
        </div>
      </nav>
    </header>
  );
}
