"""Cloud-side state machine for collective learning, over a relational database.

First version: SQLite (WAL, ``BEGIN IMMEDIATE`` per write).  The schema lives in
``migrations/*.sql`` and is applied by :func:`migrate`; see ``0001_init.sql`` for
the PostgreSQL mapping.  ``http_api`` is a thin HTTP binding of :class:`Service`.

What the service guarantees (requirement sections 8-10):

* Events are unique per (tenant_id, event_id).  The same content again is a
  DUPLICATE ack (logged in ``delivery_log``, never counted twice); the same id with
  different content is a CONFLICT that keeps the original and stores the attempt.
* A device credential can only write as itself: the payload's tenant/device must
  equal the credential's, and its line must be one the credential was granted.
  Anything else is REJECTED and audited (T09).
* Candidates are revisioned with an ETag.  Every update and transition needs
  ``If-Match``; a stale one is a CONFLICT, never last-writer-wins.
* Release state is owned by the release policy here (``RELEASE_POLICY``), never by
  candidate text.  Promotion needs the validation scopes the category requires, the
  independent-source count, and evidence that is still available.
* Bundle versions are immutable; channel pointers move in one transaction with a
  history row.  Revoking a version moves any pointer at it back to the newest
  earlier non-revoked version.
* Nothing returned to a caller contains a token.  Tokens are stored as sha256.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import json
import random
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from . import contracts as c

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
ROLES = ("device_writer", "reviewer", "publisher", "admin")
CHANNELS = ("CANARY", "RELEASED")
DEFAULT_MAX_BATCH = 500

# The release policy is data with its own version.  Production devices cannot change
# it: only code review of this file (and a new version string) can.
RELEASE_POLICY: dict[str, Any] = {
    "policy_version": "release_policy.v1",
    # validation scopes a candidate must hold before it may enter CANARY, per category
    "canary_requires_any_scope": {
        "DIRECTING_HEURISTIC": ["REAL_MEDIA_REVIEW", "CROSS_CASE_EFFECT"],
        "ENGINEERING_INVARIANT": ["DETERMINISTIC_REGRESSION"],
        "MODEL_CONSTRAINT": ["DETERMINISTIC_REGRESSION", "REAL_MEDIA_REVIEW"],
        "EXECUTION_POLICY": ["DETERMINISTIC_REGRESSION"],
    },
    # creative advice must not generalise from one success: RELEASED needs either a
    # cross-case effect validation or this many independent sources
    "release_min_independent_sources": {"DIRECTING_HEURISTIC": 2},
    "release_scope_substitute": {"DIRECTING_HEURISTIC": "CROSS_CASE_EFFECT"},
}

# Which roles may move a candidate into which state.
TRANSITION_ROLES = {
    "VALIDATED": ("reviewer", "publisher", "admin"),
    "REJECTED": ("reviewer", "publisher", "admin"),
    "NEEDS_EVIDENCE": ("reviewer", "publisher", "admin"),
    "CANDIDATE": ("reviewer", "publisher", "admin"),
    "CANARY": ("publisher", "admin"),
    "RELEASED": ("publisher", "admin"),
    "DEPRECATED": ("publisher", "admin"),
    "REVOKED": ("publisher", "admin"),
}

# Fields that make two otherwise identical events "the same observation".  A cloned
# device replaying a log produces events that differ only in these.
_IDENTITY_FIELDS = ("event_id", "device_id", "producer_sequence", "received_at", "source_event_id",
                    "run_id", "occurred_at", "line_id", "tenant_id", "schema", "visibility")


# --------------------------------------------------------------------------- errors
class ServiceError(Exception):
    code = "INTERNAL"
    http_status = 500

    def __init__(self, message: str = "", details: Any = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


class Unauthenticated(ServiceError):
    code, http_status = "UNAUTHENTICATED", 401


class Forbidden(ServiceError):
    code, http_status = "FORBIDDEN", 403


class NotFound(ServiceError):
    code, http_status = "NOT_FOUND", 404


class Conflict(ServiceError):
    code, http_status = "CONFLICT", 409


class PreconditionRequired(ServiceError):
    code, http_status = "PRECONDITION_REQUIRED", 428


class PayloadInvalid(ServiceError):
    code, http_status = "PAYLOAD_INVALID", 422


class BatchTooLarge(ServiceError):
    code, http_status = "BATCH_TOO_LARGE", 413


@dataclass(frozen=True)
class Principal:
    principal_id: str
    tenant_id: str
    role: str
    line_ids: tuple[str, ...] = field(default_factory=tuple)
    canary: bool = False


def _token_sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return "qcl_" + secrets.token_urlsafe(32)


def identity_sha(event: dict[str, Any]) -> str:
    return c.digest({k: v for k, v in event.items() if k not in _IDENTITY_FIELDS})


def _etag(candidate_id: str, revision: int, state: str, payload_sha: str, scopes: list[str],
          evidence_status: str) -> str:
    raw = c.digest([candidate_id, revision, state, payload_sha, sorted(scopes), evidence_status])
    return f'"{raw[:32]}"'


def _audited(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Every refusal of a principal-bound call leaves an audit row (written after rollback)."""
    @functools.wraps(fn)
    def wrapper(self: "Service", principal: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(self, principal, *args, **kwargs)
        except ServiceError as err:
            target = next((a for a in args if isinstance(a, str)), None)
            target = target or kwargs.get("bundle_id") or kwargs.get("candidate_id")
            self.audit_denial(principal if isinstance(principal, Principal) else None, fn.__name__, target, err)
            raise
    return wrapper


# --------------------------------------------------------------------------- migrations
def migrate(db: sqlite3.Connection) -> list[int]:
    """Apply every ``migrations/NNNN_*.sql`` not yet recorded.  Each file is atomic."""
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
               "name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    done = {int(r[0]) for r in db.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:4])
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        name = path.name.replace("'", "")
        db.executescript(f"BEGIN;\n{sql}\nINSERT INTO schema_migrations(version, name, applied_at) "
                         f"VALUES({version}, '{name}', '{c.now_iso()}');\nCOMMIT;")
        applied.append(version)
    return applied


# --------------------------------------------------------------------------- service
class Service:
    def __init__(self, db_path: Path | str, *, max_batch: int = DEFAULT_MAX_BATCH,
                 trust_store: dict[str, Any] | None = None,
                 signature_verifier: Callable[[dict[str, Any], bytes], tuple[bool, str]] | None = None,
                 object_store: Any | None = None):
        """``trust_store``: a ``bundles.make_trust_store`` document.  When given, every
        uploaded payload must be a ``bundles`` signed envelope that verifies against it.
        Without one the upload is accepted and marked NOT_VERIFIED_SERVER_SIDE (devices
        still verify before adoption).  ``signature_verifier`` overrides both (tests).
        ``object_store``: an ``object_store.ObjectStore`` (line ``collective``); bundle
        bytes are mirrored there after the database commit.  The database stays the
        source of truth: a failed mirror is recorded, never a failed upload."""
        self.db_path = str(db_path)
        self.max_batch = int(max_batch)
        self._local = threading.local()
        self._verifier = signature_verifier
        self._trust = trust_store
        self._object_store = object_store
        db = self._db()
        db.execute("PRAGMA journal_mode=WAL")
        migrate(db)

    # ------------------------------------------------------------------ plumbing
    def _db(self) -> sqlite3.Connection:
        db = getattr(self._local, "db", None)
        if db is None:
            db = sqlite3.connect(self.db_path, timeout=60, isolation_level=None)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=60000")
            self._local.db = db
        return db

    def close(self) -> None:
        db = getattr(self._local, "db", None)
        if db is not None:
            db.close()
            self._local.db = None

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        db = self._db()
        for attempt in range(100):
            try:
                db.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:  # pragma: no cover - heavy contention only
                if "locked" not in str(exc) or attempt == 99:
                    raise
                time.sleep(0.005 + random.random() * 0.05)
        try:
            yield db
        except BaseException:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")

    def _read(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        return self._db().execute(sql, args).fetchall()

    @staticmethod
    def _audit(db: sqlite3.Connection, principal: Principal | None, action: str, target: str | None,
               outcome: str, detail: Any = None, tenant_id: str | None = None) -> None:
        db.execute("INSERT INTO audit_log(at, tenant_id, principal_id, action, target, outcome, detail) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (c.now_iso(), tenant_id or (principal.tenant_id if principal else None),
                    principal.principal_id if principal else None, action, target, outcome,
                    json.dumps(detail if detail is not None else {}, ensure_ascii=False)[:4000]))

    def audit_denial(self, principal: Principal | None, action: str, target: str | None,
                     error: ServiceError) -> None:
        with self._tx() as db:
            self._audit(db, principal, action, target, f"DENIED:{error.code}",
                        {"message": error.message, "details": error.details})

    def _require_role(self, principal: Principal, action: str, roles: tuple[str, ...]) -> None:
        if principal.role not in roles:
            raise Forbidden(f"role {principal.role} may not {action}", {"allowed_roles": list(roles)})

    # ------------------------------------------------------------------ principals
    def bootstrap_tenant(self, tenant_id: str, *, admin_id: str | None = None) -> dict[str, str]:
        """Create a tenant and its first admin credential (operator CLI only, no HTTP route)."""
        if not c.is_identifier(tenant_id):
            raise PayloadInvalid("tenant_id invalid")
        token = _new_token()
        principal_id = admin_id or f"admin-{tenant_id}"
        with self._tx() as db:
            if db.execute("SELECT 1 FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone():
                raise Conflict(f"tenant exists: {tenant_id}")
            db.execute("INSERT INTO tenants(tenant_id, created_at) VALUES(?,?)", (tenant_id, c.now_iso()))
            db.execute("INSERT INTO principals(principal_id, tenant_id, role, line_ids, token_sha256, status, "
                       "created_at) VALUES(?,?,?,?,?,?,?)",
                       (principal_id, tenant_id, "admin", "[]", _token_sha(token), "ACTIVE", c.now_iso()))
            self._audit(db, None, "bootstrap_tenant", tenant_id, "OK", {"admin": principal_id}, tenant_id)
        return {"tenant_id": tenant_id, "principal_id": principal_id, "token": token}

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise Unauthenticated("bearer token required")
        rows = self._read("SELECT principal_id, tenant_id, role, line_ids, canary, status FROM principals "
                          "WHERE token_sha256=?", (_token_sha(token),))
        if not rows:
            raise Unauthenticated("unknown credential")
        pid, tenant, role, lines, canary, status = rows[0]
        if status != "ACTIVE":
            principal = Principal(pid, tenant, role, tuple(json.loads(lines)), bool(canary))
            err = Unauthenticated("credential revoked")
            self.audit_denial(principal, "authenticate", pid, err)
            raise err
        return Principal(pid, tenant, role, tuple(json.loads(lines)), bool(canary))

    @_audited
    def register_principal(self, admin: Principal, *, principal_id: str, role: str,
                           line_ids: list[str] | None = None, canary: bool = False) -> dict[str, Any]:
        self._require_role(admin, "register_principal", ("admin",))
        if role not in ROLES:
            raise PayloadInvalid(f"role invalid: {role}")
        if not c.is_identifier(principal_id):
            raise PayloadInvalid("principal_id invalid")
        lines = sorted(set(line_ids or []))
        if role == "device_writer" and not lines:
            raise PayloadInvalid("a device_writer must be granted at least one line_id")
        if not all(c.is_identifier(x) for x in lines):
            raise PayloadInvalid("line_ids invalid")
        token = _new_token()
        with self._tx() as db:
            if db.execute("SELECT 1 FROM principals WHERE principal_id=?", (principal_id,)).fetchone():
                raise Conflict(f"principal exists: {principal_id}")
            db.execute("INSERT INTO principals(principal_id, tenant_id, role, line_ids, canary, token_sha256, "
                       "status, created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (principal_id, admin.tenant_id, role, json.dumps(lines), int(bool(canary)),
                        _token_sha(token), "ACTIVE", c.now_iso()))
            self._audit(db, admin, "register_principal", principal_id, "OK",
                        {"role": role, "line_ids": lines, "canary": bool(canary)})
        return {"principal_id": principal_id, "tenant_id": admin.tenant_id, "role": role, "line_ids": lines,
                "canary": bool(canary), "token": token,
                "note": "token is shown once; only its sha256 is stored"}

    def _own_principal(self, db: sqlite3.Connection, admin: Principal, principal_id: str) -> None:
        row = db.execute("SELECT tenant_id FROM principals WHERE principal_id=?", (principal_id,)).fetchone()
        if not row or row[0] != admin.tenant_id:
            raise NotFound(f"principal not found: {principal_id}")

    @_audited
    def rotate_credential(self, admin: Principal, principal_id: str) -> dict[str, Any]:
        self._require_role(admin, "rotate_credential", ("admin",))
        token = _new_token()
        with self._tx() as db:
            self._own_principal(db, admin, principal_id)
            db.execute("UPDATE principals SET token_sha256=?, rotated_at=? WHERE principal_id=? AND status='ACTIVE'",
                       (_token_sha(token), c.now_iso(), principal_id))
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise Conflict("credential is revoked; register a new principal")
            self._audit(db, admin, "rotate_credential", principal_id, "OK")
        return {"principal_id": principal_id, "token": token, "note": "previous token no longer authenticates"}

    @_audited
    def revoke_credential(self, admin: Principal, principal_id: str) -> dict[str, Any]:
        self._require_role(admin, "revoke_credential", ("admin",))
        with self._tx() as db:
            self._own_principal(db, admin, principal_id)
            db.execute("UPDATE principals SET status='REVOKED', revoked_at=? WHERE principal_id=?",
                       (c.now_iso(), principal_id))
            self._audit(db, admin, "revoke_credential", principal_id, "OK")
        return {"principal_id": principal_id, "status": "REVOKED"}

    # ------------------------------------------------------------------ batch helpers
    def _check_batch(self, items: Any, label: str) -> list[Any]:
        if not isinstance(items, list):
            raise PayloadInvalid(f"{label} must be a list")
        if len(items) > self.max_batch:
            raise BatchTooLarge(f"{label} batch of {len(items)} exceeds {self.max_batch}",
                                {"max_batch": self.max_batch})
        return items

    def _identity_codes(self, principal: Principal, item: dict[str, Any]) -> list[str]:
        """A device may write only as itself, for a line it was granted."""
        codes = []
        if item.get("tenant_id") != principal.tenant_id:
            codes.append("IDENTITY_MISMATCH:tenant_id")
        if principal.role == "device_writer":
            if item.get("device_id") != principal.principal_id:
                codes.append("IDENTITY_MISMATCH:device_id")
            if item.get("line_id") not in principal.line_ids:
                codes.append(f"LINE_NOT_PERMITTED:{item.get('line_id')}")
        return codes

    @staticmethod
    def _quarantine(db: sqlite3.Connection, principal: Principal, kind: str, item_id: Any,
                    codes: list[str], item: Any) -> None:
        db.execute("INSERT INTO quarantine(at, tenant_id, principal_id, item_kind, item_id, codes, payload_sha) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (c.now_iso(), principal.tenant_id, principal.principal_id, kind,
                    str(item_id) if item_id is not None else None, json.dumps(codes),
                    c.digest(item) if item is not None else ""))

    @staticmethod
    def _log_delivery(db: sqlite3.Connection, principal: Principal, kind: str, item_id: str, status: str) -> None:
        db.execute("INSERT INTO delivery_log(tenant_id, item_kind, item_id, principal_id, status, at) "
                   "VALUES(?,?,?,?,?,?)", (principal.tenant_id, kind, item_id, principal.principal_id, status,
                                           c.now_iso()))

    @staticmethod
    def _count(db: sqlite3.Connection, principal: Principal, results: list[dict[str, Any]]) -> None:
        accepted = sum(1 for r in results if r["status"] == "CREATED")
        dup = sum(1 for r in results if r["status"] == "DUPLICATE")
        rejected = sum(1 for r in results if r["status"] in ("REJECTED", "CONFLICT"))
        db.execute("UPDATE principals SET last_seen=?, accepted=accepted+?, duplicates=duplicates+?, "
                   "rejected=rejected+? WHERE principal_id=?",
                   (c.now_iso(), accepted, dup, rejected, principal.principal_id))

    # ------------------------------------------------------------------ events
    @_audited
    def ingest_events(self, principal: Principal, events: Any) -> list[dict[str, Any]]:
        """Per-item persisted acknowledgement.  Partial success is normal."""
        self._require_role(principal, "ingest_events", ("device_writer",))
        events = self._check_batch(events, "events")
        results: list[dict[str, Any]] = []
        with self._tx() as db:
            for item in events:
                item_id = item.get("event_id") if isinstance(item, dict) else None
                try:
                    if not isinstance(item, dict):
                        raise c.ContractError(["EVENT_NOT_OBJECT"])
                    c.validate_observation(item)
                    codes = self._identity_codes(principal, item)
                    if item.get("visibility") == "PRIVATE_LOCAL":
                        codes.append("PRIVATE_LOCAL_EVENT_MUST_NOT_LEAVE_DEVICE")
                    if codes:
                        raise c.ContractError(codes)
                except c.ContractError as exc:
                    self._quarantine(db, principal, "EVENT", item_id, exc.codes, item)
                    results.append({"id": item_id, "status": "REJECTED", "codes": exc.codes})
                    continue
                sha = c.observation_digest(item)
                row = db.execute("SELECT content_sha FROM events WHERE tenant_id=? AND event_id=?",
                                 (principal.tenant_id, item_id)).fetchone()
                if row and row[0] == sha:
                    status, codes = "DUPLICATE", []
                elif row:
                    db.execute("INSERT INTO event_conflicts(tenant_id, event_id, existing_sha, attempted_sha, "
                               "attempted_payload, principal_id, at) VALUES(?,?,?,?,?,?,?)",
                               (principal.tenant_id, item_id, row[0], sha, json.dumps(item, ensure_ascii=False),
                                principal.principal_id, c.now_iso()))
                    status, codes = "CONFLICT", [f"EVENT_ID_CONFLICT:{item_id}"]
                else:
                    db.execute("INSERT INTO events(tenant_id, event_id, content_sha, payload, line_id, device_id, "
                               "run_id, episode_id, event_kind, source_event_id, identity_sha, received_at, "
                               "received_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (principal.tenant_id, item_id, sha, json.dumps(item, ensure_ascii=False),
                                item["line_id"], item["device_id"], item["run_id"], item["episode_id"],
                                item["event_kind"], item.get("source_event_id"), identity_sha(item),
                                c.now_iso(), principal.principal_id))
                    status, codes = "CREATED", []
                self._log_delivery(db, principal, "EVENT", item_id, status)
                results.append({"id": item_id, "status": status, "codes": codes, "content_sha": sha})
            self._count(db, principal, results)
            self._audit(db, principal, "ingest_events", None, "OK",
                        {s: sum(1 for r in results if r["status"] == s)
                         for s in ("CREATED", "DUPLICATE", "CONFLICT", "REJECTED")})
        return results

    def event_counts(self, tenant_id: str) -> dict[str, int]:
        db = self._db()
        return {
            "unique_events": db.execute("SELECT COUNT(*) FROM events WHERE tenant_id=?", (tenant_id,)).fetchone()[0],
            "deliveries": db.execute("SELECT COUNT(*) FROM delivery_log WHERE tenant_id=? AND item_kind='EVENT'",
                                     (tenant_id,)).fetchone()[0],
            "duplicate_deliveries": db.execute("SELECT COUNT(*) FROM delivery_log WHERE tenant_id=? AND "
                                               "item_kind='EVENT' AND status='DUPLICATE'", (tenant_id,)).fetchone()[0],
            "conflicts": db.execute("SELECT COUNT(*) FROM event_conflicts WHERE tenant_id=?",
                                    (tenant_id,)).fetchone()[0],
            "quarantined": db.execute("SELECT COUNT(*) FROM quarantine WHERE tenant_id=?", (tenant_id,)).fetchone()[0],
        }

    @_audited
    def get_event(self, principal: Principal, event_id: str) -> dict[str, Any]:
        rows = self._read("SELECT payload, line_id FROM events WHERE tenant_id=? AND event_id=?",
                          (principal.tenant_id, event_id))
        if not rows or (principal.role == "device_writer" and rows[0][1] not in principal.line_ids):
            raise NotFound(f"event not found: {event_id}")
        return json.loads(rows[0][0])

    # ------------------------------------------------------------------ reviews
    @_audited
    def ingest_reviews(self, principal: Principal, reviews: Any) -> list[dict[str, Any]]:
        self._require_role(principal, "ingest_reviews", ("device_writer", "reviewer", "publisher", "admin"))
        reviews = self._check_batch(reviews, "reviews")
        results: list[dict[str, Any]] = []
        with self._tx() as db:
            for item in reviews:
                item_id = item.get("review_id") if isinstance(item, dict) else None
                try:
                    if not isinstance(item, dict):
                        raise c.ContractError(["REVIEW_NOT_OBJECT"])
                    c.validate_attribution(item)
                    codes = c.sensitive_findings(item)
                    event = db.execute("SELECT line_id FROM events WHERE tenant_id=? AND event_id=?",
                                       (principal.tenant_id, item["event_id"])).fetchone()
                    if not event:
                        codes.append(f"EVENT_NOT_FOUND:{item['event_id']}")
                    elif principal.role == "device_writer":
                        codes += self._identity_codes(principal, item)
                        if event[0] not in principal.line_ids:
                            codes.append("EVENT_LINE_NOT_PERMITTED")
                    if codes:
                        raise c.ContractError(codes)
                except c.ContractError as exc:
                    self._quarantine(db, principal, "REVIEW", item_id, exc.codes, item)
                    results.append({"id": item_id, "status": "REJECTED", "codes": exc.codes})
                    continue
                sha = c.digest(item)
                row = db.execute("SELECT content_sha FROM reviews WHERE tenant_id=? AND review_id=?",
                                 (principal.tenant_id, item_id)).fetchone()
                if row and row[0] == sha:
                    status, codes = "DUPLICATE", []
                elif row:
                    status, codes = "CONFLICT", [f"REVIEW_ID_CONFLICT:{item_id}"]
                    self._quarantine(db, principal, "REVIEW", item_id, codes, item)
                else:
                    db.execute("INSERT INTO reviews(tenant_id, review_id, event_id, review_version, content_sha, "
                               "payload, received_at, received_by) VALUES(?,?,?,?,?,?,?,?)",
                               (principal.tenant_id, item_id, item["event_id"], item["review_version"], sha,
                                json.dumps(item, ensure_ascii=False), c.now_iso(), principal.principal_id))
                    status, codes = "CREATED", []
                self._log_delivery(db, principal, "REVIEW", item_id, status)
                results.append({"id": item_id, "status": status, "codes": codes})
            self._count(db, principal, results)
            self._audit(db, principal, "ingest_reviews", None, "OK", {"count": len(results)})
        return results

    def attribution_chain(self, tenant_id: str, event_id: str) -> list[dict[str, Any]]:
        rows = self._read("SELECT payload FROM reviews WHERE tenant_id=? AND event_id=? ORDER BY received_at, "
                          "review_version", (tenant_id, event_id))
        return [json.loads(r[0]) for r in rows]

    # ------------------------------------------------------------------ candidates
    def _candidate_row(self, db: sqlite3.Connection, tenant_id: str, candidate_id: str) -> dict[str, Any] | None:
        row = db.execute("SELECT revision, state, category, payload, validation_scopes, evidence_status, "
                         "promotion_eligible, needs_reevaluation, origin_line_id, created_by, etag, updated_at "
                         "FROM candidates WHERE tenant_id=? AND candidate_id=?", (tenant_id, candidate_id)).fetchone()
        if not row:
            return None
        keys = ("revision", "state", "category", "payload", "validation_scopes", "evidence_status",
                "promotion_eligible", "needs_reevaluation", "origin_line_id", "created_by", "etag", "updated_at")
        rec = dict(zip(keys, row))
        rec["payload"] = json.loads(rec["payload"])
        rec["validation_scopes"] = json.loads(rec["validation_scopes"])
        rec["promotion_eligible"] = bool(rec["promotion_eligible"])
        rec["needs_reevaluation"] = bool(rec["needs_reevaluation"])
        rec["candidate_id"] = candidate_id
        return rec

    @staticmethod
    def _public_candidate(rec: dict[str, Any]) -> dict[str, Any]:
        return {k: rec[k] for k in ("candidate_id", "revision", "state", "category", "payload", "validation_scopes",
                                    "evidence_status", "promotion_eligible", "needs_reevaluation",
                                    "origin_line_id", "etag", "updated_at")}

    @_audited
    def put_candidate(self, principal: Principal, candidate: dict[str, Any], *, if_match: str | None = None,
                      origin_line_id: str | None = None) -> dict[str, Any]:
        """Create (revision 1, no If-Match) or revise (revision+1, If-Match required)."""
        self._require_role(principal, "put_candidate", ("device_writer", "reviewer", "publisher", "admin"))
        try:
            c.validate_candidate(candidate)
        except c.ContractError as exc:
            with self._tx() as db:
                self._quarantine(db, principal, "CANDIDATE", candidate.get("candidate_id"), exc.codes, candidate)
            raise PayloadInvalid("candidate violates contract", {"codes": exc.codes}) from exc
        line = origin_line_id or (principal.line_ids[0] if principal.line_ids else "TENANT")
        if principal.role == "device_writer" and line not in principal.line_ids:
            raise Forbidden("line not permitted", {"line_id": line})
        cid = candidate["candidate_id"]
        with self._tx() as db:
            rec = self._candidate_row(db, principal.tenant_id, cid)
            unknown_events = [e for e in candidate.get("event_ids") or []
                              if not db.execute("SELECT 1 FROM events WHERE tenant_id=? AND event_id=?",
                                                (principal.tenant_id, e)).fetchone()]
            if unknown_events:
                raise PayloadInvalid("candidate cites unknown events", {"event_ids": unknown_events})
            now = c.now_iso()
            payload_json = json.dumps(candidate, ensure_ascii=False)
            if rec is None:
                if if_match:
                    raise Conflict("If-Match given but candidate does not exist")
                if candidate["revision"] != 1:
                    raise Conflict("a new candidate starts at revision 1")
                state = candidate.get("status", "CANDIDATE")
                evidence_status = "NO_EVIDENCE_REGISTERED"
                etag = _etag(cid, 1, state, c.digest(candidate), [], evidence_status)
                db.execute("INSERT INTO candidates(tenant_id, candidate_id, revision, state, category, payload, "
                           "validation_scopes, evidence_status, promotion_eligible, origin_line_id, created_by, "
                           "created_at, updated_at, etag) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (principal.tenant_id, cid, 1, state, candidate["category"], payload_json, "[]",
                            evidence_status, 1, line, principal.principal_id, now, now, etag))
                action, from_state = "CREATE", None
            else:
                if principal.role == "device_writer" and rec["origin_line_id"] not in principal.line_ids:
                    raise Forbidden("candidate belongs to another line")
                if not if_match:
                    raise PreconditionRequired("If-Match required to revise a candidate", {"etag": rec["etag"]})
                if if_match != rec["etag"]:
                    raise Conflict("stale If-Match", {"current_etag": rec["etag"], "current_revision": rec["revision"]})
                if candidate["revision"] != rec["revision"] + 1:
                    raise Conflict("revision must increase by exactly one",
                                   {"current_revision": rec["revision"]})
                if rec["state"] not in ("CANDIDATE", "NEEDS_EVIDENCE"):
                    raise Conflict(f"candidate in {rec['state']} is frozen; propose a new candidate id")
                state = "CANDIDATE"
                etag = _etag(cid, candidate["revision"], state, c.digest(candidate), rec["validation_scopes"],
                             rec["evidence_status"])
                db.execute("UPDATE candidates SET revision=?, state=?, payload=?, updated_at=?, etag=? "
                           "WHERE tenant_id=? AND candidate_id=?",
                           (candidate["revision"], state, payload_json, now, etag, principal.tenant_id, cid))
                action, from_state = "REVISE", rec["state"]
            db.execute("INSERT INTO candidate_history(tenant_id, candidate_id, revision, action, from_state, to_state, "
                       "payload, detail, actor, at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (principal.tenant_id, cid, candidate["revision"], action, from_state, state, payload_json,
                        "{}", principal.principal_id, now))
            self._audit(db, principal, "put_candidate", cid, "OK", {"action": action, "revision": candidate["revision"]})
            return self._public_candidate(self._candidate_row(db, principal.tenant_id, cid))

    @_audited
    def get_candidate(self, principal: Principal, candidate_id: str) -> dict[str, Any]:
        rec = self._candidate_row(self._db(), principal.tenant_id, candidate_id)
        if rec is None:
            raise NotFound(f"candidate not found: {candidate_id}")
        return self._public_candidate(rec)

    @_audited
    def transition_candidate(self, principal: Principal, candidate_id: str, *, to: str, if_match: str | None,
                             validation_scope: str | None = None, note: str = "") -> dict[str, Any]:
        roles = TRANSITION_ROLES.get(to)
        if roles is None:
            raise PayloadInvalid(f"unknown target state: {to}")
        self._require_role(principal, f"transition_to_{to}", roles)
        if not if_match:
            raise PreconditionRequired("If-Match required for a transition")
        with self._tx() as db:
            rec = self._candidate_row(db, principal.tenant_id, candidate_id)
            if rec is None:
                raise NotFound(f"candidate not found: {candidate_id}")
            if if_match != rec["etag"]:
                raise Conflict("stale If-Match", {"current_etag": rec["etag"]})
            frm = rec["state"]
            scopes = list(rec["validation_scopes"])
            if to == "VALIDATED":
                if validation_scope not in c.VALIDATION_SCOPES:
                    raise PayloadInvalid("VALIDATED needs validation_scope",
                                         {"allowed": list(c.VALIDATION_SCOPES)})
                if frm != "VALIDATED" and to not in c.RELEASE_TRANSITIONS.get(frm, set()):
                    raise Conflict(f"illegal transition {frm} -> {to}")
                if validation_scope not in scopes:
                    scopes.append(validation_scope)
            elif to not in c.RELEASE_TRANSITIONS.get(frm, set()):
                raise Conflict(f"illegal transition {frm} -> {to}")
            blockers = self._promotion_blockers(db, principal.tenant_id, rec, to, scopes)
            if blockers:
                raise Conflict("release policy refuses this promotion",
                               {"blockers": blockers, "policy_version": RELEASE_POLICY["policy_version"]})
            etag = _etag(candidate_id, rec["revision"], to, c.digest(rec["payload"]), scopes, rec["evidence_status"])
            now = c.now_iso()
            db.execute("UPDATE candidates SET state=?, validation_scopes=?, updated_at=?, etag=? "
                       "WHERE tenant_id=? AND candidate_id=?",
                       (to, json.dumps(scopes), now, etag, principal.tenant_id, candidate_id))
            detail = {"validation_scope": validation_scope, "note": note,
                      "policy_version": RELEASE_POLICY["policy_version"]}
            db.execute("INSERT INTO candidate_history(tenant_id, candidate_id, revision, action, from_state, to_state, "
                       "payload, detail, actor, at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (principal.tenant_id, candidate_id, rec["revision"], "TRANSITION", frm, to,
                        json.dumps(rec["payload"], ensure_ascii=False), json.dumps(detail, ensure_ascii=False),
                        principal.principal_id, now))
            self._audit(db, principal, f"transition_to_{to}", candidate_id, "OK", detail)
            return self._public_candidate(self._candidate_row(db, principal.tenant_id, candidate_id))

    def _promotion_blockers(self, db: sqlite3.Connection, tenant_id: str, rec: dict[str, Any], to: str,
                            scopes: list[str]) -> list[str]:
        if to not in ("CANARY", "RELEASED"):
            return []
        blockers = []
        if rec["evidence_status"] == "EVIDENCE_UNAVAILABLE" or not rec["promotion_eligible"]:
            blockers.append("EVIDENCE_UNAVAILABLE")
        need = RELEASE_POLICY["canary_requires_any_scope"].get(rec["category"], [])
        if need and not set(need) & set(scopes):
            blockers.append(f"VALIDATION_SCOPE_INSUFFICIENT:need_any_of={need}:have={sorted(scopes)}")
        if to == "RELEASED":
            minimum = RELEASE_POLICY["release_min_independent_sources"].get(rec["category"])
            substitute = RELEASE_POLICY["release_scope_substitute"].get(rec["category"])
            if minimum and substitute not in scopes:
                count = self._independent_sources(db, tenant_id, rec["payload"].get("event_ids") or [])
                if count["independent_sources"] < minimum:
                    blockers.append(f"INDEPENDENT_SOURCES_INSUFFICIENT:{count['independent_sources']}<{minimum}")
        return blockers

    @_audited
    def candidate_history(self, principal: Principal, candidate_id: str) -> list[dict[str, Any]]:
        rows = self._read("SELECT revision, action, from_state, to_state, detail, actor, at FROM candidate_history "
                          "WHERE tenant_id=? AND candidate_id=? ORDER BY id", (principal.tenant_id, candidate_id))
        return [{"revision": r[0], "action": r[1], "from_state": r[2], "to_state": r[3],
                 "detail": json.loads(r[4]), "actor": r[5], "at": r[6]} for r in rows]

    # ------------------------------------------------------------------ provenance
    def _independent_sources(self, db: sqlite3.Connection, tenant_id: str, event_ids: list[str]) -> dict[str, Any]:
        """Distinct origins behind ``event_ids``.

        Collapses, in order: duplicate deliveries (unique event rows already), copies
        (``source_event_id`` chains resolved to their root), and identical replays
        (events whose content minus identity fields is byte-identical -- what a cloned
        device replaying one log produces).  What remains is counted by origin
        (tenant, line, device) of each root.
        """
        roots: dict[str, tuple[str, str, str]] = {}
        identity_groups: dict[str, set[tuple[str, str, str]]] = {}
        copies = 0
        missing = []
        for event_id in sorted(set(event_ids)):
            current, seen = event_id, set()
            row = None
            while current and current not in seen:
                seen.add(current)
                row = db.execute("SELECT line_id, device_id, source_event_id, identity_sha FROM events "
                                 "WHERE tenant_id=? AND event_id=?", (tenant_id, current)).fetchone()
                if not row:
                    break
                if row[2]:
                    copies += 1
                    nxt = db.execute("SELECT 1 FROM events WHERE tenant_id=? AND event_id=?",
                                     (tenant_id, row[2])).fetchone()
                    if nxt:
                        current = row[2]
                        continue
                break
            if not row:
                missing.append(current)
                continue
            origin = (tenant_id, row[0], row[1])
            roots[current] = origin
            identity_groups.setdefault(row[3], set()).add(origin)
        # one source per identical-content group, then distinct origins across groups
        origins = {sorted(group)[0] for group in identity_groups.values()}
        replays = sum(len(g) - 1 for g in identity_groups.values())
        return {"independent_sources": len(origins), "origins": sorted("/".join(o[1:]) for o in origins),
                "root_events": sorted(roots), "copies_collapsed": copies, "identical_replays_collapsed": replays,
                "unknown_events": missing}

    @_audited
    def independent_sources(self, principal: Principal, candidate_id: str) -> dict[str, Any]:
        rec = self._candidate_row(self._db(), principal.tenant_id, candidate_id)
        if rec is None:
            raise NotFound(f"candidate not found: {candidate_id}")
        return self._independent_sources(self._db(), principal.tenant_id, rec["payload"].get("event_ids") or [])

    # ------------------------------------------------------------------ bundles
    def _verify_signature(self, record: dict[str, Any], payload: bytes) -> tuple[bool, str]:
        if self._verifier is not None:
            try:
                ok, note = self._verifier(record, payload)
            except Exception as exc:  # noqa: BLE001 -- any verifier failure is a refusal
                return False, f"SIGNATURE_VERIFY_ERROR:{type(exc).__name__}:{exc}"
            return bool(ok), ("SIGNATURE_VERIFIED:" if ok else "SIGNATURE_INVALID:") + str(note)
        if self._trust is None:
            return True, "SIGNATURE_NOT_VERIFIED_SERVER_SIDE:no_trust_store_configured"
        from . import bundles as _bundles  # signed-envelope format is owned by bundles.py
        try:
            envelope = json.loads(payload)
            _bundles.verify_bundle(envelope, self._trust)
        except Exception as exc:  # noqa: BLE001 -- BundleError, bad JSON, missing crypto: all refusals
            codes = getattr(exc, "codes", None) or [f"{type(exc).__name__}:{exc}"]
            return False, "SIGNATURE_INVALID:" + ",".join(str(x) for x in codes)[:500]
        key_id = ((envelope.get("signature") or {}).get("key_id"))
        if key_id != record.get("key_id"):
            return False, f"SIGNATURE_INVALID:key_id_mismatch:{key_id}!={record.get('key_id')}"
        return True, f"SIGNATURE_VERIFIED:bundles.verify_bundle:key_id={key_id}"

    @_audited
    def upload_bundle(self, principal: Principal, body: dict[str, Any]) -> dict[str, Any]:
        self._require_role(principal, "upload_bundle", ("publisher", "admin"))
        for key in ("bundle_id", "version", "digest", "payload_b64", "signature_b64", "key_id", "manifest"):
            if not body.get(key):
                raise PayloadInvalid(f"missing {key}")
        if not c.is_identifier(body["bundle_id"]) or not c.is_identifier(str(body["version"])):
            raise PayloadInvalid("bundle_id/version invalid")
        try:
            payload = base64.b64decode(body["payload_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise PayloadInvalid("payload_b64 is not base64") from exc
        actual = c.sha256_bytes(payload)
        if actual != body["digest"]:
            raise PayloadInvalid("digest does not match payload", {"declared": body["digest"], "actual": actual})
        manifest = body["manifest"]
        if not isinstance(manifest, dict) or not isinstance(manifest.get("scope"), dict):
            raise PayloadInvalid("manifest.scope required (bundles are never scope-less)")
        if not manifest["scope"].get("models") or not manifest["scope"].get("stages"):
            raise PayloadInvalid("manifest.scope needs models and stages")
        findings = c.sensitive_findings(manifest)
        if findings:
            raise PayloadInvalid("manifest carries sensitive content", {"codes": findings})
        ok, note = self._verify_signature(body, payload)
        if not ok:
            raise PayloadInvalid("bundle signature invalid", {"note": note})
        with self._tx() as db:
            row = db.execute("SELECT digest FROM bundles WHERE tenant_id=? AND bundle_id=? AND version=?",
                             (principal.tenant_id, body["bundle_id"], str(body["version"]))).fetchone()
            if row:
                if row[0] == actual:
                    return {"bundle_id": body["bundle_id"], "version": str(body["version"]), "digest": actual,
                            "status": "DUPLICATE"}
                raise Conflict("bundle versions are immutable", {"existing_digest": row[0]})
            db.execute("INSERT INTO bundles(tenant_id, bundle_id, version, digest, payload, signature_b64, key_id, "
                       "manifest, signature_check, uploaded_by, uploaded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (principal.tenant_id, body["bundle_id"], str(body["version"]), actual, payload,
                        body["signature_b64"], body["key_id"], json.dumps(manifest, ensure_ascii=False), note,
                        principal.principal_id, c.now_iso()))
            self._audit(db, principal, "upload_bundle", f"{body['bundle_id']}@{body['version']}", "OK",
                        {"digest": actual, "signature_check": note})
        mirror = self._mirror_bundle(principal, body["bundle_id"], str(body["version"]), payload, manifest)
        return {"bundle_id": body["bundle_id"], "version": str(body["version"]), "digest": actual,
                "object_mirror": mirror,
                "status": "CREATED", "signature_check": note}

    @_audited

    def _mirror_bundle(self, principal: Principal, bundle_id: str, version: str, payload: bytes,
                       manifest: dict[str, Any]) -> dict[str, Any]:
        """Mirror the immutable bundle bytes to object storage under
        ``collective/<tenant>/bundles/<bundle_id>/<version>.json``.  Never raises."""
        if self._object_store is None:
            return {"status": "NOT_CONFIGURED"}
        try:
            result = self._object_store.put_artifact(
                principal.tenant_id, f"bundles/{bundle_id}/{version}.json", payload,
                content_type="application/json",
                metadata={"bundle_id": bundle_id, "version": version, "scope": manifest.get("scope")})
            outcome = {"status": "MIRRORED", "key": result["key"], "sha256": result["sha256"],
                       "public_url": result.get("public_url")}
        except Exception as exc:  # noqa: BLE001 -- the database row is authoritative
            outcome = {"status": "MIRROR_FAILED", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        with self._tx() as db:
            self._audit(db, principal, "mirror_bundle", f"{bundle_id}@{version}", outcome["status"], outcome)
        return outcome
    def get_bundle(self, principal: Principal, bundle_id: str, version: str) -> dict[str, Any]:
        rows = self._read("SELECT digest, payload, signature_b64, key_id, manifest, uploaded_at FROM bundles "
                          "WHERE tenant_id=? AND bundle_id=? AND version=?", (principal.tenant_id, bundle_id, version))
        if not rows:
            raise NotFound(f"bundle not found: {bundle_id}@{version}")
        digest, payload, sig, key_id, manifest, uploaded_at = rows[0]
        manifest = json.loads(manifest)
        if principal.role == "device_writer" and manifest.get("line_ids") and not (
                set(manifest["line_ids"]) & set(principal.line_ids)):
            raise NotFound(f"bundle not found: {bundle_id}@{version}")
        revoked = self._read("SELECT reason, at FROM revocations WHERE tenant_id=? AND bundle_id=? AND version=?",
                             (principal.tenant_id, bundle_id, version))
        return {"bundle_id": bundle_id, "version": version, "digest": digest,
                "payload_b64": base64.b64encode(payload).decode("ascii"), "signature_b64": sig, "key_id": key_id,
                "manifest": manifest, "uploaded_at": uploaded_at,
                "revoked": {"reason": revoked[0][0], "at": revoked[0][1]} if revoked else None}

    @_audited
    def release(self, principal: Principal, *, bundle_id: str, version: str, channel: str,
                note: str = "") -> dict[str, Any]:
        """Point ``channel`` of ``bundle_id`` at ``version``, in one transaction, with history."""
        self._require_role(principal, "release", ("publisher", "admin"))
        if channel not in CHANNELS:
            raise PayloadInvalid(f"channel must be one of {CHANNELS}")
        with self._tx() as db:
            row = db.execute("SELECT manifest FROM bundles WHERE tenant_id=? AND bundle_id=? AND version=?",
                             (principal.tenant_id, bundle_id, version)).fetchone()
            if not row:
                raise NotFound(f"bundle not found: {bundle_id}@{version}")
            if db.execute("SELECT 1 FROM revocations WHERE tenant_id=? AND bundle_id=? AND version=?",
                          (principal.tenant_id, bundle_id, version)).fetchone():
                raise Conflict("a revoked version cannot be released")
            manifest = json.loads(row[0])
            blockers = self._bundle_rule_blockers(db, principal.tenant_id, manifest, channel)
            if blockers:
                raise Conflict("bundle contains rules not eligible for this channel", {"blockers": blockers})
            prev = db.execute("SELECT version FROM channels WHERE tenant_id=? AND bundle_id=? AND channel=?",
                              (principal.tenant_id, bundle_id, channel)).fetchone()
            now = c.now_iso()
            db.execute("INSERT INTO channels(tenant_id, bundle_id, channel, version, updated_by, updated_at) "
                       "VALUES(?,?,?,?,?,?) ON CONFLICT(tenant_id, bundle_id, channel) DO UPDATE SET "
                       "version=excluded.version, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                       (principal.tenant_id, bundle_id, channel, version, principal.principal_id, now))
            db.execute("INSERT INTO channel_history(tenant_id, bundle_id, channel, from_version, to_version, reason, "
                       "actor, at) VALUES(?,?,?,?,?,?,?,?)",
                       (principal.tenant_id, bundle_id, channel, prev[0] if prev else None, version,
                        note or "RELEASE", principal.principal_id, now))
            self._audit(db, principal, "release", f"{bundle_id}@{version}:{channel}", "OK",
                        {"from_version": prev[0] if prev else None})
        return {"bundle_id": bundle_id, "channel": channel, "version": version,
                "previous_version": prev[0] if prev else None}

    def _bundle_rule_blockers(self, db: sqlite3.Connection, tenant_id: str, manifest: dict[str, Any],
                              channel: str) -> list[str]:
        """Every rule in a bundle must already hold a state at least as strong as its channel.

        A maintainer-approved baseline bundle (``manifest.baseline``) carries rules
        that predate the candidate store; it is still publisher-only.
        """
        if manifest.get("baseline") is True:
            return []
        allowed = {"CANARY": ("CANARY", "RELEASED"), "RELEASED": ("RELEASED",)}[channel]
        blockers = []
        for rule in manifest.get("rules") or []:
            rule_id = rule.get("rule_id") if isinstance(rule, dict) else rule
            rec = self._candidate_row(db, tenant_id, str(rule_id))
            if rec is None:
                blockers.append(f"RULE_UNKNOWN:{rule_id}")
            elif rec["state"] not in allowed:
                blockers.append(f"RULE_STATE:{rule_id}:{rec['state']}")
            elif isinstance(rule, dict) and rule.get("rule_version") not in (None, rec["revision"]):
                blockers.append(f"RULE_REVISION_MISMATCH:{rule_id}:{rule.get('rule_version')}!={rec['revision']}")
        return blockers

    @_audited
    def revoke_bundle(self, principal: Principal, *, bundle_id: str, version: str, reason: str) -> dict[str, Any]:
        """Revoke a version; any channel pointing at it falls back to the newest earlier valid version."""
        self._require_role(principal, "revoke_bundle", ("publisher", "admin"))
        if not str(reason or "").strip():
            raise PayloadInvalid("reason required")
        with self._tx() as db:
            if not db.execute("SELECT 1 FROM bundles WHERE tenant_id=? AND bundle_id=? AND version=?",
                              (principal.tenant_id, bundle_id, version)).fetchone():
                raise NotFound(f"bundle not found: {bundle_id}@{version}")
            now = c.now_iso()
            db.execute("INSERT OR IGNORE INTO revocations(tenant_id, bundle_id, version, reason, actor, at) "
                       "VALUES(?,?,?,?,?,?)", (principal.tenant_id, bundle_id, version, reason, principal.principal_id,
                                               now))
            moved = []
            for (channel,) in db.execute("SELECT channel FROM channels WHERE tenant_id=? AND bundle_id=? AND version=?",
                                         (principal.tenant_id, bundle_id, version)).fetchall():
                history = db.execute("SELECT from_version FROM channel_history WHERE tenant_id=? AND bundle_id=? AND "
                                     "channel=? AND to_version=? ORDER BY id DESC",
                                     (principal.tenant_id, bundle_id, channel, version)).fetchall()
                fallback = None
                for (candidate_version,) in history:
                    # walk back past versions that are themselves revoked
                    seen = set()
                    while candidate_version and candidate_version not in seen:
                        seen.add(candidate_version)
                        if not db.execute("SELECT 1 FROM revocations WHERE tenant_id=? AND bundle_id=? AND version=?",
                                          (principal.tenant_id, bundle_id, candidate_version)).fetchone():
                            fallback = candidate_version
                            break
                        prev = db.execute("SELECT from_version FROM channel_history WHERE tenant_id=? AND bundle_id=? "
                                          "AND channel=? AND to_version=? ORDER BY id DESC LIMIT 1",
                                          (principal.tenant_id, bundle_id, channel, candidate_version)).fetchone()
                        candidate_version = prev[0] if prev else None
                    if fallback:
                        break
                if fallback:
                    db.execute("UPDATE channels SET version=?, updated_by=?, updated_at=? WHERE tenant_id=? AND "
                               "bundle_id=? AND channel=?", (fallback, principal.principal_id, now,
                                                             principal.tenant_id, bundle_id, channel))
                else:
                    db.execute("DELETE FROM channels WHERE tenant_id=? AND bundle_id=? AND channel=?",
                               (principal.tenant_id, bundle_id, channel))
                db.execute("INSERT INTO channel_history(tenant_id, bundle_id, channel, from_version, to_version, "
                           "reason, actor, at) VALUES(?,?,?,?,?,?,?,?)",
                           (principal.tenant_id, bundle_id, channel, version, fallback, f"REVOKED:{reason}",
                            principal.principal_id, now))
                moved.append({"channel": channel, "from_version": version, "to_version": fallback})
            self._audit(db, principal, "revoke_bundle", f"{bundle_id}@{version}", "OK",
                        {"reason": reason, "channels_moved": moved})
        return {"bundle_id": bundle_id, "version": version, "revoked": True, "channels_moved": moved}

    @_audited
    def resolve(self, principal: Principal, capabilities: dict[str, Any],
                channels: list[str] | None = None) -> dict[str, Any]:
        """Exact (bundle_id, version, digest) the caller may adopt, per channel.

        Only devices enrolled in canary see CANARY pointers.  A bundle's manifest
        scope must match the capabilities the device reported (unknown never matches).
        The full revocation list for the tenant is returned so a device can stop
        using a cached revoked version.
        """
        if not isinstance(capabilities, dict):
            raise PayloadInvalid("capabilities must be an object")
        findings = c.sensitive_findings(capabilities)
        if findings:
            raise PayloadInvalid("capabilities carry sensitive content", {"codes": findings})
        wanted = list(channels or (["RELEASED", "CANARY"] if principal.canary else ["RELEASED"]))
        if "CANARY" in wanted and not principal.canary and principal.role == "device_writer":
            wanted.remove("CANARY")
        db = self._db()
        rows = db.execute("SELECT ch.bundle_id, ch.channel, ch.version, b.digest, b.manifest FROM channels ch "
                          "JOIN bundles b ON b.tenant_id=ch.tenant_id AND b.bundle_id=ch.bundle_id AND "
                          "b.version=ch.version WHERE ch.tenant_id=? ORDER BY ch.bundle_id, ch.channel",
                          (principal.tenant_id,)).fetchall()
        selected, skipped = [], []
        for bundle_id, channel, version, digest, manifest_json in rows:
            if channel not in wanted:
                continue
            manifest = json.loads(manifest_json)
            if principal.role == "device_writer" and manifest.get("line_ids") and not (
                    set(manifest["line_ids"]) & set(principal.line_ids)):
                continue
            caps = dict(capabilities)
            caps["owner_match"] = (not manifest.get("owner_line_id")) or manifest["owner_line_id"] in principal.line_ids
            ok, reasons = c.scope_matches(manifest.get("scope") or {}, caps)
            entry = {"bundle_id": bundle_id, "channel": channel, "version": version, "digest": digest}
            if ok:
                selected.append(entry)
            else:
                skipped.append({**entry, "reasons": reasons})
        revocations = [{"bundle_id": b, "version": v, "reason": r, "at": a} for b, v, r, a in db.execute(
            "SELECT bundle_id, version, reason, at FROM revocations WHERE tenant_id=? ORDER BY at",
            (principal.tenant_id,)).fetchall()]
        with self._tx() as wdb:
            wdb.execute("UPDATE principals SET last_seen=? WHERE principal_id=?", (c.now_iso(), principal.principal_id))
            self._audit(wdb, principal, "resolve", None, "OK", {"selected": len(selected), "skipped": len(skipped)})
        return {"resolved_at": c.now_iso(), "channels": wanted, "bundles": selected, "not_applicable": skipped,
                "revocations": revocations, "policy_version": RELEASE_POLICY["policy_version"]}

    # ------------------------------------------------------------------ receipts
    def _ingest_receipts(self, principal: Principal, kind: str, items: Any) -> list[dict[str, Any]]:
        self._require_role(principal, f"ingest_{kind.lower()}", ("device_writer", "reviewer", "admin"))
        items = self._check_batch(items, kind.lower())
        results: list[dict[str, Any]] = []
        with self._tx() as db:
            for item in items:
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("receipt_id") or item.get("evaluation_id")
                try:
                    if not isinstance(item, dict) or not item_id:
                        raise c.ContractError([f"{kind}_ID_REQUIRED"])
                    if kind == "ADOPTION":
                        c.validate_adoption(item)
                    else:
                        missing = [k for k in ("tenant_id", "line_id", "device_id") if not item.get(k)]
                        if missing:
                            raise c.ContractError([f"MISSING:{k}" for k in missing])
                    codes = self._identity_codes(principal, item) + c.sensitive_findings(item)
                    if codes:
                        raise c.ContractError(codes)
                except c.ContractError as exc:
                    self._quarantine(db, principal, kind, item_id, exc.codes, item)
                    results.append({"id": item_id, "status": "REJECTED", "codes": exc.codes})
                    continue
                sha = c.digest(item)
                row = db.execute("SELECT content_sha FROM receipts WHERE tenant_id=? AND receipt_id=?",
                                 (principal.tenant_id, item_id)).fetchone()
                if row and row[0] == sha:
                    status, codes = "DUPLICATE", []
                elif row:
                    status, codes = "CONFLICT", [f"RECEIPT_ID_CONFLICT:{item_id}"]
                    self._quarantine(db, principal, kind, item_id, codes, item)
                else:
                    db.execute("INSERT INTO receipts(tenant_id, receipt_id, kind, content_sha, payload, line_id, "
                               "device_id, received_at) VALUES(?,?,?,?,?,?,?,?)",
                               (principal.tenant_id, item_id, kind, sha, json.dumps(item, ensure_ascii=False),
                                item["line_id"], item["device_id"], c.now_iso()))
                    status, codes = "CREATED", []
                self._log_delivery(db, principal, kind, item_id, status)
                results.append({"id": item_id, "status": status, "codes": codes})
            self._count(db, principal, results)
            self._audit(db, principal, f"ingest_{kind.lower()}", None, "OK", {"count": len(results)})
        return results

    @_audited
    def ingest_adoptions(self, principal: Principal, receipts: Any) -> list[dict[str, Any]]:
        return self._ingest_receipts(principal, "ADOPTION", receipts)

    @_audited
    def ingest_evaluations(self, principal: Principal, evaluations: Any) -> list[dict[str, Any]]:
        return self._ingest_receipts(principal, "EVALUATION", evaluations)

    @_audited
    def receipts_for_rule(self, principal: Principal, rule_id: str) -> list[dict[str, Any]]:
        rows = self._read("SELECT payload FROM receipts WHERE tenant_id=? AND kind='ADOPTION' ORDER BY received_at",
                          (principal.tenant_id,))
        return [p for p in (json.loads(r[0]) for r in rows) if p.get("rule_id") == rule_id]

    # ------------------------------------------------------------------ evidence
    @_audited
    def register_evidence(self, principal: Principal, meta: dict[str, Any]) -> dict[str, Any]:
        self._require_role(principal, "register_evidence", ("device_writer", "reviewer", "publisher", "admin"))
        if not isinstance(meta, dict):
            raise PayloadInvalid("evidence must be an object")
        evidence_id = meta.get("evidence_id") or c.new_uuid()
        if not c.is_sha256(meta.get("sha256")):
            raise PayloadInvalid("sha256 required")
        if not str(meta.get("storage_key") or "").strip():
            raise PayloadInvalid("storage_key required")
        visibility = meta.get("visibility", "LINE")
        if visibility not in ("LINE", "TENANT"):
            raise PayloadInvalid("visibility must be LINE or TENANT")
        line_id = meta.get("line_id") or (principal.line_ids[0] if principal.line_ids else "TENANT")
        if principal.role == "device_writer" and line_id not in principal.line_ids:
            raise Forbidden("line not permitted")
        findings = c.sensitive_findings({k: v for k, v in meta.items() if k != "sha256"})
        if findings:
            raise PayloadInvalid("evidence metadata carries sensitive content", {"codes": findings})
        with self._tx() as db:
            if db.execute("SELECT 1 FROM evidence WHERE tenant_id=? AND evidence_id=?",
                          (principal.tenant_id, evidence_id)).fetchone():
                raise Conflict(f"evidence exists: {evidence_id}")
            db.execute("INSERT INTO evidence(tenant_id, evidence_id, sha256, storage_key, visibility, line_id, "
                       "retention_until, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (principal.tenant_id, evidence_id, meta["sha256"], meta["storage_key"], visibility, line_id,
                        meta.get("retention_until"), principal.principal_id, c.now_iso()))
            for kind, key in (("CANDIDATE", "candidate_ids"), ("EVENT", "event_ids")):
                for target in meta.get(key) or []:
                    db.execute("INSERT OR IGNORE INTO evidence_links(tenant_id, evidence_id, target_kind, target_id) "
                               "VALUES(?,?,?,?)", (principal.tenant_id, evidence_id, kind, target))
                    if kind == "CANDIDATE":
                        self._refresh_evidence_status(db, principal.tenant_id, target)
            self._audit(db, principal, "register_evidence", evidence_id, "OK",
                        {"sha256": meta["sha256"], "visibility": visibility})
        return {"evidence_id": evidence_id, "status": "REGISTERED"}

    def _refresh_evidence_status(self, db: sqlite3.Connection, tenant_id: str, candidate_id: str) -> None:
        rows = db.execute("SELECT e.deleted_at FROM evidence_links l JOIN evidence e ON e.tenant_id=l.tenant_id AND "
                          "e.evidence_id=l.evidence_id WHERE l.tenant_id=? AND l.target_kind='CANDIDATE' AND "
                          "l.target_id=?", (tenant_id, candidate_id)).fetchall()
        if not rows:
            status, eligible = "NO_EVIDENCE_REGISTERED", 1
        elif any(r[0] for r in rows):
            status, eligible = "EVIDENCE_UNAVAILABLE", 0
        else:
            status, eligible = "EVIDENCE_AVAILABLE", 1
        rec = self._candidate_row(db, tenant_id, candidate_id)
        if rec is None:
            return
        needs = 1 if (status == "EVIDENCE_UNAVAILABLE" and rec["state"] in ("VALIDATED", "CANARY", "RELEASED")) \
            else int(rec["needs_reevaluation"])
        etag = _etag(candidate_id, rec["revision"], rec["state"], c.digest(rec["payload"]), rec["validation_scopes"],
                     status)
        db.execute("UPDATE candidates SET evidence_status=?, promotion_eligible=?, needs_reevaluation=?, etag=?, "
                   "updated_at=? WHERE tenant_id=? AND candidate_id=?",
                   (status, eligible, needs, etag, c.now_iso(), tenant_id, candidate_id))

    @_audited
    def delete_evidence(self, principal: Principal, evidence_id: str) -> dict[str, Any]:
        """Mark evidence deleted (bytes are removed from object storage by its owner).

        Every candidate citing it becomes EVIDENCE_UNAVAILABLE and loses promotion
        eligibility; a candidate already in VALIDATED/CANARY/RELEASED is flagged for
        re-evaluation instead of keeping a false "evidence complete".
        """
        with self._tx() as db:
            row = db.execute("SELECT created_by, line_id, deleted_at FROM evidence WHERE tenant_id=? AND evidence_id=?",
                             (principal.tenant_id, evidence_id)).fetchone()
            if not row:
                raise NotFound(f"evidence not found: {evidence_id}")
            if principal.role not in ("admin", "publisher") and row[0] != principal.principal_id:
                raise Forbidden("only the creator, a publisher or an admin may delete evidence")
            if row[2]:
                return {"evidence_id": evidence_id, "status": "ALREADY_DELETED", "deleted_at": row[2]}
            now = c.now_iso()
            db.execute("UPDATE evidence SET deleted_at=?, deleted_by=? WHERE tenant_id=? AND evidence_id=?",
                       (now, principal.principal_id, principal.tenant_id, evidence_id))
            affected = [r[0] for r in db.execute("SELECT target_id FROM evidence_links WHERE tenant_id=? AND "
                                                 "evidence_id=? AND target_kind='CANDIDATE'",
                                                 (principal.tenant_id, evidence_id)).fetchall()]
            for candidate_id in affected:
                self._refresh_evidence_status(db, principal.tenant_id, candidate_id)
            self._audit(db, principal, "delete_evidence", evidence_id, "OK", {"affected_candidates": affected})
        return {"evidence_id": evidence_id, "status": "DELETED", "deleted_at": now, "affected_candidates": affected}

    # ------------------------------------------------------------------ ops
    def health(self) -> dict[str, Any]:
        db = self._db()
        versions = [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
        ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        return {"status": "OK" if ok else "DEGRADED", "schema_versions": versions,
                "release_policy_version": RELEASE_POLICY["policy_version"], "time": c.now_iso()}

    @_audited
    def sync_status(self, principal: Principal) -> dict[str, Any]:
        query = ("SELECT principal_id, role, line_ids, canary, status, last_seen, accepted, duplicates, rejected, "
                 "rotated_at, revoked_at FROM principals WHERE tenant_id=?")
        args: tuple[Any, ...] = (principal.tenant_id,)
        if principal.role == "device_writer":
            query += " AND principal_id=?"
            args += (principal.principal_id,)
        rows = self._read(query + " ORDER BY principal_id", args)
        keys = ("principal_id", "role", "line_ids", "canary", "status", "last_seen", "accepted", "duplicates",
                "rejected", "rotated_at", "revoked_at")
        out = []
        for r in rows:
            d = dict(zip(keys, r))
            d["line_ids"] = json.loads(d["line_ids"])
            d["canary"] = bool(d["canary"])
            out.append(d)
        return {"tenant_id": principal.tenant_id, "principals": out}

    @_audited
    def failures(self, principal: Principal, limit: int = 200) -> dict[str, Any]:
        query = "SELECT at, principal_id, item_kind, item_id, codes, payload_sha FROM quarantine WHERE tenant_id=?"
        args: tuple[Any, ...] = (principal.tenant_id,)
        if principal.role == "device_writer":
            query += " AND principal_id=?"
            args += (principal.principal_id,)
        rows = self._read(query + " ORDER BY id DESC LIMIT ?", args + (int(limit),))
        return {"tenant_id": principal.tenant_id, "failures": [
            {"at": r[0], "principal_id": r[1], "item_kind": r[2], "item_id": r[3], "codes": json.loads(r[4]),
             "payload_sha": r[5]} for r in rows]}

    def audit_entries(self, tenant_id: str, *, action: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT at, principal_id, action, target, outcome, detail FROM audit_log WHERE tenant_id IS ?"
        args: tuple[Any, ...] = (tenant_id,)
        if action:
            query += " AND action=?"
            args += (action,)
        rows = self._read(query + " ORDER BY id", args)
        return [{"at": r[0], "principal_id": r[1], "action": r[2], "target": r[3], "outcome": r[4],
                 "detail": json.loads(r[5])} for r in rows]

    @_audited
    def trace_candidate(self, principal: Principal, candidate_id: str) -> dict[str, Any]:
        """Candidate -> events -> evidence -> reviews -> bundles/channels/revocations -> adoptions."""
        self._require_role(principal, "trace_candidate", ("admin", "publisher", "reviewer"))
        cand = self.get_candidate(principal, candidate_id)
        db = self._db()
        event_ids = cand["payload"].get("event_ids") or []
        events = []
        for event_id in event_ids:
            row = db.execute("SELECT payload, received_at FROM events WHERE tenant_id=? AND event_id=?",
                             (principal.tenant_id, event_id)).fetchone()
            if row:
                ev = json.loads(row[0])
                events.append({"event_id": event_id, "line_id": ev["line_id"], "device_id": ev["device_id"],
                               "episode_id": ev["episode_id"], "stage": ev["stage"], "event_kind": ev["event_kind"],
                               "symptom": ev["symptom"], "source_event_id": ev.get("source_event_id"),
                               "received_at": row[1],
                               "reviews": self.attribution_chain(principal.tenant_id, event_id)})
        evidence = [dict(zip(("evidence_id", "sha256", "storage_key", "visibility", "retention_until", "deleted_at"),
                             r)) for r in db.execute(
            "SELECT e.evidence_id, e.sha256, e.storage_key, e.visibility, e.retention_until, e.deleted_at FROM evidence e "
            "JOIN evidence_links l ON l.tenant_id=e.tenant_id AND l.evidence_id=e.evidence_id WHERE e.tenant_id=? AND "
            "((l.target_kind='CANDIDATE' AND l.target_id=?) OR (l.target_kind='EVENT' AND l.target_id IN (%s)))"
            % (",".join("?" * len(event_ids)) or "NULL"), (principal.tenant_id, candidate_id, *event_ids)).fetchall()]
        bundles = []
        for bundle_id, version, digest, manifest_json, uploaded_at in db.execute(
                "SELECT bundle_id, version, digest, manifest, uploaded_at FROM bundles WHERE tenant_id=? "
                "ORDER BY uploaded_at", (principal.tenant_id,)).fetchall():
            manifest = json.loads(manifest_json)
            rule_ids = [r.get("rule_id") if isinstance(r, dict) else r for r in manifest.get("rules") or []]
            if candidate_id not in rule_ids:
                continue
            channels = [ch for (ch,) in db.execute("SELECT channel FROM channels WHERE tenant_id=? AND bundle_id=? "
                                                   "AND version=?", (principal.tenant_id, bundle_id, version))]
            revoked = db.execute("SELECT reason, at FROM revocations WHERE tenant_id=? AND bundle_id=? AND version=?",
                                 (principal.tenant_id, bundle_id, version)).fetchone()
            bundles.append({"bundle_id": bundle_id, "version": version, "digest": digest, "uploaded_at": uploaded_at,
                            "channels": channels, "revoked": {"reason": revoked[0], "at": revoked[1]} if revoked else None})
        return {"candidate": cand, "history": self.candidate_history(principal, candidate_id),
                "independent_sources": self.independent_sources(principal, candidate_id),
                "events": events, "evidence": evidence, "bundles": bundles,
                "adoptions": self.receipts_for_rule(principal, candidate_id)}

    @_audited
    def list_candidates(self, principal: Principal) -> list[dict[str, Any]]:
        rows = self._read("SELECT candidate_id FROM candidates WHERE tenant_id=? ORDER BY updated_at DESC",
                          (principal.tenant_id,))
        return [self.get_candidate(principal, r[0]) for r in rows]
