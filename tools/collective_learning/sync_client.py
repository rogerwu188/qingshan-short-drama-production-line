"""Device-side uploader and bundle puller.

Upload (push): drains ``DeviceStore``'s outbox in bounded batches, one request per
item kind.  Per item:

  CREATED / DUPLICATE  -> mark DELIVERED (the service persisted it; a DUPLICATE is
                          exactly what a lost response looks like on the retry)
  CONFLICT / REJECTED  -> QUARANTINE locally with the service's codes; never
                          re-sent automatically, never blocks the rest of the queue
  no ack for the item  -> retry later
  transport error, timeout, 5xx, 429, 401/403
                       -> retry with full-jitter exponential backoff (``mark_retry``)

Nothing here ever blocks a production step: ``run_once`` returns a summary and
swallows transport failures; ``BackgroundSync`` runs it on a daemon thread.  A
cloud outage therefore means "events wait in the outbox", never "paid work waits
for the cloud".

Pull: ``pull_bundles`` resolves applicable bundles and fetches each exact version.
Verification and caching belong to ``bundles`` (signature, digest, immutable cache);
this module only transports bytes and hands each fetched record to the ``accept``
hook (default: ``bundles.accept_fetched_bundle`` when that function exists).  When
the service is unreachable the result is ``OFFLINE`` and the caller keeps using its
locked local snapshot.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

from .device_store import DeviceStore

ROUTE_BY_KIND = {
    "EVENT": ("/v1/events:batch", "events"),
    "REVIEW": ("/v1/reviews", "reviews"),
    "ADOPTION": ("/v1/adoptions:batch", "receipts"),
    "EVALUATION": ("/v1/evaluations", "evaluations"),
}
DELIVERED_STATUSES = ("CREATED", "DUPLICATE")
QUARANTINE_STATUSES = ("CONFLICT", "REJECTED")
#: The transport accepted the batch into a durable inbox but no authority has judged it yet (S3 mode).
#: Items stay PENDING with a normal backoff and are re-sent until the collector's ack arrives; the
#: re-send is idempotent on the transport side.  Never counted as delivered, never as an error.
IN_FLIGHT_STATUS = "IN_FLIGHT"
RETRYABLE_HTTP = {401, 403, 408, 425, 429, 500, 502, 503, 504}


class TransportError(Exception):
    """The request may or may not have reached the service; the response is unknown."""


class Transport(Protocol):
    def request(self, method: str, path: str, body: Any | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, Any, dict[str, str]]: ...


class HttpTransport:
    """urllib transport with a hard timeout.  Never logs or returns the token."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, Any, dict[str, str]]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {}), dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {"raw": raw[:200].decode("utf-8", "replace")}
            return exc.code, payload, dict(exc.headers.items()) if exc.headers else {}
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise TransportError(f"{type(exc).__name__}:{exc}") from exc


