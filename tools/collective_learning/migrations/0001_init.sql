-- Collective learning service, schema version 1.
--
-- Written for SQLite (first version) in a deliberately portable subset so a
-- PostgreSQL port is mechanical:
--   * INTEGER PRIMARY KEY AUTOINCREMENT  -> BIGSERIAL / GENERATED ALWAYS AS IDENTITY
--   * BLOB                                -> BYTEA
--   * TEXT timestamps (ISO-8601, UTC 'Z') -> TIMESTAMPTZ (values parse unchanged)
--   * JSON stored as TEXT                 -> JSONB
-- No SQLite-only functions are used in constraints or defaults.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

-- Every credential holder is a principal: devices (device_writer) and humans/services
-- (reviewer, publisher, admin).  Only the sha256 of a token is stored.
CREATE TABLE IF NOT EXISTS principals (
    principal_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    role TEXT NOT NULL CHECK (role IN ('device_writer', 'reviewer', 'publisher', 'admin')),
    line_ids TEXT NOT NULL,              -- JSON list; empty for tenant-wide roles
    canary INTEGER NOT NULL DEFAULT 0,   -- enrolled in the CANARY channel
    token_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    revoked_at TEXT,
    last_seen TEXT,
    accepted INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    payload TEXT NOT NULL,
    line_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    source_event_id TEXT,
    identity_sha TEXT NOT NULL,          -- content minus identity fields: collapses cloned replays
    received_at TEXT NOT NULL,
    received_by TEXT NOT NULL,
    PRIMARY KEY (tenant_id, event_id)
);
CREATE INDEX IF NOT EXISTS events_line ON events(tenant_id, line_id);

-- One row per delivery attempt that reached the service (duplicates included), so a
-- redelivery is traceable without ever inflating the unique event count.
CREATE TABLE IF NOT EXISTS delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    status TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS delivery_item ON delivery_log(tenant_id, item_kind, item_id);

CREATE TABLE IF NOT EXISTS event_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    existing_sha TEXT NOT NULL,
    attempted_sha TEXT NOT NULL,
    attempted_payload TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    tenant_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    review_version INTEGER NOT NULL,
    content_sha TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL,
    received_by TEXT NOT NULL,
    PRIMARY KEY (tenant_id, review_id)
);
CREATE INDEX IF NOT EXISTS reviews_event ON reviews(tenant_id, event_id);

CREATE TABLE IF NOT EXISTS candidates (
    tenant_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    category TEXT NOT NULL,
    payload TEXT NOT NULL,
    validation_scopes TEXT NOT NULL,     -- JSON list
    evidence_status TEXT NOT NULL,       -- EVIDENCE_AVAILABLE | EVIDENCE_UNAVAILABLE | NO_EVIDENCE_REGISTERED
    promotion_eligible INTEGER NOT NULL,
    needs_reevaluation INTEGER NOT NULL DEFAULT 0,
    origin_line_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    etag TEXT NOT NULL,
    PRIMARY KEY (tenant_id, candidate_id)
);

-- Immutable history: every revision and every state transition, never edited.
CREATE TABLE IF NOT EXISTS candidate_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    action TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    payload TEXT NOT NULL,
    detail TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bundles (
    tenant_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    version TEXT NOT NULL,
    digest TEXT NOT NULL,
    payload BLOB NOT NULL,
    signature_b64 TEXT NOT NULL,
    key_id TEXT NOT NULL,
    manifest TEXT NOT NULL,
    signature_check TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, bundle_id, version)
);

CREATE TABLE IF NOT EXISTS channels (
    tenant_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('CANARY', 'RELEASED')),
    version TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, bundle_id, channel)
);

CREATE TABLE IF NOT EXISTS channel_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    from_version TEXT,
    to_version TEXT,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revocations (
    tenant_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    version TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, bundle_id, version)
);

CREATE TABLE IF NOT EXISTS receipts (
    tenant_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ADOPTION', 'EVALUATION')),
    content_sha TEXT NOT NULL,
    payload TEXT NOT NULL,
    line_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, receipt_id)
);

-- Evidence metadata only.  Bytes live in project-authorised object storage under
-- storage_key; this service never receives private media by default.
CREATE TABLE IF NOT EXISTS evidence (
    tenant_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    visibility TEXT NOT NULL,
    line_id TEXT NOT NULL,
    retention_until TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by TEXT,
    PRIMARY KEY (tenant_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS evidence_links (
    tenant_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('CANDIDATE', 'EVENT')),
    target_id TEXT NOT NULL,
    PRIMARY KEY (tenant_id, evidence_id, target_kind, target_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    tenant_id TEXT,
    principal_id TEXT,
    action TEXT NOT NULL,
    target TEXT,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL
);

-- Bad items: diagnosable (codes, payload sha) without storing the payload, which may
-- be exactly the sensitive content that got it rejected.
CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    item_id TEXT,
    codes TEXT NOT NULL,
    payload_sha TEXT NOT NULL
);
