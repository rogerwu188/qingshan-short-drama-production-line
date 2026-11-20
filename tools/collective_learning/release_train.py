"""Review, canary and promotion of the collective knowledge base -- the collector's daily release train.

Runs ONLY on the collector (the fleet server, single publisher; approved design 2026-11-12).  Devices never
publish.  Everything here works on the service database (events, receipts, candidates, bundles, channels) plus
the publisher key; the bucket pointers follow on the next ``s3_sync.py run-cycle`` (``sync_channels`` signs
whatever the service's channel table says, through the release gate).

Flow (all thresholds in ``DEFAULTS``, overridable with ``--config``):

1. clusters     lesson-type FAILURE events grouped by ``cluster_key`` (``evidence.cluster_key`` when the producer
                gave one -- ``<failure_type>|<detail_category>`` -- else ``evidence.failure_type``, so old thin
                events keep their cluster ids).  Round/rate facts, provider outages, ``default_accepted`` facts
                (unless ``include_default_accepted``) and engine/threshold items (``lesson_class``, plus the
                legacy run-level technical types) are never lessons; engine items are listed separately in the
                review request.  A cluster is eligible when seen on >= ``min_devices`` independent
                devices (``Service._independent_sources``: copies and replays collapse) OR >= ``min_episodes``
                distinct (device, episode) pairs; author-side (DIRECTING_GUIDANCE) clusters use
                ``directing_min_devices`` / ``directing_min_episodes`` instead.
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

6. exemplars    成功样例库: SUCCESS_EXEMPLAR events (first-pass units / praised practices of well-reviewed episodes,
                privacy-scrubbed on the device) are clustered by scene type, near-duplicates merged, the best
                ``exemplar_per_type`` per type kept (most devices, then episodes, then review score), capped at
                ``exemplar_max`` and signed as the separate bundle ``exemplar_bundle_id`` (``rules: []`` + ``exemplars``)
                through the same release gate and channels: CANARY first, RELEASED after ``exemplar_canary_hours``.
                No approval step (the entries are advisory reference text that already passed objective QA and an
                independent review); the open review request lists the pending library changes and the patrol may
                veto entries (``exemplar_veto``: ids) -- a veto revokes the canary pack and the ids never return.

7. fast-track   GLOBAL final-review lessons (line owner 2026-11-20: "通用的问题不分语言 ... 应该是 global 的 lesson
                立即生效").  A cluster ``FINAL_REVIEW:<kind>|global`` (the producer's scope classifier found the
                CONFIRMED finding language-independent; route DIRECTING_GUIDANCE or MODEL_CONSTRAINT) is eligible from
                ``fasttrack_min_episodes`` (1) episode.  ``fasttrack`` (hourly, collector_fasttrack.sh) exports only
                those clusters as a separate review request (``ft-...``, its own slot next to the daily ``rv-...``);
                the patrol reviews it within the hour; ``import-review`` of an ``ft-`` result moves every approved
                rule without ``scope.languages`` straight to RELEASED (VALIDATED -> CANARY -> RELEASED with the
                service's FAST_TRACK_SINGLE_SOURCE waiver) and ships a RELEASED-labelled pack to every device at
                once (an in-flight canary pack is re-signed with the rule added).  An approval the patrol scoped to
                a language goes to the normal backlog / canary.  Safety valves: ``fasttrack_max_rules`` active
                fast-track rules (and the global ``max_active_rules``); auto-retire when the target cluster recurs
                in >= ``fasttrack_retire_recurrences`` distinct episodes after ``fasttrack_retire_grace_hours``, or
                when the fleet got clearly worse after the rule shipped (same margins as the canary, before vs after
                windows, plus final-review rejects per episode); a kill switch (``fasttrack_enabled: false`` in the
                config or the file ``<state>/FASTTRACK_KILL``) stops export and publish (retirement keeps running);
                ``fasttrack-kill --rule ID|--all --reason R`` (or ``fasttrack_kill: [ids]`` in any review result)
                retires rules by hand.  Every step is logged in the state history.

Status: ``status.json`` (and ``--status-out``) -- the dashboard line
"新增候选 N · 灰度中 M · 上一批次 已全量/已回滚 · 退役 K".
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
    #: author-side lessons (DIRECTING_GUIDANCE: craft-standard gaps, final-review findings routed to the writer) are
    #: eligible on these lower thresholds (line owner 2026-11-20: single-language lines with one device each must be
    #: able to learn; the 12-24 h canary guards against a bad rule).  Model / engineering clusters keep the strict
    #: ``min_devices`` / ``min_episodes``.  A cluster is author-side when its failure type starts with one of
    #: ``directing_prefixes`` or its newest event carries ``evidence.lesson_route == "DIRECTING_GUIDANCE"``.
    "directing_prefixes": ["CRAFT_STD_GAP"],
    "directing_min_devices": 2,
    "directing_min_episodes": 2,
    "batch_max": 5,
    "max_active_rules": 40,
    "canary_hours": 24,
    #: line owner 2026-11-13: review every 6 h instead of daily -> at most one new pack per this many hours
    "pack_min_interval_hours": 24,
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
    "include_default_accepted": False,
    "review_samples_per_cluster": 3,
    #: 成功样例库 (exemplars.py): a separate signed bundle, auto-curated from SUCCESS_EXEMPLAR events, CANARY first,
    #: RELEASED after ``exemplar_canary_hours`` unless the patrol vetoes entries in its review result
    "exemplar_bundle_id": "nalu-exemplars",
    "exemplars_enabled": True,
    "exemplar_lookback_days": 60,
    "exemplar_canary_hours": 24,
    "exemplar_min_interval_hours": 24,
    "exemplar_per_type": 2,
    "exemplar_max": 60,
    #: 7. fast-track for GLOBAL confirmed final-review lessons (see the module docstring)
    "fasttrack_enabled": True,
    "fasttrack_min_episodes": 1,
    "fasttrack_routes": ["DIRECTING_GUIDANCE", "MODEL_CONSTRAINT"],
    "fasttrack_max_rules": 12,
    "fasttrack_batch_max": 3,
    "fasttrack_request_max_clusters": 10,
    "fasttrack_retire_recurrences": 3,
    "fasttrack_retire_grace_hours": 6,
    "fasttrack_regression_window_hours": 72,
    "fasttrack_regression_min_episodes": 3,
}
FASTTRACK_PREFIX = "FINAL_REVIEW:"
FASTTRACK_SCOPE = "global"
FASTTRACK_KILL_FILE = "FASTTRACK_KILL"
FASTTRACK_WAIVER = "FAST_TRACK_SINGLE_SOURCE"
FASTTRACK_INSTRUCTIONS = (
    "FAST-TRACK review (owner 2026-11-20): every cluster here is keyed FINAL_REVIEW:<kind>|global -- a CONFIRMED "
    "finding of the independent final review (reviewer problem, must-check DEFECT, or a Gemini finding the reviewer "
    "confirmed) that the engine classified as language-independent (each sample's scope_decision gives the basis "
    "and reason).  It is offered from ONE episode because an obvious, language-independent problem should be "
    "fixed for every line now.  An APPROVE ships to RELEASED on every device within minutes -- there is no canary; "
    "the train retires the rule automatically if the same kind recurs in 3 later episodes or the fleet gets worse.  "
    "Default APPROVE when the samples show one clear, general cause: lesson_route DIRECTING_GUIDANCE -> category "
    "DIRECTING_HEURISTIC, application {carrier: DIRECTING_GUIDANCE, prompt_clause: {zh, en}}, scope {models, stages "
    "[SCRIPT_AUTHORING, STORYBOARD_AUTHORING]} with NO scope.languages, one short general clause (no names, places "
    "or plot), exceptions required; lesson_route MODEL_CONSTRAINT -> category MODEL_CONSTRAINT with a provider-prompt "
    "clause (carrier NEGATIVE_CONSTRAINT or BEAT_DIRECTION, scope.stages [VIDEO_COMPILE], no scope.languages) only "
    "when a clause can plausibly prevent it.  Override the scope by adding scope.languages [<lang>] when the clause "
    "clearly only makes sense for one language -- that rule then takes the normal canary path.  REJECT when the "
    "finding is story-specific, a one-off taste call, contradicts NALU_CRAFT_STANDARD_v1 (e.g. it asks for an "
    "establishing shot, which C-01 drops), is an engine problem, or the samples do not share one cause.  At most "
    "batch_max approvals are used; never put money, gates, authority or secrets into a clause.  Result format is the "
    "daily one; to retire a live fast-track rule add \"fasttrack_kill\": [rule_id, ...] + \"fasttrack_kill_reason\".")
ROUND_TYPES = ("Q1_ROUND", "Q2_ROUND", "POSTGEN_ROUND")
NOT_LESSON_PREFIXES = ("PROVIDER_OUTAGE",)
#: producer lesson_class values that a prompt rule cannot fix (engine thresholds, the reviewer's own evidence)
ENGINE_LESSON_CLASSES = ("ENGINE_THRESHOLD", "ENGINE_BOOKKEEPING", "REVIEW_EVIDENCE_INVALID")
#: failure types recorded before producers tagged lesson_class (2026-11-13 review): raster / duration / container
#: checks on provider output and the S7 mix loudness -- engine/threshold items whatever event carried them
LEGACY_ENGINE_TYPES = frozenset({
    "POSTGEN_FAIL:RESOLUTION", "POSTGEN_FAIL:DURATION", "POSTGEN_FAIL:ASPECT_RATIO", "POSTGEN_FAIL:CODEC",
    "POSTGEN_FAIL:SAMPLE_RATE", "POSTGEN_FAIL:FRAME_RATE", "POSTGEN_FAIL:AUDIO_STREAM", "POSTGEN_FAIL:AV_SYNC",
    "S7_DETECTOR:loudness"})
ENGINE_ITEM_NOTE = ("Engine / threshold items: run-level technical mismatches (provider raster or duration vs the "
                    "engine's tolerance, container checks, the engine's own mix loudness).  A prompt rule cannot "
                    "fix them; they go to the engine maintainers.  Listed for information only -- do not decide.")
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


def _evidence(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("evidence") if isinstance(event.get("evidence"), dict) else {}


def cluster_key(event: dict[str, Any]) -> str:
    """The clustering key: the producer's ``cluster_key`` (``<failure_type>|<detail_category>``) when it is
    consistent with the event's failure type, else the failure type itself (old events: unchanged clusters)."""
    ft = failure_type(event)
    key = _evidence(event).get("cluster_key")
    if isinstance(key, str) and (key == ft or key.startswith(ft + "|")) and len(key) <= 200:
        return key
    return ft


