-- Collective learning service, schema version 2: explicit one-time baseline import.
--
-- Audit 2026-11-12 §5.2 gap 1: a bundle whose manifest says ``baseline: true`` used to skip
-- every rule-state check on release.  Now that bypass applies only to a bundle version an
-- admin imported through ``Service.import_baseline`` (s3_sync.py import-baseline), and only
-- once per tenant: the first approved snapshot of rules that predate the candidate store.
-- Any later bundle -- baseline flag or not -- goes through the normal candidate states.

CREATE TABLE IF NOT EXISTS baseline_imports (
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    bundle_id TEXT NOT NULL,
    version TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, bundle_id, version)
);
