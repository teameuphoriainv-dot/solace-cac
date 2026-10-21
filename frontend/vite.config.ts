import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The backend runs locally on :8000 (see the root README). The dev server proxies
// /api and /media to it, so the browser only ever talks to one origin.
const API_TARGET = process.env.VITE_DEV_API_TARGET || "http://localhost:8000";

// The /ai-disclosure and /stress-test pages import these two files from the repo root
// (outside frontend/). The dev server may read only them, not the rest of the repo.
const REPO_DOCS = [
  path.resolve(__dirname, "../AI-DISCLOSURE.md"),
  path.resolve(__dirname, "../docs/evidence/red-flag-stress-test.md"),
];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    host: true,
    // Accept any host, so a phone on the same Wi-Fi (or a tunnel) can scan the QR code.
    allowedHosts: true,
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), ...REPO_DOCS] },
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/media": { target: API_TARGET, changeOrigin: true },
    },
  },
});
