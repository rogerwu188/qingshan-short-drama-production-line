import json
import hashlib
import subprocess
import sys
from pathlib import Path


def test_migration_imports_only_verified_rows(tmp_path):
    contract = {"episode": "E59", "character_entities": [
        {"character_id": "a", "canonical_name": "甲", "aliases": ["阿甲"]},
        {"character_id": "b", "canonical_name": "乙", "aliases": []},
    ], "shots": [
        {"prompt_spec": {"dialogue": "阿甲：你好"}},
        {"prompt_spec": {"dialogue": "乙：再见"}},
    ]}
    ref = tmp_path / "a.wav"; ref.write_bytes(b"a")
    legacy = {"major_roles": [{"entity_id": "a", "status": "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY", "remote_asset_id": "asset-a", "local_reference": str(ref), "local_sha256": hashlib.sha256(b"a").hexdigest(), "generation_voice_id": "tts-a"}]}
    c = tmp_path / "c.json"; l = tmp_path / "l.json"; r = tmp_path / "r.json"; cat = tmp_path / "cat.json"; rep = tmp_path / "rep.json"
    c.write_text(json.dumps(contract, ensure_ascii=False)); l.write_text(json.dumps(legacy, ensure_ascii=False))
    tool = Path(__file__).parents[2] / "lines/nalu/runtime/tools/migrate_legacy_voice_registry.py"
    subprocess.run([sys.executable, str(tool), "--contract", str(c), "--legacy-registry", str(l), "--registry-out", str(r), "--catalog-out", str(cat), "--report", str(rep)], check=True)
    out = json.loads(r.read_text())
    assert [(x["entity_id"], x["status"]) for x in out["major_roles"]] == [("a", "LOCKED_PRODUCTION_READY")]
    assert any(x["entity_id"] == "b" for x in json.loads(rep.read_text())["pending"])
    assert json.loads(cat.read_text())["voices"]["a"]["voice_id"] == "tts-a"
