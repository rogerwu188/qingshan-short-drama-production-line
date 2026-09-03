#!/usr/bin/env python3
"""Fail-closed period-world and visible-element anachronism gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORBIDDEN_VISIBLE_TERMS = (
    "手机",
    "二维码",
    "条形码",
    "塑料瓶",
    "汽车",
    "麦克风",
    "拉链",
    "玻璃罩煤油灯",
    "煤油灯",
    "大盖帽",
    "现代警服",
    "诊所招牌",
    "smartphone",
    "qr code",
    "barcode",
    "plastic bottle",
    "motor car",
    "microphone",
    "zipper",
    "kerosene lamp",
    "modern police uniform",
)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_text(item) for item in value)
    )


def _roger_approval(value: Any) -> bool:
    return _text(value) and str(value).upper().startswith("ROGER-")


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    decisions: list[dict[str, Any]] = []
    contract = payload.get("period_contract")
    if not isinstance(contract, dict):
        failures.append("period_contract_missing")
        contract = {}
    if not _text(contract.get("era")):
        failures.append("period_contract_era_missing")
    if str(contract.get("status") or "").upper() != "PASS":
        failures.append("period_contract_not_pass")
    if not _text_list(contract.get("source_refs")):
        failures.append("period_contract_source_refs_missing")

    units = payload.get("units")
    if not isinstance(units, list) or not units:
        failures.append("period_lock_units_missing")
        units = []

    for index, unit in enumerate(units, start=1):
        unit_id = str(unit.get("unit_id") or f"UNIT_{index}")
        lock = unit.get("period_lock")
        unit_failures: list[str] = []
        if not isinstance(lock, dict):
            unit_failures.append("period_lock_evidence_missing")
            lock = {}
        if str(lock.get("status") or "").upper() != "PASS":
            unit_failures.append("period_lock_not_pass")
        elements = lock.get("reviewed_visible_elements")
        if not _text_list(elements):
            unit_failures.append("reviewed_visible_elements_missing")
            elements = []
        if not _text_list(lock.get("evidence_refs")):
            unit_failures.append("period_lock_evidence_refs_missing")

        declared = lock.get("detected_anachronisms")
        if not isinstance(declared, list):
            unit_failures.append("detected_anachronisms_not_declared")
            declared = []
        elif declared:
            unit_failures.append("detected_anachronisms_present")

        exception_approvals = lock.get("exception_approvals") or {}
        visible_text = "\n".join(str(item).lower() for item in elements)
        for term in FORBIDDEN_VISIBLE_TERMS:
            if term.lower() not in visible_text:
                continue
            approval = exception_approvals.get(term)
            if not _roger_approval(approval):
                unit_failures.append(f"forbidden_visible_element:{term}")

        failures.extend(f"{unit_id}:{item}" for item in unit_failures)
        decisions.append(
            {
                "unit_id": unit_id,
                "status": "PASS" if not unit_failures else "FAIL",
                "failures": unit_failures,
            }
        )

    return {
        "schema": "qingshan.anachronism_lock_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "period_contract": contract,
        "decisions": decisions,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
