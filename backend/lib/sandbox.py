"""Private demo hospitals, so visitors to the hosted demo never see each other's patients.

The front door gives every visitor their own hospital id, like demo-k3x9q2. The first
request for a new id creates that hospital on the spot: the hospital record, the three
demo clinicians (same PINs as the main demo), and the five example patients from
services/demo_seed.py. A sandbox nobody has used for 2 hours is deleted with all of its
data, and at most 300 can exist at once. In the shared "demo" hospital, check-ins older
than DEMO_WALKIN_MAX_HOURS (6 by default) are removed and the examples kept.

So one client cannot take every slot, a client address (lib/quota.client_key) may
create SANDBOX_CREATES_PER_CLIENT_HOUR new sandboxes in any 60 minutes (a sliding
window over the times it made them, so the allowance does not refill at the top of
the clock hour) and keep SANDBOX_LIVE_PER_CLIENT alive at once. When a new id cannot
get its own sandbox (one of those limits, or every slot in use), it is served from the shared "demo" hospital
instead: the middleware rewrites /api/demo-xxxxxx/... to /api/demo/... and the alias is
remembered, so that id keeps working the same way (sign-in, check-ins, polling) until it
sits idle as long as a sandbox would. A visitor never gets an error for this.

Valid ids: "demo" (the shared demo hospital) and "demo-" plus six lowercase letters or
digits. Any other id that is not a real hospital gets a plain 404 "Unknown hospital"
before the request runs (see the middleware in main.py). Local mode only: sandboxes
live in memory like everything else.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path

from lib.config import settings

log = logging.getLogger(__name__)

DEMO_ID_RX = re.compile(r"^demo(-[a-z0-9]{6})?$")
SWEEP_EVERY_SECONDS = 60
# Most aliases remembered at once; the least recently used is forgotten first.
ALIAS_MAX = 20_000
_ALIAS_LOG_EVERY = 10.0  # seconds between alias log lines (the count in between is kept)
CREATE_WINDOW_SECONDS = 3600  # the per-client creation limit counts the last hour


_lock = threading.RLock()
_last_seen: dict[str, float] = {}               # sandbox id -> last request time
_provisioning: dict[str, threading.Lock] = {}   # sandbox id -> lock while it is being built
_owner: dict[str, str] = {}                     # sandbox id -> client key that created it
_aliases: OrderedDict[str, float] = OrderedDict()  # id served by the shared demo -> last use
_demo_first_seen: dict[str, float] = {}         # shared demo patient id -> first sweep that saw it
_created_at: dict[str, deque[float]] = {}       # client key -> when it made sandboxes (last hour)
_last_sweep = 0.0
_alias_log = {"at": 0.0, "quiet": 0}


def is_demo_id(hospital_id: str | None) -> bool:
    """True for "demo" and for sandbox ids like demo-k3x9q2."""
    return bool(DEMO_ID_RX.match(hospital_id or ""))


def is_sandbox(hospital_id: str | None) -> bool:
    return is_demo_id(hospital_id) and hospital_id != "demo"


def is_live(hospital_id: str) -> bool:
    return hospital_id in _last_seen


def _idle_seconds() -> float:
    return max(60, int(settings.sandbox_idle_minutes) * 60)


def seed_examples(hospital_id: str) -> list[str]:
    """Add the five example patients to a hospital. Never raises; returns their ids."""
    try:
        from services import demo_seed  # noqa: PLC0415
    except ImportError:
        log.info("services.demo_seed is not available; skipping example patients")
        return []
    try:
        return list(demo_seed.seed_canonical_patients(hospital_id) or [])
    except Exception as e:  # noqa: BLE001 (example data must never block startup or a request)
        log.exception("seeding example patients for %s failed: %s", hospital_id, e)
        return []


def _provision(hospital_id: str) -> None:
    from db import storage  # noqa: PLC0415
    from lib import accounts  # noqa: PLC0415

    if not storage.get_hospital(hospital_id):
        storage.put_hospital({
            "hospital_id": hospital_id,
            "name": settings.demo_hospital_name,
            "sandbox": True,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
    accounts.seed_demo_clinicians(hospital_id)
    seeded = seed_examples(hospital_id)
    log.info("sandbox %s created with %d example patients (%d live)", hospital_id, len(seeded), len(_last_seen) + 1)


def shared_id() -> str:
    return settings.demo_hospital_id or "demo"


def alias_of(hospital_id: str) -> str | None:
    """The shared hospital id if this sandbox id is being served from it, else None."""
    return shared_id() if hospital_id in _aliases else None


def _alias_locked(hospital_id: str, now: float, reason: str) -> str:
    _aliases[hospital_id] = now
    _aliases.move_to_end(hospital_id)
    while len(_aliases) > ALIAS_MAX:
        _aliases.popitem(last=False)
    if now - _alias_log["at"] >= _ALIAS_LOG_EVERY:
        log.warning(
            "sandbox %s is served from the shared demo hospital (%s; %d live of %d, "
            "%d aliased, %d more since the last line)",
            hospital_id, reason, len(_last_seen), int(settings.sandbox_max),
            len(_aliases), _alias_log["quiet"],
        )
        _alias_log["at"], _alias_log["quiet"] = now, 0
    else:
        _alias_log["quiet"] += 1
    return shared_id()


def _recent_creations_locked(client_key: str, now: float) -> deque[float]:
    """This client's creation times in the last hour (older ones are dropped)."""
    times = _created_at.setdefault(client_key, deque())
    while times and now - times[0] >= CREATE_WINDOW_SECONDS:
        times.popleft()
    return times


