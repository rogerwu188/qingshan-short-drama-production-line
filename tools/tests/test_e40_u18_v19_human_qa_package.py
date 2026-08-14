import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v19_human_qa_package import EXPECTED, HUMAN_TEMPLATE, OUTPUT_GATE, ROOT, compile_human_qa_package


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path) -> tuple[Path, Path]:
    for relative, _ in (OUTPUT_GATE, HUMAN_TEMPLATE):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    assets = []
    for task_id, expected in EXPECTED.items():
        output = root / "outputs" / f"{task_id}.png"
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(("synthetic-output-" + task_id).encode())
        assets.append({
            "asset_id": expected["asset_id"],
            "exact_task_id": task_id,
            "transaction_fingerprint": expected["fingerprint"],
            "output_path": str(output.relative_to(root)),
            "output_sha256": sha(output),
            "dimensions": {"width": 1024, "height": 1024},
            "provenance": "exact synthetic output fixture",
            "license_or_local_authorship": "locally authored test fixture",
            "output_mask_path": None,
            "output_mask_sha256": None,
        })
    promotion = {
        "schema": "qingshan.e40.u18.v17.output_machine_promotion_manifest.v1",
        "status": "READY_FOR_EXISTING_U18_OUTPUT_MACHINE_QA_NO_ADMISSION",
        "scope": "U18_ONLY",
        "assets": assets,
        "output_admission_permitted": False,
        "assembly_permitted": False,
        "video_authorization_permitted": False,
    }
    promotion_path = root / "v17_promotion.json"
    promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
    machine = {
        "schema": "qingshan.e40.u18.isolated_asset_output_gate.v1",
        "status": "PASS_MACHINE_OUTPUT_GATE_REQUIRES_HUMAN_QA_NO_AUTO_ADMISSION",
        "manifest_sha256": sha(promotion_path),
        "failures": [],
        "automatic_admission": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    machine_path = root / "machine_result.json"
    machine_path.write_text(json.dumps(machine), encoding="utf-8")
    return promotion_path, machine_path


class HumanQaPackageTest(unittest.TestCase):
    def test_machine_pass_compiles_two_scale_no_admission_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promotion, machine = fixture(root)
            result = compile_human_qa_package(promotion, machine, root)
            self.assertEqual(result["status"], "HUMAN_QA_PACKAGE_READY_NO_ADMISSION")
            self.assertEqual(len(result["human_qa_manifest"]["assets"]), 2)
            self.assertEqual([x["name"] for x in result["human_qa_manifest"]["assets"][0]["review_layers"]], ["ORIGINAL_RESOLUTION", "AUDIENCE_SCALE_720X1280"])
            self.assertEqual(result["human_qa_manifest"]["review_policy"]["layers"][1]["name"], "AUDIENCE_SCALE_720X1280")
            self.assertFalse(result["output_admission_permitted"])
            self.assertFalse(result["composite_permitted"])
            self.assertFalse(result["video_authorization_permitted"])

    def test_machine_fail_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promotion, machine = fixture(root)
            row = json.loads(machine.read_text())
            row["status"] = "FAIL_CLOSED_OUTPUT_GATE"
            row["failures"] = ["fixture failure"]
            machine.write_text(json.dumps(row))
            self.assertEqual(compile_human_qa_package(promotion, machine, root)["status"], "TASK_LOCAL_REMOTE_WAIT")

    def test_stale_machine_promotion_sha_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promotion, machine = fixture(root)
            row = json.loads(machine.read_text())
            row["manifest_sha256"] = "0" * 64
            machine.write_text(json.dumps(row))
            result = compile_human_qa_package(promotion, machine, root)
            self.assertIn("OUTPUT_MACHINE_STALE_OR_WRONG_PROMOTION_SHA", result["failures"])
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")

    def test_output_sha_drift_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promotion, machine = fixture(root)
            row = json.loads(promotion.read_text())
            row["assets"][0]["output_sha256"] = "f" * 64
            promotion.write_text(json.dumps(row))
            machine_row = json.loads(machine.read_text())
            machine_row["manifest_sha256"] = sha(promotion)
            machine.write_text(json.dumps(machine_row))
            result = compile_human_qa_package(promotion, machine, root)
            self.assertTrue(any("OUTPUT_SHA_MISMATCH" in failure for failure in result["failures"]))
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")

    def test_rights_missing_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promotion, machine = fixture(root)
            row = json.loads(promotion.read_text())
            row["assets"][1]["license_or_local_authorship"] = ""
            promotion.write_text(json.dumps(row))
            machine_row = json.loads(machine.read_text())
            machine_row["manifest_sha256"] = sha(promotion)
            machine.write_text(json.dumps(machine_row))
            result = compile_human_qa_package(promotion, machine, root)
            self.assertTrue(any("RIGHTS_MISSING" in failure for failure in result["failures"]))
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")


if __name__ == "__main__":
    unittest.main()