def is_engine_item(event: dict[str, Any]) -> bool:
    return (str(_evidence(event).get("lesson_class") or "") in ENGINE_LESSON_CLASSES
            or failure_type(event) in LEGACY_ENGINE_TYPES)


def is_lesson(event: dict[str, Any], include_default_accepted: bool = False) -> bool:
    if event.get("event_kind") != "FAILURE_OBSERVATION":
        return False
    ft = failure_type(event)
    if ft in ROUND_TYPES or ft.startswith(NOT_LESSON_PREFIXES) or is_engine_item(event):
        return False
    return include_default_accepted or _evidence(event).get("default_accepted") is not True


def evidence_sample(event: dict[str, Any]) -> dict[str, Any]:
    """One concrete, reviewer-readable sample of an event: where it happened, the symptom, and the producer's
    first unit sample (unit, scene/shot label, reason, measured-vs-threshold detail, excerpt) or S7 detail."""
    ev = _evidence(event)
    out: dict[str, Any] = {"device": event.get("device_id"), "episode": event.get("episode_id"),
                           "stage": event.get("stage"), "symptom": str(event.get("symptom") or "")[:300]}
    for key in ("failure_code", "detail_category", "item", "asset_kind", "units_failed", "units_in_round",
                "default_accepted", "accepted_order_seq", "language", "lesson_route", "review_round", "kb_scope",
                "scope_decision", "confirmed_by"):
        if ev.get(key) not in (None, ""):
            out[key] = ev[key]
    samples = ev.get("samples")
    if isinstance(samples, list) and samples and isinstance(samples[0], dict):
        out["unit_samples"] = samples[:2]
    elif isinstance(samples, list) and samples:  # old thin events: raw reason strings
        out["reasons"] = [str(x)[:160] for x in samples[:3]]
    if isinstance(ev.get("detail"), dict):
        out["detail"] = ev["detail"]
    return out


def lesson_route(events: list[dict[str, Any]], prefixes: Any = ()) -> str | None:
    """``DIRECTING_GUIDANCE`` when the cluster is an author-side lesson (prefix match or the newest event's
    ``evidence.lesson_route``), else the newest event's route (``MODEL_CONSTRAINT`` ...) or None."""
    if not events:
        return None
    ft = failure_type(events[-1])
    if any(ft == p or ft.startswith(str(p) + ":") or ft.startswith(str(p) + "|") for p in prefixes or ()):
        return "DIRECTING_GUIDANCE"
    route = _evidence(events[-1]).get("lesson_route")
    return str(route) if isinstance(route, str) and route else None


def cluster_id(ftype: str) -> str:
    return "cl-" + hashlib.sha256(ftype.encode("utf-8")).hexdigest()[:12]


def is_fasttrack_key(key: str) -> bool:
    return str(key).startswith(FASTTRACK_PREFIX) and str(key).endswith("|" + FASTTRACK_SCOPE)


