#!/usr/bin/env python3
"""Read-only, standard-library knowledge validation and task-context export.

No provider requests, writes, imports of production submitters or authorizations.
REFERENCE_IMPLEMENTATION means a related source exists, not end-to-end coverage.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "configs/ENGINEERING_KNOWLEDGE_V1.json"
STATUSES = {"REFERENCE_IMPLEMENTATION", "GUIDANCE_ONLY", "INTEGRATION_PENDING"}


def validate(data, root):
    if data.get("schema") != "qingshan.knowledge_registry.v1":
        raise ValueError("KNOWLEDGE_SCHEMA_INVALID")
    if data.get("scope") != "PORTABLE_KNOWLEDGE_NOT_PRODUCTION_AUTHORIZATION":
        raise ValueError("KNOWLEDGE_AUTHORITY_INVALID")
    rows = data.get("rules")
    if not isinstance(rows, list) or not rows:
        raise ValueError("KNOWLEDGE_RULES_EMPTY")
    seen = set()
    root = Path(root).resolve()
    for row in rows:
        key = row.get("id", "")
        if not re.fullmatch(r"K\d{3}", key) or key in seen:
            raise ValueError("KNOWLEDGE_ID_INVALID_OR_DUPLICATE")
        seen.add(key)
        for field in ("stage", "rule", "lesson", "recovery", "owner", "authority"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError("KNOWLEDGE_FIELD_MISSING:" + field)
        if row.get("status") not in STATUSES or row.get("runtime_gate_added") is not False:
            raise ValueError("KNOWLEDGE_FALSE_GATE_CLAIM")
        sources = row.get("implementation")
        if not isinstance(sources, list):
            raise ValueError("KNOWLEDGE_SOURCES_INVALID")
        if row["status"] == "REFERENCE_IMPLEMENTATION" and not sources:
            raise ValueError("KNOWLEDGE_IMPLEMENTATION_EVIDENCE_MISSING")
        for name in sources + [row.get("decision_record"), row.get("regression")]:
            if not isinstance(name, str) or not name:
                raise ValueError("KNOWLEDGE_LINK_MISSING")
            rel = PurePosixPath(name)
            path = root / name
            if (rel.is_absolute() or ".." in rel.parts or "\\" in name
                    or path.is_symlink() or root not in path.resolve().parents):
                raise ValueError("KNOWLEDGE_PATH_UNSAFE")
            if not path.is_file():
                raise ValueError("KNOWLEDGE_LINK_NOT_FOUND:" + name)
    return data


def export_context(data, stage=None):
    stages = {row["stage"] for row in data["rules"]}
    if stage and stage not in stages:
        raise ValueError("KNOWLEDGE_STAGE_UNKNOWN:" + stage)
    rules = [row for row in data["rules"] if not stage or row["stage"] == stage]
    return {
        "schema": "qingshan.knowledge_context.v1",
        "registry_version": data["version"],
        "production_authorization": False,
        "media_qa_pass": False,
        "purpose": "AGENT_AND_DEVELOPER_CONTEXT_ONLY",
        "rules": rules,
        "integration_pending": [row["id"] for row in rules
                                if row["status"] == "INTEGRATION_PENDING"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--stage", help="Export one exact stage; unknown stages fail")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = validate(json.loads((args.root / REGISTRY).read_text()), args.root)
        result = ({"status": "PASS", "scope": "KNOWLEDGE_LINKS_AND_SCHEMA_ONLY",
                   "rule_count": len(data["rules"]), "production_authorization": False}
                  if args.validate else export_context(data, args.stage))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
