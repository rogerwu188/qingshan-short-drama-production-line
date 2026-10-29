"""One device's durable store: facts, revisions, adoption/evaluation receipts and the outbox.

Why SQLite and not the existing JSONL: ``tools/knowledge_event_log.py`` rewrites the
whole file on every update (read-all / write-all).  Two processes doing that at
once lose each other's rows -- ``test_collective_device_store.LegacyLogRaceTest``
reproduces it.  Here every write is one ``BEGIN IMMEDIATE`` transaction that
inserts the fact AND its outbox row together, so a crash can never leave a fact
without its pending upload or an upload without its fact (transactional outbox).

One authority: the SQLite file.  ``export_jsonl`` regenerates the legacy
``KNOWLEDGE_EVENTS.jsonl`` view for tools that still read it; nothing reads the
JSONL back as a source of truth.

Identity: ``device_id`` is minted once per store and kept in ``meta``.  It is not a
hostname and not a line id -- several lines can share one device, and each line
has its own store file, so (device_id, line_id) pairs stay distinct.

Durability: WAL + ``synchronous=FULL``; a committed fact survives power loss.  An
item is marked DELIVERED only after the service returned a per-item persisted
acknowledgement (see ``sync_client``).
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import contracts as c

STORE_RELPATH = "reports/COLLECTIVE_DEVICE_STORE.sqlite"
LEGACY_EXPORT_RELPATH = "reports/KNOWLEDGE_EVENTS.jsonl"
STORE_SCHEMA_VERSION = 1

OUTBOX_KINDS = ("EVENT", "REVIEW", "ADOPTION", "EVALUATION")
OUTBOX_STATES = ("PENDING", "DELIVERED", "QUARANTINED")

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sequences (stream TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    content_sha TEXT NOT NULL,
    payload TEXT NOT NULL,
    run_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    visibility TEXT NOT NULL,
    producer_sequence INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_episode ON events(episode_id);
CREATE TABLE IF NOT EXISTS event_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    existing_sha TEXT NOT NULL,
    attempted_sha TEXT NOT NULL,
    attempted_payload TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    review_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(event_id),
    review_version INTEGER NOT NULL,
    content_sha TEXT NOT NULL,
    payload TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(event_id, review_version)
);
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    payload TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    server_ack TEXT,
    UNIQUE(item_kind, item_id)
);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(state, next_attempt_at);
"""


class EventConflict(c.ContractError):
    """Same event_id, different content.  The original is kept; the attempt is audited."""