def fasttrack_candidate(key: str, events: list[dict[str, Any]], route: str | None, routes: Any) -> bool:
    """A GLOBAL final-review cluster whose newest event is a confirmed finding on a fast-track route."""
    if not is_fasttrack_key(key) or not events or route not in set(routes or ()):
        return False
    ev = _evidence(events[-1])
    return ev.get("confirmed") is True and ev.get("kb_scope") == FASTTRACK_SCOPE


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
        include_accepted = bool(self.cfg.get("include_default_accepted"))
        for event in self.events(since=since):
            if is_lesson(event, include_accepted):
                groups.setdefault(cluster_key(event), []).append(event)
        out = []
        db = self.service._db()
        for key, events in sorted(groups.items()):
            ftype = failure_type(events[0])
            events.sort(key=lambda e: e["_at"])
            ids = [e["event_id"] for e in events]
            sources = self.service._independent_sources(db, self.tenant, ids)
            episodes = {(e.get("device_id"), e.get("episode_id")) for e in events}
            symptoms: list[str] = []
            for e in reversed(events):
                if e.get("symptom") not in symptoms:
                    symptoms.append(str(e.get("symptom")))
            route = lesson_route(events, self.cfg.get("directing_prefixes") or ())
            directing = route == "DIRECTING_GUIDANCE"
            min_devices = int(self.cfg["directing_min_devices" if directing else "min_devices"])
            min_episodes = int(self.cfg["directing_min_episodes" if directing else "min_episodes"])
            languages = sorted({str(_evidence(e).get("language")) for e in events if _evidence(e).get("language")})
            fast = fasttrack_candidate(key, events, route, self.cfg.get("fasttrack_routes"))
            out.append({
                "cluster_id": cluster_id(key), "failure_type": ftype, "cluster_key": key,
                "detail_category": key[len(ftype) + 1:] if key != ftype else None,
                "stages": sorted({str(e.get("stage")) for e in events}),
                "devices": sources["independent_sources"], "episodes": len(episodes), "event_count": len(events),
                "first_seen": _iso(events[0]["_at"]), "last_seen": _iso(events[-1]["_at"]),
                "sample_symptoms": symptoms[:5],
                "sample_evidence": [{k: v for k, v in (e.get("evidence") or {}).items() if k != "failure_type"}
                                    for e in events[-3:]],
                "evidence_samples": self._evidence_samples(events),
                "models": sorted({str(e.get("provider_model_version")) for e in events})[:5],
                **({"lesson_route": route} if route else {}),
                **({"languages": languages} if languages else {}),
                "thresholds": {"min_devices": min_devices, "min_episodes": min_episodes},
                "event_ids": ids[-50:],
                "eligible": (sources["independent_sources"] >= min_devices or len(episodes) >= min_episodes),
                **({"kb_scope": FASTTRACK_SCOPE, "fast_track": True,
                    "fast_track_eligible": len(episodes) >= int(self.cfg["fasttrack_min_episodes"])} if fast else {}),
            })
        return out

    def _evidence_samples(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Up to ``review_samples_per_cluster`` concrete samples, newest first, one per device where possible."""
        limit = max(1, int(self.cfg.get("review_samples_per_cluster") or 3))
        picked, devices = [], set()
        for pass_ in (0, 1):
            for event in reversed(events):
                if len(picked) >= limit:
                    break
                if event in picked or (pass_ == 0 and event.get("device_id") in devices):
                    continue
                picked.append(event)
                devices.add(event.get("device_id"))
        return [evidence_sample(e) for e in picked]

    def engine_items(self) -> list[dict[str, Any]]:
        """Engine / threshold facts (not lessons) grouped by cluster key: counts and two samples each."""
        since = self.now() - float(self.cfg["lookback_days"]) * 86400
        groups: dict[str, list[dict[str, Any]]] = {}
        for event in self.events(since=since):
            if event.get("event_kind") == "FAILURE_OBSERVATION" and is_engine_item(event):
                groups.setdefault(cluster_key(event), []).append(event)
        out = []
        for key, events in sorted(groups.items()):
            events.sort(key=lambda e: e["_at"])
            out.append({"cluster_key": key, "failure_type": failure_type(events[0]),
                        "lesson_class": _evidence(events[-1]).get("lesson_class") or "LEGACY_ENGINE_TYPE",
                        "devices": len({e.get("device_id") for e in events}),
                        "episodes": len({(e.get("device_id"), e.get("episode_id")) for e in events}),
                        "event_count": len(events), "last_seen": _iso(events[-1]["_at"]),
                        "samples": [evidence_sample(e) for e in events[-2:]]})
        out.sort(key=lambda row: (-row["devices"], -row["episodes"], row["cluster_key"]))
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
                targeted.add(row.get("cluster_key") or row.get("failure_type"))
        fast_live = self.fasttrack_active()
        pending_ft = self._open_cluster_ids(state.get("open_fasttrack_review"))
        clusters = [cl for cl in self.clusters() if cl["eligible"] and cl["cluster_id"] not in handled
                    and cl["cluster_key"] not in targeted and cl["failure_type"] not in targeted
                    and cl["cluster_id"] not in pending_ft and not (fast_live and cl.get("fast_track"))]
        exemplar_changes = self._exemplar_review_section(state)
        if not clusters and not exemplar_changes:
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
            "thresholds": {k: self.cfg[k] for k in ("min_devices", "min_episodes", "lookback_days",
                                                    "directing_min_devices", "directing_min_episodes")},
            "instructions": (
                "For each cluster decide APPROVE or REJECT with a reason.  APPROVE only a problem a prompt-level "
                "rule can prevent; give the rule: category (DIRECTING_HEURISTIC|MODEL_CONSTRAINT|"
                "ENGINEERING_INVARIANT|EXECUTION_POLICY), scope {models, stages, ...}, trigger, recommendation, "
                "exceptions (required for DIRECTING_HEURISTIC), verification, cost_class, evidence_level, "
                "validation_scope, application {carrier: BEAT_DIRECTION|NEGATIVE_CONSTRAINT|CHECK_ONLY|"
                "DIRECTING_GUIDANCE, prompt_clause: {zh, en}}.  BEAT_DIRECTION / NEGATIVE_CONSTRAINT clauses go "
                "into the provider video prompt (scope.stages [VIDEO_COMPILE]).  DIRECTING_GUIDANCE is a lesson "
                "for the AUTHOR -- Codex writing the dispatch, script, storyboard and shot prompt_specs -- injected "
                "into its episode start prompt (scope.stages [SCRIPT_AUTHORING]; optional scope.languages [zh|en|ja|ko] "
                "and scope.genres [X2C category name]); use it when the fix is how the episode is written, e.g. "
                "\"open every episode on an on-screen conflict in the first 3 s\" or \"keep expository dialogue "
                "under 3 lines per scene\" (category DIRECTING_HEURISTIC, with exceptions).  A cluster keyed "
                "CRAFT_STD_GAP|<item id> (e.g. CRAFT_STD_GAP|S-03) is a recurring gap the independent final reviewer "
                "found against NALU_CRAFT_STANDARD_v1 (lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md; its samples "
                "carry the item id, the measured numbers and a scrubbed fix line): when it recurs, APPROVE it as a "
                "DIRECTING_GUIDANCE rule (category DIRECTING_HEURISTIC, scope.stages [SCRIPT_AUTHORING]) whose "
                "trigger and recommendation cite the item id and whose prompt_clause restates that item's Codex line "
                "with the numbers the samples show; REJECT it only when the samples contradict each other.  "
                "A cluster keyed FINAL_REVIEW:<kind>|<language> (e.g. FINAL_REVIEW:PACING|ko) is a recurring "
                "CONFIRMED finding of the independent final review (reviewer problem, must-check DEFECT or a Gemini "
                "A/V finding the reviewer confirmed) that the engine classified as depending on that dialogue "
                "language (each sample's scope_decision gives the basis and reason); its samples carry the source, "
                "severity, time window and an anonymised description.  FINAL_REVIEW:<kind>|global clusters "
                "(language-independent) normally go through the separate fast-track review (ft-...); they appear "
                "here only while the fast-track is switched off -- then approve them WITHOUT scope.languages.  "
                "lesson_route DIRECTING_GUIDANCE (kinds "
                "PACING, STORY, LENGTH, STATIC_SHOT_SPLIT, OTHER) means an AUTHOR-side lesson: APPROVE it as a "
                "DIRECTING_GUIDANCE rule (category DIRECTING_HEURISTIC, scope.stages [SCRIPT_AUTHORING], "
                "scope.languages [<language>]) that turns the descriptions into one general writing / directing "
                "instruction (never the story itself: no names, places or plot); REJECT when the descriptions do "
                "not share one cause.  lesson_route MODEL_CONSTRAINT (BURNED_TEXT, FACE_DRIFT, SKIN_SHEEN, COSTUME_IDENTITY, "
                "LOOKALIKE, VOICE, ASR_MISMATCH) may become a provider-prompt clause only when a clause can plausibly "
                "prevent it.  Author-side clusters (CRAFT_STD_GAP, lesson_route DIRECTING_GUIDANCE) are offered "
                "from directing_min_episodes episodes (one device is enough); the canary decides whether they help.  "
                "At most batch_max approvals ship per day; extra approvals wait in the backlog.  Never put money, gates, authority "
                "or secrets into a clause.  Each cluster's evidence_samples carry the concrete cause (unit, "
                "scene/shot label, measured vs threshold, transcript / reviewer-note excerpt); detail_category is "
                "the normalised cause the cluster is keyed on.  engine_items are NOT clusters: information only.  "
                "exemplar_changes (when present) lists the auto-curated 成功样例库 canary: no decision needed; "
                "to veto entries add \"exemplar_veto\": [exemplar_id, ...] (+ \"exemplar_veto_reason\") to the "
                "result."),
            "clusters": clusters,
            **({"exemplar_changes": exemplar_changes} if exemplar_changes else {}),
            "engine_items": {"note": ENGINE_ITEM_NOTE, "items": self.engine_items()[:30]},
        }
        out_dir = self.dir / "review_requests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{request_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        state["open_review"] = request_id
        if exemplar_changes:
            state.setdefault("exemplars", {})["reviewed_in"] = request_id
        self._log(state, "export_review", request_id=request_id, clusters=len(clusters))
        self.save(state)
        return {"status": "EXPORTED", "request_id": request_id, "path": str(path), "clusters": len(clusters)}

    def import_review(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict) or result.get("schema") != RESULT_SCHEMA:
            raise TrainError("REVIEW_RESULT_SCHEMA_INVALID")
        state = self.state()
        request_id = str(result.get("request_id") or "")
        req_path = self.dir / "review_requests" / f"{request_id}.json"
        fast = bool(request_id) and request_id == state.get("open_fasttrack_review")
        if not request_id or request_id not in (state.get("open_review"), state.get("open_fasttrack_review")) \
                or not req_path.is_file():
            raise TrainError("REVIEW_REQUEST_NOT_OPEN", {"open": state.get("open_review"),
                                                         "open_fasttrack": state.get("open_fasttrack_review"),
                                                         "got": request_id})
        request = json.loads(req_path.read_text(encoding="utf-8"))
        ft = state.setdefault("fasttrack", {})
        ft_slots = max(0, min(int(self.cfg["fasttrack_max_rules"]) - self._fasttrack_active_count(state),
                              int(self.cfg["max_active_rules"]) - self._active_count(state)
                              - len(ft.get("queue") or [])))
        ft_taken = 0
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
            base = {"failure_type": cl["failure_type"], "cluster_key": cl.get("cluster_key") or cl["failure_type"],
                    "reviewer": reviewer, "reason": reason[:500],
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
            rule_scope = (decision.get("rule") or {}).get("scope") or {}
            if fast and not rule_scope.get("languages") and ft_taken < min(ft_slots, int(self.cfg["fasttrack_batch_max"])):
                ft_taken += 1
                ft.setdefault("queue", []).append(rule_id)
                state["clusters"][cid]["fast_track"] = True
                outcomes.append({"cluster_id": cid, "status": "VALIDATED", "rule_id": rule_id, "fast_track": True})
                continue
            if fast:  # scoped to a language by the patrol, or over the fast-track cap: the normal canary path
                state["clusters"][cid]["fast_track_declined"] = ("SCOPED_TO_LANGUAGE" if rule_scope.get("languages")
                                                                 else "FASTTRACK_CAP")
            state.setdefault("backlog", []).append(rule_id)
            outcomes.append({"cluster_id": cid, "status": "VALIDATED", "rule_id": rule_id})
        veto = [str(x) for x in result.get("exemplar_veto") or [] if str(x).strip()]
        if veto:
            outcomes.append({"exemplar_veto": self._exemplar_veto(
                state, veto, str(result.get("exemplar_veto_reason") or "patrol veto"), reviewer)})
        kill = [str(x) for x in result.get("fasttrack_kill") or [] if str(x).strip()]
        if fast:
            state["open_fasttrack_review"] = None
        else:
            state["open_review"] = None
        results_dir = self.dir / "review_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / f"{request_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                                         encoding="utf-8")
        self._log(state, "import_review", request_id=request_id, fast_track=fast,
                  outcomes={k: sum(1 for o in outcomes if o.get("status") == k)
                            for k in {o["status"] for o in outcomes if "status" in o}})
        self.save(state)
        out = {"status": "IMPORTED", "request_id": request_id, "outcomes": [o for o in outcomes if "status" in o],
               **({"exemplar_veto": next(o["exemplar_veto"] for o in outcomes if "exemplar_veto" in o)}
                  if veto else {}),
               "backlog": len(state.get("backlog") or [])}
        if kill:
            out["fasttrack_kill"] = self.fasttrack_kill(kill, str(result.get("fasttrack_kill_reason") or "patrol"),
                                                        by=reviewer)
        if fast and (self.state().get("fasttrack") or {}).get("queue"):
            # immediate effect: publish the approved global rules now (the hourly run retries a failed publish)
            try:
                out["fasttrack_publish"] = self.fasttrack_publish()
            except (TrainError, svc_mod.ServiceError, b.BundleError, c.ContractError, OSError) as exc:
                out["fasttrack_publish"] = {"status": "ERROR", "code": getattr(exc, "code", type(exc).__name__),
                                            "error": str(exc)[:300]}
        return out

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
                          "target_failure_types": [cl.get("cluster_key") or cl["failure_type"]],
                          "cluster_id": cl["cluster_id"],
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

    def _next_version(self, state: dict[str, Any], bundle_id: str | None = None) -> int:
        bundle_id = bundle_id or self.cfg["bundle_id"]
        rows = self.service._read("SELECT version FROM bundles WHERE tenant_id=? AND bundle_id=?",
                                  (self.tenant, bundle_id))
        packs = state["packs"] if bundle_id == self.cfg["bundle_id"] else \
            (state.get("exemplars") or {}).get("packs") or []
        known = [int(v) for (v,) in rows if str(v).isdigit()] + [int(p["version"]) for p in packs]
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
        gap_s = float(self.cfg.get("pack_min_interval_hours", 24)) * 3600
        if any(p.get("label") == "CANARY" and (_epoch(p.get("created_at")) or 0) > now - gap_s for p in state["packs"]):
            return {"status": "PACK_INTERVAL_NOT_ELAPSED"}
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
            if event.get("event_kind") == "SUCCESS_EXEMPLAR":
                continue  # library input, not a production-rate fact
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
                if (failure_type(e) in targets or cluster_key(e) in targets) \
                        and e.get("event_kind") == "FAILURE_OBSERVATION":
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
        for version in [pack["version"], *(pack.get("superseded_versions") or [])]:
            self.service.revoke_bundle(self.pub, bundle_id=self.cfg["bundle_id"], version=str(version),
                                       reason=reason[:300])
        released = next((p for p in reversed(state["packs"]) if p.get("status") == "RELEASED"), None)
        if pack.get("superseded_versions") and released:
            # the canary pack was re-signed by a fast-track publish: canary devices fall back to the full RELEASED set
            self.service.release(self.pub, bundle_id=self.cfg["bundle_id"], version=str(released["version"]),
                                 channel="CANARY", note=f"rollback of canary pack {pack['version']}")
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
                 ("build_pack", self.build_pack), ("exemplars", self.exemplar_step), ("review", self.export_review))
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
        exemplar_status = self._exemplar_status(state)
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
            "exemplars": exemplar_status,
            "open_fasttrack_review_request": state.get("open_fasttrack_review"),
            "fast_track": self._fasttrack_status(state),
            "summary_zh": f"新增候选 {pending} · 灰度中 {m} · 上一批次 {last_text} · 退役 {len(state.get('retired') or [])}"
                          + (f" · 样例 {exemplar_status['count']}" if exemplar_status["count"] else "")
                          + (f" · 快速通道 {self._fasttrack_active_count(state)}"
                             if self._fasttrack_active_count(state) else "")
                          + (" · 快速通道已关闭" if not self.fasttrack_active() else ""),
        }
        (self.dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return status


    # ------------------------------------------------------------------ 7. fast-track (GLOBAL lessons)
    def fasttrack_active(self) -> bool:
        """False when the kill switch is on: ``fasttrack_enabled: false`` or the file ``<state>/FASTTRACK_KILL``."""
        return bool(self.cfg.get("fasttrack_enabled", True)) and not (self.dir / FASTTRACK_KILL_FILE).exists()

    def _fasttrack_live_rules(self, state: dict[str, Any]) -> list[str]:
        rules = (state.get("fasttrack") or {}).get("rules") or {}
        pending = set(state.get("retire_pending") or [])
        return [r for r, row in rules.items() if row.get("status") == "RELEASED" and r not in pending]

    def _fasttrack_active_count(self, state: dict[str, Any]) -> int:
        return len(self._fasttrack_live_rules(state))

    def _open_cluster_ids(self, request_id: Any) -> set[str]:
        if not request_id:
            return set()
        try:
            data = json.loads((self.dir / "review_requests" / f"{request_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {str(cl.get("cluster_id")) for cl in data.get("clusters") or []}

    def fasttrack_export(self) -> dict[str, Any]:
        """Export the fast-track-eligible GLOBAL clusters as their own review request (``ft-...``)."""
        state = self.state()
        if not self.fasttrack_active():
            return {"status": "KILLED"}
        open_id = state.get("open_fasttrack_review")
        if open_id and (self.dir / "review_requests" / f"{open_id}.json").is_file():
            return {"status": "OPEN_REVIEW_PENDING", "request_id": open_id}
        handled = {cid for cid, row in state["clusters"].items() if row.get("status") in
                   ("VALIDATED", "REJECTED", "CANARY", "RELEASED", "BLOCKED_POLICY", "DEPRECATED")}
        targeted = {row.get("cluster_key") or row.get("failure_type") for row in state["clusters"].values()
                    if row.get("status") in ("VALIDATED", "CANARY", "RELEASED")}
        in_daily = self._open_cluster_ids(state.get("open_review"))
        clusters = [cl for cl in self.clusters() if cl.get("fast_track_eligible") and cl["cluster_id"] not in handled
                    and cl["cluster_key"] not in targeted and cl["cluster_id"] not in in_daily]
        if not clusters:
            state["open_fasttrack_review"] = None
            self.save(state)
            return {"status": "NOTHING_TO_REVIEW", "clusters": 0}
        clusters.sort(key=lambda cl: (-cl["episodes"], -cl["devices"], cl["cluster_key"]))
        clusters = clusters[: int(self.cfg["fasttrack_request_max_clusters"])]
        now = self.now()
        digest = hashlib.sha256(json.dumps([cl["cluster_id"] for cl in clusters]).encode()).hexdigest()[:6]
        request_id = f"ft-{_iso(now).replace(':', '').replace('-', '')}-{digest}"
        slots = max(0, min(int(self.cfg["fasttrack_max_rules"]) - self._fasttrack_active_count(state),
                           int(self.cfg["max_active_rules"]) - self._active_count(state)))
        request = {
            "schema": REQUEST_SCHEMA, "request_id": request_id, "tenant": self.tenant, "created_at": _iso(now),
            "fast_track": True, "batch_max": min(int(self.cfg["fasttrack_batch_max"]), slots),
            "active_rules": self._active_count(state), "rule_cap": int(self.cfg["max_active_rules"]),
            "fast_track_rules": self._fasttrack_active_count(state),
            "fast_track_rule_cap": int(self.cfg["fasttrack_max_rules"]), "free_rule_slots": slots,
            "thresholds": {k: self.cfg[k] for k in ("fasttrack_min_episodes", "fasttrack_retire_recurrences",
                                                    "fasttrack_retire_grace_hours", "lookback_days")},
            "instructions": FASTTRACK_INSTRUCTIONS, "clusters": clusters,
        }
        out_dir = self.dir / "review_requests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{request_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        state["open_fasttrack_review"] = request_id
        self._log(state, "fasttrack_export", request_id=request_id, clusters=len(clusters))
        self.save(state)
        return {"status": "EXPORTED", "request_id": request_id, "path": str(path), "clusters": len(clusters)}

    def _fasttrack_ship(self, state: dict[str, Any], note: str) -> dict[str, Any]:
        """Sign the live RELEASED set as a RELEASED pack for every device; an in-flight canary pack is re-signed
        with the same set plus its own new rules, so canary devices see the change too."""
        pending = set(state.get("retire_pending") or [])
        live = [r for r in dict.fromkeys(state.get("released_rules") or []) if r not in pending
                and (self.candidate(r) or {}).get("state") == "RELEASED"]
        canary = self._canary_pack(state)
        version = self._next_version(state)
        shipped = self._ship(version, "RELEASED", live, ["RELEASED"] if canary else ["RELEASED", "CANARY"], note)
        out: dict[str, Any] = {"released_version": version, "rules": live}
        if canary:
            new = [r for r in canary.get("new_rules") or [] if (self.candidate(r) or {}).get("state") == "CANARY"]
            cversion = self._next_version(state)  # the RELEASED version above is already in the service
            cshipped = self._ship(cversion, "CANARY", live + new, ["CANARY"], f"{note} (canary pack {canary['version']} re-signed)")
            canary.setdefault("superseded_versions", []).append(canary["version"])
            canary.update({"version": cversion, "kept_rules": live, "digest": cshipped["digest"],
                           "rules": cshipped["rules"]})
            out["canary_version"] = cversion
        state["packs"].append({**shipped, "created_at": _iso(self.now()), "status": "RELEASED", "fast_track": True})
        state["released_rules"] = live
        state["retire_pending"] = [r for r in state.get("retire_pending") or [] if r in live]
        return out

    def fasttrack_publish(self) -> dict[str, Any]:
        """Approved fast-track rules -> RELEASED on every device now (VALIDATED -> CANARY -> RELEASED, waiver
        FAST_TRACK_SINGLE_SOURCE), then one RELEASED pack."""
        state = self.state()
        ft = state.setdefault("fasttrack", {})
        queue = list(ft.get("queue") or [])
        if not queue:
            return {"status": "NOTHING_TO_SHIP"}
        if not self.fasttrack_active():
            return {"status": "KILLED", "queued": queue}
        if self.publisher_key is None:
            raise TrainError("PUBLISHER_KEY_UNAVAILABLE")
        promoted, blocked = [], []
        for rule_id in queue:
            rec = self.candidate(rule_id)
            if rec is None or rec["state"] not in ("VALIDATED", "CANARY"):
                ft["queue"].remove(rule_id)
                continue
            try:
                if rec["state"] == "VALIDATED":
                    self._transition(rule_id, "CANARY", "fast-track: global confirmed final-review lesson")
                rec = self.service.get_candidate(self.pub, rule_id)
                self.service.transition_candidate(self.pub, rule_id, to="RELEASED", if_match=rec["etag"],
                                                  note="fast-track: RELEASED directly (no canary)",
                                                  waive=(FASTTRACK_WAIVER,))
                promoted.append(rule_id)
            except svc_mod.ServiceError as exc:
                blocked.append({"rule_id": rule_id, "code": exc.code, "details": exc.details})
                try:
                    if (self.candidate(rule_id) or {}).get("state") == "CANARY":
                        self._transition(rule_id, "DEPRECATED", f"fast-track refused: {exc.details}")
                except svc_mod.ServiceError:
                    pass
                self._mark_cluster(state, rule_id, "BLOCKED_POLICY", reason=json.dumps(exc.details)[:300])
            ft["queue"].remove(rule_id)
        if not promoted:
            self._log(state, "fasttrack_publish", outcome="NOTHING_PROMOTED", blocked=blocked)
            self.save(state)
            return {"status": "NOTHING_TO_SHIP", "blocked": blocked}
        state["released_rules"] = list(dict.fromkeys(list(state.get("released_rules") or []) + promoted))
        shipped = self._fasttrack_ship(state, f"fast-track: +{len(promoted)} global")
        now = _iso(self.now())
        for rule_id in promoted:
            self._mark_cluster(state, rule_id, "RELEASED", fast_track=True)
            cl = next((row for row in state["clusters"].values() if row.get("rule_id") == rule_id), {})
            ft.setdefault("rules", {})[rule_id] = {
                "status": "RELEASED", "released_at": now, "version": shipped["released_version"],
                "cluster_key": cl.get("cluster_key"), "batch": shipped["released_version"]}
        self._log(state, "fasttrack_publish", version=shipped["released_version"], promoted=promoted,
                  blocked=blocked, canary_version=shipped.get("canary_version"))
        self.save(state)
        return {"status": "PUBLISHED_TO_RELEASED", "version": shipped["released_version"], "promoted": promoted,
                "blocked": blocked, **({"canary_version": shipped["canary_version"]}
                                       if shipped.get("canary_version") else {})}

    def _merged_rates(self, since: float, until: float) -> dict[str, Any]:
        """Fleet-wide (canary + control) production rates over a window, plus final-review rejects per episode."""
        m = self.metrics(since, until)
        a, b_ = m["canary"], m["control"]
        eps = a["episodes"] + b_["episodes"]

        def wavg(key: str, units: str) -> float | None:
            n = a[units] + b_[units]
            if not n:
                return None
            return round(((a[key] or 0) * a[units] + (b_[key] or 0) * b_[units]) / n, 4)

        def per_ep(key: str) -> float | None:
            if not eps:
                return None
            return round(((a[key] or 0) * a["episodes"] + (b_[key] or 0) * b_["episodes"]) / eps, 3)
        rejects = {(e.get("device_id"), e.get("episode_id")) for e in self.events(since=since, until=until)
                   if failure_type(e) == "S7_FINAL_REVIEW_REJECT" and e.get("event_kind") == "FAILURE_OBSERVATION"}
        return {"episodes": eps, "q1_admission_rate": wavg("q1_admission_rate", "q1_units"),
                "q1_units": a["q1_units"] + b_["q1_units"], "q2_pass_rate": wavg("q2_pass_rate", "q2_units"),
                "q2_units": a["q2_units"] + b_["q2_units"],
                "redo_rounds_per_episode": per_ep("redo_rounds_per_episode"),
                "content_rejections_per_episode": per_ep("content_rejections_per_episode"),
                "final_rejects_per_episode": round(len(rejects) / eps, 3) if eps else None}

    def fasttrack_retire(self) -> dict[str, Any]:
        """Safety valves for live fast-track rules: the target recurs in >= ``fasttrack_retire_recurrences``
        distinct episodes after the grace period (the rule is not helping), or the fleet got clearly worse after
        the batch shipped (canary margins, before vs after windows) -> DEPRECATED and a new RELEASED pack."""
        state = self.state()
        rules = (state.get("fasttrack") or {}).get("rules") or {}
        live = self._fasttrack_live_rules(state)
        if not live:
            return {"status": "OK", "checked": 0, "retired": []}
        now = self.now()
        grace = float(self.cfg["fasttrack_retire_grace_hours"]) * 3600
        need = int(self.cfg["fasttrack_retire_recurrences"])
        events = self.events(since=min(_epoch(rules[r].get("released_at")) or now for r in live))
        retire: list[dict[str, Any]] = []
        for rule_id in live:
            row = rules[rule_id]
            start = (_epoch(row.get("released_at")) or now) + grace
            target = row.get("cluster_key")
            eps = sorted({f"{e.get('device_id')}/{e.get('episode_id')}" for e in events
                          if e["_at"] >= start and e.get("event_kind") == "FAILURE_OBSERVATION"
                          and cluster_key(e) == target})
            row["recurrences"] = len(eps)
            if len(eps) >= need:
                retire.append({"rule_id": rule_id, "reason": f"FAST_TRACK_TARGET_RECURRED:{len(eps)}_episodes",
                               "episodes": eps[:10]})
        window = float(self.cfg["fasttrack_regression_window_hours"]) * 3600
        min_eps = int(self.cfg["fasttrack_regression_min_episodes"])
        batches: dict[Any, list[str]] = {}
        for rule_id in live:
            if not rules[rule_id].get("regression_checked"):
                batches.setdefault(rules[rule_id].get("batch"), []).append(rule_id)
        checks = []
        for batch, ids in batches.items():
            at = _epoch(rules[ids[0]].get("released_at")) or now
            before, after = self._merged_rates(at - window, at), self._merged_rates(at, min(now, at + window))
            if before["episodes"] < min_eps or after["episodes"] < min_eps:
                if now - at >= window:
                    for r in ids:
                        rules[r]["regression_checked"] = "INSUFFICIENT_DATA"
                continue
            worse = self._worse(after, before)
            fb, fa = before["final_rejects_per_episode"], after["final_rejects_per_episode"]
            if fb is not None and fa is not None and fa - fb >= float(self.cfg["per_episode_abs_margin"]) \
                    and fa > fb * (1 + float(self.cfg["per_episode_ratio_margin"])):
                worse.append(f"final_rejects_per_episode:after={fa}:before={fb}")
            checks.append({"batch": batch, "before": before, "after": after, "worse": worse})
            for r in ids:
                rules[r]["regression_checked"] = "WORSE" if worse else "NOT_WORSE"
            if worse:
                retire += [{"rule_id": r, "reason": "FAST_TRACK_REGRESSION:" + "; ".join(worse)} for r in ids
                           if r not in {x["rule_id"] for x in retire}]
        out = self._retire_fasttrack(state, retire, by="release-train")
        if not retire:
            self.save(state)
        return {"status": "OK", "checked": len(live), "retired": [r["rule_id"] for r in retire],
                "regression_checks": checks, **({"shipped": out} if out else {})}

    def _retire_fasttrack(self, state: dict[str, Any], rows: list[dict[str, Any]], *, by: str) -> dict[str, Any]:
        if not rows:
            return {}
        rules = state.setdefault("fasttrack", {}).setdefault("rules", {})
        at = _iso(self.now())
        for row in rows:
            try:
                self._transition(row["rule_id"], "DEPRECATED", f"RETIRED: {row['reason']}"[:300])
            except svc_mod.ServiceError:
                pass
            state.setdefault("retire_pending", []).append(row["rule_id"])
            state.setdefault("retired", []).append({"rule_id": row["rule_id"], "reason": row["reason"][:300],
                                                    "at": at, "fast_track": True, "by": by})
            rules.setdefault(row["rule_id"], {}).update({"status": "RETIRED", "retired_at": at,
                                                         "retire_reason": row["reason"][:300]})
            self._mark_cluster(state, row["rule_id"], "DEPRECATED", reason=row["reason"][:300])
        shipped: dict[str, Any] = {}
        if self.publisher_key is not None:
            try:
                shipped = self._fasttrack_ship(state, f"fast-track retire: -{len(rows)}")
            except (TrainError, svc_mod.ServiceError, b.BundleError, c.ContractError) as exc:
                shipped = {"status": "ERROR", "code": getattr(exc, "code", type(exc).__name__)}
        self._log(state, "fasttrack_retire", rules=[r["rule_id"] for r in rows],
                  reasons=[r["reason"][:120] for r in rows], by=by, shipped=shipped.get("released_version"))
        self.save(state)
        return shipped

    def fasttrack_kill(self, rule_ids: list[str] | None, reason: str, *, by: str = "operator",
                       all_rules: bool = False) -> dict[str, Any]:
        """Manual kill: retire the named live fast-track rules (or all of them) and republish at once."""
        state = self.state()
        live = self._fasttrack_live_rules(state)
        ids = live if all_rules else [r for r in rule_ids or [] if r in live]
        unknown = [] if all_rules else [r for r in rule_ids or [] if r not in live]
        shipped = self._retire_fasttrack(state, [{"rule_id": r, "reason": f"MANUAL_KILL: {reason}"} for r in ids],
                                         by=by)
        return {"status": "OK", "retired": ids, "not_live": unknown, **({"shipped": shipped} if shipped else {})}

    def fasttrack(self) -> dict[str, Any]:
        """The hourly fast-track step: safety valves first (always), then -- unless killed -- publish any approved
        rule still queued and export newly eligible GLOBAL clusters for the patrol."""
        out: dict[str, Any] = {"at": _iso(self.now()), "active": self.fasttrack_active()}
        steps = [("retire", self.fasttrack_retire)]
        if out["active"]:
            steps += [("publish", self.fasttrack_publish), ("review", self.fasttrack_export)]
        for name, fn in steps:
            try:
                out[name] = fn()
            except (TrainError, svc_mod.ServiceError, b.BundleError, c.ContractError, OSError) as exc:
                out[name] = {"status": "ERROR", "code": getattr(exc, "code", type(exc).__name__),
                             "error": str(exc)[:300]}
        out["summary"] = self.status()
        return out

    def _fasttrack_status(self, state: dict[str, Any]) -> dict[str, Any]:
        ft = state.get("fasttrack") or {}
        rules = ft.get("rules") or {}
        return {"enabled": self.fasttrack_active(), "open_request": state.get("open_fasttrack_review"),
                "live_rules": self._fasttrack_live_rules(state), "rule_cap": int(self.cfg["fasttrack_max_rules"]),
                "queued": list(ft.get("queue") or []),
                "retired": sorted(r for r, row in rules.items() if row.get("status") == "RETIRED")}

    # ------------------------------------------------------------------ 6. 成功样例库
    def exemplar_rows(self) -> list[dict[str, Any]]:
        since = self.now() - float(self.cfg["exemplar_lookback_days"]) * 86400
        rows = []
        for event in self.events(since=since):
            if event.get("event_kind") != "SUCCESS_EXEMPLAR":
                continue
            exemplar = _evidence(event).get("exemplar")
            if isinstance(exemplar, dict):
                rows.append({"exemplar": exemplar, "device_id": event.get("device_id"),
                             "episode_id": event.get("episode_id")})
        return rows

    def curate_exemplars(self, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from . import exemplars as ex_mod  # noqa: PLC0415
        state = state or self.state()
        return ex_mod.curate(self.exemplar_rows(),
                             config={"per_type": int(self.cfg["exemplar_per_type"]),
                                     "practice_per_type": int(self.cfg["exemplar_per_type"]),
                                     "max_exemplars": int(self.cfg["exemplar_max"])},
                             vetoed=(state.get("exemplars") or {}).get("vetoed") or [])

    def _ship_exemplars(self, version: int, label: str, library: list[dict[str, Any]], channels: list[str],
                        note: str) -> dict[str, Any]:
        """Sign the library as ``exemplar_bundle_id@version`` (``rules: []``) and release it on ``channels``."""
        if self.publisher_key is None:
            raise TrainError("PUBLISHER_KEY_UNAVAILABLE")
        bundle_id = str(self.cfg["exemplar_bundle_id"])
        models = sorted({str((e.get("tags") or {}).get("model")) for e in library
                         if (e.get("tags") or {}).get("model") not in (None, "", c.UNKNOWN)} | set(self.cfg["models"]))
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": bundle_id, "version": int(version),
                  "created_at": _iso(self.now()), "release_channel": label,
                  "compat": {"engine_api_versions": list(self.cfg["engine_api_versions"]), "models": models},
                  "rules": [], "exemplars": library}
        key_id, private = self.publisher_key()
        envelope = b.sign_bundle(bundle, key_id=key_id, private_raw=private)
        raw = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self.service.upload_bundle(self.pub, {
            "bundle_id": bundle_id, "version": str(version), "digest": c.sha256_bytes(raw),
            "payload_b64": base64.b64encode(raw).decode("ascii"), "signature_b64": envelope["signature"]["value_b64"],
            "key_id": key_id,
            "manifest": {"scope": {"models": models, "stages": ["SCRIPT_AUTHORING"]}, "rules": [],
                         "exemplars": len(library), "release_train": note[:200]}})
        for channel in channels:
            self.service.release(self.pub, bundle_id=bundle_id, version=str(version), channel=channel, note=note[:200])
        return {"version": int(version), "label": label, "count": len(library), "digest": envelope["digest"],
                "channels": channels, "ids": [e["exemplar_id"] for e in library]}

    def exemplar_step(self) -> dict[str, Any]:
        """Promote a canary library whose veto window passed; otherwise curate and ship a changed library."""
        from . import exemplars as ex_mod  # noqa: PLC0415
        if not self.cfg.get("exemplars_enabled", True):
            return {"status": "DISABLED"}
        state = self.state()
        ex = state.setdefault("exemplars", {})
        packs = ex.setdefault("packs", [])
        now = self.now()
        canary = next((p for p in reversed(packs) if p.get("status") == "CANARY"), None)
        if canary:
            hours = (now - (_epoch(canary.get("canary_at")) or now)) / 3600
            if hours < float(self.cfg["exemplar_canary_hours"]):
                return {"status": "CANARY_IN_FLIGHT", "version": canary["version"], "hours_on_canary": round(hours, 1)}
            version = self._next_version(state, str(self.cfg["exemplar_bundle_id"]))
            shipped = self._ship_exemplars(version, "RELEASED", canary["library"], ["RELEASED", "CANARY"],
                                           f"exemplar library canary {canary['version']} promoted (no veto)")
            canary.update({"status": "PROMOTED", "promoted_as": version, "decided_at": _iso(now)})
            packs.append({**{k: v for k, v in shipped.items() if k != "ids"}, "status": "RELEASED",
                          "created_at": _iso(now), "library": canary["library"], "promoted_from": canary["version"],
                          "digest_library": canary["digest_library"]})
            ex["released_digest"] = canary["digest_library"]
            ex["packs"] = packs[-10:]
            self._log(state, "exemplars_promote", from_version=canary["version"], to_version=version,
                      count=shipped["count"])
            self.save(state)
            return {"status": "PROMOTED", "canary_version": canary["version"], "released_version": version,
                    "count": shipped["count"]}
        gap = float(self.cfg["exemplar_min_interval_hours"]) * 3600
        if any((_epoch(p.get("created_at")) or 0) > now - gap for p in packs if p.get("label") == "CANARY"):
            return {"status": "INTERVAL_NOT_ELAPSED"}
        library = self.curate_exemplars(state)
        digest = ex_mod.library_digest(library)
        released = next((p for p in reversed(packs) if p.get("status") == "RELEASED"), None)
        if digest == ex.get("released_digest") or (not library and released is None):
            return {"status": "UNCHANGED", "count": len(library)}
        before = {e["exemplar_id"] for e in (released or {}).get("library") or []}
        after = {e["exemplar_id"] for e in library}
        version = self._next_version(state, str(self.cfg["exemplar_bundle_id"]))
        shipped = self._ship_exemplars(version, "CANARY", library, ["CANARY"],
                                       f"exemplar library: +{len(after - before)} -{len(before - after)}")
        packs.append({**{k: v for k, v in shipped.items() if k != "ids"}, "status": "CANARY", "created_at": _iso(now),
                      "canary_at": _iso(now), "library": library, "digest_library": digest,
                      "added": sorted(after - before), "removed": sorted(before - after)})
        ex["packs"] = packs[-10:]
        self._log(state, "exemplars_canary", version=version, added=len(after - before), removed=len(before - after))
        self.save(state)
        return {"status": "PUBLISHED_TO_CANARY", "version": version, "count": len(library),
                "added": len(after - before), "removed": len(before - after)}

    def _exemplar_review_section(self, state: dict[str, Any]) -> dict[str, Any] | None:
        """The pending canary library's changes, once per canary pack (never a blocking decision)."""
        from . import exemplars as ex_mod  # noqa: PLC0415
        ex = state.get("exemplars") or {}
        canary = next((p for p in reversed(ex.get("packs") or []) if p.get("status") == "CANARY"), None)
        if not canary or canary.get("reviewed"):
            return None
        by_id = {e["exemplar_id"]: e for e in canary.get("library") or []}
        canary["reviewed"] = True
        return {"bundle": f"{self.cfg['exemplar_bundle_id']}@{canary['version']}", "count": canary.get("count"),
                "promotes_after_hours": float(self.cfg["exemplar_canary_hours"]),
                "note": ("Auto-curated from first-pass units of well-reviewed episodes (privacy-scrubbed on the "
                         "device, re-validated here).  No decision needed; veto entries with exemplar_veto."),
                "added": [ex_mod.summarize(by_id[i]) for i in canary.get("added") or [] if i in by_id][:30],
                "removed": list(canary.get("removed") or [])[:30]}

    def _exemplar_veto(self, state: dict[str, Any], ids: list[str], reason: str, reviewer: str) -> dict[str, Any]:
        ex = state.setdefault("exemplars", {})
        ex["vetoed"] = sorted(set(ex.get("vetoed") or []) | set(ids))[-500:]
        out: dict[str, Any] = {"vetoed": ids, "revoked_canary": None}
        canary = next((p for p in reversed(ex.get("packs") or []) if p.get("status") == "CANARY"), None)
        if canary and set(ids) & {e["exemplar_id"] for e in canary.get("library") or []}:
            try:
                self.service.revoke_bundle(self.pub, bundle_id=str(self.cfg["exemplar_bundle_id"]),
                                           version=str(canary["version"]), reason=f"patrol veto: {reason}"[:300])
            except svc_mod.ServiceError as exc:
                out["revoke_error"] = exc.code
            canary.update({"status": "VETOED", "decided_at": _iso(self.now()), "veto_reason": reason[:300]})
            canary["created_at"] = _iso(0)  # the corrected library may ship on the next step, no interval wait
            out["revoked_canary"] = canary["version"]
        self._log(state, "exemplars_veto", ids=ids, reviewer=reviewer, revoked=out["revoked_canary"])
        return out

    def _exemplar_status(self, state: dict[str, Any]) -> dict[str, Any]:
        packs = (state.get("exemplars") or {}).get("packs") or []
        released = next((p for p in reversed(packs) if p.get("status") == "RELEASED"), None)
        canary = next((p for p in reversed(packs) if p.get("status") == "CANARY"), None)
        return {"bundle_id": self.cfg["exemplar_bundle_id"], "count": (released or {}).get("count") or 0,
                "released_version": (released or {}).get("version"),
                "canary": {"version": canary["version"], "count": canary.get("count"), "since": canary.get("canary_at")}
                if canary else None,
                "vetoed": len((state.get("exemplars") or {}).get("vetoed") or [])}


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
                                        "retire", "register-cohort", "exemplars", "daily", "status", "fasttrack",
                                        "fasttrack-kill"])
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--config", help="JSON overriding DEFAULTS (thresholds, bundle id, models)")
    parser.add_argument("--cohort", help="fleet cohort file {devices: [{device_id, channel}]}")
    parser.add_argument("--status-out", help="also write the status JSON here (the fleet dashboard reads it)")
    parser.add_argument("--result", help="import-review: the review-result JSON")
    parser.add_argument("--replace", action="store_true", help="export-review: replace an open request")
    parser.add_argument("--rule", action="append", default=[], help="fasttrack-kill: a live fast-track rule id")
    parser.add_argument("--all", action="store_true", help="fasttrack-kill: every live fast-track rule")
    parser.add_argument("--reason", default="", help="fasttrack-kill: why (logged)")
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
        elif args.cmd == "exemplars":
            result = train.exemplar_step()
        elif args.cmd == "register-cohort":
            result = {"status": "OK", **train.register_cohort()}
        elif args.cmd == "daily":
            result = {"status": "OK", **train.daily()}
        elif args.cmd == "fasttrack":
            result = {"status": "OK", **train.fasttrack()}
        elif args.cmd == "fasttrack-kill":
            if not args.reason.strip() or not (args.rule or args.all):
                raise TrainError("KILL_NEEDS_RULE_AND_REASON")
            result = train.fasttrack_kill(args.rule, args.reason.strip(), by="operator", all_rules=args.all)
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
