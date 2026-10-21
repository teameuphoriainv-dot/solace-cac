import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { getRuntimeConfig } from "../lib/runtime-config";

/**
 * Full-screen QR code for the patient check-in of this hospital. Show it on a
 * laptop or a printed card and scan it with a phone. It always points at the site
 * that is serving this page (or config.json's publicUrl when one is set), so a
 * local run hands out a local link and the hosted demo hands out the hosted one.
 */
export default function QRCard() {
  const { hospitalId = "demo" } = useParams();
  const origin = (getRuntimeConfig().publicUrl || window.location.origin).replace(/\/+$/, "");
  const intakeUrl = `${origin}/${hospitalId}`;

  useEffect(() => {
    document.title = "Scan to check in: Solace";
  }, []);

  return (
    <div
      className="min-h-[100dvh] flex flex-col items-center justify-center bg-surface px-4 sm:px-8 gap-8 sm:gap-10"
      style={{
        paddingTop: "calc(2rem + env(safe-area-inset-top, 0px))",
        paddingBottom: "calc(2rem + env(safe-area-inset-bottom, 0px))",
      }}
    >
      <Link to="/" className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
        <img
          src="/solace-logo.png"
          alt="Solace home"
          className="h-14 sm:h-20 w-auto select-none"
          draggable={false}
        />
      </Link>

      <div className="flex flex-col items-center gap-3 text-center max-w-lg">
        <h1 className="font-display font-normal text-[36px] sm:text-[48px] tracking-editorial-tight leading-[1.05] text-ink">
          Scan to check in
        </h1>
        <p className="text-[17px] sm:text-lg text-text-muted leading-snug">
          Point your phone camera at the code. There is nothing to install and no account to make.
        </p>
      </div>

      <div
        className="w-full max-w-[460px] bg-surface-lowest rounded-[28px] p-5 sm:p-8 shadow-card ring-1 ring-line"
        role="img"
        aria-label={`QR code for the patient check-in page at ${intakeUrl}`}
      >
        <QRCodeSVG
          value={intakeUrl}
          size={420}
          level="H"
          marginSize={0}
          bgColor="#FFFFFF"
          fgColor="#1A2023"
          style={{ width: "100%", height: "auto", display: "block" }}
        />
      </div>

      <div className="flex flex-col items-center gap-1 max-w-full text-center">
        <p className="text-[14px] text-text-muted">Or open this link</p>
        <a
          href={intakeUrl}
          className="font-mono text-[14px] sm:text-[15px] text-ink break-all underline-offset-4 hover:underline"
        >
          {intakeUrl}
        </a>
      </div>

      <p className="text-[14px] text-text-muted text-center">
        Student demo, 2026 Congressional App Challenge
      </p>
    </div>
  );
}
