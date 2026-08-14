#!/usr/bin/env python3
"""Reconcile exact Giggle Pay/Refund/Net for the active E37 repair round."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from tools.giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "workflow/tasks/E37_V15_V16_EXACT_CREDIT_RECONCILIATION_20260804.json"

TASKS = [
    ("U03-S1", "ccf876aa-7e62-4e3c-81ad-7d6a7195953e"),
    ("U03-S2", "dca24ba9-c4ce-4c5a-9a81-19c4b58b2fb0"),
    ("U03-S3", "57b93ce3-25fa-42ba-ab64-5bccdf2a1f02"),
    ("U03-S4", "03e5410d-8c2e-43a0-8710-6a04cc58e267"),
    ("U07-S1", "56d856be-835d-41c9-b94f-ef0322b89445"),
    ("U07-S2", "767fa688-b43e-4d51-851b-d3c577b2645d"),
    ("U07-S3", "c0ba239d-3d94-479c-91c9-696572dcca5f"),
    ("U07-S4", "272f297e-0987-4a80-ab02-d2831e3b47e5"),
    ("U07-S5", "88e3d047-2655-4b96-a848-bfd403c1aa0d"),
    ("U07-S6", "b90797a6-1b54-4bd0-96b1-798c2a5b4f10"),
    ("A02A-FAILED-ICE-BUNDLED", "954c4216-f658-4b79-aafb-196896854c83"),
    ("A02A-R2-FAILED-BODY-OVERLAP", "25dda385-473a-496d-abe8-ef58ad2a5342"),
    ("A02A-R3-ACCEPTED", "321a8cf7-7f48-41eb-8cc0-cd96dabb48f4"),
    ("A02B-ICE-SCREEN-RISE", "7eb9ac2b-a219-4ab6-b390-11c29fc73024"),
    ("A02B-TERMINAL-R2", "02b058a0-5be2-43f7-bad5-cb047bbfae5b"),
    ("A02B-R2-FAILED-SUSPENDED-FOOT", "99c2e3d1-76df-4a4e-b64b-b68f734b6504"),
    ("A02B-TERMINAL-R3-STABLE-FEET", "20450159-6569-413a-9b7a-810472f5145e"),
    ("A02B-R3-STABLE-SUPPORT", "21192e48-0d94-4adf-a6cc-70918fc90c83"),
    ("A02C-TERMINAL-R1-FAILED-HAND-CONTACT", "cc0ad335-2cab-4a53-9c6c-bcfdd41201bb"),
    ("A02C-TERMINAL-R2-SHOULDER-ONLY", "9696fd7d-b37a-4f56-a06f-c32674a268e4"),
    ("A02C-SHOULDER-CONTACT", "9e112cea-b3ef-4f95-bd3e-f3a7442b0237"),
    ("A02C-TERMINAL-R3-FAILED", "ed915c1a-4409-4f43-b64f-cd9a7434f244"),
    ("A02C-TERMINAL-R4-FAILED", "b276bb23-234b-4f84-8f40-a2a605c12a61"),
    ("A02C-TERMINAL-R5-PENDING", "4cb49479-719f-4aad-bb7b-73932817676f"),
    ("A02B-TERMINAL-R4-DOORWAY-WALL-PENDING", "0786503e-6925-4bc7-8da3-7261d1fc9b38"),
    ("U03-S1-V16-RETRY", "e9f30434-ea72-494a-952e-9c9a2d6245a5"),
    ("U03-S2-V16-RETRY", "4c28cd25-3eb8-4c75-a73e-d4d8d2f8a2cd"),
    ("U07-S1-V16-RETRY", "b5f0bf52-0033-4cf7-ad20-82fb027c11d6"),
    ("U07-S6-V16-RETRY", "5d011e4e-d40e-4b8a-a9da-833371ed13e7"),
    ("V17-LONG-A-KF03-GUARD-BRACE", "e3c461c8-16ad-4ca0-a301-b5af641861a4"),
    ("V17-LONG-A-KF04-PAPER-CATCH", "bc2c9f15-0a88-4fe6-8f37-8a8b1a820c5e"),
    ("V17-LONG-A-KF05-YUNYANG-WALL-CONTACT", "fbdb0d3d-3174-4812-9afd-1cb2ab9b22d0"),
    ("V17-LONG-A-KF06-HUMAN-SCALE-BREACH", "2a628a1a-246d-47b6-ad59-305264f13859"),
    ("V17-LONG-A-15S-PRO-OMNI", "033e15d7-447b-4d29-be00-7f93e9167f93"),
    ("V17-LONG-B-KF02-LEDGER", "29b8789d-3a48-4866-af12-933e1629cec1"),
    ("V17-LONG-B-KF03-FROST-PATH", "b23f40fe-b8d3-41df-a8cb-a6aa5900caae"),
    ("V17-LONG-B-KF04-CROSSING", "e1e5a6a9-a8c1-4e65-89d2-c4645601ce3a"),
    ("V17-LONG-B-KF05-R1-OVERSIZED-BREACH", "0eedabea-18d3-48f4-86f6-ed3cbd1742c9"),
    ("V17-LONG-B-KF05-R2-EXACT-BREACH", "363261dc-0006-463c-82b4-13d2610e1695"),
    ("V17-LONG-B-KF06-R1-DUPLICATED-LEDGER", "c1595e6f-d119-4823-ba5b-85ae9854a372"),
    ("V17-LONG-B-KF06-R2-UNIQUE-LEDGER", "170b022c-4d96-4ed5-8839-ab8e387b2603"),
    ("V17-LONG-B-15S-PRO-OMNI-R1-HIDDEN-CUT", "7c8e91f2-3763-4368-8d53-9a9f273279b2"),
    ("V17-LONG-B-R2-KF01-R1-SINGLE-REFERENCE", "b5c1e26b-02b0-40bf-8f4f-a1da352bf8be"),
    ("V17-LONG-B-R2-KF02-R1-IDENTITY-CONVERGENCE", "b6f28153-8e21-4448-8b66-612d932043d1"),
    ("V17-LONG-B-R2-KF03-R1-IDENTITY-CONVERGENCE", "217bd454-88d1-4958-912f-a96756ecad53"),
    ("V17-LONG-B-R2-KF01-R2-FOUR-ROLE-REFS", "6433f4af-8929-40e6-92ba-21e030b3da73"),
    ("V17-LONG-B-R2-KF02-R2-FOUR-ROLE-REFS", "fec5a7bd-d475-417f-853e-a6dee69940f8"),
    ("V17-LONG-B-R2-KF03-R2-FOUR-ROLE-REFS", "3cd978af-8cc5-49d5-ac13-fc882bb41e29"),
    ("V17-LONG-B-R2-KF04-R2-FOUR-ROLE-REFS", "8ff57de2-3112-49b4-899f-2d55e86fd320"),
    ("V17-LONG-B-R2-KF05-INWARD-COLLAPSE", "bc411ce5-9bbe-47cc-bfcc-f06fb4d940b4"),
    ("V17-LONG-B-R2-15S-PRO-OMNI-PASS", "5c6f5ddd-10b1-4b90-a1f1-4b372cddd16f"),
]


def statements(task_id: str, credit_type: str) -> list[dict]:
    response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": credit_type, "page": 1, "page_size": 40, "project_id": task_id},
    )
    return (response.get("data") or {}).get("list") or []


def amount(rows: list[dict]) -> int:
    return sum(abs(int(row.get("credit") or 0)) for row in rows)


def main() -> None:
    def reconcile_task(item: tuple[str, str]) -> dict:
        label, task_id = item
        pay_rows = statements(task_id, "Pay")
        refund_rows = statements(task_id, "Refund")
        pay = amount(pay_rows)
        refund = amount(refund_rows)
        return {
            "label": label,
            "task_id": task_id,
            "pay": pay,
            "refund": refund,
            "net": pay - refund,
            "pay_statements": pay_rows,
            "refund_statements": refund_rows,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(reconcile_task, TASKS))
    pay = sum(row["pay"] for row in rows)
    refund = sum(row["refund"] for row in rows)
    payload = {
        "schema": "qingshan.e37.v15_v16_exact_credit_reconciliation.v1",
        "queried_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repair_round_cap": 10000,
        "pay": pay,
        "refund": refund,
        "net": pay - refund,
        "within_cap": pay - refund <= 10000,
        "tasks": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "pay": pay, "refund": refund, "net": pay - refund, "within_cap": payload["within_cap"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
