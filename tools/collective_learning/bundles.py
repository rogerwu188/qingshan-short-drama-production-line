"""Immutable, signed knowledge bundles; executable skill packages; run knowledge locks.

Knowledge bundle (``qingshan.collective.knowledge_bundle.v1``) -- DATA ONLY:
    {schema, bundle_id, version, created_at, release_channel,
     compat: {engine_api_versions: [...], models: [...]},
     rules: [{rule_id, rule_version, category, scope, trigger, recommendation, exceptions,
              known_counterexamples, verification, cost_class, evidence_level, validation_scope,
              impact_scope?, application?: {carrier, prompt_clause: {zh?, en?}}}]}

Signed envelope (``qingshan.collective.signed_bundle.v1``):
    {schema, bundle, digest = sha256(canonical_json(bundle)),
     signature: {key_id, algorithm: "Ed25519", value_b64}}
The signature covers ``SIGNING_DOMAIN + digest`` (domain-separated, so a bundle
signature can never be replayed as a skill signature or vice versa).

Trust: devices pin publisher public keys in a local trust store
(``qingshan.collective.trust_store.v1``).  A signature proves WHO published, not
that the content is right -- regression and review happen before release, on the
service side.  Verification fails closed: no ``cryptography`` module, unknown or
revoked key, wrong role, digest mismatch, schema violation, executable content or
an authority flag on any rule -> rejected.

Skills are executable and NEVER travel inside a knowledge bundle (a bundle that
carries one is rejected).  A skill package is a signed manifest whose code ships
with the engine release process (git + deployment integrity); this module only
verifies the manifest's provenance, declared permissions and code digest.

Run lock: written once per run_id, never re-resolved.  A new release only reaches
new runs.  ``verify_lock_for_send`` re-hashes the locked bytes before every send or
resume, so a same-path replacement after the check is detected (T13).
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import contracts as c
from .selection import CONTROL_LANGUAGE

SIGNED_SCHEMA = "qingshan.collective.signed_bundle.v1"
TRUST_SCHEMA = "qingshan.collective.trust_store.v1"
SKILL_SCHEMA = "qingshan.collective.skill_package.v1"
SIGNED_SKILL_SCHEMA = "qingshan.collective.signed_skill.v1"
REVOCATION_SCHEMA = "qingshan.collective.revocation_list.v1"
SIGNING_DOMAIN = b"qingshan.collective.bundle.v1\n"
SKILL_SIGNING_DOMAIN = b"qingshan.collective.skill.v1\n"
REVOCATION_SIGNING_DOMAIN = b"qingshan.collective.revocations.v1\n"
BUILTIN_LABEL = "BUILTIN_BASELINE_NOT_CLOUD_SYNCED"

KNOWLEDGE_PUBLISHER = "KNOWLEDGE_PUBLISHER"
SKILL_PUBLISHER = "SKILL_PUBLISHER"

CHANNELS = ("CANARY", "RELEASED")
# A device enrolled in CANARY also accepts RELEASED; a RELEASED device never takes CANARY.
CHANNEL_ACCEPTS = {"RELEASED": {"RELEASED"}, "CANARY": {"CANARY", "RELEASED"}}
CARRIERS = ("BEAT_DIRECTION", "NEGATIVE_CONSTRAINT", "CHECK_ONLY")
EXECUTABLE_KEYS = ("skill", "skills", "executable", "code", "python", "shell", "script", "exec", "entrypoint")


class BundleError(c.ContractError):
    pass


# --------------------------------------------------------------------------- crypto
def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # fail closed: no crypto, no adoption
        raise BundleError([f"SIGNATURE_VERIFICATION_UNAVAILABLE:{exc}"]) from exc
    return Ed25519PrivateKey, Ed25519PublicKey, serialization, InvalidSignature


def generate_keypair() -> tuple[bytes, str]:
    """(private key raw bytes, public key base64).  Private keys stay with the publisher."""
    priv_cls, _, serialization, _ = _crypto()
    key = priv_cls.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw, base64.b64encode(pub).decode("ascii")


def _sign(private_raw: bytes, message: bytes) -> str:
    priv_cls, _, _, _ = _crypto()
    return base64.b64encode(priv_cls.from_private_bytes(private_raw).sign(message)).decode("ascii")


def _verify_sig(public_b64: str, signature_b64: str, message: bytes) -> bool:
    _, pub_cls, _, invalid = _crypto()
    try:
        pub_cls.from_public_bytes(base64.b64decode(public_b64)).verify(base64.b64decode(signature_b64), message)
        return True
    except (invalid, ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- trust store
def make_trust_store(publishers: dict[str, dict[str, Any]], *, allow_shell: bool = False,
                     allow_network: bool = False, allow_dynamic_install: bool = False) -> dict[str, Any]:
    return {"schema": TRUST_SCHEMA, "publishers": publishers,
            "skill_policy": {"allow_shell": allow_shell, "allow_network": allow_network,
                             "allow_dynamic_install": allow_dynamic_install}}


def load_trust_store(path: Path) -> dict[str, Any]:
    trust = json.loads(Path(path).read_text(encoding="utf-8"))
    if trust.get("schema") != TRUST_SCHEMA or not isinstance(trust.get("publishers"), dict):
        raise BundleError(["TRUST_STORE_INVALID"])
    return trust


def _check_signer(trust: dict[str, Any], signature: dict[str, Any], role: str, message: bytes) -> list[str]:
    key_id = str((signature or {}).get("key_id") or "")
    publisher = (trust.get("publishers") or {}).get(key_id)
    if not publisher:
        return [f"SIGNER_UNKNOWN:{key_id}"]
    if publisher.get("status") != "ACTIVE":
        return [f"SIGNER_NOT_ACTIVE:{key_id}:{publisher.get('status')}"]
    if role not in (publisher.get("roles") or []):
        return [f"SIGNER_LACKS_ROLE:{key_id}:{role}"]
    if signature.get("algorithm") != "Ed25519":
        return [f"SIGNATURE_ALGORITHM_UNSUPPORTED:{signature.get('algorithm')}"]
    if not _verify_sig(publisher["public_key_b64"], str(signature.get("value_b64") or ""), message):
        return ["SIGNATURE_INVALID"]
    return []


# --------------------------------------------------------------------------- bundle shape
def _rule_as_candidate(rule: dict[str, Any]) -> dict[str, Any]:
    """Map a released rule onto the candidate contract so the same field rules apply."""
    mapped = {k: v for k, v in rule.items() if k not in ("rule_id", "rule_version", "status", "validation_scope",
                                                          "impact_scope", "application")}
    mapped["candidate_id"] = rule.get("rule_id")
    mapped["revision"] = rule.get("rule_version")
    return mapped


def validate_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(bundle, dict):
        raise BundleError(["BUNDLE_NOT_OBJECT"])
    if bundle.get("schema") != c.BUNDLE_SCHEMA:
        failures.append(f"BUNDLE_SCHEMA_INVALID:{bundle.get('schema')}")
    if not c.is_identifier(bundle.get("bundle_id")):
        failures.append("BUNDLE_ID_INVALID")
    if not isinstance(bundle.get("version"), int) or bundle.get("version", 0) < 1:
        failures.append("BUNDLE_VERSION_MUST_BE_POSITIVE_INT")
    if bundle.get("release_channel") not in CHANNELS + ("BUILTIN",):
        failures.append(f"RELEASE_CHANNEL_INVALID:{bundle.get('release_channel')}")
    compat = bundle.get("compat") or {}
    for key in ("engine_api_versions", "models"):
        if not isinstance(compat.get(key), list) or not compat.get(key):
            failures.append(f"COMPAT_{key.upper()}_REQUIRED")
    for key in EXECUTABLE_KEYS:
        if key in bundle:
            failures.append(f"BUNDLE_CANNOT_CARRY_EXECUTABLE:{key}")
    rules = bundle.get("rules")
    if not isinstance(rules, list):
        failures.append("RULES_MUST_BE_LIST")
        rules = []
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            failures.append(f"RULE_NOT_OBJECT:{index}")
            continue
        rid = str(rule.get("rule_id") or "")
        if rid in seen:
            failures.append(f"RULE_ID_DUPLICATE:{rid}")
        seen.add(rid)
        for key in EXECUTABLE_KEYS:
            if key in rule:
                failures.append(f"RULE_CANNOT_CARRY_EXECUTABLE:{rid}:{key}")
        if rule.get("validation_scope") not in c.VALIDATION_SCOPES:
            failures.append(f"RULE_VALIDATION_SCOPE_INVALID:{rid}:{rule.get('validation_scope')}")
        application = rule.get("application") or {"carrier": "CHECK_ONLY"}
        if application.get("carrier") not in CARRIERS:
            failures.append(f"RULE_CARRIER_INVALID:{rid}")
        clause = application.get("prompt_clause") or {}
        if not isinstance(clause, dict) or not all(isinstance(v, str) for v in clause.values()):
            failures.append(f"RULE_PROMPT_CLAUSE_INVALID:{rid}")
        elif any(CONTROL_LANGUAGE.search(v) for v in clause.values()):
            # Clauses may only shape direction text; money, authority, gates and secrets are not data.
            failures.append(f"RULE_PROMPT_CLAUSE_CONTROL_LANGUAGE:{rid}")
        if rule.get("category") == "ENGINEERING_INVARIANT" and application.get("carrier") != "CHECK_ONLY":
            # Engineering invariants are enforced by code/contract checks, never re-stated as prompt bans.
            failures.append(f"ENGINEERING_INVARIANT_MUST_BE_CHECK_ONLY:{rid}")
        impact = rule.get("impact_scope")
        if impact is not None and (not isinstance(impact, dict) or not all(
                isinstance(impact.get(k, []), list) for k in ("free_checks", "modules", "stages"))):
            failures.append(f"RULE_IMPACT_SCOPE_INVALID:{rid}")
        try:
            c.validate_candidate(_rule_as_candidate(rule))
        except c.ContractError as exc:
            failures.extend(f"RULE_INVALID:{rid}:{code}" for code in exc.codes)
    if failures:
        raise BundleError(failures)
    return bundle


def bundle_digest(bundle: dict[str, Any]) -> str:
    return c.digest(bundle)


def sign_bundle(bundle: dict[str, Any], *, key_id: str, private_raw: bytes) -> dict[str, Any]:
    validate_bundle(bundle)
    digest = bundle_digest(bundle)
    return {"schema": SIGNED_SCHEMA, "bundle": bundle, "digest": digest,
            "signature": {"key_id": key_id, "algorithm": "Ed25519",
                          "value_b64": _sign(private_raw, SIGNING_DOMAIN + digest.encode("ascii"))}}


def verify_bundle(envelope: dict[str, Any], trust: dict[str, Any]) -> dict[str, Any]:
    """Return the verified bundle or raise.  Never returns partially-verified content."""
    if not isinstance(envelope, dict) or envelope.get("schema") != SIGNED_SCHEMA:
        raise BundleError(["SIGNED_ENVELOPE_INVALID"])
    bundle = envelope.get("bundle")
    validate_bundle(bundle)
    digest = bundle_digest(bundle)
    if digest != envelope.get("digest"):
        raise BundleError([f"DIGEST_MISMATCH:declared={envelope.get('digest')}:actual={digest}"])
    failures = _check_signer(trust, envelope.get("signature") or {}, KNOWLEDGE_PUBLISHER,
                             SIGNING_DOMAIN + digest.encode("ascii"))
    if failures:
        raise BundleError(failures)
    return bundle


# --------------------------------------------------------------------------- revocations
def sign_revocations(entries: list[dict[str, Any]], *, key_id: str, private_raw: bytes,
                     sequence: int) -> dict[str, Any]:
    body = {"schema": REVOCATION_SCHEMA, "sequence": sequence, "revoked": entries}
    digest = c.digest(body)
    return {"body": body, "digest": digest,
            "signature": {"key_id": key_id, "algorithm": "Ed25519",
                          "value_b64": _sign(private_raw, REVOCATION_SIGNING_DOMAIN + digest.encode("ascii"))}}


def verify_revocations(signed: dict[str, Any], trust: dict[str, Any]) -> set[str]:
    """Digests revoked by a trusted publisher.  A revocation can only REMOVE adoption."""
    body = signed.get("body") or {}
    digest = c.digest(body)
    if body.get("schema") != REVOCATION_SCHEMA or digest != signed.get("digest"):
        raise BundleError(["REVOCATION_LIST_INVALID"])
    failures = _check_signer(trust, signed.get("signature") or {}, KNOWLEDGE_PUBLISHER,
                             REVOCATION_SIGNING_DOMAIN + digest.encode("ascii"))
    if failures:
        raise BundleError(failures)
    return {str(row.get("digest")) for row in body.get("revoked") or [] if c.is_sha256(row.get("digest"))}


# --------------------------------------------------------------------------- cache
class BundleCache:
    """Content-addressed local cache: ``objects/<digest>.json`` + ``index.json``.

    A version is immutable: (bundle_id, version) maps to exactly one digest.  New
    content is verified, written to a temp file, re-read and re-verified, then
    atomically renamed into place -- a tampered or half-written download can never
    replace or shadow a valid cached object.
    """

    def __init__(self, root: Path, trust: dict[str, Any]):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.trust = trust

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def _index(self) -> dict[str, Any]:
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"entries": []}

    def _write_index(self, index: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".index.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.index_path)

    def object_path(self, digest: str) -> Path:
        if not c.is_sha256(digest):
            raise BundleError(["DIGEST_INVALID"])
        return self.objects / f"{digest}.json"

    def admit(self, raw: bytes, *, source: str = "cloud") -> dict[str, Any]:
        """Verify downloaded bytes and add them.  Raises (cache untouched) on any failure."""
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BundleError([f"BUNDLE_BYTES_NOT_JSON:{exc}"]) from exc
        bundle = verify_bundle(envelope, self.trust)
        digest = envelope["digest"]
        index = self._index()
        for entry in index["entries"]:
            if entry["bundle_id"] == bundle["bundle_id"] and entry["version"] == bundle["version"]:
                if entry["digest"] != digest:
                    raise BundleError([f"VERSION_IMMUTABLE_CONFLICT:{bundle['bundle_id']}@{bundle['version']}"])
                return entry
        target = self.object_path(digest)
        if not target.is_file():
            fd, tmp = tempfile.mkstemp(dir=self.objects, prefix=".incoming.", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                verify_bundle(json.loads(Path(tmp).read_bytes().decode("utf-8")), self.trust)
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        entry = {"bundle_id": bundle["bundle_id"], "version": bundle["version"], "digest": digest,
                 "release_channel": bundle["release_channel"], "admitted_at": c.now_iso(), "source": source}
        index["entries"].append(entry)
        self._write_index(index)
        return entry

    def load(self, digest: str) -> dict[str, Any]:
        """Re-read and re-verify one cached object (detects on-disk replacement)."""
        path = self.object_path(digest)
        if not path.is_file():
            raise BundleError([f"BUNDLE_NOT_CACHED:{digest}"])
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8"))
        bundle = verify_bundle(envelope, self.trust)
        if envelope["digest"] != digest:
            raise BundleError([f"CACHED_OBJECT_DIGEST_MISMATCH:{digest}"])
        return bundle

    def entries(self) -> list[dict[str, Any]]:
        return list(self._index()["entries"])


# --------------------------------------------------------------------------- baseline
def builtin_baseline(path: Path, pinned_digest: str) -> dict[str, Any]:
    """An approved baseline shipped with the engine release for first-install offline use.

    Trust root is the engine release itself (deployment integrity pins this file), so the
    bundle is digest-pinned rather than signed.  It is always labelled
    BUILTIN_BASELINE_NOT_CLOUD_SYNCED -- it never claims to have been synced.
    """
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_bundle(bundle)
    if bundle.get("release_channel") != "BUILTIN":
        raise BundleError(["BASELINE_CHANNEL_MUST_BE_BUILTIN"])
    digest = bundle_digest(bundle)
    if digest != pinned_digest:
        raise BundleError([f"BASELINE_DIGEST_MISMATCH:{digest}"])
    return {"bundle": bundle, "digest": digest, "label": BUILTIN_LABEL}


# --------------------------------------------------------------------------- resolve
def compat_matches(bundle: dict[str, Any], capabilities: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    compat = bundle.get("compat") or {}
    for key, cap in (("engine_api_versions", "engine_api_version"), ("models", "model")):
        value = capabilities.get(cap)
        if value in (None, "", c.UNKNOWN):
            reasons.append(f"CAPABILITY_UNKNOWN:{cap}")
        elif value not in (compat.get(key) or []):
            reasons.append(f"INCOMPATIBLE:{cap}={value}")
    return (not reasons), reasons


def resolve_local(capabilities: dict[str, Any], cache: BundleCache, *, channel: str = "RELEASED",
                  revoked: Iterable[str] = (), baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Newest verified, non-revoked, compatible version per bundle_id from the local cache.

    Only cached, verified content is considered -- the network is never on this path,
    so a slow or unreachable service cannot hold a run.  With nothing cached the
    approved baseline is used and labelled as such.
    """
    accepted = CHANNEL_ACCEPTS.get(channel)
    if accepted is None:
        raise BundleError([f"CHANNEL_INVALID:{channel}"])
    revoked = set(revoked)
    best: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for entry in cache.entries():
        if entry["digest"] in revoked:
            rejected.append({**entry, "reason": "REVOKED"})
            continue
        if entry["release_channel"] not in accepted:
            rejected.append({**entry, "reason": f"CHANNEL_NOT_ACCEPTED:{entry['release_channel']}"})
            continue
        try:
            bundle = cache.load(entry["digest"])
        except BundleError as exc:
            rejected.append({**entry, "reason": ";".join(exc.codes)})
            continue
        ok, reasons = compat_matches(bundle, capabilities)
        if not ok:
            rejected.append({**entry, "reason": ";".join(reasons)})
            continue
        current = best.get(entry["bundle_id"])
        if current is None or entry["version"] > current["version"]:
            best[entry["bundle_id"]] = {**entry, "bundle": bundle}
    selected = sorted(best.values(), key=lambda e: e["bundle_id"])
    if not selected and baseline is not None:
        ok, reasons = compat_matches(baseline["bundle"], capabilities)
        if ok:
            selected = [{"bundle_id": baseline["bundle"]["bundle_id"], "version": baseline["bundle"]["version"],
                         "digest": baseline["digest"], "release_channel": "BUILTIN", "bundle": baseline["bundle"],
                         "label": BUILTIN_LABEL}]
    return {"capabilities": {k: capabilities.get(k) for k in sorted(capabilities)},
            "channel": channel, "selected": selected, "rejected": rejected}


