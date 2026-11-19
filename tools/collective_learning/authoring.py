"""Collective knowledge at the AUTHORING stage: the 「本集导演经验」 section of Codex's episode start prompt.

Until now locked rules reached only the provider (H3/SD2) video prompts at S2 compile, and the S1 knowledge
briefing was written but never read by the author.  Codex writes the dispatch, the narrative canon, the script
layers, the storyboard and every shot ``prompt_spec`` before S1 runs, so the knowledge has to be in its start
prompt.  ``codex_production.start`` calls:

  :func:`prepare`         runs the line-upgrade preflight early (engine freshness, the S1 briefing, the run
                          knowledge lock -- written once per run, so S1 later keeps exactly this snapshot), then
                          builds the section from the locked knowledge:
                            * DIRECTING_GUIDANCE rules whose scope matches the episode (stage SCRIPT_AUTHORING
                              / S1 / S2, model, language, genre); RELEASED, plus CANARY on a canary device
                              (the lock already resolved the device's channel);
                            * 2-3 exemplars from the signed 成功样例库 bundle (language required; genre, model and
                              the previous episode's scene types preferred);
                            * a pointer to the S1 briefing file.
                          Hard cap ``MAX_SECTION_CHARS``; no money, gates, authority or secrets (the bundle
                          validator and CONTROL_LANGUAGE already refuse those, checked again here).
  :func:`record_applied`  after the launch: an APPLIED adoption receipt per injected rule (clause present in
                          the prompt sent, absent from the same prompt without the section -- the same evidence
                          the video path records), NOT_APPLICABLE/DEFERRED for the rest, and
                          ``<reports>/<EP>_AUTHORING_GUIDANCE.json`` for knowledge_status.

Inert without ``COLLECTIVE_LEARNING_CONFIG.json``; with no applicable rule and no exemplar the section is empty
and the prompt is byte-identical to before.  Every failure is returned as a status, never raised.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):  # `python tools/collective_learning/authoring.py` (codex_production runs it so)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.collective_learning"  # noqa: A001

from . import adoption, bundles, contracts as c, exemplars as ex_mod, selection  # noqa: E402

GUIDANCE_SCHEMA = "qingshan.collective.authoring_guidance.v1"
AUTHORING_STAGE = "SCRIPT_AUTHORING"
#: scope.stages values that mean "the author's script/storyboard stage"
AUTHORING_STAGES = ("SCRIPT_AUTHORING", "STORYBOARD_AUTHORING", "S1", "S2")
ENTRYPOINT = "codex_production.start"
CARRIER_FIELD = "codex_start_prompt.本集导演经验"
MAX_SECTION_CHARS = 1500
MAX_RULES = 5
RULE_LINE_MAX = 200
#: characters kept free for 参考写法 when the library has matching exemplars
EXEMPLAR_RESERVE = 560
SECTION_TITLE = "## 本集导演经验"
CONFIG_NAME = "COLLECTIVE_LEARNING_CONFIG.json"
SCENE_PROFILE = "EXEMPLAR_SCENE_PROFILE.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def reports_dir(rt: Path) -> Path:
    """line_upgrade_gate._reports for the pipeline's ``RT`` (= ``<runtime>/runtime``)."""
    rt = Path(rt)
    if (rt / "runtime").is_dir():
        return rt / "runtime" / "reports"
    return rt / "reports"


def _episode_key(name: str) -> tuple[int, str]:
    digits = "".join(ch for ch in name if ch.isdigit())
    return (int(digits) if digits else 0, name)


def episode_profile(runtime: Path, episode: str) -> dict[str, str]:
    """Language and genre of the episode: its own production brief, else the newest earlier one (the next
    episode copies those clauses verbatim from the previous brief)."""
    briefs = Path(runtime) / "briefs"
    brief = _read(briefs / f"{episode}_PRODUCTION_BRIEF.json")
    if not brief and briefs.is_dir():
        earlier = sorted((p for p in briefs.glob("*_PRODUCTION_BRIEF.json")
                          if _episode_key(p.name.split("_")[0]) < _episode_key(episode)),
                         key=lambda p: _episode_key(p.name.split("_")[0]))
        brief = _read(earlier[-1]) if earlier else {}
    language = str(brief.get("dialogue_language") or brief.get("genre_lang") or "").strip().lower()
    return {"language": language, "genre": str(brief.get("genre") or "").strip()}


