"""HTTP binding of :class:`service.Service` (standard library only).

Routes follow requirement section 8.  Authentication is ``Authorization: Bearer
<token>``.  Every error is ``{"error": {"code", "message", "details"}}`` with a
stable code and status:

  UNAUTHENTICATED 401, FORBIDDEN 403, NOT_FOUND 404, CONFLICT 409,
  BATCH_TOO_LARGE 413, PAYLOAD_INVALID 422, PRECONDITION_REQUIRED 428, INTERNAL 500

The OpenAPI document is generated from the same ``ROUTES`` table the server
dispatches on (``openapi_document``) and checked into
``docs/collective_learning/openapi.json``; a test asserts the two are identical.

``/admin`` pages are read-only, server-rendered and escaped, and require an admin,
publisher or reviewer bearer token.  They show provenance (candidate -> events ->
evidence -> reviews -> bundles -> adoptions), not a score leaderboard.

CLI::

    python -m tools.collective_learning.http_api bootstrap --db svc.sqlite --tenant acme
    python -m tools.collective_learning.http_api serve --db svc.sqlite --port 8787 [--ready-file f]
    python -m tools.collective_learning.http_api openapi --out docs/collective_learning/openapi.json
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

if __package__ in (None, ""):  # allow `python tools/collective_learning/http_api.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.collective_learning"  # noqa: A001

from . import contracts as c  # noqa: E402
from .service import (  # noqa: E402
    BatchTooLarge, NotFound, PayloadInvalid, Principal, Service, ServiceError, Unauthenticated,
)

MAX_BODY_BYTES = 32 * 1024 * 1024
API_VERSION = "1.0.0"
OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "collective_learning" / "openapi.json"

_ID = r"([A-Za-z0-9][A-Za-z0-9._:\-]{0,127})"


class Route:
    def __init__(self, method: str, template: str, handler: str, summary: str, roles: tuple[str, ...],
                 request: str | None = None, response: str = "Object", params: dict[str, str] | None = None):
        self.method, self.template, self.handler, self.summary = method, template, handler, summary
        self.roles, self.request, self.response = roles, request, response
        self.params = params or {}
        names = re.findall(r"\{(\w+)\}", template)
        pattern = re.escape(template)
        for name in names:
            pattern = pattern.replace(re.escape("{" + name + "}"), _ID)
        self.regex = re.compile("^" + pattern + "$")
        self.names = names


ALL = ("device_writer", "reviewer", "publisher", "admin")
ROUTES = [
    Route("POST", "/v1/devices", "register_device", "Register a device or role credential (admin)", ("admin",),
          "DeviceRegistration", "IssuedCredential"),
    Route("POST", "/v1/devices/{principal_id}:rotate", "rotate", "Rotate a credential (admin)", ("admin",),
          None, "IssuedCredential"),
    Route("POST", "/v1/devices/{principal_id}:revoke", "revoke", "Revoke a credential (admin)", ("admin",)),
    Route("POST", "/v1/events:batch", "events_batch", "Batch-upload observation events (idempotent, per-item ack)",
          ("device_writer",), "EventBatch", "BatchResult"),
    Route("POST", "/v1/reviews", "reviews", "Upload attribution reviews (immutable revisions)", ALL,
          "ReviewBatch", "BatchResult"),
    Route("POST", "/v1/candidates", "put_candidate", "Create a candidate, or revise one with If-Match", ALL,
          "CandidatePut", "Candidate"),
    Route("GET", "/v1/candidates/{candidate_id}", "get_candidate", "Read a candidate (returns ETag)", ALL,
          None, "Candidate"),
    Route("POST", "/v1/candidates/{candidate_id}:transition", "transition",
          "Move a candidate through the release state machine (If-Match)", ("reviewer", "publisher", "admin"),
          "Transition", "Candidate"),
    Route("GET", "/v1/candidates/{candidate_id}/sources", "sources",
          "Independent-source count behind a candidate (copies and cloned replays collapsed)", ALL),
    Route("POST", "/v1/bundles", "upload_bundle", "Upload an immutable signed bundle version (publisher)",
          ("publisher", "admin"), "BundleUpload"),
    Route("GET", "/v1/bundles/{bundle_id}/versions/{version}", "get_bundle",
          "Fetch an immutable bundle version with signature and compatibility manifest", ALL, None, "Bundle"),
    Route("POST", "/v1/bundles:resolve", "resolve", "Resolve exact bundle versions applicable to capabilities",
          ALL, "ResolveRequest", "ResolveResult"),
    Route("POST", "/v1/releases", "release", "Point a channel (CANARY/RELEASED) at a bundle version (publisher)",
          ("publisher", "admin"), "Release"),
    Route("POST", "/v1/revocations", "revocation", "Revoke a bundle version; channels fall back (publisher)",
          ("publisher", "admin"), "Revocation"),
    Route("POST", "/v1/adoptions:batch", "adoptions", "Upload adoption receipts (idempotent)",
          ("device_writer", "reviewer", "admin"), "AdoptionBatch", "BatchResult"),
    Route("POST", "/v1/evaluations", "evaluations", "Upload episode evaluations (idempotent)",
          ("device_writer", "reviewer", "admin"), "EvaluationBatch", "BatchResult"),
    Route("POST", "/v1/evidence", "register_evidence", "Register evidence metadata (bytes stay in object storage)",
          ALL, "Evidence"),
    Route("DELETE", "/v1/evidence/{evidence_id}", "delete_evidence",
          "Mark evidence deleted; dependent candidates lose promotion eligibility", ALL),
    Route("GET", "/v1/health", "health", "Liveness and schema version (no auth)", ()),
    Route("GET", "/v1/sync-status", "sync_status", "Per-credential sync counters (no secrets)", ALL),
    Route("GET", "/v1/failures", "failures", "Quarantined items with diagnostic codes", ALL),
    Route("GET", "/v1/openapi.json", "openapi", "This OpenAPI document (no auth)", ()),
    Route("GET", "/admin", "admin_index", "Read-only admin overview (HTML)", ("reviewer", "publisher", "admin"),
          None, "Html"),
    Route("GET", "/admin/candidates/{candidate_id}", "admin_candidate",
          "Read-only candidate traceability page (HTML)", ("reviewer", "publisher", "admin"), None, "Html"),
]


# --------------------------------------------------------------------------- OpenAPI
def _schemas() -> dict[str, Any]:
    obj = {"type": "object"}
    string_list = {"type": "array", "items": {"type": "string"}}
    ack = {"type": "object", "required": ["id", "status", "codes"], "properties": {
        "id": {"type": ["string", "null"]},
        "status": {"type": "string", "enum": ["CREATED", "DUPLICATE", "CONFLICT", "REJECTED"]},
        "codes": string_list, "content_sha": {"type": "string"}}}
    return {
        "Object": obj,
        "Html": {"type": "string"},
        "Error": {"type": "object", "required": ["error"], "properties": {"error": {
            "type": "object", "required": ["code", "message"], "properties": {
                "code": {"type": "string", "enum": ["UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND", "CONFLICT",
                                                     "BATCH_TOO_LARGE", "PAYLOAD_INVALID", "PRECONDITION_REQUIRED",
                                                     "INTERNAL"]},
                "message": {"type": "string"}, "details": {}}}}},
        "DeviceRegistration": {"type": "object", "required": ["principal_id", "role"], "properties": {
            "principal_id": {"type": "string"}, "role": {"type": "string", "enum": list(ALL)},
            "line_ids": string_list, "canary": {"type": "boolean"}}},
        "IssuedCredential": {"type": "object", "properties": {
            "principal_id": {"type": "string"}, "token": {"type": "string",
                                                          "description": "shown once; stored as sha256 only"}}},
        "ObservationEvent": {"type": "object", "description": "contracts.validate_observation is authoritative",
                             "required": ["schema_version", "event_id", "tenant_id", "line_id", "device_id", "run_id",
                                          "episode_id", "stage", "event_kind", "occurred_at", "producer_sequence",
                                          "engine_version", "provider_model_version", "knowledge_bundle_digest",
                                          "detected_by", "evidence", "symptom", "visibility"],
                             "properties": {"event_id": {"type": "string", "format": "uuid"},
                                            "event_kind": {"type": "string", "enum": list(c.EVENT_KINDS)},
                                            "visibility": {"type": "string", "enum": ["LINE", "TENANT"]},
                                            "source_event_id": {"type": "string", "format": "uuid"}},
                             "not": {"anyOf": [{"required": [k]} for k in sorted(c.FORBIDDEN_OBSERVATION_KEYS)]}},
        "EventBatch": {"type": "object", "required": ["events"], "properties": {
            "events": {"type": "array", "items": {"$ref": "#/components/schemas/ObservationEvent"}}}},
        "ReviewBatch": {"type": "object", "required": ["reviews"], "properties": {
            "reviews": {"type": "array", "items": obj}}},
        "AdoptionBatch": {"type": "object", "required": ["receipts"], "properties": {
            "receipts": {"type": "array", "items": obj}}},
        "EvaluationBatch": {"type": "object", "required": ["evaluations"], "properties": {
            "evaluations": {"type": "array", "items": obj}}},
        "ItemAck": ack,
        "BatchResult": {"type": "object", "required": ["results"], "properties": {
            "results": {"type": "array", "items": {"$ref": "#/components/schemas/ItemAck"}}}},
        "CandidatePut": {"type": "object", "required": ["candidate"], "properties": {
            "candidate": obj, "origin_line_id": {"type": "string"}},
            "description": "contracts.validate_candidate is authoritative; revisions need If-Match"},
        "Candidate": {"type": "object", "properties": {
            "candidate_id": {"type": "string"}, "revision": {"type": "integer"},
            "state": {"type": "string", "enum": list(c.RELEASE_STATES)}, "etag": {"type": "string"},
            "validation_scopes": string_list, "evidence_status": {"type": "string"},
            "promotion_eligible": {"type": "boolean"}, "payload": obj}},
        "Transition": {"type": "object", "required": ["to"], "properties": {
            "to": {"type": "string", "enum": list(c.RELEASE_STATES)},
            "validation_scope": {"type": "string", "enum": list(c.VALIDATION_SCOPES)}, "note": {"type": "string"}}},
        "BundleUpload": {"type": "object", "required": ["bundle_id", "version", "digest", "payload_b64",
                                                        "signature_b64", "key_id", "manifest"], "properties": {
            "bundle_id": {"type": "string"}, "version": {"type": "string"},
            "digest": {"type": "string", "description": "sha256 of the decoded payload"},
            "payload_b64": {"type": "string"}, "signature_b64": {"type": "string"}, "key_id": {"type": "string"},
            "manifest": {"type": "object", "required": ["scope"]}}},
        "Bundle": {"type": "object", "properties": {
            "bundle_id": {"type": "string"}, "version": {"type": "string"}, "digest": {"type": "string"},
            "payload_b64": {"type": "string"}, "signature_b64": {"type": "string"}, "key_id": {"type": "string"},
            "manifest": obj, "revoked": {"type": ["object", "null"]}}},
        "ResolveRequest": {"type": "object", "required": ["capabilities"], "properties": {
            "capabilities": {"type": "object", "description": "only the capability tags scope matching needs",
                             "properties": {k: {"type": "string"} for k in c.SCOPE_TO_CAPABILITY.values()}},
            "channels": {"type": "array", "items": {"type": "string", "enum": ["CANARY", "RELEASED"]}}}},
        "ResolveResult": {"type": "object", "properties": {
            "bundles": {"type": "array", "items": {"type": "object", "properties": {
                "bundle_id": {"type": "string"}, "channel": {"type": "string"}, "version": {"type": "string"},
                "digest": {"type": "string"}}}},
            "not_applicable": {"type": "array", "items": obj}, "revocations": {"type": "array", "items": obj}}},
        "Release": {"type": "object", "required": ["bundle_id", "version", "channel"], "properties": {
            "bundle_id": {"type": "string"}, "version": {"type": "string"},
            "channel": {"type": "string", "enum": ["CANARY", "RELEASED"]}, "note": {"type": "string"}}},
        "Revocation": {"type": "object", "required": ["bundle_id", "version", "reason"], "properties": {
            "bundle_id": {"type": "string"}, "version": {"type": "string"}, "reason": {"type": "string"}}},
        "Evidence": {"type": "object", "required": ["sha256", "storage_key"], "properties": {
            "evidence_id": {"type": "string"}, "sha256": {"type": "string"}, "storage_key": {"type": "string"},
            "visibility": {"type": "string", "enum": ["LINE", "TENANT"]}, "retention_until": {"type": "string"},
            "candidate_ids": string_list, "event_ids": string_list}},
    }


def openapi_document() -> dict[str, Any]:
    errors = {"401": "UNAUTHENTICATED", "403": "FORBIDDEN", "404": "NOT_FOUND", "409": "CONFLICT",
              "413": "BATCH_TOO_LARGE", "422": "PAYLOAD_INVALID", "428": "PRECONDITION_REQUIRED"}
    paths: dict[str, Any] = {}
    for route in ROUTES:
        op: dict[str, Any] = {
            "operationId": route.handler, "summary": route.summary,
            "x-allowed-roles": list(route.roles),
            "responses": {"200": {"description": "OK", "content": {
                "text/html" if route.response == "Html" else "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{route.response}"}}}}},
        }
        if route.roles:
            op["security"] = [{"bearer": []}]
            for status, code in errors.items():
                op["responses"][status] = {"description": code, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Error"}}}}
        else:
            op["security"] = []
        if route.names:
            op["parameters"] = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
                                for n in route.names]
        if route.handler in ("put_candidate", "transition"):
            op.setdefault("parameters", []).append({"name": "If-Match", "in": "header", "required": False,
                                                    "schema": {"type": "string"},
                                                    "description": "required to revise or transition"})
        if route.request:
            op["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": {"$ref": f"#/components/schemas/{route.request}"}}}}
        paths.setdefault(route.template, {})[route.method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "Qingshan collective learning service", "version": API_VERSION,
                 "description": "Facts, attribution, candidates, signed knowledge bundles, adoption and evaluation "
                                "receipts shared across production lines. Generated from http_api.ROUTES."},
        "servers": [{"url": "/"}],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
                       "schemas": _schemas()},
        "paths": paths,
    }


# --------------------------------------------------------------------------- server
class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256

    def __init__(self, address: tuple[str, int], service: Service):
        self.service = service
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: ApiServer

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet; the audit log is the record
        return

    # ------------------------------------------------------------------ io
    def _send(self, status: int, body: Any, *, content_type: str = "application/json",
              headers: dict[str, str] | None = None) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, err: ServiceError) -> None:
        self._send(err.http_status, {"error": {"code": err.code, "message": err.message, "details": err.details}})

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise BatchTooLarge("request body too large", {"max_bytes": MAX_BODY_BYTES})
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise PayloadInvalid("body is not JSON") from exc

    def _principal(self) -> Principal:
        auth = self.headers.get("Authorization") or ""
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else None
        try:
            return self.server.service.authenticate(token)
        except Unauthenticated as err:
            self.server.service.audit_denial(None, f"{self.command} {urlsplit(self.path).path}", None, err)
            raise

    def _dispatch(self) -> None:
        path = unquote(urlsplit(self.path).path)
        for route in ROUTES:
            if route.method != self.command:
                continue
            match = route.regex.match(path)
            if not match:
                continue
            args = dict(zip(route.names, match.groups()))
            try:
                principal = self._principal() if route.roles else None
                getattr(self, "h_" + route.handler)(principal, **args)
            except ServiceError as err:
                self._error(err)
            except Exception as exc:  # noqa: BLE001 -- never leak a traceback to a client
                self._error(ServiceError(f"internal error: {type(exc).__name__}"))
            return
        self._error(NotFound(f"no route {self.command} {path}"))

    do_GET = do_POST = do_DELETE = _dispatch  # noqa: N815

    @property
    def svc(self) -> Service:
        return self.server.service

    def _batch(self, key: str) -> Any:
        body = self._body()
        if not isinstance(body, dict) or key not in body:
            raise PayloadInvalid(f"body must be an object with '{key}'")
        return body[key]

    # ------------------------------------------------------------------ handlers
    def h_register_device(self, p: Principal) -> None:
        body = self._body()
        self._send(200, self.svc.register_principal(p, principal_id=body.get("principal_id", ""),
                                                    role=body.get("role", ""), line_ids=body.get("line_ids"),
                                                    canary=bool(body.get("canary"))))

    def h_rotate(self, p: Principal, principal_id: str) -> None:
        self._send(200, self.svc.rotate_credential(p, principal_id))

    def h_revoke(self, p: Principal, principal_id: str) -> None:
        self._send(200, self.svc.revoke_credential(p, principal_id))

    def h_events_batch(self, p: Principal) -> None:
        self._send(200, {"results": self.svc.ingest_events(p, self._batch("events"))})

    def h_reviews(self, p: Principal) -> None:
        self._send(200, {"results": self.svc.ingest_reviews(p, self._batch("reviews"))})

    def h_put_candidate(self, p: Principal) -> None:
        body = self._body()
        if not isinstance(body, dict) or not isinstance(body.get("candidate"), dict):
            raise PayloadInvalid("body must be {candidate: {...}}")
        rec = self.svc.put_candidate(p, body["candidate"], if_match=self.headers.get("If-Match"),
                                     origin_line_id=body.get("origin_line_id"))
        self._send(200, rec, headers={"ETag": rec["etag"]})

    def h_get_candidate(self, p: Principal, candidate_id: str) -> None:
        rec = self.svc.get_candidate(p, candidate_id)
        self._send(200, rec, headers={"ETag": rec["etag"]})

    def h_transition(self, p: Principal, candidate_id: str) -> None:
        body = self._body()
        rec = self.svc.transition_candidate(p, candidate_id, to=str(body.get("to") or ""),
                                            if_match=self.headers.get("If-Match"),
                                            validation_scope=body.get("validation_scope"), note=body.get("note", ""))
        self._send(200, rec, headers={"ETag": rec["etag"]})

    def h_sources(self, p: Principal, candidate_id: str) -> None:
        self._send(200, self.svc.independent_sources(p, candidate_id))

    def h_upload_bundle(self, p: Principal) -> None:
        self._send(200, self.svc.upload_bundle(p, self._body()))

    def h_get_bundle(self, p: Principal, bundle_id: str, version: str) -> None:
        self._send(200, self.svc.get_bundle(p, bundle_id, version))

    def h_resolve(self, p: Principal) -> None:
        body = self._body()
        self._send(200, self.svc.resolve(p, body.get("capabilities") or {}, channels=body.get("channels")))

    def h_release(self, p: Principal) -> None:
        body = self._body()
        self._send(200, self.svc.release(p, bundle_id=str(body.get("bundle_id") or ""),
                                         version=str(body.get("version") or ""),
                                         channel=str(body.get("channel") or ""), note=body.get("note", "")))

    def h_revocation(self, p: Principal) -> None:
        body = self._body()
        self._send(200, self.svc.revoke_bundle(p, bundle_id=str(body.get("bundle_id") or ""),
                                               version=str(body.get("version") or ""),
                                               reason=str(body.get("reason") or "")))

    def h_adoptions(self, p: Principal) -> None:
        self._send(200, {"results": self.svc.ingest_adoptions(p, self._batch("receipts"))})

    def h_evaluations(self, p: Principal) -> None:
        self._send(200, {"results": self.svc.ingest_evaluations(p, self._batch("evaluations"))})

    def h_register_evidence(self, p: Principal) -> None:
        self._send(200, self.svc.register_evidence(p, self._body()))

    def h_delete_evidence(self, p: Principal, evidence_id: str) -> None:
        self._send(200, self.svc.delete_evidence(p, evidence_id))

    def h_health(self, p: None) -> None:
        self._send(200, self.svc.health())

    def h_sync_status(self, p: Principal) -> None:
        self._send(200, self.svc.sync_status(p))

    def h_failures(self, p: Principal) -> None:
        self._send(200, self.svc.failures(p))

    def h_openapi(self, p: None) -> None:
        self._send(200, openapi_document())

    # ------------------------------------------------------------------ admin (read-only HTML)
    def _page(self, title: str, body: str) -> None:
        doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
               "<meta name='viewport' content='width=device-width, initial-scale=1'>"
               "<style>body{font:14px system-ui,sans-serif;margin:16px;max-width:1100px}"
               "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:4px 6px;"
               "text-align:left;vertical-align:top}code{font-size:12px;word-break:break-all}"
               "h2{margin-top:24px}.muted{color:#666}</style></head><body>"
               f"<h1>{html.escape(title)}</h1>{body}</body></html>")
        self._send(200, doc, content_type="text/html")

    @staticmethod
    def _table(headers: list[str], rows: list[list[Any]]) -> str:
        esc = html.escape
        head = "".join(f"<th>{esc(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{cell if isinstance(cell, _Raw) else esc(str(cell))}</td>"
                                        for cell in row) + "</tr>" for row in rows)
        return f"<table><tr>{head}</tr>{body or '<tr><td colspan=99 class=muted>none</td></tr>'}</table>"

    def h_admin_index(self, p: Principal) -> None:
        cands = self.svc.list_candidates(p)
        status = self.svc.sync_status(p)
        rows = [[_Raw(f"<a href='/admin/candidates/{html.escape(x['candidate_id'])}'>"
                      f"{html.escape(x['candidate_id'])}</a>"), x["revision"], x["state"], x["category"],
                 ", ".join(x["validation_scopes"]), x["evidence_status"]] for x in cands]
        devices = [[d["principal_id"], d["role"], ", ".join(d["line_ids"]), d["status"], d["last_seen"] or "",
                    d["accepted"], d["duplicates"], d["rejected"]] for d in status["principals"]]
        self._page(f"Collective learning — {p.tenant_id}",
                   "<p class=muted>Read-only. Each candidate links to its sources, evidence, reviews, bundle "
                   "versions and adoptions. No ranking is computed here.</p>"
                   "<h2>Candidates</h2>" + self._table(["candidate", "rev", "state", "category", "validation scopes",
                                                        "evidence"], rows)
                   + "<h2>Credentials and sync</h2>" + self._table(
                       ["principal", "role", "lines", "status", "last seen", "accepted", "duplicates", "rejected"],
                       devices))

    def h_admin_candidate(self, p: Principal, candidate_id: str) -> None:
        trace = self.svc.trace_candidate(p, candidate_id)
        cand = trace["candidate"]
        esc = html.escape
        events = [[e["event_id"], e["line_id"], e["device_id"], e["episode_id"], e["stage"], e["event_kind"],
                   e["symptom"], e["source_event_id"] or "",
                   "; ".join(f"v{r.get('review_version')} {r.get('status')} {r.get('root_cause_hypothesis') or r.get('reason') or ''}"
                             for r in e["reviews"])] for e in trace["events"]]
        evidence = [[x["evidence_id"], x["sha256"], x["storage_key"], x["visibility"], x["retention_until"] or "",
                     x["deleted_at"] or "available"] for x in trace["evidence"]]
        bundles = [[b["bundle_id"], b["version"], b["digest"], ", ".join(b["channels"]) or "-",
                    (b["revoked"] or {}).get("reason", "")] for b in trace["bundles"]]
        adoptions = [[a.get("receipt_id"), a.get("line_id"), a.get("device_id"), a.get("run_id"), a.get("state"),
                      a.get("rule_version"), a.get("evidence_scope", ""),
                      (a.get("outcome") or {}).get("kind", "")] for a in trace["adoptions"]]
        history = [[h["at"], h["action"], h["from_state"] or "", h["to_state"], h["revision"], h["actor"],
                    json.dumps(h["detail"], ensure_ascii=False)] for h in trace["history"]]
        src = trace["independent_sources"]
        self._page(f"Candidate {candidate_id}",
                   f"<p><a href='/admin'>&larr; overview</a></p><p>state <b>{esc(cand['state'])}</b>, revision "
                   f"{cand['revision']}, evidence {esc(cand['evidence_status'])}, validation "
                   f"{esc(', '.join(cand['validation_scopes']) or 'none')}, independent sources "
                   f"{src['independent_sources']} (copies collapsed {src['copies_collapsed']}, identical replays "
                   f"collapsed {src['identical_replays_collapsed']})</p>"
                   f"<h2>Candidate payload</h2><pre><code>{esc(json.dumps(cand['payload'], ensure_ascii=False, indent=2))}"
                   "</code></pre><h2>History</h2>" + self._table(
                       ["at", "action", "from", "to", "rev", "actor", "detail"], history)
                   + "<h2>Source events and attribution</h2>" + self._table(
                       ["event", "line", "device", "episode", "stage", "kind", "symptom", "copy of", "reviews"], events)
                   + "<h2>Evidence</h2>" + self._table(
                       ["evidence", "sha256", "storage key", "visibility", "retention", "status"], evidence)
                   + "<h2>Bundle versions</h2>" + self._table(
                       ["bundle", "version", "digest", "channels", "revoked"], bundles)
                   + "<h2>Adoption and outcomes</h2>" + self._table(
                       ["receipt", "line", "device", "run", "state", "rule rev", "evidence scope", "outcome"],
                       adoptions))


class _Raw(str):
    """A table cell that is already escaped HTML."""


def _admin_guard(fn: Callable[..., None]) -> Callable[..., None]:
    def wrapper(self: Handler, p: Principal, **kw: Any) -> None:
        from .service import Forbidden
        if p.role not in ("reviewer", "publisher", "admin"):
            err = Forbidden("admin pages need reviewer, publisher or admin")
            self.server.service.audit_denial(p, "admin", None, err)
            raise err
        fn(self, p, **kw)
    return wrapper


Handler.h_admin_index = _admin_guard(Handler.h_admin_index)  # type: ignore[method-assign]
Handler.h_admin_candidate = _admin_guard(Handler.h_admin_candidate)  # type: ignore[method-assign]


def start_server(service: Service, host: str = "127.0.0.1", port: int = 0) -> tuple[ApiServer, threading.Thread]:
    """Serve in a daemon thread; returns (server, thread).  ``server.server_address[1]`` is the port."""
    server = ApiServer((host, port), service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="collective learning HTTP service")
    sub = parser.add_subparsers(dest="cmd", required=True)
    boot = sub.add_parser("bootstrap", help="create a tenant and print its first admin token (once)")
    boot.add_argument("--db", required=True)
    boot.add_argument("--tenant", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--db", required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--max-batch", type=int, default=500)
    serve.add_argument("--ready-file", help="write the bound port here once listening")
    spec = sub.add_parser("openapi")
    spec.add_argument("--out", default=str(OPENAPI_PATH))
    args = parser.parse_args(argv)
    if args.cmd == "openapi":
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(openapi_document(), ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        print(args.out)
        return 0
    service = Service(args.db, max_batch=getattr(args, "max_batch", 500))
    if args.cmd == "bootstrap":
        print(json.dumps(service.bootstrap_tenant(args.tenant), ensure_ascii=False))
        return 0
    server = ApiServer((args.host, args.port), service)
    if args.ready_file:
        Path(args.ready_file).write_text(str(server.server_address[1]), encoding="utf-8")
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