def _no_room_locked(client_key: str | None, now: float | None = None) -> str | None:
    """Why a new sandbox cannot be made right now, or None. Records the creation
    against the client's allowance (any 60 minutes, not the clock hour) when it can."""
    if len(_last_seen) + len(_provisioning) >= int(settings.sandbox_max):
        return "every sandbox slot is in use"
    if not client_key:
        return None
    if sum(1 for owner in _owner.values() if owner == client_key) >= int(settings.sandbox_live_per_client):
        return "this client already has its limit of live sandboxes"
    now = time.time() if now is None else now
    times = _recent_creations_locked(client_key, now)
    if len(times) >= max(0, int(settings.sandbox_creates_per_client_hour)):
        return "this client made its limit of new sandboxes in the last hour"
    times.append(now)
    return None


def resolve(hospital_id: str, client_key: str | None = None) -> str:
    """The hospital id a request for this sandbox id should run against.

    A live sandbox is marked as used and keeps its own id. A new id gets its own
    sandbox (built here, which takes about a second) when there is room for it, and
    otherwise, or if building it fails, is served from the shared demo hospital from
    now on. Never raises.
    """
    now = time.time()
    with _lock:
        if hospital_id in _last_seen:
            _last_seen[hospital_id] = now
            return hospital_id
        if hospital_id in _aliases:
            _aliases[hospital_id] = now
            _aliases.move_to_end(hospital_id)
            return shared_id()
        plock = _provisioning.get(hospital_id)
        if plock is None:
            _sweep_locked(now)
            reason = _no_room_locked(client_key, now)
            if reason:
                return _alias_locked(hospital_id, now, reason)
            plock = _provisioning[hospital_id] = threading.Lock()
            if client_key:
                _owner[hospital_id] = client_key
    with plock:
        with _lock:
            if hospital_id in _last_seen:  # built by a concurrent request while we waited
                _last_seen[hospital_id] = time.time()
                return hospital_id
            if hospital_id in _aliases:
                return shared_id()
        try:
            _provision(hospital_id)
        except Exception as e:  # noqa: BLE001 (a visitor must still get a working demo)
            log.exception("building sandbox %s failed: %s", hospital_id, e)
            with _lock:
                _provisioning.pop(hospital_id, None)
                try:
                    purge(hospital_id)  # drop whatever was half made
                except Exception:  # noqa: BLE001
                    _owner.pop(hospital_id, None)
                return _alias_locked(hospital_id, time.time(), "building it failed")
        with _lock:
            _provisioning.pop(hospital_id, None)
            _last_seen[hospital_id] = time.time()
    return hospital_id


def touch_or_provision(hospital_id: str, client_key: str | None = None) -> str:
    """Older name for resolve()."""
    return resolve(hospital_id, client_key)


def hospital_known(hospital_id: str) -> bool:
    """A non-sandbox id is valid if the hospital exists or already has patients."""
    from db import storage  # noqa: PLC0415

    if hospital_id in (settings.demo_hospital_id, "demo") or storage.get_hospital(hospital_id):
        return True
    return bool(storage.list_patients_for_hospital(hospital_id, status="all"))


def admit(hospital_id: str, client_key: str | None = None) -> tuple[int, str] | None:
    """None if requests for this hospital may run, else (status, plain message).

    A sandbox id is always admitted (see resolve(), which the middleware uses to learn
    whether it runs as itself or as the shared demo hospital)."""
    if is_sandbox(hospital_id):
        resolve(hospital_id, client_key)
        return None
    if hospital_known(hospital_id):
        return None
    return 404, "Unknown hospital"


