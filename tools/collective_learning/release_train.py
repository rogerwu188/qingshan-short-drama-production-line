"""Review, canary and promotion of the collective knowledge base -- the collector's daily release train.

Runs ONLY on the collector (the fleet server, single publisher; approved design 2026-11-12).  Devices never
publish.  Everything here works on the service database (events, receipts, candidates, bundles, channels) plus
the publisher key; the bucket pointers follow on the next ``s3_sync.py run-cycle`` (``sync_channels`` signs
whatever the service's channel table says, through the release gate).

Flow (all thresholds in ``DEFAULTS``, overridable with ``--config``):

1. clusters     lesson-type FAILURE events grouped by ``evidence.failure_type`` (round/rate facts and provider
                outages are never lessons).  A cluster is eligible when seen on >= ``min_devices`` independent
                devices (``Service._independent_sources``: copies and replays collapse) OR >= ``min_episodes``
                distinct (device, episode) pairs.
2. review hook  ``export-review`` writes the eligible, unhandled clusters to a review-request JSON; the reviewer
                (patrol / Claude, via an admin command) answers with a review-result JSON: per cluster APPROVE
                (with the full rule: trigger, recommendation, scope, ...) or REJECT (with a reason).
                ``import-review`` turns approvals into candidates (CANDIDATE -> VALIDATED) and records rejections.
3. daily pack   at most one pack per UTC day, at most ``batch_max`` new rules, total active rules capped at
                ``max_active_rules``: released rules (minus retired) + the oldest validated backlog -> CANARY,
                signed as ``<bundle_id>@<n>`` labelled CANARY, released to the CANARY channel.
4. evaluation   once the pack has been on CANARY >= ``canary_hours``: canary vs non-canary devices over the same
                window -- Q1 admission rate, Q2 pass rate, redo rounds per episode, content rejections per episode
                (from the production events), plus per rule the recurrence of its target failure type on the
                devices that APPLIED it (adoption receipts).  Not worse -> promote: the same rule set is re-signed
                as ``n+1`` labelled RELEASED (a device cache filters by the signed label, so a CANARY-labelled pack
                can never reach RELEASED devices) and released to both channels.  Clearly worse -> roll back:
                the pack version is revoked (the CANARY pointer falls back, the signed revocation list drops it
                from every cache) and its new rules are DEPRECATED with the reason.
5. retirement   a released rule APPLIED >= ``retire_min_applied`` times whose target failure rate on the applying
                devices did not drop (after vs before first application) is DEPRECATED and left out of the next pack.

Status: ``status.json`` (and ``--status-out``) -- the dashboard line
"新增候选 N · 灰度中 M · 昨日批次 已全量/已回滚 · 退役 K".
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):  # allow `python tools/collective_learning/release_train.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.collective_learning"  # noqa: A001

from . import bundles as b  # noqa: E402
from . import contracts as c  # noqa: E402
from . import service as svc_mod  # noqa: E402

STATE_SCHEMA = "collective.release_train_state.v1"
STATUS_SCHEMA = "collective.release_train_status.v1"
REQUEST_SCHEMA = "collective.release_train.review_request.v1"
RESULT_SCHEMA = "collective.release_train.review_result.v1"
DEFAULTS: dict[str, Any] = {
    "bundle_id": "nalu-kb",
    "line_id": "nalu",
    "engine_api_versions": ["nalu-engine-api-1"],
    "models": ["MiniMax-H3"],
    "min_devices": 3,
    "min_episodes": 5,
    "lookback_days": 30,
    "batch_max": 5,
    "max_active_rules": 40,
    "canary_hours": 24,
    "max_canary_hours": 72,
    "min_canary_episodes": 3,
    "min_control_episodes": 3,
    "promote_on_insufficient_data": True,
    "min_rate_units": 10,
    "rate_margin": 0.10,
    "per_episode_ratio_margin": 0.5,
    "per_episode_abs_margin": 0.5,
    "retire_min_applied": 20,
    "retire_min_episodes": 3,
    "retire_min_drop": 0.0,
}
ROUND_TYPES = ("Q1_ROUND", "Q2_ROUND", "POSTGEN_ROUND")
NOT_LESSON_PREFIXES = ("PROVIDER_OUTAGE",)
DEFAULT_SCOPE = {"DIRECTING_HEURISTIC": "REAL_MEDIA_REVIEW", "MODEL_CONSTRAINT": "REAL_MEDIA_REVIEW",
                 "ENGINEERING_INVARIANT": "DETERMINISTIC_REGRESSION", "EXECUTION_POLICY": "DETERMINISTIC_REGRESSION"}
RULE_FIELDS = ("category", "scope", "trigger", "recommendation", "exceptions", "known_counterexamples",
               "verification", "cost_class", "evidence_level")


class TrainError(Exception):
    def __init__(self, code: str, detail: Any = None):
        super().__init__(code)
        self.code, self.detail = code, detail


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(stamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() if stamp else None
    except ValueError:
        return None


def _ident(text: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._:\-]", "-", str(text or "")).strip("-")[:100]
    return out if c.is_identifier(out) else "reviewer"


def failure_type(event: dict[str, Any]) -> str:
    evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
    return str(evidence.get("failure_type") or f"{event.get('stage')}:{event.get('detected_by')}")


def is_lesson(event: dict[str, Any]) -> bool:
    if event.get("event_kind") != "FAILURE_OBSERVATION":
        return False
    ft = failure_type(event)
    return ft not in ROUND_TYPES and not ft.startswith(NOT_LESSON_PREFIXES)


def cluster_id(ftype: str) -> str:
    return "cl-" + hashlib.sha256(ftype.encode("utf-8")).hexdigest()[:12]


class Train:
    """One tenant's release train over a service database and the publisher key."""

    def __init__(self, service: svc_mod.Service, tenant: str, state_dir: Path, *,
                 publisher_key: Callable[[], tuple[str, bytes]] | None = None, config: dict[str, Any] | None = None,
                 cohort: dict[str, str] | None = None, now: Callable[[], float] | None = None):
        self.service, self.tenant = service, tenant
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.publisher_key = publisher_key
        self.cfg = {**DEFAULTS, **(config or {})}
        self.cohort = dict(cohort or {})
        self.now = now or time.time
        self.pub = svc_mod.Principal("release-train", tenant, "publisher")
        self.admin = svc_mod.Principal(f"admin-{tenant}", tenant, "admin")

    # ------------------------------------------------------------------ state
    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema") == STATE_SCHEMA:
                return data
        except (OSError, ValueError):
            pass
        return {"schema": STATE_SCHEMA, "clusters": {}, "packs": [], "released_rules": [], "backlog": [],
                "retired": [], "open_review": None, "history": []}

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _iso(self.now())
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def _log(self, state: dict[str, Any], action: str, **detail: Any) -> None:
        state.setdefault("history", []).append({"at": _iso(self.now()), "action": action, **detail})
        state["history"] = state["history"][-500:]

    # ------------------------------------------------------------------ data
    def events(self, since: float | None = None, until: float | None = None) -> list[dict[str, Any]]:
        rows = self.service._read("SELECT payload FROM events WHERE tenant_id=?", (self.tenant,))
        out = []
        for (payload,) in rows:
            try:
                event = json.loads(payload)
            except ValueError:
                continue
            at = _epoch(event.get("occurred_at"))
            if at is None or (since is not None and at < since) or (until is not None and at > until):
                continue
            event["_at"] = at
            out.append(event)
        return out

    def receipts(self, kind: str = "ADOPTION") -> list[dict[str, Any]]:
        rows = self.service._read("SELECT payload FROM receipts WHERE tenant_id=? AND kind=?", (self.tenant, kind))
        out = []
        for (payload,) in rows:
            try:
                row = json.loads(payload)
            except ValueError:
                continue
            row["_at"] = _epoch(row.get("recorded_at"))
            out.append(row)
        return out

    def candidate(self, rule_id: str) -> dict[str, Any] | None:
        try:
            return self.service.get_candidate(self.pub, rule_id)
        except svc_mod.NotFound:
            return None

    def _transition(self, rule_id: str, to: str, note: str, principal: svc_mod.Principal | None = None,
                    validation_scope: str | None = None) -> dict[str, Any]:
        rec = self.service.get_candidate(self.pub, rule_id)
        return self.service.transition_candidate(principal or self.pub, rule_id, to=to, if_match=rec["etag"],
                                                 validation_scope=validation_scope, note=note[:300])

    # ------------------------------------------------------------------ 1. clusters
    def clusters(self) -> list[dict[str, Any]]:
        since = self.now() - float(self.cfg["lookback_days"]) * 86400
        groups: dict[str, list[dict[str, Any]]] = {}
        for event in self.events(since=since):
            if is_lesson(event):
                groups.setdefault(failure_type(event), []).append(event)
        out = []
        db = self.service._db()
        for ftype, events in sorted(groups.items()):
            events.sort(key=lambda e: e["_at"])
            ids = [e["event_id"] for e in events]
            sources = self.service._independent_sources(db, self.tenant, ids)
            episodes = {(e.get("device_id"), e.get("episode_id")) for e in events}
            symptoms: list[str] = []
            for e in reversed(events):
                if e.get("symptom") not in symptoms:
                    symptoms.append(str(e.get("symptom")))
            out.append({
                "cluster_id": cluster_id(ftype), "failure_type": ftype,
                "stages": sorted({str(e.get("stage")) for e in events}),
                "devices": sources["independent_sources"], "episodes": len(episodes), "event_count": len(events),
                "first_seen": _iso(events[0]["_at"]), "last_seen": _iso(events[-1]["_at"]),
                "sample_symptoms": symptoms[:5],
                "sample_evidence": [{k: v for k, v in (e.get("evidence") or {}).items() if k != "failure_type"}
                                    for e in events[-3:]],
                "models": sorted({str(e.get("provider_model_version")) for e in events})[:5],
                "event_ids": ids[-50:],
                "eligible": (sources["independent_sources"] >= int(self.cfg["min_devices"])
                             or len(episodes) >= int(self.cfg["min_episodes"])),
            })
        return out

    # ------------------------------------------------------------------ 2. review hook
    def export_review(self, *, replace: bool = False) -> dict[str, Any]:
        state = self.state()
        if state.get("open_review") and not replace:
            path = self.dir / "review_requests" / f"{state['open_review']}.json"
            if path.is_file():
                return {"status": "OPEN_REVIEW_PENDING", "request_id": state["open_review"], "path": str(path)}
        handled = {cid for cid, row in state["clusters"].items() if row.get("status") in
                   ("VALIDATED", "REJECTED", "CANARY", "RELEASED", "BLOCKED_POLICY", "DEPRECATED")}
        targeted = set()
        for row in state["clusters"].values():
            if row.get("status") in ("VALIDATED", "CANARY", "RELEASED"):
                targeted.add(row.get("failure_type"))
        clusters = [cl for cl in self.clusters() if cl["eligible"] and cl["cluster_id"] not in handled
                    and cl["failure_type"] not in targeted]
        if not clusters:
            state["open_review"] = None
            self.save(state)
            return {"status": "NOTHING_TO_REVIEW", "clusters": 0}
        clusters.sort(key=lambda cl: (-cl["devices"], -cl["episodes"], cl["failure_type"]))
        now = self.now()
        request_id = f"rv-{_iso(now).replace(':', '').replace('-', '')}-{hashlib.sha256(json.dumps([cl['cluster_id'] for cl in clusters]).encode()).hexdigest()[:6]}"
        slots = max(0, int(self.cfg["max_active_rules"]) - self._active_count(state))
        request = {
            "schema": REQUEST_SCHEMA, "request_id": request_id, "tenant": self.tenant, "created_at": _iso(now),
            "batch_max": int(self.cfg["batch_max"]), "active_rules": self._active_count(state),
            "rule_cap": int(self.cfg["max_active_rules"]), "free_rule_slots": slots,
            "thresholds": {k: self.cfg[k] for k in ("min_devices", "min_episodes", "lookback_days")},
            "instructions": (
                "For each cluster decide APPROVE or REJECT with a reason.  APPROVE only a problem a prompt-level "
                "rule can prevent; give the rule: category (DIRECTING_HEURISTIC|MODEL_CONSTRAINT|"
                "ENGINEERING_INVARIANT|EXECUTION_POLICY), scope {models, stages, ...}, trigger, recommendation, "
                "exceptions (required for DIRECTING_HEURISTIC), verification, cost_class, evidence_level, "
                "validation_scope, application {carrier: BEAT_DIRECTION|NEGATIVE_CONSTRAINT|CHECK_ONLY, "
                "prompt_clause: {zh, en}}.  At most batch_max approvals ship per day; extra approvals wait in the "
                "backlog.  Never put money, gates, authority or secrets into a clause."),
            "clusters": clusters,
        }
        out_dir = self.dir / "review_requests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{request_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        state["open_review"] = request_id
        self._log(state, "export_review", request_id=request_id, clusters=len(clusters))
        self.save(state)
        return {"status": "EXPORTED", "request_id": request_id, "path": str(path), "clusters": len(clusters)}

    def import_review(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict) or result.get("schema") != RESULT_SCHEMA:
            raise TrainError("REVIEW_RESULT_SCHEMA_INVALID")
        state = self.state()
        request_id = str(result.get("request_id") or "")
        req_path = self.dir / "review_requests" / f"{request_id}.json"
        if not request_id or request_id != state.get("open_review") or not req_path.is_file():
            raise TrainError("REVIEW_REQUEST_NOT_OPEN", {"open": state.get("open_review"), "got": request_id})
        request = json.loads(req_path.read_text(encoding="utf-8"))
        by_id = {cl["cluster_id"]: cl for cl in request.get("clusters") or []}
        reviewer = _ident(result.get("reviewer") or "patrol")
        rev = svc_mod.Principal(reviewer, self.tenant, "reviewer")
        outcomes: list[dict[str, Any]] = []
        for decision in result.get("decisions") or []:
            cid = str((decision or {}).get("cluster_id") or "")
            cl = by_id.get(cid)
            verdict = str((decision or {}).get("decision") or "").upper()
            reason = str((decision or {}).get("reason") or "").strip()
            if cl is None:
                outcomes.append({"cluster_id": cid, "status": "UNKNOWN_CLUSTER"})
                continue
            if not reason:
                outcomes.append({"cluster_id": cid, "status": "REASON_REQUIRED"})
                continue
            base = {"failure_type": cl["failure_type"], "reviewer": reviewer, "reason": reason[:500],
                    "request_id": request_id, "decided_at": _iso(self.now()), "devices": cl["devices"],
                    "episodes": cl["episodes"]}
            if verdict == "REJECT":
                state["clusters"][cid] = {**base, "status": "REJECTED"}
                outcomes.append({"cluster_id": cid, "status": "REJECTED"})
                continue
            if verdict != "APPROVE":
                outcomes.append({"cluster_id": cid, "status": "DECISION_INVALID"})
                continue
            try:
                rule_id = self._create_candidate(rev, cl, decision.get("rule") or {}, reason, request_id)
            except (c.ContractError, svc_mod.ServiceError, TrainError, KeyError, TypeError, ValueError) as exc:
                codes = getattr(exc, "codes", None) or [getattr(exc, "code", type(exc).__name__)]
                outcomes.append({"cluster_id": cid, "status": "RULE_INVALID", "codes": [str(x) for x in codes][:8],
                                 "details": getattr(exc, "details", None)})
                continue
            state["clusters"][cid] = {**base, "status": "VALIDATED", "rule_id": rule_id}
            state.setdefault("backlog", []).append(rule_id)
            outcomes.append({"cluster_id": cid, "status": "VALIDATED", "rule_id": rule_id})
        state["open_review"] = None
        results_dir = self.dir / "review_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / f"{request_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                                         encoding="utf-8")
        self._log(state, "import_review", request_id=request_id,
                  outcomes={k: sum(1 for o in outcomes if o["status"] == k) for k in {o["status"] for o in outcomes}})
        self.save(state)
        return {"status": "IMPORTED", "request_id": request_id, "outcomes": outcomes,
                "backlog": len(state["backlog"])}

    def _create_candidate(self, rev: svc_mod.Principal, cl: dict[str, Any], rule: dict[str, Any], reason: str,
                          request_id: str) -> str:
        if not isinstance(rule, dict):
            raise TrainError("RULE_REQUIRED")
        rule_id = str(rule.get("rule_id") or f"kb-{cl['cluster_id'][3:]}")
        if self.candidate(rule_id) is not None:
            raise TrainError("RULE_ID_EXISTS", rule_id)
        application = rule.get("application") or {"carrier": "CHECK_ONLY"}
        candidate = {k: rule[k] for k in RULE_FIELDS if k in rule}
        candidate.setdefault("known_counterexamples", [])
        candidate.update({"candidate_id": rule_id, "revision": 1, "status": "CANDIDATE",
                          "event_ids": list(cl.get("event_ids") or [])[-50:],
                          "target_failure_types": [cl["failure_type"]], "cluster_id": cl["cluster_id"],
                          "application": application,
                          "review": {"reviewer": rev.principal_id, "reason": reason[:500], "request_id": request_id}})
        # the rule must also be valid inside a signed pack (carrier, clause language, executable keys)
        b.validate_bundle({"schema": c.BUNDLE_SCHEMA, "bundle_id": self.cfg["bundle_id"], "version": 1,
                           "release_channel": "CANARY", "created_at": c.now_iso(),
                           "compat": {"engine_api_versions": list(self.cfg["engine_api_versions"]),
                                      "models": list(self.cfg["models"])},
                           "rules": [self._pack_rule(candidate, rule.get("validation_scope")
                                                     or DEFAULT_SCOPE.get(candidate.get("category"),
                                                                          "REAL_MEDIA_REVIEW"))]})
        rec = self.service.put_candidate(rev, candidate, origin_line_id=str(self.cfg["line_id"]))
        scope = rule.get("validation_scope") or DEFAULT_SCOPE.get(candidate.get("category"), "REAL_MEDIA_REVIEW")
        self.service.transition_candidate(rev, rule_id, to="VALIDATED", if_match=rec["etag"], validation_scope=scope,
                                          note=f"release_train review {request_id}: {reason[:200]}")
        return rule_id

    @staticmethod
    def _pack_rule(payload: dict[str, Any], validation_scope: str, revision: int = 1) -> dict[str, Any]:
        rule = {k: payload[k] for k in RULE_FIELDS if k in payload}
        rule.update({"rule_id": payload["candidate_id"], "rule_version": int(payload.get("revision") or revision),
                     "validation_scope": validation_scope,
                     "application": payload.get("application") or {"carrier": "CHECK_ONLY"},
                     "target_failure_types": list(payload.get("target_failure_types") or [])})
        return rule

    # ------------------------------------------------------------------ 3. packs
    def _active_count(self, state: dict[str, Any]) -> int:
        return len([r for r in state.get("released_rules") or [] if r not in (state.get("retire_pending") or [])])

    def _canary_pack(self, state: dict[str, Any]) -> dict[str, Any] | None:
        return next((p for p in reversed(state["packs"]) if p.get("status") == "CANARY"), None)

    def _next_version(self, state: dict[str, Any]) -> int:
        rows = self.service._read("SELECT version FROM bundles WHERE tenant_id=? AND bundle_id=?",
                                  (self.tenant, self.cfg["bundle_id"]))
        known = [int(v) for (v,) in rows if str(v).isdigit()] + [int(p["version"]) for p in state["packs"]]
        return max(known, default=0) + 1

    def _ship(self, version: int, label: str, rule_ids: list[str], channels: list[str], note: str) -> dict[str, Any]:
        """Sign ``rule_ids`` (current candidate payloads) as ``bundle_id@version`` labelled ``label``,
        upload to the service and point ``channels`` at it."""
        if self.publisher_key is None:
            raise TrainError("PUBLISHER_KEY_UNAVAILABLE")
        rules, stages, models = [], set(), set(self.cfg["models"])
        for rule_id in rule_ids:
            rec = self.service.get_candidate(self.pub, rule_id)
            scopes = rec["validation_scopes"] or ["STRUCTURE_VALID"]
            rules.append(self._pack_rule(rec["payload"], scopes[-1], rec["revision"]))
            stages.update(rec["payload"]["scope"].get("stages") or [])
            models.update(rec["payload"]["scope"].get("models") or [])
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": self.cfg["bundle_id"], "version": int(version),
                  "created_at": _iso(self.now()), "release_channel": label,
                  "compat": {"engine_api_versions": list(self.cfg["engine_api_versions"]), "models": sorted(models)},
                  "rules": rules}
        key_id, private = self.publisher_key()
        envelope = b.sign_bundle(bundle, key_id=key_id, private_raw=private)
        raw = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self.service.upload_bundle(self.pub, {
            "bundle_id": self.cfg["bundle_id"], "version": str(version), "digest": c.sha256_bytes(raw),
            "payload_b64": base64.b64encode(raw).decode("ascii"), "signature_b64": envelope["signature"]["value_b64"],
            "key_id": key_id,
            "manifest": {"scope": {"models": sorted(models), "stages": sorted(stages) or ["VIDEO_COMPILE"]},
                         "rules": [{"rule_id": r["rule_id"], "rule_version": r["rule_version"]} for r in rules],
                         "release_train": note[:200]}})
        for channel in channels:
            self.service.release(self.pub, bundle_id=self.cfg["bundle_id"], version=str(version), channel=channel,
                                 note=note[:200])
        return {"version": int(version), "label": label, "rules": [r["rule_id"] for r in rules],
                "digest": envelope["digest"], "channels": channels}

    def build_pack(self) -> dict[str, Any]:
        state = self.state()
        now = self.now()
        if self._canary_pack(state):
            return {"status": "CANARY_IN_FLIGHT", "version": self._canary_pack(state)["version"]}
        today = _iso(now)[:10]
        if any(str(p.get("created_at") or "")[:10] == today and p.get("label") == "CANARY" for p in state["packs"]):
            return {"status": "DAILY_PACK_ALREADY_BUILT"}
        kept = [r for r in state["released_rules"] if r not in (state.get("retire_pending") or [])
                and (self.candidate(r) or {}).get("state") == "RELEASED"]
        slots = max(0, int(self.cfg["max_active_rules"]) - len(kept))
        new, blocked = [], []
        for rule_id in list(state.get("backlog") or []):
            if len(new) >= min(int(self.cfg["batch_max"]), slots):
                break
            rec = self.candidate(rule_id)
            if rec is None or rec["state"] != "VALIDATED":
                state["backlog"].remove(rule_id)
                continue
            try:
                self._transition(rule_id, "CANARY", "release_train daily pack")
                new.append(rule_id)
            except svc_mod.ServiceError as exc:
                blocked.append({"rule_id": rule_id, "code": exc.code, "details": exc.details})
                state["backlog"].remove(rule_id)
                self._mark_cluster(state, rule_id, "BLOCKED_POLICY", reason=json.dumps(exc.details)[:300])
        retired_now = [r for r in state["released_rules"] if r not in kept]
        if not new and not retired_now:
            self._log(state, "build_pack", outcome="NOTHING_TO_SHIP", blocked=blocked)
            self.save(state)
            return {"status": "NOTHING_TO_SHIP", "blocked": blocked}
        version = self._next_version(state)
        shipped = self._ship(version, "CANARY", kept + new, ["CANARY"], f"daily pack: +{len(new)} -{len(retired_now)}")
        for rule_id in new:
            state["backlog"].remove(rule_id)
            self._mark_cluster(state, rule_id, "CANARY")
        pack = {**shipped, "created_at": _iso(now), "canary_at": _iso(now), "status": "CANARY", "new_rules": new,
                "kept_rules": kept, "dropped_rules": retired_now}
        state["packs"].append(pack)
        self._log(state, "build_pack", version=version, new=new, dropped=retired_now, blocked=blocked)
        self.save(state)
        return {"status": "PUBLISHED_TO_CANARY", "version": version, "new_rules": new, "dropped_rules": retired_now,
                "blocked": blocked}

    def _mark_cluster(self, state: dict[str, Any], rule_id: str, status: str, **extra: Any) -> None:
        for row in state["clusters"].values():
            if row.get("rule_id") == rule_id:
                row["status"] = status
                row.update(extra)

    # ------------------------------------------------------------------ 4. evaluation
    def _cohort_of(self, device_id: str) -> str:
        return "canary" if self.cohort.get(str(device_id)) == "CANARY" else "control"

    def metrics(self, since: float, until: float) -> dict[str, Any]:
        out = {k: {"episodes": set(), "q1_units": 0, "q1_failed": 0, "q2_units": 0, "q2_failed": 0,
                   "redo_rounds": 0, "content_rejections": 0, "devices": set()} for k in ("canary", "control")}
        for event in self.events(since=since, until=until):
            m = out[self._cohort_of(event.get("device_id"))]
            m["episodes"].add((event.get("device_id"), event.get("episode_id")))
            m["devices"].add(event.get("device_id"))
            ft = failure_type(event)
            opp = event.get("opportunity") if isinstance(event.get("opportunity"), dict) else {}
            failed = event.get("event_kind") == "FAILURE_OBSERVATION"
            if ft in ("Q1_ROUND", "Q2_ROUND"):
                key = ft[:2].lower()
                m[f"{key}_units"] += int(opp.get("applicable_units") or 0)
                m[f"{key}_failed"] += int(opp.get("observed_units") or 0) if failed else 0
            if ft in ROUND_TYPES and failed:
                m["redo_rounds"] += 1
            if ft.startswith("PROVIDER_CONTENT_REJECTION"):
                m["content_rejections"] += 1
        result = {}
        for name, m in out.items():
            eps = len(m["episodes"])
            result[name] = {
                "devices": len(m["devices"]), "episodes": eps,
                "q1_admission_rate": round(1 - m["q1_failed"] / m["q1_units"], 4) if m["q1_units"] else None,
                "q1_units": m["q1_units"],
                "q2_pass_rate": round(1 - m["q2_failed"] / m["q2_units"], 4) if m["q2_units"] else None,
                "q2_units": m["q2_units"],
                "redo_rounds_per_episode": round(m["redo_rounds"] / eps, 3) if eps else None,
                "content_rejections_per_episode": round(m["content_rejections"] / eps, 3) if eps else None,
            }
        return result

    def rule_recurrence(self, rule_ids: list[str], since: float | None = None,
                        until: float | None = None) -> dict[str, Any]:
        """Per rule: target-failure events per episode on the devices that APPLIED it, before vs after each
        device's first APPLIED receipt (and APPLIED count)."""
        receipts = [r for r in self.receipts() if r.get("state") == "APPLIED" and r.get("_at")]
        events = self.events(until=until)
        out: dict[str, Any] = {}
        for rule_id in rule_ids:
            rec = self.candidate(rule_id)
            targets = set((rec or {}).get("payload", {}).get("target_failure_types") or [])
            applied = [r for r in receipts if r.get("rule_id") == rule_id
                       and (since is None or r["_at"] >= since) and (until is None or r["_at"] <= until)]
            first: dict[str, float] = {}
            for r in applied:
                dev = str(r.get("device_id"))
                first[dev] = min(first.get(dev, r["_at"]), r["_at"])
            before_eps, after_eps, before_hits, after_hits = set(), set(), 0, 0
            for e in events:
                dev = str(e.get("device_id"))
                if dev not in first:
                    continue
                after = e["_at"] >= first[dev]
                (after_eps if after else before_eps).add((dev, e.get("episode_id")))
                if failure_type(e) in targets and e.get("event_kind") == "FAILURE_OBSERVATION":
                    if after:
                        after_hits += 1
                    else:
                        before_hits += 1
            out[rule_id] = {"target_failure_types": sorted(targets), "applied": len(applied),
                            "applied_devices": len(first),
                            "before": {"episodes": len(before_eps), "target_events": before_hits,
                                       "per_episode": round(before_hits / len(before_eps), 3) if before_eps else None},
                            "after": {"episodes": len(after_eps), "target_events": after_hits,
                                      "per_episode": round(after_hits / len(after_eps), 3) if after_eps else None}}
        return out

    def _worse(self, canary: dict[str, Any], control: dict[str, Any]) -> list[str]:
        reasons = []
        for key, units in (("q1_admission_rate", "q1_units"), ("q2_pass_rate", "q2_units")):
            a, b_ = canary.get(key), control.get(key)
            if a is None or b_ is None or min(canary[units], control[units]) < int(self.cfg["min_rate_units"]):
                continue
            if b_ - a > float(self.cfg["rate_margin"]):
                reasons.append(f"{key}:canary={a}:control={b_}")
        for key in ("redo_rounds_per_episode", "content_rejections_per_episode"):
            a, b_ = canary.get(key), control.get(key)
            if a is None or b_ is None:
                continue
            if a - b_ >= float(self.cfg["per_episode_abs_margin"]) and a > b_ * (1 + float(self.cfg["per_episode_ratio_margin"])):
                reasons.append(f"{key}:canary={a}:control={b_}")
        return reasons

    def evaluate(self) -> dict[str, Any]:
        state = self.state()
        pack = self._canary_pack(state)
        if pack is None:
            return {"status": "NO_CANARY"}
        now = self.now()
        since = _epoch(pack["canary_at"]) or now
        hours = (now - since) / 3600
        if hours < float(self.cfg["canary_hours"]):
            return {"status": "WAITING", "version": pack["version"], "hours_on_canary": round(hours, 1)}
        metrics = self.metrics(since, now)
        recurrence = self.rule_recurrence(pack.get("new_rules") or [], since=since, until=now)
        enough = (metrics["canary"]["episodes"] >= int(self.cfg["min_canary_episodes"])
                  and metrics["control"]["episodes"] >= int(self.cfg["min_control_episodes"]))
        decision: dict[str, Any] = {"at": _iso(now), "hours_on_canary": round(hours, 1), "metrics": metrics,
                                    "rule_recurrence": recurrence}
        if not enough:
            if hours < float(self.cfg["max_canary_hours"]) or not self.cfg["promote_on_insufficient_data"]:
                pack["last_check"] = {**decision, "outcome": "WAITING_FOR_DATA"}
                self.save(state)
                return {"status": "WAITING_FOR_DATA", "version": pack["version"], "metrics": metrics}
            decision["note"] = "INSUFFICIENT_DATA_AFTER_MAX_CANARY_HOURS: promoted, no evidence of harm"
            worse: list[str] = []
        else:
            worse = self._worse(metrics["canary"], metrics["control"])
        if worse:
            return self._rollback(state, pack, decision, worse)
        return self._promote(state, pack, decision)

    def _promote(self, state: dict[str, Any], pack: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        promoted, blocked = [], []
        for rule_id in pack.get("new_rules") or []:
            try:
                self._transition(rule_id, "RELEASED", f"canary pack {pack['version']} not worse")
                promoted.append(rule_id)
                self._mark_cluster(state, rule_id, "RELEASED")
            except svc_mod.ServiceError as exc:
                blocked.append({"rule_id": rule_id, "code": exc.code, "details": exc.details})
                try:
                    self._transition(rule_id, "DEPRECATED", f"release policy refused RELEASED: {exc.details}")
                except svc_mod.ServiceError:
                    pass
                self._mark_cluster(state, rule_id, "BLOCKED_POLICY", reason=json.dumps(exc.details)[:300])
        rules = [r for r in pack.get("kept_rules") or [] if (self.candidate(r) or {}).get("state") == "RELEASED"]
        rules += promoted
        version = self._next_version(state)
        shipped = self._ship(version, "RELEASED", rules, ["RELEASED", "CANARY"],
                             f"promoted canary pack {pack['version']}")
        pack.update({"status": "PROMOTED", "decided_at": decision["at"], "decision": {**decision, "outcome": "PROMOTED",
                     "promoted_rules": promoted, "blocked": blocked}, "promoted_as": version})
        state["packs"].append({**shipped, "created_at": decision["at"], "status": "RELEASED",
                               "promoted_from": pack["version"]})
        state["released_rules"] = rules
        state["retire_pending"] = [r for r in state.get("retire_pending") or [] if r in rules]
        self._log(state, "promote", from_version=pack["version"], to_version=version, promoted=promoted, blocked=blocked)
        self.save(state)
        return {"status": "PROMOTED", "canary_version": pack["version"], "released_version": version,
                "promoted_rules": promoted, "blocked": blocked, "metrics": decision["metrics"]}

    def _rollback(self, state: dict[str, Any], pack: dict[str, Any], decision: dict[str, Any],
                  worse: list[str]) -> dict[str, Any]:
        reason = "canary clearly worse: " + "; ".join(worse)
        self.service.revoke_bundle(self.pub, bundle_id=self.cfg["bundle_id"], version=str(pack["version"]),
                                   reason=reason[:300])
        for rule_id in pack.get("new_rules") or []:
            try:
                self._transition(rule_id, "DEPRECATED", f"ROLLED_BACK: {reason}")
            except svc_mod.ServiceError:
                pass
            self._mark_cluster(state, rule_id, "DEPRECATED", reason=f"ROLLED_BACK: {reason}"[:300])
        pack.update({"status": "ROLLED_BACK", "decided_at": decision["at"],
                     "decision": {**decision, "outcome": "ROLLED_BACK", "reasons": worse}})
        self._log(state, "rollback", version=pack["version"], reasons=worse)
        self.save(state)
        return {"status": "ROLLED_BACK", "version": pack["version"], "reasons": worse, "metrics": decision["metrics"]}

    # ------------------------------------------------------------------ 5. retirement
    def retire(self) -> dict[str, Any]:
        state = self.state()
        released = [r for r in state.get("released_rules") or [] if r not in (state.get("retire_pending") or [])]
        recurrence = self.rule_recurrence(released)
        retired: list[dict[str, Any]] = []
        for rule_id, row in recurrence.items():
            before, after = row["before"], row["after"]
            if (row["applied"] < int(self.cfg["retire_min_applied"])
                    or after["episodes"] < int(self.cfg["retire_min_episodes"]) or not before["episodes"]):
                continue
            if after["per_episode"] >= before["per_episode"] * (1 - float(self.cfg["retire_min_drop"])):
                retired.append({"rule_id": rule_id, "reason": "TARGET_FAILURE_DID_NOT_DROP", **row})
        live = [r for r in released if r not in {x["rule_id"] for x in retired}]
        over = len(live) - int(self.cfg["max_active_rules"])
        if over > 0:  # the cap was lowered: retire the oldest-released extras
            for rule_id in live[:over]:
                retired.append({"rule_id": rule_id, "reason": "RULE_CAP"})
        for row in retired:
            try:
                self._transition(row["rule_id"], "DEPRECATED", f"RETIRED: {row['reason']}")
            except svc_mod.ServiceError:
                pass
            state.setdefault("retire_pending", []).append(row["rule_id"])
            state.setdefault("retired", []).append({"rule_id": row["rule_id"], "reason": row["reason"],
                                                    "at": _iso(self.now()), "applied": row.get("applied"),
                                                    "before": row.get("before"), "after": row.get("after")})
            self._mark_cluster(state, row["rule_id"], "DEPRECATED", reason=row["reason"])
        if retired:
            self._log(state, "retire", rules=[r["rule_id"] for r in retired])
            self.save(state)
        return {"status": "OK", "retired": [r["rule_id"] for r in retired], "checked": len(released)}

    # ------------------------------------------------------------------ cohort, daily, status
    def register_cohort(self) -> dict[str, Any]:
        from .s3_sync import register_device  # noqa: PLC0415
        out = {"registered": 0, "unchanged": 0, "errors": []}
        for device_id in sorted(self.cohort):
            if not c.is_identifier(device_id):
                out["errors"].append(f"DEVICE_ID_INVALID:{device_id[:40]}")
                continue
            try:
                res = register_device(self.service, self.tenant, device_id, str(self.cfg["line_id"]))
            except svc_mod.ServiceError as exc:
                out["errors"].append(f"{device_id}:{exc.code}")
                continue
            out["unchanged" if res.get("registration") == "UNCHANGED" else "registered"] += 1
        return out

    def daily(self) -> dict[str, Any]:
        out: dict[str, Any] = {"at": _iso(self.now())}
        steps = (("cohort", self.register_cohort), ("evaluate", self.evaluate), ("retire", self.retire),
                 ("build_pack", self.build_pack), ("review", self.export_review))
        for name, fn in steps:
            try:
                out[name] = fn()
            except (TrainError, svc_mod.ServiceError, b.BundleError, c.ContractError, OSError) as exc:
                out[name] = {"status": "ERROR", "code": getattr(exc, "code", type(exc).__name__),
                             "error": str(exc)[:300]}
        out["summary"] = self.status()
        return out

    def status(self) -> dict[str, Any]:
        state = self.state()
        now = self.now()
        canary = self._canary_pack(state)
        decided = [p for p in state["packs"] if p.get("status") in ("PROMOTED", "ROLLED_BACK")]
        last = decided[-1] if decided else None
        pending = 0
        if state.get("open_review"):
            path = self.dir / "review_requests" / f"{state['open_review']}.json"
            try:
                pending = len(json.loads(path.read_text(encoding="utf-8")).get("clusters") or [])
            except (OSError, ValueError):
                pending = 0
        retired_7d = [r for r in state.get("retired") or [] if (_epoch(r.get("at")) or 0) >= now - 7 * 86400]
        active = self._active_count(state)
        last_text = "无"
        if last and (_epoch(last.get("decided_at")) or 0) >= now - 48 * 3600:
            last_text = "已全量" if last["status"] == "PROMOTED" else "已回滚"
        m = len(canary.get("new_rules") or []) if canary else 0
        status = {
            "schema": STATUS_SCHEMA, "at": _iso(now), "tenant": self.tenant, "bundle_id": self.cfg["bundle_id"],
            "new_candidates_pending_review": pending, "open_review_request": state.get("open_review"),
            "backlog_validated": len(state.get("backlog") or []),
            "active_rules": active, "rule_cap": int(self.cfg["max_active_rules"]),
            "canary": ({"version": canary["version"], "since": canary["canary_at"], "new_rules": m,
                        "hours_on_canary": round((now - (_epoch(canary["canary_at"]) or now)) / 3600, 1)}
                       if canary else None),
            "last_batch": ({"version": last["version"], "outcome": last["status"], "decided_at": last.get("decided_at"),
                            "reasons": (last.get("decision") or {}).get("reasons")} if last else None),
            "released_version": next((p["version"] for p in reversed(state["packs"]) if p.get("status") == "RELEASED"),
                                     None),
            "retired_total": len(state.get("retired") or []), "retired_7d": len(retired_7d),
            "cohort": {"canary_devices": sum(1 for v in self.cohort.values() if v == "CANARY"),
                       "devices": len(self.cohort)},
            "summary_zh": f"新增候选 {pending} · 灰度中 {m} · 昨日批次 {last_text} · 退役 {len(state.get('retired') or [])}",
        }
        (self.dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return status


# --------------------------------------------------------------------------- CLI
def load_cohort(path: str | None) -> dict[str, str]:
    """``{"devices": [{"device_id", "channel"}, ...]}`` written by the fleet server (device_id -> channel)."""
    if not path:
        return {}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(d.get("device_id")): str(d.get("channel") or "RELEASED") for d in doc.get("devices") or []
            if isinstance(d, dict) and d.get("device_id")}


def open_train(args: argparse.Namespace) -> Train:
    from .s3_sync import CollectiveRoot  # noqa: PLC0415
    root = CollectiveRoot(args.runtime_root)
    root.dir.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    # before the publisher is bootstrapped there is no trust store: status/clusters still work, shipping refuses
    service = svc_mod.Service(root.db, trust_store=root.trust() if root.trust_path.is_file() else None)
    return Train(service, args.tenant, root.dir / "release_train",
                 publisher_key=root.publisher_key if root.key_path.is_file() else None,
                 config=config, cohort=load_cohort(args.cohort))


def _write_status_out(train: Train, path: str | None) -> None:
    if not path:
        return
    status = train.status()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def main(argv: list[str] | None = None, *, out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="release_train", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["clusters", "export-review", "import-review", "build-pack", "evaluate",
                                        "retire", "register-cohort", "daily", "status"])
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--config", help="JSON overriding DEFAULTS (thresholds, bundle id, models)")
    parser.add_argument("--cohort", help="fleet cohort file {devices: [{device_id, channel}]}")
    parser.add_argument("--status-out", help="also write the status JSON here (the fleet dashboard reads it)")
    parser.add_argument("--result", help="import-review: the review-result JSON")
    parser.add_argument("--replace", action="store_true", help="export-review: replace an open request")
    args = parser.parse_args(argv)
    try:
        train = open_train(args)
        if args.cmd == "clusters":
            result = {"status": "OK", "clusters": [{k: v for k, v in cl.items() if k != "event_ids"}
                                                   for cl in train.clusters()]}
        elif args.cmd == "export-review":
            result = train.export_review(replace=args.replace)
        elif args.cmd == "import-review":
            if not args.result:
                raise TrainError("RESULT_REQUIRED")
            result = train.import_review(json.loads(Path(args.result).read_text(encoding="utf-8")))
        elif args.cmd == "build-pack":
            result = train.build_pack()
        elif args.cmd == "evaluate":
            result = train.evaluate()
        elif args.cmd == "retire":
            result = train.retire()
        elif args.cmd == "register-cohort":
            result = {"status": "OK", **train.register_cohort()}
        elif args.cmd == "daily":
            result = {"status": "OK", **train.daily()}
        else:
            result = {"status": "OK", **train.status()}
        _write_status_out(train, args.status_out)
    except (TrainError, svc_mod.ServiceError, b.BundleError, c.ContractError, OSError, ValueError) as exc:
        result = {"status": "ERROR", "code": getattr(exc, "code", type(exc).__name__),
                  "detail": getattr(exc, "detail", None) or getattr(exc, "details", None), "error": str(exc)[:300]}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), file=out)
    return 0 if result.get("status") not in ("ERROR",) else 2


if __name__ == "__main__":
    sys.exit(main())
