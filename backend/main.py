"""FastAPI entrypoint for Solace.

Run locally:   uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
or simply:     python main.py        (reads PORT, default 8000)

The Docker demo runs the same app on port 7860 and also serves the built frontend
(frontend/dist) from this server, so one URL serves the API, /media and the app.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware, GZipResponder

from lib import accounts, quota, sandbox, spend
from lib.config import ROOT, hydrate_from_secrets_manager, settings
from db import storage
from routers import (
    admin, auth, clinical_ai, identity, insurance, intake, notes, pain_flag, patients,
    prescriptions, public, sms as sms_router, transcribe, triage,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Install log redaction before other modules log anything, so patient ids and
# tokens never show up in the request log.
from lib import log_redaction  # noqa: E402

log_redaction.install()

log = logging.getLogger("solace")
log.info("Solace starting in %s mode", settings.solace_mode)
# Hosted demo: read the Anthropic key from SOLACE_KEYS_SECRET once. With that unset
# (and not in aws mode) this returns at once and makes no AWS call.
hydrate_from_secrets_manager()


def _warm_triage_model() -> None:
    """Load the bedside model in the background so the first patient does not wait."""
    try:
        from services import triage_ml  # noqa: PLC0415 (heavy import)

        # This goes through the model's load lock, so a request that arrives mid-load
        # waits for this load instead of starting a second copy of the model.
        art = getattr(triage_ml, "_get_art", triage_ml._load)()
        log.info("bedside model %s", "loaded" if art is not None else "not installed (rules only)")
    except Exception as e:  # noqa: BLE001 (warm-up is best effort)
        log.warning("bedside model warm-up failed: %s", e)


# ---- startup work, and its progress for /health ------------------------------------------
# Set while the demo clinicians exist. Starts set so a server whose startup did not run
# (some tests) never waits; cleared only while background startup is creating them.
_clinicians_ready = threading.Event()
_clinicians_ready.set()
_warmup_lock = threading.Lock()
_warmup: dict = {"state": "not_started", "step": None, "background": False,
                 "clinicians_ready": True, "example_patients": None, "seconds": None}
_warmup_started = 0.0


def _warmup_set(**changes) -> None:
    with _warmup_lock:
        _warmup.update(changes)


def _warmup_begin(background: bool) -> None:
    global _warmup_started
    _warmup_started = time.monotonic()
    if background:
        _clinicians_ready.clear()
    _warmup_set(state="running", step="clinicians", background=background,
                clinicians_ready=not background, example_patients=None, seconds=None)


def _warmup_finish(state: str) -> None:
    _clinicians_ready.set()
    _warmup_set(state=state, step=None, seconds=round(time.monotonic() - _warmup_started, 2))


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.seed_demo_hospital()
    seed = settings.solace_mode == "local" and settings.solace_seed_demo
    # In the container the server must answer health checks right away, so making the
    # demo clinicians (about a second of PIN hashing) and the example patients (which
    # loads the model first) runs in the background there. Sign-in requests that arrive
    # before the clinicians exist wait for them (EdgeMiddleware). Tests keep it synchronous.
    background = os.environ.get("SOLACE_SEED_BACKGROUND") == "1"
    _warmup_begin(background)
    if background:
        threading.Thread(target=_startup_work, args=(seed, settings.solace_warm_model, True),
                         name="seed-and-warm", daemon=True).start()
    else:
        _startup_work(seed, False, False)
        if settings.solace_warm_model:
            threading.Thread(target=_warm_triage_model, name="warm-triage-model", daemon=True).start()
    yield


def _seed_demo() -> int:
    ids = sandbox.seed_examples(settings.demo_hospital_id)
    log.info("demo hospital has %d example patients", len(ids))
    return len(ids)


def _startup_work(seed: bool, warm: bool, background: bool) -> None:
    try:
        accounts.seed_demo_clinicians(settings.demo_hospital_id)
        _clinicians_ready.set()
        _warmup_set(clinicians_ready=True, step="example_patients" if seed else None)
        if seed:
            _warmup_set(example_patients=_seed_demo())
        if warm:
            _warmup_set(step="model")
            _warm_triage_model()
        _warmup_finish("done")
    except Exception:  # noqa: BLE001 (a failed background seed must not take the server down)
        _warmup_finish("failed")
        if not background:
            raise
        log.exception("background seed failed")


def _model_state() -> str:
    """"ready", "not_installed" or "not_loaded_yet", read without waiting for a load."""
    try:
        from services import triage_ml  # noqa: PLC0415

        if not triage_ml._load_files.cache_info().currsize:
            return "not_loaded_yet"
        return "ready" if triage_ml._load_files() is not None else "not_installed"
    except Exception:  # noqa: BLE001 (health must answer whatever the model module does)
        return "not_loaded_yet"


def _warmup_status() -> dict:
    with _warmup_lock:
        out = dict(_warmup)
    if out["state"] == "running":
        out["seconds"] = round(time.monotonic() - _warmup_started, 2)
    out["model"] = _model_state()
    return out


app = FastAPI(title="Solace API", version="1.0.0", lifespan=lifespan)

VALIDATION_MESSAGE = (
    "Some of the information sent was not in the expected format. "
    "Reload the page and try again."
)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """A malformed request gets one plain sentence, not FastAPI's list of error objects.

    Only the field locations and error types are logged, never the values sent.
    """
    where = [".".join(str(p) for p in e.get("loc", ())) + f" ({e.get('type', '?')})" for e in exc.errors()[:5]]
    log.info("request validation failed: %s", ", ".join(where))
    return JSONResponse(status_code=422, content={"detail": VALIDATION_MESSAGE})


# ---- hospital gate + visitor identity ----------------------------------------------------
_API_HOSPITAL = re.compile(r"^/api/([^/]+)/")
# Answered for any sandbox id without making (or keeping alive) a sandbox for it.
_PROBE_PATH = re.compile(r"^/api/[^/]+/capabilities/?$")
_AUTH_PATH = re.compile(r"^/api/[^/]+/auth/")


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _served_as(scope, requested: str, effective: str) -> dict:
    """The same request with /api/<requested>/ rewritten to /api/<effective>/."""
    old, new = f"/api/{requested}/", f"/api/{effective}/"
    out = dict(scope)
    out["path"] = new + scope["path"][len(old):]
    raw = scope.get("raw_path")
    if isinstance(raw, (bytes, bytearray)) and raw.startswith(old.encode()):
        out["raw_path"] = new.encode() + bytes(raw[len(old):])
    return out


class HospitalGate:
    """For every /api/<hospital>/... request (local mode):

    - creates a private demo hospital (demo-xxxxxx) on its first request, unless that
      client already made its share of sandboxes or every slot is taken: then the id is
      served from the shared "demo" hospital (the path is rewritten, and the choice is
      remembered for that id), so a visitor never gets an error (lib/sandbox.py),
    - answers GET /capabilities for a sandbox id without creating a sandbox,
    - answers 404 "Unknown hospital" for any other id that does not exist, before
      the request runs (so a mistyped link fails on the first screen, not the last),
    - tags the request with the visitor's identity for the per-visitor AI limit.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or settings.solace_mode != "local":
            await self.app(scope, receive, send)
            return
        m = _API_HOSPITAL.match(scope.get("path") or "")
        if not m or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        hospital_id = m.group(1)
        refusal = None
        if sandbox.is_sandbox(hospital_id):
            if scope.get("method") in ("GET", "HEAD") and _PROBE_PATH.match(scope["path"]):
                effective = sandbox.alias_of(hospital_id) or hospital_id
            elif sandbox.is_live(hospital_id) or sandbox.alias_of(hospital_id):
                effective = sandbox.resolve(hospital_id)
            else:  # a new id: building a sandbox takes about a second, so not on the event loop
                effective = await run_in_threadpool(sandbox.resolve, hospital_id, quota.client_key())
            if effective != hospital_id:
                scope = _served_as(scope, hospital_id, effective)
        else:
            refusal = sandbox.admit(hospital_id)
        if sandbox.sweep_due():
            await run_in_threadpool(sandbox.sweep)
        if refusal:
            status, detail = refusal
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
            return

        token = spend.set_visitor(_visitor_identity(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            spend.reset_visitor(token)


def _visitor_identity(scope) -> str | None:
    try:  # identity_of reads the client address EdgeMiddleware resolved for this request
        return quota.identity_of(None, _header(scope, b"user-agent"))
    except Exception:  # noqa: BLE001 (never fail a request over the AI limit tag)
        return None


# ---- client address + security headers --------------------------------------------------
# The built app loads its own scripts and styles, Google Fonts (index.html), and shows
# photos and recordings from blob: and data: URLs. React sets inline style attributes,
# hence 'unsafe-inline' for styles only. /showcase frames the app's own pages, so framing
# is allowed for this origin and nobody else.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; worker-src 'self' blob:; "
    "frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
)
SECURITY_HEADERS = {
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=()",
}
# FastAPI's own API docs pages load their scripts from a CDN, so they skip the CSP.
_NO_CSP_PREFIXES = ("/docs", "/redoc")


class EdgeMiddleware:
    """Runs first for every HTTP request:

    - works out the client address once (lib/quota.client_ip: the last
      X-Forwarded-For entry, which the AWS proxy appends) for every limit and identity,
    - holds a sign-in request while startup is still creating the demo clinicians,
    - adds the security headers to every response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = quota.client_ip(_header(scope, b"x-forwarded-for"), client[0] if client else None)
        csp = not (scope.get("path") or "").startswith(_NO_CSP_PREFIXES)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers") or [])
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers.append(name, value)
                if csp and "content-security-policy" not in headers:
                    headers.append("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            await send(message)

        token = quota.set_request_ip(ip)
        try:
            if not _clinicians_ready.is_set() and _AUTH_PATH.match(scope.get("path") or ""):
                await run_in_threadpool(_clinicians_ready.wait, 30)
            await self.app(scope, receive, send_with_headers)
        finally:
            quota.reset_request_ip(token)


# Middleware added last runs first: EdgeMiddleware wraps compression, which wraps CORS,
# which wraps the gate, so the gate's 404 answers still carry CORS headers for the Vite
# dev server, and every answer carries the security headers.
app.add_middleware(HospitalGate)

_LOCAL_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def _build_cors_origins() -> list[str]:
    """Local dev ports, plus any extra origins passed in SOLACE_CORS_ORIGINS (comma-separated)."""
    origins = list(_LOCAL_ORIGINS)
    extra = os.environ.get("SOLACE_CORS_ORIGINS", "")
    origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)

# Text answers of 1 KB or more (the app's scripts and styles, index.html, JSON) go out
# gzipped to a browser that accepts it. Photos, audio and fonts are already compressed.
_COMPRESSIBLE = ("text/", "application/javascript", "application/json", "application/xml",
                 "application/manifest+json", "image/svg+xml")


class _TextGZipResponder(GZipResponder):
    async def send_with_gzip(self, message) -> None:
        await super().send_with_gzip(message)
        if message["type"] == "http.response.start":
            ctype = Headers(raw=message["headers"]).get("content-type", "")
            if not ctype.startswith(_COMPRESSIBLE) or ctype.startswith("text/event-stream"):
                self.content_encoding_set = True  # the GZip responder then sends it as is


class TextGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get("accept-encoding", ""):
            responder = _TextGZipResponder(self.app, self.minimum_size, compresslevel=self.compresslevel)
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)


# Inside EdgeMiddleware, so a compressed answer still gets the security headers.
app.add_middleware(TextGZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(EdgeMiddleware)


def _health_capabilities() -> dict:
    """The capabilities, without waiting for the bedside model to load.

    Asking the model module for its status loads the model (or waits for a load in
    progress), which can take many seconds right after startup. Until it has loaded,
    this reports the model as not loaded and leaves out the slower checks."""
    if _model_state() != "not_loaded_yet":
        return public.build_capabilities()
    from lib import claude  # noqa: PLC0415

    llm = public._safe(claude.available, False)
    return {"llm": llm, "ocr": llm, "triage_model": {"loaded": False, "mode": "rules_only", "folds": 0},
            "complete": False}


# async so it runs on the event loop: it never waits for a worker thread, even while
# startup work or slow requests hold them all.
@app.get("/health")
async def health() -> dict:
    from lib import claude  # noqa: PLC0415

    caps = _health_capabilities()
    return {
        "status": "ok",
        "mode": settings.solace_mode,
        "triage": caps["triage_model"]["mode"],
        "capabilities": caps,
        # On or off and why, failed calls, and the last failure as a code (never the key
        # or the AI service's own message).
        "ai": claude.health(),
        "ai_budget": spend.status(),
        "sandboxes": sandbox.stats(),
        "seeding": _warmup_status(),
    }


# Audio and photos are written to a local folder and served from /media.
if settings.solace_mode == "local":
    media_dir = Path(settings.local_media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

# Every router is mounted per hospital at /api/{hospital_id}/...
# Patient side: check-in, voice transcription, ID/insurance scan, pain flag.
app.include_router(public.router, prefix="/api/{hospital_id}", tags=["public"])
app.include_router(intake.router, prefix="/api/{hospital_id}", tags=["intake"])
app.include_router(transcribe.router, prefix="/api/{hospital_id}", tags=["transcribe"])
app.include_router(identity.router, prefix="/api/{hospital_id}", tags=["identity"])
app.include_router(insurance.router, prefix="/api/{hospital_id}", tags=["insurance"])
app.include_router(pain_flag.router, prefix="/api/{hospital_id}", tags=["pain-flag"])
app.include_router(sms_router.router, prefix="/api/{hospital_id}", tags=["sms"])
# Clinician side: sign-in, queue, bedside ML re-triage, notes, prescriptions, AI reasoning.
app.include_router(auth.router, prefix="/api/{hospital_id}", tags=["auth"])
app.include_router(patients.router, prefix="/api/{hospital_id}", tags=["patients"])
app.include_router(triage.router, prefix="/api/{hospital_id}", tags=["triage"])
app.include_router(notes.router, prefix="/api/{hospital_id}", tags=["notes"])
app.include_router(prescriptions.router, prefix="/api/{hospital_id}", tags=["prescriptions"])
app.include_router(clinical_ai.router, prefix="/api/{hospital_id}", tags=["clinical-ai"])
app.include_router(admin.router, prefix="/api/{hospital_id}", tags=["admin"])


# ---- built frontend (one-origin deploy) ------------------------------------------------
# Registered last so /api, /media and /health always win. Any other GET returns the
# file if it exists, else index.html, so client routes like /demo/clinician load.
# The folder is SOLACE_STATIC_DIR, or frontend/dist when it has been built.
_RESERVED_PREFIXES = ("api", "media", "health", "docs", "redoc", "openapi.json")


def _static_dir() -> Path | None:
    configured = settings.solace_static_dir.strip()
    path = Path(configured) if configured else ROOT / "frontend" / "dist"
    return path.resolve() if (path / "index.html").is_file() else None


_OG_IMAGE = re.compile(
    r'(<meta\s+(?:property="og:image"|name="twitter:image")\s+content=")(/[^"]*)(")'
)
_index_cache: dict[tuple, str] = {}
# Served when the built app has no robots.txt of its own.
ROBOTS_TXT = "User-agent: *\nAllow: /\n"
# The runtime config (config.json) inlined into index.html as a JSON data block, so the
# app can read it without waiting for a second request. A data block never runs, so
# the script-src policy is unchanged. /config.json is still served as before.
_CONFIG_BLOCK = '<script id="solace-runtime-config" type="application/json">{}</script>'


def _public_url() -> str | None:
    """SOLACE_PUBLIC_URL without a trailing slash, or None when unset or not http(s)."""
    url = (settings.solace_public_url or "").strip().rstrip("/")
    return url if re.match(r"^https?://[^\s\"'<>]+$", url) else None


def _runtime_config(dist: Path) -> str | None:
    """config.json as compact JSON that is safe inside a <script> block, or None."""
    try:
        data = json.loads((dist / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    text = json.dumps(data, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _index_html(index: Path) -> str | None:
    """index.html with absolute share-preview links and the runtime config inlined, or
    None to send the file as built (no public URL and no config.json)."""
    base = _public_url()
    config_file = index.parent / "config.json"
    config_mtime = config_file.stat().st_mtime if config_file.is_file() else None
    if base is None and config_mtime is None:
        return None
    key = (str(index), index.stat().st_mtime, base, config_mtime)
    if key not in _index_cache:
        text = index.read_text(encoding="utf-8")
        if base is not None:
            safe = html.escape(base, quote=True)
            text = _OG_IMAGE.sub(lambda m: f"{m.group(1)}{safe}{m.group(2)}{m.group(3)}", text)
            if 'property="og:url"' not in text:
                text = text.replace(
                    '<meta property="og:type"', f'<meta property="og:url" content="{safe}/" />\n    <meta property="og:type"', 1,
                )
        config = _runtime_config(index.parent)
        if config is not None and "</head>" in text:
            text = text.replace("</head>", _CONFIG_BLOCK.format(config) + "\n  </head>", 1)
        _index_cache.clear()
        _index_cache[key] = text
    return _index_cache[key]


def _index_response(dist: Path):
    index = dist / "index.html"
    rewritten = _index_html(index)
    if rewritten is None:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(rewritten, headers={"Cache-Control": "no-cache"})


@app.get("/{full_path:path}", include_in_schema=False)
def frontend(full_path: str):
    first = full_path.split("/", 1)[0]
    if first in _RESERVED_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")
    dist = _static_dir()
    if full_path == "robots.txt" and not (dist and (dist / "robots.txt").is_file()):
        return PlainTextResponse(ROBOTS_TXT, headers={"Cache-Control": "public, max-age=86400"})
    if dist is None:
        if not full_path:
            return {
                "status": "ok",
                "message": (
                    "This is the Solace API. To use the app, run the frontend "
                    "(cd frontend && npm run dev) and open http://localhost:5173, "
                    "or build it (npm run build) so this server can serve it."
                ),
            }
        raise HTTPException(status_code=404, detail="Not Found")
    if full_path:
        candidate = (dist / full_path).resolve()
        if candidate == dist / "index.html":
            return _index_response(dist)
        if candidate.is_file() and candidate.is_relative_to(dist):
            # Vite puts content-hashed files in /assets, so they can be cached for good.
            cache = "public, max-age=31536000, immutable" if first == "assets" else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        if first == "assets" or "." in full_path.rsplit("/", 1)[-1]:
            # A missing file (an old asset, a typo) is a real 404, not the app shell.
            raise HTTPException(status_code=404, detail="Not Found")
    return _index_response(dist)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")))