# --------------------------------------------------------------------------- run lock
def lock_path(lock_dir: Path, run_id: str) -> Path:
    if not c.is_identifier(run_id):
        raise BundleError(["RUN_ID_INVALID"])
    return Path(lock_dir) / f"{run_id}.knowledge_lock.json"


def lock_run(lock_dir: Path, run_id: str, *, resolved: dict[str, Any], engine_commit: str,
             provider_model_version: str = c.UNKNOWN, skill_bundle_digest: str = "NONE",
             rubric_version: str = c.UNKNOWN, evaluation_model_version: str = c.UNKNOWN,
             improvement_plan_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the run's knowledge lock once.  An existing lock is returned unchanged.

    ``resolved`` is :func:`resolve_local` output.  Only the first selected bundle is
    bound per bundle_id; the lock records exact digests and rule versions, never "latest".
    """
    path = lock_path(lock_dir, run_id)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        return {**existing, "lock_path": str(path), "lock_sha256": c.sha256_bytes(path.read_bytes()),
                "lock_status": "EXISTING_LOCK_KEPT"}
    bundles = [{"bundle_id": e["bundle_id"], "version": e["version"], "digest": e["digest"],
                "release_channel": e["release_channel"], **({"label": e["label"]} if e.get("label") else {}),
                "rules": [{"rule_id": r["rule_id"], "rule_version": r["rule_version"]}
                          for r in e["bundle"].get("rules") or []]}
               for e in resolved.get("selected") or []]
    lock = {
        "schema": c.RUN_LOCK_SCHEMA, "run_id": run_id, "locked_at": c.now_iso(),
        "engine_commit": engine_commit or c.UNKNOWN,
        "provider_model_version": provider_model_version or c.UNKNOWN,
        "knowledge_bundle_digest": bundles[0]["digest"] if len(bundles) == 1 else (
            c.digest([b["digest"] for b in bundles]) if bundles else "NONE"),
        "knowledge_bundles": bundles,
        "skill_bundle_digest": skill_bundle_digest or "NONE",
        "rubric_version": rubric_version or c.UNKNOWN,
        "evaluation_model_version": evaluation_model_version or c.UNKNOWN,
        "capabilities": resolved.get("capabilities") or {},
        "channel": resolved.get("channel"),
        "improvement_plan_ref": improvement_plan_ref,
        "resolution_policy": "LOCKED_SNAPSHOT_NEVER_RE_RESOLVED_WITHIN_RUN",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:  # a concurrent writer won; its lock is the run's lock
        return lock_run(lock_dir, run_id, resolved=resolved, engine_commit=engine_commit)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {**lock, "lock_path": str(path), "lock_sha256": c.sha256_bytes(data), "lock_status": "CREATED"}


def lock_ref(lock: dict[str, Any]) -> dict[str, Any]:
    """The small reference a task carries to its run lock."""
    return {"path": lock["lock_path"], "sha256": lock["lock_sha256"], "run_id": lock["run_id"],
            "knowledge_bundle_digest": lock["knowledge_bundle_digest"]}


def locked_rules(lock_path_value: Path, cache: BundleCache) -> list[dict[str, Any]]:
    """The exact locked rules, re-verified from the cache (never re-resolved)."""
    lock = json.loads(Path(lock_path_value).read_text(encoding="utf-8"))
    rules: list[dict[str, Any]] = []
    for entry in lock.get("knowledge_bundles") or []:
        if entry.get("label") == BUILTIN_LABEL:
            continue  # the baseline is digest-pinned by the engine release, not cached
        bundle = cache.load(entry["digest"])
        wanted = {(r["rule_id"], r["rule_version"]) for r in entry["rules"]}
        for rule in bundle.get("rules") or []:
            if (rule["rule_id"], rule["rule_version"]) in wanted:
                rules.append({**rule, "_bundle_digest": entry["digest"]})
    return rules


def verify_lock_for_send(ref: dict[str, Any], cache: BundleCache) -> dict[str, Any]:
    """Re-hash the lock file and every locked bundle immediately before a send or resume."""
    failures: list[str] = []
    path = Path(str(ref.get("path") or ""))
    if not path.is_file():
        return {"status": "FAIL", "failures": [f"KNOWLEDGE_LOCK_MISSING:{path}"]}
    actual = c.sha256_bytes(path.read_bytes())
    if actual != ref.get("sha256"):
        failures.append(f"KNOWLEDGE_LOCK_CHANGED_AFTER_BINDING:expected={ref.get('sha256')}:actual={actual}")
        return {"status": "FAIL", "failures": failures}
    lock = json.loads(path.read_text(encoding="utf-8"))
    for entry in lock.get("knowledge_bundles") or []:
        if entry.get("label") == BUILTIN_LABEL:
            continue
        try:
            cache.load(entry["digest"])
        except BundleError as exc:
            failures.extend(f"LOCKED_BUNDLE_INVALID:{entry['digest']}:{code}" for code in exc.codes)
    return {"status": "FAIL" if failures else "PASS", "failures": failures,
            "lock_sha256": actual, "knowledge_bundle_digest": lock.get("knowledge_bundle_digest")}


# --------------------------------------------------------------------------- skills
def validate_skill(manifest: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if manifest.get("schema") != SKILL_SCHEMA:
        failures.append("SKILL_SCHEMA_INVALID")
    for key in ("skill_id", "interface_version", "entrypoint"):
        if not c.is_identifier(manifest.get(key)) and key != "entrypoint":
            failures.append(f"SKILL_{key.upper()}_INVALID")
    if not isinstance(manifest.get("version"), int) or manifest.get("version", 0) < 1:
        failures.append("SKILL_VERSION_INVALID")
    entry = str(manifest.get("entrypoint") or "")
    if not entry or entry.startswith("/") or ".." in entry.split("/") or not entry.endswith(".py"):
        failures.append("SKILL_ENTRYPOINT_MUST_BE_RELATIVE_ENGINE_MODULE")
    if not c.is_sha256(manifest.get("code_sha256")):
        failures.append("SKILL_CODE_DIGEST_REQUIRED")
    perms = manifest.get("permissions")
    if not isinstance(perms, dict):
        failures.append("SKILL_PERMISSIONS_REQUIRED")
    else:
        for key in ("shell", "network", "paid", "dynamic_install"):
            if not isinstance(perms.get(key), bool):
                failures.append(f"SKILL_PERMISSION_MUST_BE_DECLARED:{key}")
    if not isinstance(manifest.get("dependencies"), list):
        failures.append("SKILL_DEPENDENCIES_MUST_BE_LIST")
    for cost in manifest.get("cost_capabilities") or []:
        if cost not in c.COST_CLASSES:
            failures.append(f"SKILL_COST_CLASS_INVALID:{cost}")
    if failures:
        raise BundleError(failures)
    return manifest


def sign_skill(manifest: dict[str, Any], *, key_id: str, private_raw: bytes) -> dict[str, Any]:
    validate_skill(manifest)
    digest = c.digest(manifest)
    return {"schema": SIGNED_SKILL_SCHEMA, "skill": manifest, "digest": digest,
            "signature": {"key_id": key_id, "algorithm": "Ed25519",
                          "value_b64": _sign(private_raw, SKILL_SIGNING_DOMAIN + digest.encode("ascii"))}}


def verify_skill(envelope: dict[str, Any], trust: dict[str, Any], *, code_bytes: bytes | None = None) -> dict[str, Any]:
    if envelope.get("schema") != SIGNED_SKILL_SCHEMA:
        raise BundleError(["SIGNED_SKILL_ENVELOPE_INVALID"])
    manifest = validate_skill(envelope.get("skill") or {})
    digest = c.digest(manifest)
    failures: list[str] = []
    if digest != envelope.get("digest"):
        failures.append("SKILL_DIGEST_MISMATCH")
    else:
        failures.extend(_check_signer(trust, envelope.get("signature") or {}, SKILL_PUBLISHER,
                                      SKILL_SIGNING_DOMAIN + digest.encode("ascii")))
    policy = trust.get("skill_policy") or {}
    perms = manifest["permissions"]
    if perms["shell"] and not policy.get("allow_shell"):
        failures.append("SKILL_REQUESTS_SHELL_NOT_ALLOWED")
    if perms["network"] and not policy.get("allow_network"):
        failures.append("SKILL_REQUESTS_NETWORK_NOT_ALLOWED")
    if perms["dynamic_install"] and not policy.get("allow_dynamic_install"):
        failures.append("SKILL_REQUESTS_DYNAMIC_INSTALL_NOT_ALLOWED")
    if perms["paid"]:
        # Money authority never comes from a skill package; it stays with the line's paid order.
        failures.append("SKILL_CANNOT_HOLD_PAID_AUTHORITY")
    if code_bytes is not None and c.sha256_bytes(code_bytes) != manifest["code_sha256"]:
        failures.append("SKILL_CODE_DIGEST_MISMATCH")
    if failures:
        raise BundleError(failures)
    return manifest
