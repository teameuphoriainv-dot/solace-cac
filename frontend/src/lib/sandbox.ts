/**
 * Private demo hospitals for judges and visitors.
 *
 * Each browser gets its own hospital id like "demo-k3x9q2", so nobody sees another
 * visitor's patients. The backend creates the hospital (with the demo clinicians and
 * the five example patients) the first time it sees the id, and clears it after two
 * idle hours. If storage is blocked we fall back to the shared "demo" hospital.
 */
import { useEffect, useState } from "react";

const STORAGE_KEY = "solace.sandbox.v1";
const SANDBOX_RE = /^demo-[a-z0-9]{6}$/;
const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";
const CHANGED_EVENT = "solace:sandbox-changed";

/** True for the shared demo hospital and for every private sandbox copy of it. */
export function isDemoHospital(id: string | undefined | null): boolean {
  return !!id && (id === "demo" || id.startsWith("demo-"));
}

function newSandboxId(): string {
  const bytes = new Uint8Array(6);
  try {
    crypto.getRandomValues(bytes);
  } catch {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  let out = "demo-";
  for (const b of bytes) out += ALPHABET[b % ALPHABET.length];
  return out;
}

/** This browser's private demo hospital id, created on first use. */
export function getSandboxId(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SANDBOX_RE.test(saved)) return saved;
    const id = newSandboxId();
    localStorage.setItem(STORAGE_KEY, id);
    return id;
  } catch {
    return "demo";
  }
}

/** Swap to a brand new private hospital (empty except for the example patients). */
export function startFreshSandbox(): string {
  const id = newSandboxId();
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    return "demo";
  }
  window.dispatchEvent(new Event(CHANGED_EVENT));
  return id;
}

/** getSandboxId() that re-renders when another tab or "Start fresh" changes it. */
export function useSandboxId(): string {
  const [id, setId] = useState(getSandboxId);
  useEffect(() => {
    const sync = () => setId(getSandboxId());
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) sync();
    };
    window.addEventListener(CHANGED_EVENT, sync);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(CHANGED_EVENT, sync);
      window.removeEventListener("storage", onStorage);
    };
  }, []);
  return id;
}