def scene_hints(reports: Path) -> dict[str, dict[str, int]]:
    """Scene-type counts of the latest episode that reached S7 (written by the exemplar capture hook)."""
    data = _read(Path(reports) / SCENE_PROFILE)
    hints = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    return {k: {str(t): int(n) for t, n in v.items() if isinstance(n, int)}
            for k, v in hints.items() if isinstance(v, dict)}


# --------------------------------------------------------------------------- rule choice
def _clause_text(rule: dict[str, Any], language: str) -> str:
    clause = (rule.get("application") or {}).get("prompt_clause") or {}
    code = str(language or "").strip().lower()[:2]
    # Japanese / Korean (2026-11-18): their own clause, else the English one (a Chinese clause is not a
    # directing note a ja / ko writer acts on), Chinese last
    order = (("en", "zh") if language == "en" else (code, "en", "zh") if code in ("ja", "ko")
             else ("zh", "en"))
    return next((str(clause[k]).strip() for k in order if isinstance(clause.get(k), str) and clause[k].strip()), "")


def directing_rules(rules: list[dict[str, Any]], caps: dict[str, Any]) -> tuple[list[dict[str, Any]],
                                                                                list[dict[str, Any]]]:
    """(applicable rows ranked, decisions for the directing rules that are not applicable).

    Only DIRECTING_GUIDANCE rules are considered; video-prompt carriers stay with the S2 compile path."""
    rows: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    genre = ex_mod.genre_key(caps.get("genre"))
    for rule in rules:
        if (rule.get("application") or {}).get("carrier") not in bundles.AUTHORING_CARRIERS:
            continue
        base = {"rule_id": rule["rule_id"], "rule_version": rule["rule_version"],
                "bundle_digest": rule.get("_bundle_digest") or "NONE"}
        scope = dict(rule.get("scope") or {})
        stages = set(scope.pop("stages", None) or [])
        if not stages & set(AUTHORING_STAGES):
            decisions.append({**base, "state": "NOT_APPLICABLE", "reason": f"OUT_OF_SCOPE:stage={AUTHORING_STAGE}"})
            continue
        if scope.get("genres"):
            scope["genres"] = [ex_mod.genre_key(g) for g in scope["genres"]]
        ok, reasons = c.scope_matches(scope, {**caps, "genre": genre or c.UNKNOWN})
        if not ok:
            decisions.append({**base, "state": "NOT_APPLICABLE", "reason": ";".join(reasons)[:300]})
            continue
        text = _clause_text(rule, str(caps.get("language") or "zh"))
        if not text:
            decisions.append({**base, "state": "DEFERRED", "reason": "CLAUSE_MISSING"})
            continue
        if selection.CONTROL_LANGUAGE.search(text) or c.sensitive_findings(text):
            decisions.append({**base, "state": "FAILED", "reason": "CONTROL_LANGUAGE_IN_CLAUSE_NOT_APPLIED"})
            continue
        exceptions = [str(x).strip() for x in rule.get("exceptions") or [] if str(x).strip()]
        exception = exceptions[0] if exceptions else ""
        if exception and (selection.CONTROL_LANGUAGE.search(exception) or c.sensitive_findings(exception)):
            exception = ""
        rows.append({**base, "clause": text, "exception": exception[:60],
                     "rank": selection._rank(rule, caps)})  # noqa: SLF001 -- same ranking as the video path
    rows.sort(key=lambda r: r["rank"])
    return rows, decisions


