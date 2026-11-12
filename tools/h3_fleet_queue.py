#!/usr/bin/env python3
"""Fleet-wide concurrency queue for HopsAPI MiniMax-H3 video tasks (line owner 2026-11-12).

The HopsAPI account runs at most 5 H3 tasks at once for the WHOLE fleet; every device's S6 waves share it, and a
task over the limit comes back status 3 "Provider error" at cost 0.  The nalu-fleet service keeps a lease-based
semaphore (``POST /v1/h3/acquire|renew|release``, FIFO waiters, leases expire unless renewed).

* ``acquire(task_key, episode)`` -- called by the submitter right before the H3 create POST (after the
  prior-binding / live-binding checks decided a POST will happen, before the reference uploads).  Blocks,
  polling every ``retry_after_s``, until the fleet grants a lease; while it waits it settles this device's own
  leased tasks (``reap_own``: free status GETs, record_settlement, release) so a wave whose earlier tasks finish
  frees its slots without waiting for the poll step.  Gives up after ``NALU_H3_QUEUE_MAX_WAIT_S`` (default 4 h)
  with ``H3QueueTimeout`` -- a pre-intent failure, nothing recorded, nothing charged.
* ``bind`` / ``renew`` / ``release`` -- the lease is stored on the transaction row (``h3_lease``); it is renewed
  while the task renders and released when ``hopsapi_video_client.record_settlement`` records a terminal state,
  or when the POST provably created no task.  A lost create response keeps its lease until it expires (a task
  may be rendering).
* Fallback: fleet off (``NALU_FLEET_URL=off``), unreachable, no token, or a server without the queue -> this
  device runs at most ONE H3 task at a time (a lease file under ``$NALU_RUNTIME_ROOT/runtime/h3_queue``) and
  proceeds; ``mode: "local"`` + ``fallback_reason`` are recorded on the lease.

Active only on a device runtime (``NALU_RUNTIME_ROOT`` set) unless ``NALU_H3_QUEUE=on``; ``NALU_H3_QUEUE=off``
disables it.  Never raises from renew/release; never prints the fleet token.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

ENGINE = Path(__file__).resolve().parents[1]
FLEET_SCRIPTS = ENGINE / "skills" / "nalu-claude-code" / "scripts"
DEFAULT_MAX_WAIT_S = 4 * 3600
LEASE_TTL_S = 900          # local leases; the fleet sends its own ttl
LOCAL_CAPACITY = 1
LOCAL_POLL_S = 15
REAP_MIN_INTERVAL_S = 20
RELEASE_REASONS = ("completed", "failed", "cancelled", "submit_failed")

_sleep = time.sleep   # module hooks (tests patch these)
_clock = time.time
_reap_lock = threading.Lock()
_last_reap = [0.0]


class H3QueueTimeout(RuntimeError):
    """No H3 slot within the wait cap; raised before any intent or POST (not charged)."""


class FleetUnavailable(Exception):
    pass


def enabled() -> bool:
    flag = os.environ.get("NALU_H3_QUEUE", "").strip().lower()
    if flag in ("off", "0", "false", "no"):
        return False
    if flag in ("on", "1", "true", "yes"):
        return True
    return bool(os.environ.get("NALU_RUNTIME_ROOT", "").strip())


def max_wait_s() -> int:
    try:
        return max(0, int(os.environ.get("NALU_H3_QUEUE_MAX_WAIT_S") or DEFAULT_MAX_WAIT_S))
    except ValueError:
        return DEFAULT_MAX_WAIT_S


def runtime_root() -> Path:
    return Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()


def state_dir() -> Path:
    d = runtime_root() / "runtime" / "h3_queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iso(t: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    print(f"[h3-queue] {msg}", file=sys.stderr, flush=True)


def _event(kind: str, **fields: Any) -> None:
    try:
        with (state_dir() / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": _iso(), "event": kind, **fields}, ensure_ascii=False) + "\n")
    except OSError:
        pass


@contextlib.contextmanager
def _locked_json(name: str) -> Iterator[dict]:
    """Read-modify-write a small JSON file under its own short flock (never the transaction lock)."""
    d = state_dir()
    with (d / f".{name}.lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        path = d / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        yield data
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)


# ------------------------------------------------------------------ fleet transport (reuses fleet_sync)
def _fleet_sync():
    if str(FLEET_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(FLEET_SCRIPTS))
    import fleet_sync  # noqa: PLC0415
    return fleet_sync


def _post(path: str, body: dict) -> dict:
    try:
        fs = _fleet_sync()
    except Exception as exc:  # noqa: BLE001
        raise FleetUnavailable(f"FLEET_CLIENT_IMPORT:{type(exc).__name__}") from None
    if not fs._url():
        raise FleetUnavailable("FLEET_OFF")
    runtime = runtime_root()
    try:
        token = (runtime / "credentials" / "fleet_token").read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    try:
        if not token:
            import device_sn  # noqa: PLC0415  (same scripts dir)
            sn, _source = device_sn.resolve()
            if not sn:
                raise FleetUnavailable("NO_DEVICE_SN")
            token = fs._token(runtime, sn)
        if not token:
            raise FleetUnavailable("NO_FLEET_TOKEN")
        code, out = fs._req("POST", path, body, token=token)
    except FleetUnavailable:
        raise
    except (OSError, ValueError) as exc:  # URLError / timeout / reset / bad JSON
        raise FleetUnavailable(f"FLEET_UNREACHABLE:{type(exc).__name__}") from None
    if code == 401:
        raise FleetUnavailable("FLEET_TOKEN_REJECTED")
    if code == 404 and (out or {}).get("error") == "NOT_FOUND":
        raise FleetUnavailable("FLEET_H3_QUEUE_NOT_DEPLOYED")
    if code != 200:
        raise FleetUnavailable(f"FLEET_HTTP_{code}")
    return out or {}


# ------------------------------------------------------------------ local fallback slot (cap 1 per device)
def _local_try_acquire(task_key: str, episode: str, t: float) -> str | None:
    with _locked_json("local_slots.json") as data:
        holders = {k: v for k, v in (data.get("holders") or {}).items() if float(v.get("expires_at") or 0) > t}
        data["holders"] = holders
        for lid, row in holders.items():
            if row.get("task_key") == task_key and row.get("episode") == episode:
                row["expires_at"] = t + LEASE_TTL_S
                return lid
        if len(holders) >= LOCAL_CAPACITY:
            return None
        lid = "local_" + uuid.uuid4().hex[:20]
        holders[lid] = {"task_key": task_key, "episode": episode, "granted_at": t, "expires_at": t + LEASE_TTL_S}
        return lid


def _local_renew(lease_id: str, t: float) -> bool:
    with _locked_json("local_slots.json") as data:
        row = (data.get("holders") or {}).get(lease_id)
        if row is None:
            return False
        row["expires_at"] = t + LEASE_TTL_S
        return True


def _local_release(lease_id: str) -> None:
    with _locked_json("local_slots.json") as data:
        (data.get("holders") or {}).pop(lease_id, None)


# ------------------------------------------------------------------ registry of this device's open leases
def _registry_put(lease_id: str, **fields: Any) -> None:
    with _locked_json("leases.json") as data:
        data.setdefault("leases", {}).setdefault(lease_id, {}).update(fields)


def _registry_pop(lease_id: str) -> None:
    with _locked_json("leases.json") as data:
        (data.get("leases") or {}).pop(lease_id, None)


def _registry() -> dict[str, dict]:
    with _locked_json("leases.json") as data:
        return dict(data.get("leases") or {})


# ------------------------------------------------------------------ public API
def acquire(task_key: str, episode: str, *, transaction: Path | None = None,
            sleep: Callable[[float], None] | None = None, clock: Callable[[], float] | None = None,
            reap: Callable[..., Any] | None = None) -> dict | None:
    """Block until this H3 task may POST.  Returns the lease record to store on the transaction, or None when
    the queue is disabled.  Raises H3QueueTimeout after max_wait_s() (nothing recorded, nothing charged)."""
    if not enabled():
        return None
    reap = reap_own if reap is None else reap
    sleep = _sleep if sleep is None else sleep
    clock = _clock if clock is None else clock
    start = clock()
    cap_s = max_wait_s()
    mode, reason = "fleet", None
    last_pos: Any = None
    max_pos = 0
    while True:
        if mode == "fleet":
            try:
                out = _post("/v1/h3/acquire", {"task_key": task_key, "episode": episode})
            except FleetUnavailable as exc:
                mode, reason = "local", str(exc)
                _log(f"{task_key}: fleet queue unavailable ({reason}); local fallback, 1 H3 task at a time on "
                     "this device")
                _event("fallback", task_key=task_key, episode=episode, reason=reason)
                continue
            if out.get("granted") and out.get("lease_id"):
                lease = {"lease_id": str(out["lease_id"]), "mode": "fleet", "ttl_s": out.get("ttl_s")}
                break
            pos = out.get("position")
            max_pos = max(max_pos, int(pos or 0))
            if pos != last_pos:
                _log(f"{task_key}: waiting for an H3 slot, queue position {pos} "
                     f"(fleet active {out.get('active')}/{out.get('capacity')})")
                last_pos = pos
            wait = min(30.0, max(5.0, float(out.get("retry_after_s") or 15)))
        else:
            lid = _local_try_acquire(task_key, episode, clock())
            if lid:
                lease = {"lease_id": lid, "mode": "local", "fallback_reason": reason}
                break
            if last_pos != "local":
                _log(f"{task_key}: waiting for the local H3 slot (fallback cap {LOCAL_CAPACITY})")
                last_pos = "local"
            wait = float(LOCAL_POLL_S)
        waited = clock() - start
        if waited + wait > cap_s:
            _event("timeout", task_key=task_key, episode=episode, waited_s=round(waited), mode=mode)
            raise H3QueueTimeout(
                f"{task_key} H3_FLEET_QUEUE_WAIT_TIMEOUT: no MiniMax-H3 slot after {round(waited)} s "
                f"(cap NALU_H3_QUEUE_MAX_WAIT_S={cap_s}, mode={mode}, last position {last_pos}); "
                "not charged, no intent recorded -- re-run S6 to queue again")
        try:
            reap(skip_transaction=transaction)
        except Exception as exc:  # noqa: BLE001 -- reaping is best effort
            _log(f"reap skipped: {type(exc).__name__}")
        sleep(wait)
    waited = round(clock() - start)
    lease.update({"task_key": task_key, "episode": episode, "granted_at": _iso(clock()), "waited_s": waited,
                  "max_queue_position": max_pos})
    _registry_put(lease["lease_id"], mode=lease["mode"], task_key=task_key, episode=episode,
                  transaction=str(transaction) if transaction else None, task_id=None, granted_epoch=clock())
    _event("acquire", **{k: lease.get(k) for k in ("lease_id", "mode", "task_key", "episode", "waited_s",
                                                    "max_queue_position", "fallback_reason")})
    if waited >= 5:
        _log(f"{task_key}: H3 slot granted after {waited} s ({lease['mode']})")
    return lease


def renew(lease: dict | None, provider_task_id: str = "") -> bool:
    """Extend the lease (and tell the fleet the provider task id).  Never raises."""
    if not lease or not lease.get("lease_id"):
        return False
    try:
        if lease.get("mode") == "local":
            return _local_renew(str(lease["lease_id"]), time.time())
        out = _post("/v1/h3/renew", {"lease_id": lease["lease_id"], "provider_task_id": provider_task_id or ""})
        return bool(out.get("ok"))
    except Exception:  # noqa: BLE001 -- an unreachable fleet lets the lease expire, never breaks the caller
        return False


def bind(lease: dict | None, task_id: str, transaction: Path) -> None:
    """The create POST returned a task id: remember it for reaping and renew with it."""
    if not lease or not lease.get("lease_id"):
        return
    try:
        _registry_put(str(lease["lease_id"]), task_id=str(task_id), transaction=str(transaction))
    except Exception:  # noqa: BLE001
        pass
    renew(lease, str(task_id))


def release(lease: dict | None, reason: str) -> bool:
    """Free the slot.  Never raises; an unreachable fleet lets the lease expire instead."""
    if not lease or not lease.get("lease_id"):
        return False
    reason = reason if reason in RELEASE_REASONS else "failed"
    lid = str(lease["lease_id"])
    ok = False
    try:
        if lease.get("mode") == "local":
            _local_release(lid)
            ok = True
        else:
            ok = bool(_post("/v1/h3/release", {"lease_id": lid, "reason": reason}).get("ok"))
    except Exception:  # noqa: BLE001
        ok = False
    with contextlib.suppress(Exception):
        _registry_pop(lid)
        _event("release", lease_id=lid, mode=lease.get("mode"), reason=reason, ok=ok,
               task_key=lease.get("task_key"))
    return ok


def renew_for_transaction(transaction: Path | None, task_id: str) -> bool:
    """Poll path: the task is still rendering -> renew the lease recorded on its transaction (read only)."""
    if transaction is None:
        return False
    try:
        row = json.loads(Path(transaction).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    lease = row.get("h3_lease")
    if not isinstance(lease, dict) or lease.get("released_at") or str(row.get("task_id") or "") != str(task_id):
        return False
    return renew(lease, str(task_id))


def _try_settle(path: Path, task_id: str, status: dict) -> bool:
    """record_settlement without ever waiting on a transaction lock another thread holds (a submit worker keeps
    its own transaction's flock while it waits in acquire: waiting on it here would stall every waiter)."""
    try:
        import hopsapi_video_client as hopsapi  # noqa: PLC0415
    except ModuleNotFoundError:
        from tools import hopsapi_video_client as hopsapi  # noqa: PLC0415
    return hopsapi.record_settlement(path, task_id, status, now=_iso(), blocking=False) is not None


def reap_own(*, skip_transaction: Path | None = None, query: Callable[[str], dict] | None = None,
             force: bool = False) -> int:
    """Settle this device's own leased H3 tasks while a submit worker waits: a free status GET each; a terminal
    one gets record_settlement (which releases its lease), a running one is renewed.  Throttled and
    single-flight across threads.  Returns the number of leases released."""
    if not _reap_lock.acquire(blocking=False):
        return 0
    try:
        now_t = time.time()
        if not force and now_t - _last_reap[0] < REAP_MIN_INTERVAL_S:
            return 0
        _last_reap[0] = now_t
        if query is None:
            try:
                import hopsapi_video_client as hopsapi  # noqa: PLC0415
            except ModuleNotFoundError:
                from tools import hopsapi_video_client as hopsapi  # noqa: PLC0415
            query = hopsapi.query_task
        skip = str(Path(skip_transaction).resolve()) if skip_transaction else None
        released = 0
        for lid, entry in _registry().items():
            lease = {"lease_id": lid, "mode": entry.get("mode"), "task_key": entry.get("task_key")}
            tx, task_id = entry.get("transaction"), entry.get("task_id")
            if not task_id:
                if now_t - float(entry.get("granted_epoch") or now_t) > 2 * LEASE_TTL_S:
                    _registry_pop(lid)  # never bound (crashed between grant and POST): the lease expired
                continue
            path = Path(tx) if tx else None
            if path is None or not path.is_file():
                released += release(lease, "cancelled")
                continue
            if skip and str(path.resolve()) == skip:
                continue
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            row_lease = row.get("h3_lease") if isinstance(row.get("h3_lease"), dict) else {}
            if str(row.get("task_id") or "") != str(task_id) or row_lease.get("lease_id") != lid \
                    or row_lease.get("released_at"):
                # the row moved on (released to a new attempt, or already settled + released): free the slot
                released += release(lease, str(row_lease.get("release_reason") or "failed"))
                continue
            try:
                status = query(str(task_id))
            except Exception:  # noqa: BLE001 -- a failed GET just tries again next round
                continue
            if status.get("remote_status") in ("completed", "failed", "cancelled"):
                if _try_settle(path, str(task_id), status):
                    released += 1
            else:
                renew(lease, str(task_id))
        return released
    finally:
        _reap_lock.release()
