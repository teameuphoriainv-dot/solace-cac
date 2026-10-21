import { useEffect } from "react";
import { ExternalLink } from "lucide-react";
import { SiteNav } from "../components/marketing/SiteNav";
import { SiteFooter } from "../components/marketing/SiteFooter";
import { MiniMarkdown } from "../components/marketing/MiniMarkdown";
import { STRESS_REPORT_URL } from "../components/marketing/site";

// The full red-flag stress test report (docs/evidence/red-flag-stress-test.md), with
// every missed phrase, shown on the site. Loaded with a glob so the site still builds
// if the file is not in the build folder.
const files = import.meta.glob("../../../docs/evidence/red-flag-stress-test.md", {
  query: "?raw",
  import: "default",
  eager: true,
});
const TEXT = String(Object.values(files)[0] ?? "");

export default function StressTestReport() {
  useEffect(() => {
    document.title = "Stress test report: Solace";
  }, []);

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <div className="bg-surface-lowest border-b border-line">
        <SiteNav />
      </div>
      <main className="flex-1">
        <article className="mx-auto w-full max-w-4xl px-4 sm:px-6 py-10 sm:py-14">
          {TEXT ? (
            <MiniMarkdown source={TEXT} baseDir="docs/evidence/" />
          ) : (
            <>
              <h1 className="font-display font-normal text-[34px] sm:text-[44px] leading-[1.08] tracking-editorial-tight text-ink">
                Red-flag stress test
              </h1>
              <p className="mt-4 text-[16px] leading-relaxed text-ink">
                This copy of the site was built without the report file. It is in the project&rsquo;s
                code as docs/evidence/red-flag-stress-test.md.
              </p>
            </>
          )}
          <p className="mt-10 pt-6 border-t border-line text-[14px] text-text-muted">
            This page shows the file docs/evidence/red-flag-stress-test.md from the project&rsquo;s code.{" "}
            <a
              href={STRESS_REPORT_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary underline underline-offset-2"
            >
              The same file on GitHub <ExternalLink size={13} aria-hidden />
            </a>
          </p>
        </article>
      </main>
      <SiteFooter />
    </div>
  );
}
