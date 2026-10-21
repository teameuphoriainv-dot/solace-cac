/**
 * Shared state for one patient, used by the full patient page and by the cards
 * on the dashboard board.
 *
 * Every tab in ./tabs renders inside <PatientWorkspaceProvider> and takes no
 * props. It reads what it needs from usePatientWorkspace():
 *
 *   hospitalId, patientId  route ids, passed to every lib/api.ts call
 *   patient                the loaded record, or null while loading / on error
 *   loading                true only while there is no record to show yet
 *   error                  plain-English load error, or null
 *   reloadPatient()        re-fetch in the background after a write
 *   updatePatient(fn)      apply a local change right away (then reload)
 *   prefilledFromRecord    true when check-in matched a sample patient record
 *
 * A reload after a save keeps the current record on screen until the new one
 * arrives, so forms in the middle of being filled in are never unmounted.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiErrorMessage, getPatientDetail } from "../../lib/api";
import type { PatientDetail } from "../../types";

export type PatientWorkspaceValue = {
  hospitalId: string;
  patientId: string;
  patient: PatientDetail | null;
  loading: boolean;
  error: string | null;
  reloadPatient: () => void;
  updatePatient: (updater: (d: PatientDetail | null) => PatientDetail | null) => void;
  prefilledFromRecord: boolean;
};

const PatientWorkspaceContext = createContext<PatientWorkspaceValue | null>(null);

type ProviderProps = {
  hospitalId: string;
  patientId: string;
  authenticated: boolean;
  children: React.ReactNode;
};

export function PatientWorkspaceProvider({
  hospitalId,
  patientId,
  authenticated,
  children,
}: ProviderProps) {
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  // Which patient id the last finished request was for, and its error if any.
  const [settled, setSettled] = useState<{ id: string; error: string | null }>({ id: "", error: null });
  const [reloadKey, setReloadKey] = useState<number>(0);

  const reloadPatient = useCallback(() => {
    setReloadKey((k) => k + 1);
  }, []);

  const updatePatient = useCallback(
    (updater: (d: PatientDetail | null) => PatientDetail | null) => {
      setPatient((cur) => updater(cur));
    },
    [],
  );

  useEffect(() => {
    if (!authenticated || !patientId) return;
    let cancelled = false;
    getPatientDetail(hospitalId, patientId)
      .then((d) => {
        if (cancelled) return;
        setPatient(d);
        setSettled({ id: patientId, error: null });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // A failed background refresh keeps the record already on screen.
        setSettled({ id: patientId, error: apiErrorMessage(e, "Could not load this patient.") });
      });
    return () => {
      cancelled = true;
    };
  }, [hospitalId, patientId, authenticated, reloadKey]);

  // Never show one patient's record under another patient's id.
  const current = patient && patient.patient_id === patientId ? patient : null;
  const carrier = current as (PatientDetail & { ehr_fhir_id?: string | null }) | null;
  const waiting = authenticated && !!patientId && !current && settled.id !== patientId;

  const value: PatientWorkspaceValue = {
    hospitalId,
    patientId,
    patient: current,
    loading: waiting,
    error: current || waiting || settled.id !== patientId ? null : settled.error,
    reloadPatient,
    updatePatient,
    prefilledFromRecord: !!carrier?.ehr_fhir_id,
  };

  return (
    <PatientWorkspaceContext.Provider value={value}>
      {children}
    </PatientWorkspaceContext.Provider>
  );
}

/** Hook for tabs and workspace chrome to read the current patient context. */
export function usePatientWorkspace(): PatientWorkspaceValue {
  const ctx = useContext(PatientWorkspaceContext);
  if (!ctx) {
    throw new Error("usePatientWorkspace must be used within a PatientWorkspaceProvider");
  }
  return ctx;
}

/** Same as usePatientWorkspace, but returns null outside a provider instead of throwing. */
export function useOptionalPatientWorkspace(): PatientWorkspaceValue | null {
  return useContext(PatientWorkspaceContext);
}
