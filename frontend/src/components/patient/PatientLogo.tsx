import { Link } from "react-router-dom";
import { t } from "../../lib/i18n";
import { isDemoHospital } from "../../lib/sandbox";

type Props = {
  hospitalId: string;
  lang: string;
  /** Height and layout classes for the image, for example "h-12 sm:h-16". */
  className?: string;
};

/**
 * The Solace logo on the patient screens. On a demo hospital it links to the home
 * page, so a visitor can always get back. At a real hospital it stays a plain
 * picture: a patient in the waiting room has no reason to leave check-in.
 */
export function PatientLogo({ hospitalId, lang, className = "h-12" }: Props) {
  const img = (
    <img src="/solace-logo.png" alt="Solace" className={`${className} w-auto select-none`} draggable={false} />
  );
  if (!isDemoHospital(hospitalId)) return img;
  return (
    <Link
      to="/"
      aria-label={t("logo_home_aria", lang)}
      className="inline-flex shrink-0 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2"
    >
      {img}
    </Link>
  );
}
