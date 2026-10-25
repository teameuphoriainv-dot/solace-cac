import { useParams } from "react-router-dom";

export type SidePaths = {
  /** Where the patient check-in lives, e.g. "/patient" or "/demo-k3x9q2". */
  patient: string;
  /** Where the clinician queue lives, e.g. "/clinician" or "/demo-k3x9q2/clinician". */
  clinician: string;
  /** True on "/patient" and "/clinician": the shared demo hospital, no id in the address. */
  bare: boolean;
};

/**
 * The two sides of the hospital in the current address. "/patient" and "/clinician" open
 * the shared "demo" hospital, so a phone and a laptop see the same queue; every other
 * hospital keeps "/:hospitalId" and "/:hospitalId/clinician".
 */
export function useSidePaths(): SidePaths {
  const { hospitalId } = useParams<{ hospitalId: string }>();
  if (!hospitalId) return { patient: "/patient", clinician: "/clinician", bare: true };
  return { patient: `/${hospitalId}`, clinician: `/${hospitalId}/clinician`, bare: false };
}