# ---- cleanup ---------------------------------------------------------------------------
def purge(hospital_id: str) -> int:
    """Delete a sandbox and everything in it. Returns how many patients were removed."""
    from db import storage  # noqa: PLC0415
    from lib import accounts  # noqa: PLC0415

    with _lock:
        _last_seen.pop(hospital_id, None)
        _owner.pop(hospital_id, None)
        pids = [p.get("patient_id") for p in storage.list_patients_for_hospital(hospital_id, status="all")]
        removed = storage.delete_hospital(hospital_id)
        accounts.remove_hospital_accounts(hospital_id)
    _delete_media([pid for pid in pids if pid])
    return removed


def _delete_media(patient_ids: list[str]) -> None:
    base = Path(settings.local_media_dir)
    for kind in ("audio", "photos"):
        folder = base / kind
        if not folder.is_dir():
            continue
        for pid in patient_ids:
            for f in folder.glob(f"{pid}*"):
                try:
                    f.unlink()
                except OSError:
                    pass


def is_example(patient: dict) -> bool:
    """True for the example patients from services/demo_seed.py."""
    return bool(patient.get("seed") or patient.get("demo_seed") or patient.get("canonical"))


def prune_shared_demo(now: float | None = None) -> int:
    """Remove check-ins that have been in the shared demo hospital longer than
    DEMO_WALKIN_MAX_HOURS, then put back any example patient that is missing.
    Returns how many were removed.

    Age is counted from when a sweep first saw the patient, not from created_at,
    which a caller (or a test) may set to any time."""
    from db import storage  # noqa: PLC0415

    hours = float(settings.demo_walkin_max_hours or 0)
    if hours <= 0:
        return 0
    now = time.time() if now is None else now
    present: set[str] = set()
    old: list[str] = []
    for p in storage.list_patients_for_hospital(settings.demo_hospital_id, status="all"):
        pid = p.get("patient_id")
        if not pid or is_example(p):
            continue
        present.add(pid)
        if now - _demo_first_seen.setdefault(pid, now) > hours * 3600:
            old.append(pid)
    for pid in [k for k in _demo_first_seen if k not in present]:
        _demo_first_seen.pop(pid, None)
    for pid in old:
        storage.delete_patient(pid)
        _demo_first_seen.pop(pid, None)
    if old:
        _delete_media(old)
        seed_examples(settings.demo_hospital_id)
        log.info("removed %d check-ins older than %g hours from the shared demo hospital", len(old), hours)
    return len(old)


def _sweep_locked(now: float) -> list[str]:
    """Delete every sandbox idle longer than the limit. The caller holds _lock, so a
    request for an expiring id waits and then gets a fresh sandbox."""
    global _last_sweep
    _last_sweep = now
    idle = [h for h, ts in _last_seen.items() if now - ts > _idle_seconds()]
    for h in idle:
        try:
            n = purge(h)
            log.info("sandbox %s expired; removed %d patients", h, n)
        except Exception as e:  # noqa: BLE001
            _last_seen.pop(h, None)
            _owner.pop(h, None)
            log.warning("could not purge sandbox %s: %s", h, e)
    # Forget aliases nobody has used for as long as a sandbox may sit idle. The dict is
    # kept in order of last use, so the stale ones are at the front.
    while _aliases:
        _, ts = next(iter(_aliases.items()))
        if now - ts <= _idle_seconds():
            break
        _aliases.popitem(last=False)
    # Forget clients whose last creation is more than an hour old.
    for key in [k for k, times in _created_at.items() if not times or now - times[-1] >= CREATE_WINDOW_SECONDS]:
        _created_at.pop(key, None)
    try:
        prune_shared_demo(now)
    except Exception as e:  # noqa: BLE001 (cleanup must never fail a request)
        log.warning("could not prune the shared demo hospital: %s", e)
    return idle


def sweep_due() -> bool:
    return time.time() - _last_sweep >= SWEEP_EVERY_SECONDS


def sweep() -> list[str]:
    """Delete idle sandboxes now. Returns the ids removed."""
    with _lock:
        return _sweep_locked(time.time())


def stats() -> dict:
    return {"live": len(_last_seen), "max": int(settings.sandbox_max), "shared_aliases": len(_aliases)}


def _reset_for_tests() -> None:
    global _last_sweep
    with _lock:
        _last_seen.clear()
        _provisioning.clear()
        _owner.clear()
        _aliases.clear()
        _demo_first_seen.clear()
        _created_at.clear()
        _alias_log.update(at=0.0, quiet=0)
        _last_sweep = 0.0