class DeviceStore:
    def __init__(self, path: Path, *, tenant_id: str, line_id: str, device_id: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tenant_id = tenant_id
        self.line_id = line_id
        self._init_schema()
        self.device_id = self._identity(device_id)

    # ------------------------------------------------------------------ plumbing
    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=60000")
        return db

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            for attempt in range(50):
                try:
                    db.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:  # pragma: no cover - only under heavy contention
                    if "locked" not in str(exc) or attempt == 49:
                        raise
                    time.sleep(0.01 + random.random() * 0.05)
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        finally:
            db.close()

    def _init_schema(self) -> None:
        db = self._connect()
        try:
            db.executescript(_DDL)
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('store_schema_version', ?)",
                       (str(STORE_SCHEMA_VERSION),))
        finally:
            db.close()

    def _identity(self, requested: str | None) -> str:
        with self._tx() as db:
            row = db.execute("SELECT value FROM meta WHERE key='device_id'").fetchone()
            if row:
                if requested and requested != row[0]:
                    raise c.ContractError([f"DEVICE_ID_MISMATCH:store={row[0]}:requested={requested}"])
                stored_line = db.execute("SELECT value FROM meta WHERE key='line_id'").fetchone()
                if stored_line and stored_line[0] != self.line_id:
                    raise c.ContractError([f"STORE_BELONGS_TO_OTHER_LINE:{stored_line[0]}"])
                return row[0]
            device_id = requested or f"dev-{c.new_uuid()}"
            if not c.is_identifier(device_id):
                raise c.ContractError(["DEVICE_ID_INVALID"])
            db.executemany("INSERT INTO meta(key, value) VALUES(?, ?)",
                           [("device_id", device_id), ("tenant_id", self.tenant_id), ("line_id", self.line_id)])
            return device_id

    @staticmethod
    def _next_sequence(db: sqlite3.Connection, stream: str) -> int:
        db.execute("INSERT INTO sequences(stream, value) VALUES(?, 1) "
                   "ON CONFLICT(stream) DO UPDATE SET value = value + 1", (stream,))
        return int(db.execute("SELECT value FROM sequences WHERE stream=?", (stream,)).fetchone()[0])

    @staticmethod
    def _enqueue(db: sqlite3.Connection, kind: str, item_id: str, payload: dict[str, Any]) -> None:
        db.execute("INSERT OR IGNORE INTO outbox(item_kind, item_id, payload, created_at) VALUES(?,?,?,?)",
                   (kind, item_id, json.dumps(payload, ensure_ascii=False), c.now_iso()))

    # ------------------------------------------------------------------ facts
    def record_observation(self, *, run_id: str, episode_id: str, stage: str, event_kind: str,
                           symptom: str, evidence: dict[str, Any], detected_by: str,
                           unit_ids: list[str] | None = None, visibility: str = "PRIVATE_LOCAL",
                           opportunity: dict[str, int] | None = None, artifact_digest: str | None = None,
                           engine_version: str = c.UNKNOWN, provider_model_version: str = c.UNKNOWN,
                           knowledge_bundle_digest: str = "NONE", occurred_at: str | None = None,
                           event_id: str | None = None, source_event_id: str | None = None,
                           _crash_after_event_insert: bool = False) -> dict[str, Any]:
        """Persist one fact and (unless PRIVATE_LOCAL) its upload row in ONE transaction.

        There is no ``root_cause`` parameter: a cause is a separate revision
        (:meth:`record_review`).  ``_crash_after_event_insert`` exists only for the
        crash-consistency test: it raises between the two inserts.
        """
        with self._tx() as db:
            seq = self._next_sequence(db, f"device:{self.device_id}")
            event = c.make_observation(
                tenant_id=self.tenant_id, line_id=self.line_id, device_id=self.device_id, run_id=run_id,
                episode_id=episode_id, stage=stage, event_kind=event_kind, symptom=symptom, evidence=evidence,
                detected_by=detected_by, producer_sequence=seq, unit_ids=unit_ids,
                artifact_digest=artifact_digest, engine_version=engine_version,
                provider_model_version=provider_model_version, knowledge_bundle_digest=knowledge_bundle_digest,
                visibility=visibility, opportunity=opportunity, occurred_at=occurred_at, event_id=event_id,
                source_event_id=source_event_id)
            self._insert_event(db, event)
            if _crash_after_event_insert:
                raise RuntimeError("SIMULATED_CRASH_BETWEEN_FACT_AND_OUTBOX")
            if event["visibility"] != "PRIVATE_LOCAL":
                self._enqueue(db, "EVENT", event["event_id"], event)
            return event

    def put_observation(self, event: dict[str, Any]) -> dict[str, Any]:
        """Store an already-built event (replay/import).  Idempotent on identical content."""
        c.validate_observation(event)
        with self._tx() as db:
            result = self._insert_event(db, event)
            if result["status"] == "CREATED" and event["visibility"] != "PRIVATE_LOCAL":
                self._enqueue(db, "EVENT", event["event_id"], event)
        if result["status"] == "CONFLICT":
            raise EventConflict([f"EVENT_ID_CONFLICT:{event['event_id']}"])
        return result

    def _insert_event(self, db: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
        sha = c.observation_digest(event)
        row = db.execute("SELECT content_sha FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
        if row:
            if row[0] == sha:
                return {"status": "DUPLICATE", "event_id": event["event_id"], "content_sha": sha}
            db.execute("INSERT INTO event_conflicts(event_id, existing_sha, attempted_sha, attempted_payload, "
                       "detected_at) VALUES(?,?,?,?,?)",
                       (event["event_id"], row[0], sha, json.dumps(event, ensure_ascii=False), c.now_iso()))
            return {"status": "CONFLICT", "event_id": event["event_id"], "existing_sha": row[0],
                    "attempted_sha": sha}
        db.execute("INSERT INTO events(event_id, content_sha, payload, run_id, episode_id, event_kind, "
                   "visibility, producer_sequence, recorded_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (event["event_id"], sha, json.dumps(event, ensure_ascii=False), event["run_id"],
                    event["episode_id"], event["event_kind"], event["visibility"],
                    event["producer_sequence"], c.now_iso()))
        return {"status": "CREATED", "event_id": event["event_id"], "content_sha": sha}

    # ------------------------------------------------------------------ revisions
    def record_review(self, *, event_id: str, reviewer_id: str, status: str,
                      root_cause_hypothesis: str | None = None, basis: str | None = None,
                      confidence: str | None = None, supporting_evidence: list[Any] | None = None,
                      counter_evidence: list[Any] | None = None, reason: str | None = None,
                      candidate_ids: list[str] | None = None, share: bool = True) -> dict[str, Any]:
        """Append an immutable attribution revision.  Never edits the fact or an earlier revision."""
        with self._tx() as db:
            if not db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                raise c.ContractError([f"EVENT_NOT_FOUND:{event_id}"])
            version = 1 + int(db.execute("SELECT COALESCE(MAX(review_version), 0) FROM revisions "
                                         "WHERE event_id=?", (event_id,)).fetchone()[0])
            review: dict[str, Any] = {
                "schema": c.ATTRIBUTION_SCHEMA, "schema_version": c.SCHEMA_VERSION,
                "review_id": c.new_uuid(), "event_id": event_id, "reviewer_id": reviewer_id,
                "status": status, "review_version": version, "reviewed_at": c.now_iso(),
                "tenant_id": self.tenant_id, "line_id": self.line_id, "device_id": self.device_id,
            }
            if status == "ATTRIBUTED":
                review.update(root_cause_hypothesis=root_cause_hypothesis, basis=basis, confidence=confidence,
                              supporting_evidence=list(supporting_evidence or []),
                              counter_evidence=list(counter_evidence or []))
            else:
                review["reason"] = reason
            if candidate_ids:
                review["candidate_ids"] = list(candidate_ids)
            c.validate_attribution(review)
            db.execute("INSERT INTO revisions(review_id, event_id, review_version, content_sha, payload, "
                       "recorded_at) VALUES(?,?,?,?,?,?)",
                       (review["review_id"], event_id, version, c.digest(review),
                        json.dumps(review, ensure_ascii=False), review["reviewed_at"]))
            visibility = json.loads(db.execute("SELECT payload FROM events WHERE event_id=?",
                                               (event_id,)).fetchone()[0])["visibility"]
            if share and visibility != "PRIVATE_LOCAL":  # a review inherits its event's visibility
                findings = c.sensitive_findings(review)
                if findings:
                    raise c.ContractError(findings)
                self._enqueue(db, "REVIEW", review["review_id"], review)
            return review

    def attribution_chain(self, event_id: str) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            rows = db.execute("SELECT payload FROM revisions WHERE event_id=? ORDER BY review_version",
                              (event_id,)).fetchall()
        finally:
            db.close()
        return [json.loads(r[0]) for r in rows]

    # ------------------------------------------------------------------ receipts
    def record_receipt(self, kind: str, receipt: dict[str, Any], *, share: bool = True) -> dict[str, Any]:
        """Adoption or evaluation receipt.  Immutable: a receipt id is written once."""
        if kind not in ("ADOPTION", "EVALUATION"):
            raise c.ContractError([f"RECEIPT_KIND_INVALID:{kind}"])
        receipt_id = receipt.get("receipt_id") or receipt.get("evaluation_id")
        if not receipt_id:
            raise c.ContractError(["RECEIPT_ID_REQUIRED"])
        if kind == "ADOPTION":
            c.validate_adoption(receipt)
        sha = c.digest(receipt)
        with self._tx() as db:
            row = db.execute("SELECT content_sha FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
            if row:
                if row[0] != sha:
                    raise c.ContractError([f"RECEIPT_ID_CONFLICT:{receipt_id}"])
                return receipt
            db.execute("INSERT INTO receipts(receipt_id, kind, content_sha, payload, recorded_at) "
                       "VALUES(?,?,?,?,?)", (receipt_id, kind, sha, json.dumps(receipt, ensure_ascii=False),
                                             c.now_iso()))
            if share:
                findings = c.sensitive_findings(receipt)
                if findings:
                    raise c.ContractError(findings)
                self._enqueue(db, kind, receipt_id, receipt)
        return receipt

    def receipts(self, kind: str | None = None) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            query = "SELECT payload FROM receipts" + (" WHERE kind=?" if kind else "") + " ORDER BY recorded_at"
            rows = db.execute(query, (kind,) if kind else ()).fetchall()
        finally:
            db.close()
        return [json.loads(r[0]) for r in rows]

    # ------------------------------------------------------------------ reads
    def events(self, *, episode_id: str | None = None) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            if episode_id:
                rows = db.execute("SELECT payload FROM events WHERE episode_id=? ORDER BY producer_sequence",
                                  (episode_id,)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM events ORDER BY producer_sequence").fetchall()
        finally:
            db.close()
        return [json.loads(r[0]) for r in rows]

    def conflicts(self) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            rows = db.execute("SELECT event_id, existing_sha, attempted_sha, detected_at FROM event_conflicts "
                              "ORDER BY id").fetchall()
        finally:
            db.close()
        return [dict(zip(("event_id", "existing_sha", "attempted_sha", "detected_at"), r)) for r in rows]

    def count(self, table: str, where: str = "", args: tuple[Any, ...] = ()) -> int:
        if table not in ("events", "revisions", "receipts", "outbox", "event_conflicts"):
            raise ValueError(table)
        db = self._connect()
        try:
            return int(db.execute(f"SELECT COUNT(*) FROM {table} {where}", args).fetchone()[0])
        finally:
            db.close()

    # ------------------------------------------------------------------ outbox
    def claim_due(self, limit: int, *, now: float | None = None) -> list[dict[str, Any]]:
        """Pending items whose backoff has elapsed, oldest first.  Does not change state."""
        now = time.time() if now is None else now
        db = self._connect()
        try:
            rows = db.execute("SELECT outbox_id, item_kind, item_id, payload, attempts FROM outbox "
                              "WHERE state='PENDING' AND next_attempt_at<=? ORDER BY outbox_id LIMIT ?",
                              (now, int(limit))).fetchall()
        finally:
            db.close()
        return [{"outbox_id": r[0], "item_kind": r[1], "item_id": r[2], "payload": json.loads(r[3]),
                 "attempts": r[4]} for r in rows]

    def mark_delivered(self, acks: list[tuple[int, dict[str, Any]]]) -> None:
        with self._tx() as db:
            db.executemany("UPDATE outbox SET state='DELIVERED', delivered_at=?, server_ack=?, last_error=NULL "
                           "WHERE outbox_id=? AND state='PENDING'",
                           [(c.now_iso(), json.dumps(ack, ensure_ascii=False), oid) for oid, ack in acks])

    def mark_retry(self, outbox_ids: list[int], error: str, *, base: float = 1.0, cap: float = 300.0,
                   now: float | None = None) -> None:
        """Full-jitter exponential backoff per item, so a fleet reconnecting does not stampede."""
        now = time.time() if now is None else now
        with self._tx() as db:
            for oid in outbox_ids:
                row = db.execute("SELECT attempts FROM outbox WHERE outbox_id=?", (oid,)).fetchone()
                attempts = int(row[0]) + 1 if row else 1
                delay = random.uniform(0, min(cap, base * (2 ** min(attempts, 16))))
                db.execute("UPDATE outbox SET attempts=?, next_attempt_at=?, last_error=? WHERE outbox_id=? "
                           "AND state='PENDING'", (attempts, now + delay, error[:500], oid))

    def quarantine(self, outbox_id: int, reason: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE outbox SET state='QUARANTINED', last_error=? WHERE outbox_id=?",
                       (reason[:2000], outbox_id))

    def outbox_status(self) -> dict[str, Any]:
        db = self._connect()
        try:
            counts = dict(db.execute("SELECT state, COUNT(*) FROM outbox GROUP BY state").fetchall())
            quarantined = db.execute("SELECT item_kind, item_id, last_error FROM outbox WHERE state='QUARANTINED' "
                                     "ORDER BY outbox_id").fetchall()
        finally:
            db.close()
        return {"device_id": self.device_id, "line_id": self.line_id,
                "counts": {s: int(counts.get(s, 0)) for s in OUTBOX_STATES},
                "quarantined": [{"item_kind": k, "item_id": i, "reason": e} for k, i, e in quarantined]}

    # ------------------------------------------------------------------ legacy export
    def export_jsonl(self, path: Path) -> int:
        """Regenerate the legacy ``knowledge_event_log`` view (one row per fact, latest attribution).

        A derived view: written atomically, never read back as authority.
        """
        rows = []
        for event in self.events():
            chain = self.attribution_chain(event["event_id"])
            latest = chain[-1] if chain else None
            if latest is None:
                attribution: dict[str, Any] = {"status": "UNATTRIBUTED"}
            elif latest["status"] == "ATTRIBUTED":
                attribution = {"status": "ATTRIBUTED", "root_cause": latest["root_cause_hypothesis"],
                               "attributed_by": latest["reviewer_id"], "attributed_at": latest["reviewed_at"],
                               "confidence": latest["confidence"], "basis": latest["basis"]}
            else:
                attribution = {"status": "INCONCLUSIVE", "reason": latest["reason"],
                               "attributed_by": latest["reviewer_id"], "attributed_at": latest["reviewed_at"]}
            rows.append({
                "schema": "qingshan.knowledge_event.v1", "event_id": event["event_id"],
                "recorded_at": event["occurred_at"], "line": event["line_id"], "episode": event["episode_id"],
                "stage": event["stage"], "unit_ids": event["unit_ids"], "symptom": event["symptom"],
                "evidence": event["evidence"], "detected_by": event["detected_by"],
                "attribution": attribution, "attribution_history": [
                    {"status": r["status"], "review_id": r["review_id"]} for r in chain[:-1]],
                "collective_event_kind": event["event_kind"], "device_id": event["device_id"],
                "run_id": event["run_id"],
            })
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(path)
        return len(rows)


def store_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / STORE_RELPATH


def open_store(runtime_root: Path, *, tenant_id: str, line_id: str, create: bool = False) -> DeviceStore | None:
    """The line's store if the line opted in (file exists), else None.  ``create`` opts in."""
    path = store_path(runtime_root)
    if not path.is_file() and not create:
        return None
    return DeviceStore(path, tenant_id=tenant_id, line_id=line_id)
