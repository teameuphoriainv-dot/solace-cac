import { useEffect, useRef, useState } from "react";
import { Camera, ImagePlus, Loader2, RotateCcw, X } from "lucide-react";
import { t } from "../../lib/i18n";

type Props = {
  onCapture: (file: File) => void;
  onClose: () => void;
  label?: string;
  aspectHint?: "card" | "free"; // "card" = insurance card overlay guides
  language?: string;
};

/** Full-screen in-app camera. Uses getUserMedia → <video> preview → canvas capture → File. */
export function InAppCamera({ onCapture, onClose, label, aspectHint = "free", language = "en" }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = s;
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          await videoRef.current.play().catch(() => undefined);
        }
        setReady(true);
      } catch {
        setError(true);
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  function capture() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !ready) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const file = new File([blob], `capture-${Date.now()}.jpg`, { type: "image/jpeg" });
        onCapture(file);
      },
      "image/jpeg",
      0.92
    );
  }

  async function flipCamera() {
    // Best-effort: stop current stream, restart with the other facing mode.
    const current = streamRef.current?.getVideoTracks()[0]?.getSettings().facingMode;
    const next = current === "user" ? "environment" : "user";
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setReady(false);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: next } },
        audio: false,
      });
      streamRef.current = s;
      if (videoRef.current) {
        videoRef.current.srcObject = s;
        await videoRef.current.play().catch(() => undefined);
      }
      setReady(true);
    } catch {
      // swallow — keep the error state visible
    }
  }

  // File-picker fallback — always wired, surfaced when the camera can't start
  const fileInputRef = useRef<HTMLInputElement>(null);
  function pickFromGallery() {
    fileInputRef.current?.click();
  }

  return (
    <div className="fixed inset-0 z-50 bg-black flex flex-col" style={{ height: "100dvh" }}>
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-4 bg-black text-white shrink-0"
        style={{ paddingTop: "calc(1rem + env(safe-area-inset-top, 0px))" }}
      >
        <button
          type="button"
          onClick={onClose}
          className="w-11 h-11 rounded-full bg-white/10 flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          aria-label={t("cam_close", language)}
        >
          <X size={20} aria-hidden="true" />
        </button>
        <div className="text-sm font-medium">{label || t("cam_title", language)}</div>
        <button
          type="button"
          onClick={flipCamera}
          disabled={!ready || error}
          className="w-11 h-11 rounded-full bg-white/10 flex items-center justify-center disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          aria-label={t("cam_flip", language)}
        >
          <RotateCcw size={18} aria-hidden="true" />
        </button>
      </div>

      {/* Preview */}
      <div className="relative flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden">
        {error ? (
          <div className="text-white text-center p-6 max-w-sm">
            <p className="mb-3">{t("cam_error", language)}</p>
            <p className="text-[13px] opacity-80 mb-5">{t("cam_error_help", language)}</p>
            <button
              type="button"
              onClick={pickFromGallery}
              className="inline-flex items-center gap-2 bg-white text-black rounded-full px-5 min-h-[44px] text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black"
            >
              <ImagePlus size={16} aria-hidden="true" /> {t("cam_upload_instead", language)}
            </button>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              playsInline
              muted
              autoPlay
              className="max-w-full max-h-full object-contain"
            />
            {!ready && (
              <div className="absolute inset-0 flex items-center justify-center text-white/80">
                <Loader2 className="animate-spin" size={32} aria-hidden="true" />
              </div>
            )}
          </>
        )}
        {aspectHint === "card" && ready && !error && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-[86%] aspect-[1.586] border-2 border-white/70 rounded-lg shadow-lifted" />
          </div>
        )}
        <canvas ref={canvasRef} className="hidden" />
      </div>

      {/* Controls — always visible, even while loading */}
      <div
        className="bg-black flex items-center justify-center gap-6 px-6 py-5 shrink-0"
        style={{ paddingBottom: "calc(1.25rem + env(safe-area-inset-bottom, 0px))" }}
      >
        <button
          type="button"
          onClick={pickFromGallery}
          className="w-12 h-12 rounded-full bg-white/10 text-white flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          aria-label={t("cam_gallery", language)}
        >
          <ImagePlus size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={capture}
          disabled={!ready || error}
          className="w-20 h-20 rounded-full bg-white ring-4 ring-white/40 disabled:opacity-40 active:scale-95 transition-transform flex items-center justify-center focus-visible:outline-none focus-visible:ring-white/90"
          aria-label={t("cam_capture", language)}
        >
          <Camera size={28} className="text-black" aria-hidden="true" />
        </button>
        {/* spacer to balance the gallery icon so the capture button stays centered */}
        <div className="w-12 h-12" aria-hidden />
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onCapture(f);
        }}
      />
    </div>
  );
}
