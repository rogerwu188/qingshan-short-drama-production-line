import json
from pathlib import Path

ROOT = Path(__file__).parents[2]

def test_portable_artifacts_exist_and_are_redacted():
    paths = [ROOT / "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md", ROOT / "docs/decisions/DECISION_RECORDS.md", ROOT / "examples/handoff/HANDOFF_TEMPLATE.md"]
    assert all(p.is_file() for p in paths)
    text = "\n".join(p.read_text() for p in paths)
    assert "GIGGLE_API_KEY=" not in text and "Bearer " not in text and "task_id" not in text


def test_knowledge_registry_k001_to_k034_exist_and_link_to_repo_files():
    registry_path = ROOT / "configs/ENGINEERING_KNOWLEDGE_V1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    rules = registry["rules"]
    assert [row["id"] for row in rules] == [f"K{i:03d}" for i in range(1, 35)]

    # Every rule must remain discoverable from a clean clone.  Empty
    # implementation lists are intentional for guidance/integration-pending
    # rules, but every declared evidence link must resolve inside this repo.
    for row in rules:
        for field in ("implementation", "decision_record", "regression"):
            values = row[field] if field == "implementation" else [row[field]]
            for relative in values:
                assert relative and not Path(relative).is_absolute()
                assert (ROOT / relative).is_file(), f"{row['id']}: missing {relative}"