# --------------------------------------------------------------------------- rendering
def _rule_line(row: dict[str, Any]) -> str:
    """The clause verbatim (the APPLIED receipt proves exactly this text is in the prompt); the exception only
    when the line stays short."""
    line = f"- {row['clause']}" + (f"（例外：{row['exception']}）" if row.get("exception") else "")
    return line if len(line) <= RULE_LINE_MAX else f"- {row['clause']}"


def render_section(*, rules: list[dict[str, Any]], exemplars: list[dict[str, Any]], briefing: str | None,
                   label: str, cap: int = MAX_SECTION_CHARS) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]],
                                                                       list[dict[str, Any]]]:
    """(section text, rules used, exemplars used, rules deferred by the cap).  Empty text when nothing fits."""
    head = [f"{SECTION_TITLE}（集体知识库 {label}；学做法，不抄内容）",
            "写派单、叙事正典、剧本、分镜和每个镜头的 prompt_spec 之前先读完本节"
            + (f"，并打开本集 S1 知识简报 `{briefing}`（要避免的失败原因，开工时已写好）。" if briefing else "。")]
    body: list[str] = []
    used_rules: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    used_ex: list[dict[str, Any]] = []

    def size(lines: list[str]) -> int:
        return len("\n".join(head + lines))

    rule_header = "导演规则（照此写；与线主派单冲突时以派单为准）："
    rule_cap = cap - (EXEMPLAR_RESERVE if exemplars else 0)  # rules never crowd the exemplars out entirely
    for row in rules[:MAX_RULES]:
        if len(row["clause"]) > RULE_LINE_MAX - 2:
            deferred.append({**row, "state": "DEFERRED", "reason": f"CLAUSE_TOO_LONG:{len(row['clause'])}"})
            continue
        candidate = body + ([rule_header] if not used_rules else []) + [_rule_line(row)]
        if size(candidate) <= rule_cap:
            body = candidate
            used_rules.append(row)
        else:
            deferred.append({**row, "state": "DEFERRED", "reason": f"SECTION_CHAR_CAP:{cap}"})
    deferred.extend({**row, "state": "DEFERRED", "reason": f"SECTION_RULE_CAP:{MAX_RULES}"} for row in rules[MAX_RULES:])
    ex_header = "参考写法（他机首过 Q1/Q2、终审高分的镜头与做法；角色名已换成角色A/B，学结构与分寸）："
    for ex in exemplars:
        candidate = body + ([ex_header] if not used_ex else []) + [ex_mod.render_line(ex)]
        if size(candidate) <= cap:
            body = candidate
            used_ex.append(ex)
    if not used_rules and not used_ex:
        return "", [], [], deferred
    return "\n".join(head + body), used_rules, used_ex, deferred


# --------------------------------------------------------------------------- prepare / record
def _default_preflight(engine: Path, rt: Path, line: str, episode: str) -> dict[str, Any]:
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("_authoring_line_upgrade_gate", engine / "tools" / "line_upgrade_gate.py")
    lug = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lug)  # the engine's own gate (the same file S1 runs)
    return lug.preflight(line, episode, rt, engine)


