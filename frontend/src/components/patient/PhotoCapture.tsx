import { useEffect, useRef, useState } from "react";
import { Camera, ImagePlus, RefreshCw, X } from "lucide-react";
import { InAppCamera } from "../ui/InAppCamera";
import { t } from "../../lib/i18n";

type Props = {
  file: File | null;
  onChange: (file: File | null) => void;
  label?: string;
  description?: string;
  language?: string;
};

function hasGetUserMedia(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

const iconButton =
  "bg-surface-lowest/90 backdrop-blur w-11 h-11 rounded-full flex items-center justify-center shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2";

export function PhotoCapture({ file, onChange, label, description, language = "en" }: Props) {
  const [preview, setPreview] = useState<string | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const title = label ?? t("photo_take", language);
  const desc = description ?? t("photo_desc", language);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function openPrimaryCamera() {
    if (hasGetUserMedia()) {
      setCameraOpen(true);
    } else {
      fileInputRef.current?.click();
    }
  }

  const hiddenInput = (
    <input
      ref={fileInputRef}
      type="file"
      accept="image/*"
      capture="environment"
      className="hidden"
      tabIndex={-1}
      aria-hidden="true"
      onChange={(e) => onChange(e.target.files?.[0] || null)}
    />
  );

  const camera = cameraOpen && (
    <InAppCamera
      label={title}
      language={language}
      onCapture={(f) => {
        onChange(f);
        setCameraOpen(false);
      }}
      onClose={() => setCameraOpen(false)}
    />
  );

  if (preview) {
    return (
      <>
        <div className="relative">
          <img src={preview} alt={t("photo_preview_alt", language)} className="w-full rounded-lg shadow-soft" />
          <div className="absolute top-3 right-3 flex gap-2">
            <button type="button" onClick={openPrimaryCamera} className={iconButton} aria-label={t("photo_retake", language)}>
              <RefreshCw size={18} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => onChange(null)} className={iconButton} aria-label={t("photo_remove", language)}>
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
        {hiddenInput}
        {camera}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={openPrimaryCamera}
        className="w-full rounded-lg bg-surface-low hover:bg-primary-dim transition-colors py-8 flex flex-col items-center gap-2 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
      >
        <div className="w-14 h-14 rounded-full bg-primary-fixed text-primary flex items-center justify-center">
          <Camera size={26} aria-hidden="true" />
        </div>
        <div className="font-semibold tracking-editorial rtl:tracking-normal">{title}</div>
        <div className="text-[13px] text-text-muted text-center px-6">{desc}</div>
      </button>
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        className="self-center inline-flex items-center gap-1 min-h-[44px] px-3 text-sm text-text-muted underline underline-offset-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
      >
        <ImagePlus size={14} aria-hidden="true" /> {t("photo_upload", language)}
      </button>
      {hiddenInput}
      {camera}
    </div>
  );
}