class SyncClient:
    def __init__(self, store: DeviceStore, transport: Transport, *, batch_size: int = 100,
                 max_batches_per_run: int = 50, backoff_base: float = 1.0, backoff_cap: float = 300.0):
        self.store = store
        self.transport = transport
        self.batch_size = max(1, int(batch_size))
        self.max_batches_per_run = max(1, int(max_batches_per_run))
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    # ------------------------------------------------------------------ push
    def run_once(self, *, now: float | None = None) -> dict[str, Any]:
        summary = {"sent": 0, "delivered": 0, "quarantined": 0, "retry": 0, "in_flight": 0, "batches": 0, "errors": []}
        for _ in range(self.max_batches_per_run):
            due = self.store.claim_due(self.batch_size, now=now)
            if not due:
                break
            by_kind: dict[str, list[dict[str, Any]]] = {}
            for item in due:
                by_kind.setdefault(item["item_kind"], []).append(item)
            progressed = False
            # Facts before the revisions that cite them: a review uploaded ahead of its event
            # is rejected with EVENT_NOT_FOUND, so kinds go in ROUTE_BY_KIND's dependency order.
            for kind in sorted(by_kind, key=lambda k: list(ROUTE_BY_KIND).index(k) if k in ROUTE_BY_KIND else 99):
                items = by_kind[kind]
                result = self._send_kind(kind, items, now=now)
                summary["batches"] += 1
                summary["sent"] += len(items)
                for key in ("delivered", "quarantined", "retry", "in_flight"):
                    summary[key] += result.get(key, 0)
                if result.get("error"):
                    summary["errors"].append(result["error"])
                progressed = progressed or result["delivered"] or result["quarantined"]
            if not progressed:
                break  # everything due went back to backoff; stop hammering
        summary["outbox"] = self.store.outbox_status()["counts"]
        return summary

    def _send_kind(self, kind: str, items: list[dict[str, Any]], *, now: float | None) -> dict[str, Any]:
        out = {"delivered": 0, "quarantined": 0, "retry": 0, "in_flight": 0}
        route = ROUTE_BY_KIND.get(kind)
        if route is None:
            for item in items:
                self.store.quarantine(item["outbox_id"], f"UNKNOWN_OUTBOX_KIND:{kind}")
            out["quarantined"] = len(items)
            return out
        path, key = route
        ids = [i["outbox_id"] for i in items]
        try:
            status, body, _ = self.transport.request("POST", path, {key: [i["payload"] for i in items]})
        except TransportError as exc:
            self.store.mark_retry(ids, f"TRANSPORT:{exc}", base=self.backoff_base, cap=self.backoff_cap, now=now)
            out["retry"] = len(ids)
            out["error"] = f"TRANSPORT:{exc}"
            return out
        if status == 413 and len(items) > 1:
            self.batch_size = max(1, self.batch_size // 2)
            self.store.mark_retry(ids, "BATCH_TOO_LARGE", base=0.0, cap=0.0, now=now)
            out["retry"] = len(ids)
            out["error"] = f"HTTP_413:batch_size_now={self.batch_size}"
            return out
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("results"), list):
            code = ((body or {}).get("error") or {}).get("code") if isinstance(body, dict) else None
            if status in RETRYABLE_HTTP or status >= 500 or status == 200:
                self.store.mark_retry(ids, f"HTTP_{status}:{code}", base=self.backoff_base, cap=self.backoff_cap,
                                      now=now)
                out["retry"] = len(ids)
            else:  # a whole-batch 4xx that is not about auth/backpressure: the items themselves are unusable
                for oid in ids:
                    self.store.quarantine(oid, f"HTTP_{status}:{code}:{json.dumps(body, ensure_ascii=False)[:500]}")
                out["quarantined"] = len(ids)
            out["error"] = f"HTTP_{status}:{code}"
            return out
        acks = {str(r.get("id")): r for r in body["results"] if isinstance(r, dict)}
        delivered, retry, in_flight = [], [], []
        for item in items:
            ack = acks.get(str(item["item_id"]))
            if ack is None:
                retry.append(item["outbox_id"])
            elif ack.get("status") in DELIVERED_STATUSES:
                delivered.append((item["outbox_id"], ack))
            elif ack.get("status") in QUARANTINE_STATUSES:
                self.store.quarantine(item["outbox_id"], f"{ack['status']}:{','.join(ack.get('codes') or [])}")
                out["quarantined"] += 1
            elif ack.get("status") == IN_FLIGHT_STATUS:
                in_flight.append(item["outbox_id"])
            else:
                retry.append(item["outbox_id"])
        if delivered:
            self.store.mark_delivered(delivered)
        if retry:
            self.store.mark_retry(retry, "NO_ACK_FOR_ITEM", base=self.backoff_base, cap=self.backoff_cap, now=now)
        if in_flight:
            # due again on the next run (the agent interval is the pacing); run_once itself never loops on it
            self.store.mark_retry(in_flight, "IN_FLIGHT_AWAITING_COLLECT", base=0.0, cap=0.0, now=now)
        out["delivered"] = len(delivered)
        out["retry"] += len(retry)
        out["in_flight"] = len(in_flight)
        return out

    # ------------------------------------------------------------------ pull
    def pull_bundles(self, capabilities: dict[str, Any], *, channels: list[str] | None = None,
                     accept: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
        """Resolve and fetch exact versions.  Never raises for a network problem.

        ``accept`` receives each fetched bundle record (``payload_b64``, ``digest``,
        ``signature_b64``, ``key_id``, ``manifest``) and is responsible for
        verification and caching.  Default: ``bundles.accept_fetched_bundle``.
        """
        if accept is None:
            try:
                from . import bundles as _bundles
                accept = getattr(_bundles, "accept_fetched_bundle", None)
            except ImportError:
                accept = None
        body: dict[str, Any] = {"capabilities": capabilities}
        if channels:
            body["channels"] = channels
        try:
            status, resolved, _ = self.transport.request("POST", "/v1/bundles:resolve", body)
        except TransportError as exc:
            return {"status": "OFFLINE", "error": str(exc), "fetched": []}
        if status != 200:
            return {"status": "RESOLVE_FAILED", "http_status": status, "body": resolved, "fetched": []}
        fetched = []
        for entry in resolved.get("bundles") or []:
            try:
                st, record, _ = self.transport.request(
                    "GET", f"/v1/bundles/{entry['bundle_id']}/versions/{entry['version']}")
            except TransportError as exc:
                fetched.append({**entry, "status": "OFFLINE", "error": str(exc)})
                continue
            if st != 200:
                fetched.append({**entry, "status": "FETCH_FAILED", "http_status": st})
                continue
            if record.get("digest") != entry["digest"]:
                fetched.append({**entry, "status": "DIGEST_MISMATCH_WITH_RESOLVE"})
                continue
            accepted = accept(record) if accept else None
            fetched.append({**entry, "status": "FETCHED", "accepted": accepted,
                            "accept_hook": getattr(accept, "__name__", None) if accept else "NONE_AVAILABLE"})
        return {"status": "OK", "resolved": resolved, "fetched": fetched}


class BackgroundSync:
    """Run ``SyncClient.run_once`` every ``interval`` seconds on a daemon thread."""

    def __init__(self, client: SyncClient, *, interval: float = 5.0):
        self.client = client
        self.interval = interval
        self.stop_event = threading.Event()
        self.last_summary: dict[str, Any] | None = None
        self.last_error: str | None = None
        self._thread = threading.Thread(target=self._loop, name="collective-sync", daemon=True)

    def start(self) -> "BackgroundSync":
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.last_summary = self.client.run_once()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 -- the uploader must never crash its host
                self.last_error = f"{type(exc).__name__}:{exc}"
            self.stop_event.wait(self.interval)

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        self._thread.join(timeout)


def drain(client: SyncClient, *, rounds: int = 20, now: float | None = None) -> dict[str, Any]:
    """Test/ops helper: run until the outbox has nothing due (``now`` far ahead skips backoff)."""
    summary: dict[str, Any] = {}
    for _ in range(rounds):
        summary = client.run_once(now=now)
        if summary["sent"] == 0:
            break
    return summary


def far_future() -> float:
    return time.time() + 10 ** 7