def prepare(*, engine: Path, runtime: Path, episode: str, line: str = "nalu",
            preflight: Callable[[Path, Path, str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the section for ``episode``.  ``{"status": READY, "section": ...}`` or a status with no section."""
    try:
        rt = Path(runtime) / "runtime"
        reports = reports_dir(rt)
        config_path = reports / CONFIG_NAME
        if not config_path.is_file():
            return {"status": "INACTIVE", "reason": f"no {CONFIG_NAME}", "section": ""}
        config = _read(config_path)
        receipt = (preflight or _default_preflight)(Path(engine), rt, line, episode)
        collective = receipt.get("collective") if isinstance(receipt, dict) else None
        if not isinstance(collective, dict) or collective.get("status") != "LOCKED":
            return {"status": "NOT_LOCKED", "section": "",
                    "detail": (collective or {}).get("status") if isinstance(collective, dict) else None}
        from . import runtime_wiring  # noqa: PLC0415
        env = {k: str(v) for k, v in (collective.get("child_env") or {}).items()}
        run = runtime_wiring.active(env)
        if run is None or run.verify()["status"] != "PASS":
            return {"status": "LOCK_NOT_VERIFIED", "section": ""}
        profile = episode_profile(Path(runtime), episode)
        caps_cfg = config.get("capabilities") if isinstance(config.get("capabilities"), dict) else {}
        language = profile["language"] or str(caps_cfg.get("language") or "zh")
        if language[:2] in ("ja", "ko"):  # "ja-jp" / "ko-kr" briefs match rules scoped to "ja" / "ko"
            language = language[:2]
        caps = {"model": caps_cfg.get("model") or c.UNKNOWN, "engine_api_version": run.api, "stage": AUTHORING_STAGE,
                "language": language, "genre": profile["genre"], "flags": []}
        rules, decisions = directing_rules(run.rules(), caps)
        library = bundles.locked_exemplars(run.lock_path, run.cache)
        chosen = ex_mod.select_for_episode(library, language=language, genre=profile["genre"],
                                           model=str(caps["model"]), scene_hints=scene_hints(reports),
                                           config=config.get("exemplars") if isinstance(config.get("exemplars"),
                                                                                       dict) else None)
        knowledge = receipt.get("knowledge") if isinstance(receipt.get("knowledge"), dict) else {}
        # the <= 5 KB short briefing when preflight wrote one (Codex cost 2026-11-16), else the full one
        briefing = None
        if knowledge.get("status") == "READ":
            for key in ("briefing_short_md", "briefing_md"):
                if knowledge.get(key) and Path(knowledge[key]).is_file():
                    briefing = knowledge[key]
                    break
        labels = sorted({f"{b.get('bundle_id')}@{b.get('version')} {b.get('release_channel')}"
                         for b in collective.get("bundles") or []})
        section, used_rules, used_ex, deferred = render_section(rules=rules, exemplars=chosen, briefing=briefing,
                                                                label="、".join(labels) or "locked")
        return {"status": "READY" if section else "NO_KNOWLEDGE", "section": section, "episode": episode,
                "language": language, "genre": profile["genre"], "rules": used_rules,
                "decisions": decisions + deferred, "exemplar_ids": [e["exemplar_id"] for e in used_ex],
                "exemplar_bundles": sorted({e.get("_bundle") for e in used_ex if e.get("_bundle")}),
                "library_size": len(library), "briefing": briefing, "env": env, "reports": str(reports),
                "lock": run.ref}
    except Exception as exc:  # noqa: BLE001 -- knowledge must never stop an episode from starting
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:300]}", "section": ""}


def record_applied(prepared: dict[str, Any], *, prompt_with: str, prompt_without: str) -> dict[str, Any]:
    """APPLIED receipts for the rules the sent prompt carries + the guidance record.  Never raises.

    A restart of the same episode with the identical section does not record the receipts a second time."""
    try:
        if prepared.get("status") != "READY" or not prepared.get("section"):
            return {"status": "NOTHING_INJECTED"}
        from . import runtime_wiring  # noqa: PLC0415
        reports = Path(prepared["reports"])
        episode = str(prepared["episode"])
        section_sha = hashlib.sha256(prepared["section"].encode("utf-8")).hexdigest()
        path = reports / f"{episode}_AUTHORING_GUIDANCE.json"
        previous = _read(path)
        if previous.get("section_sha256") == section_sha and previous.get("status") == "INJECTED":
            previous.update({"restarts": int(previous.get("restarts") or 0) + 1, "last_injected_at": _now()})
            path.write_text(json.dumps(previous, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            return {"status": "ALREADY_RECORDED", "guidance": str(path)}
        run = runtime_wiring.active(prepared["env"])
        ident = run.identity()
        unit_ids = [episode] if c.is_identifier(episode) else []
        source = {"episode": episode, "section_sha256": section_sha, "stage": AUTHORING_STAGE,
                  "rule_ids": [r["rule_id"] for r in prepared.get("rules") or []],
                  "exemplar_ids": prepared.get("exemplar_ids") or []}
        receipts: list[dict[str, Any]] = []
        applied_ids: list[str] = []
        for row in prepared.get("rules") or []:
            rule = {"rule_id": row["rule_id"], "rule_version": row["rule_version"]}
            try:
                receipts.append(adoption.applied(
                    identity=ident, rule=rule, stage=AUTHORING_STAGE, unit_ids=unit_ids, entrypoint=ENTRYPOINT,
                    bundle_digest=row.get("bundle_digest") or "NONE", clause=row["clause"], source_contract=source,
                    compiled_with=prompt_with, compiled_without=prompt_without, carrier_fields=[CARRIER_FIELD]))
                applied_ids.append(row["rule_id"])
            except c.ContractError as exc:
                receipts.append(adoption.not_adopted(identity=ident, rule=rule, stage=AUTHORING_STAGE,
                                                     unit_ids=unit_ids, entrypoint=ENTRYPOINT,
                                                     bundle_digest=row.get("bundle_digest") or "NONE",
                                                     state="FAILED", reason=";".join(exc.codes)[:300]))
        for row in prepared.get("decisions") or []:
            receipts.append(adoption.not_adopted(identity=ident, rule={"rule_id": row["rule_id"],
                                                                       "rule_version": row["rule_version"]},
                                                 stage=AUTHORING_STAGE, unit_ids=unit_ids, entrypoint=ENTRYPOINT,
                                                 bundle_digest=row.get("bundle_digest") or "NONE",
                                                 state=row["state"], reason=str(row.get("reason") or "-")[:300]))
        run.record(receipts)
        record = {"schema": GUIDANCE_SCHEMA, "episode": episode, "status": "INJECTED", "injected_at": _now(),
                  "section_sha256": section_sha, "chars": len(prepared["section"]),
                  "rule_ids": applied_ids, "exemplar_ids": prepared.get("exemplar_ids") or [],
                  "exemplar_bundles": prepared.get("exemplar_bundles") or [],
                  "library_size": prepared.get("library_size"), "briefing": prepared.get("briefing"),
                  "language": prepared.get("language"), "genre": prepared.get("genre"),
                  "lock": prepared.get("lock"), "receipt_ids": [r["receipt_id"] for r in receipts], "restarts": 0}
        reports.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return {"status": "RECORDED", "guidance": str(path), "applied": applied_ids, "receipts": len(receipts)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:300]}"}


# --------------------------------------------------------------------------- CLI (run with the engine venv)
def main(argv: list[str] | None = None) -> int:
    """``prepare --engine-root E --runtime-root R --episode EP --out prepared.json`` /
    ``record --prepared prepared.json --prompt-with a.md --prompt-without b.md``.  One JSON line on stdout."""
    ap = argparse.ArgumentParser(prog="authoring")
    ap.add_argument("cmd", choices=["prepare", "record"])
    ap.add_argument("--engine-root", type=Path)
    ap.add_argument("--runtime-root", type=Path)
    ap.add_argument("--episode")
    ap.add_argument("--line", default="nalu")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--prepared", type=Path)
    ap.add_argument("--prompt-with", type=Path)
    ap.add_argument("--prompt-without", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        out = prepare(engine=a.engine_root, runtime=a.runtime_root, episode=a.episode, line=a.line)
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({k: out.get(k) for k in ("status", "reason", "error", "detail")} | {
            "chars": len(out.get("section") or ""), "rules": [r["rule_id"] for r in out.get("rules") or []],
            "exemplars": out.get("exemplar_ids") or []}, ensure_ascii=False))
        return 0
    prepared = _read(a.prepared) if a.prepared else {}
    out = record_applied(prepared, prompt_with=a.prompt_with.read_text(encoding="utf-8"),
                         prompt_without=a.prompt_without.read_text(encoding="utf-8"))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
