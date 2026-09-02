# -*- coding: utf-8 -*-
"""冒烟：每个门能 import；申报门的判据行为正确。"""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "gates", "writer_scene_source_declaration_gate.py")


def run_gate(manifest: dict):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
        p = f.name
    try:
        r = subprocess.run([sys.executable, GATE, p], capture_output=True, text=True)
        return r.returncode, r.stdout
    finally:
        os.unlink(p)


BASE = {
    "episode": "E99", "version": "v1",
    "structure": [{"scene_id": "E99-S01"}, {"scene_id": "E99-S02"}],
    "beat_disposition": [
        {"event_id": "E99-EV-01", "disposition": "landed",
         "landed_at": "E99-S01（三镜）", "summary": "x"}],
    "★authorized_insertions": [],
}


class T(unittest.TestCase):
    def test_all_gates_importable(self):
        d = os.path.join(ROOT, "gates")
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            r = subprocess.run([sys.executable, "-m", "py_compile", os.path.join(d, fn)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{fn} 编译失败: {r.stderr}")

    def test_undeclared_scene_fails(self):
        code, out = run_gate(BASE)          # S02 无源未申报
        self.assertEqual(code, 1)
        self.assertIn("E99-S02", out)

    def test_declared_scene_passes(self):
        m = json.loads(json.dumps(BASE))
        m["★authorized_insertions"] = [{
            "insertion_id": "INS-E99-01", "scene_id": "E99-S02",
            "shots": ["E99-S02-01"], "seconds": 6.0,
            "source_basis": "来自 E98 已落地字节", "new_information": "y",
            "self_deduction": "-1.0 分"}]
        code, out = run_gate(m)
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_upstream_scene_id_is_not_own_declaration(self):
        """插入项里引用上一集场次号，不得被当成本集申报。"""
        m = json.loads(json.dumps(BASE))
        m["★authorized_insertions"] = [{
            "insertion_id": "INS-E99-01", "scene_id": "E98-S07",
            "source_basis": "引用上游 E98-S07", "self_deduction": "-1.0 分"}]
        code, out = run_gate(m)
        self.assertEqual(code, 1, "引用上游场次不应让本集 S02 过门")

    def test_beat_disposition_without_scene_granularity_warns(self):
        m = json.loads(json.dumps(BASE))
        m["beat_disposition"] = {"basis": "x", "landed": ["E99-EV-01"], "merged": []}
        code, out = run_gate(m)
        self.assertIn("BEAT_DISPOSITION_HAS_NO_SCENE_LEVEL_LANDING", out)


if __name__ == "__main__":
    unittest.main()
