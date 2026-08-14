#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def verified_roger_override(ref: str | None, audit_text: str, episode: str) -> bool:
    if not ref or not ref.startswith("ROGER-"):
        return False
    match = re.search(
        rf"(?mis)^.*{re.escape(ref)}.*?(?=^## |\Z)",
        audit_text,
    )
    if not match:
        return False
    section = match.group(0)
    return (
        episode.lower() in section.lower()
        and re.search(r"approved|approve|authorize|override|豁免|批准|授权", section, re.IGNORECASE)
        is not None
    )


def evaluate_release_signoff(
    episode: str,
    ci: dict[str, Any],
    watch: dict[str, Any],
    *,
    override_ref: str | None = None,
    audit_text: str = "",
) -> dict[str, Any]:
    ci_pass = ci.get("status") == "PASS"
    watch_status = str(watch.get("status", "MISSING"))
    watch_pass = watch_status.startswith("PASS")
    override_verified = verified_roger_override(override_ref, audit_text, episode)
    failures: list[str] = []
    if not ci_pass and not override_verified:
        failures.append("ci_fail_cannot_be_overridden_by_watch_gate")
    if not watch_pass:
        failures.append(f"watch_gate_not_pass:{watch_status}")
    return {
        "episode": episode,
        "status": "PASS" if not failures else "FAIL",
        "ci_status": ci.get("status"),
        "ci_failures": ci.get("failures", []),
        "watch_status": watch_status,
        "roger_override_ref": override_ref,
        "roger_override_verified": override_verified,
        "failures": failures,
        "rule": (
            "WATCH may reject a CI PASS, but may never convert CI FAIL into release approval. "
            "A CI FAIL override is valid only with a verified Roger authorization reference."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce CI-before-watch release authority.")
    parser.add_argument("--episode", required=True)
    parser.add_argument("--ci-report", required=True)
    parser.add_argument("--watch-report", required=True)
    parser.add_argument("--roger-override-ref")
    parser.add_argument("--approval-audit-file", action="append")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    ci = json.loads(Path(args.ci_report).expanduser().resolve().read_text(encoding="utf-8"))
    watch = json.loads(Path(args.watch_report).expanduser().resolve().read_text(encoding="utf-8"))
    audit_text = "\n".join(
        Path(path).expanduser().resolve().read_text(encoding="utf-8")
        for path in args.approval_audit_file or []
    )
    report = evaluate_release_signoff(
        args.episode,
        ci,
        watch,
        override_ref=args.roger_override_ref,
        audit_text=audit_text,
    )
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
