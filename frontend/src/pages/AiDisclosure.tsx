import { useEffect } from "react";
import { ExternalLink } from "lucide-react";
import { SiteNav } from "../components/marketing/SiteNav";
import { SiteFooter } from "../components/marketing/SiteFooter";
import { MiniMarkdown } from "../components/marketing/MiniMarkdown";
import { AI_DISCLOSURE_URL } from "../components/marketing/site";

// The repo's AI-DISCLOSURE.md, shown on the site so judges never depend on GitHub.
// Loaded with a glob so the site still builds if the file is not in the build folder.
const files = import.meta.glob("../../../AI-DISCLOSURE.md", { query: "?raw", import: "default", eager: true });
const TEXT = String(Object.values(files)[0] ?? "");

export default function AiDisclosure() {
  useEffect(() => {
    document.title = "AI disclosure: Solace";
  }, []);

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <div className="bg-surface-lowest border-b border-line">
        <SiteNav />
      </div>
      <main className="flex-1">
        <article className="mx-auto w-full max-w-3xl px-4 sm:px-6 py-10 sm:py-14">
          {TEXT ? (
            <MiniMarkdown source={TEXT} />
          ) : (
            <>
              <h1 className="font-display font-normal text-[34px] sm:text-[44px] leading-[1.08] tracking-editorial-tight text-ink">
                AI disclosure
              </h1>
              <p className="mt-4 text-[16px] leading-relaxed text-ink">
                This copy of the site was built without the disclosure file. It is in the project&rsquo;s
                code as AI-DISCLOSURE.md.
              </p>
            </>
          )}
          <p className="mt-10 pt-6 border-t border-line text-[14px] text-text-muted">
            This page shows the file AI-DISCLOSURE.md from the project&rsquo;s code.{" "}
            <a
              href={AI_DISCLOSURE_URL}
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
