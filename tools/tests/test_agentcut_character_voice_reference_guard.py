import hashlib
import json
from pathlib import Path

from tools import agentcut_character_voice_reference_guard as guard


def test_nonexempt_legacy_voice_is_blocked(tmp_path, monkeypatch):
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"voice")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    policy = {"roles": [{"entity_id": "wuyun", "name": "乌云"}]}
    registry = {
        "major_roles": [
            {"entity_id": "chenji", "status": "LOCKED_PRODUCTION_READY", "remote_asset_id": "a"},
            {"entity_id": "baili", "status": "LOCKED_PRODUCTION_READY", "remote_asset_id": "b"},
            {
                "entity_id": "wuyun",
                "status": "LOCKED_PRODUCTION_READY",
                "remote_asset_id": "old",
                "local_reference": str(sample),
                "local_sha256": hashlib.sha256(b"voice").hexdigest(),
                "source_generator": "SEEDANCE_NATIVE",
            },
        ]
    }
    report = guard.evaluate(policy, registry)
    assert report["status"] == "FAIL"
    assert any(row["code"] == "CANONICAL_SOURCE_NOT_AGENTCUT" for row in report["failures"])


def test_agentcut_registered_voice_passes(tmp_path, monkeypatch):
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"voice")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    policy = {"roles": [{"entity_id": "wuyun", "name": "乌云"}]}
    registry = {
        "major_roles": [
            {"entity_id": "chenji", "status": "LOCKED_PRODUCTION_READY", "remote_asset_id": "a"},
            {"entity_id": "baili", "status": "LOCKED_PRODUCTION_READY", "remote_asset_id": "b"},
            {
                "entity_id": "wuyun",
                "status": "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY",
                "remote_asset_id": "new",
                "local_reference": str(sample),
                "local_sha256": hashlib.sha256(b"voice").hexdigest(),
                "source_generator": "AGENTCUT_SPEECH_GENERATION",
                "agentcut_capability": "AGENTCUT-SPEECH-001",
                "generation_task_id": "task",
                "registration_receipt": "registration.json",
                "qa_receipt": "qa.json",
                "credit_status": "UNKNOWN_NOT_ESTIMATED",
            },
        ]
    }
    assert guard.evaluate(policy, registry)["status"] == "PASS"
