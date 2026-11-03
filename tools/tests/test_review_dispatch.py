import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
import review_dispatch as rd  # noqa: E402


def make_request(path: Path, n: int) -> dict:
    req = {"schema": "nalu.vlm_review_request.v1", "request_id": "E99-video_q2-T", "kind": "video_q2", "episode": "E99",
           "created_at": "2026-01-01T00:00:00Z", "questionnaire": {"q": {"enum": ["PASS", "FAIL"]}},
           "answer_rules": {"min_observation_chars": 20},
           "items": [{"item_id": f"E99-VU-{i:03d}", "expectations": {"x": i}, "media": []} for i in range(1, n + 1)]}
    path.write_text(json.dumps(req), encoding="utf-8")
    return req


def make_answers(items):
    return {"schema": rd.ANSWERS_SCHEMA, "items": [{"item_id": i, "answers": {"q": "PASS"}, "observation": "x" * 30, "defects": []} for i in items]}


class ReviewDispatchTest(unittest.TestCase):
    def test_shards_carry_only_their_items_and_the_shared_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = make_request(Path(tmp, "r.json"), 5)
            shards = rd.shard_request(req, items_per_shard=2)
            self.assertEqual([s["item_count"] for s in shards], [2, 2, 1])
            self.assertEqual(shards[0]["questionnaire"], req["questionnaire"])
            self.assertEqual(shards[2]["shard"]["item_ids"], ["E99-VU-005"])

    def test_merge_refuses_missing_or_duplicate_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "r.json"); make_request(p, 3)
            with self.assertRaises(ValueError):
                rd.merge_answers(p, [make_answers(["E99-VU-001", "E99-VU-002"])], reviewer="t")
            with self.assertRaises(ValueError):
                rd.merge_answers(p, [make_answers(["E99-VU-001", "E99-VU-002"]), make_answers(["E99-VU-002", "E99-VU-003"])], reviewer="t")
            merged = rd.merge_answers(p, [make_answers(["E99-VU-002"]), make_answers(["E99-VU-001", "E99-VU-003"])], reviewer="t")
            self.assertEqual([it["item_id"] for it in merged["items"]], ["E99-VU-001", "E99-VU-002", "E99-VU-003"])
            self.assertEqual(merged["request_sha256"], rd.sha256_file(p))

    def test_replay_run_parallel_is_faster_than_serial_and_merges_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "r.json"); make_request(p, 8)
            replay = Path(tmp, "a.json"); replay.write_text(json.dumps(make_answers([f"E99-VU-{i:03d}" for i in range(1, 9)])), encoding="utf-8")
            t0 = time.monotonic()
            serial = rd.run(p, Path(tmp, "w1"), workers=1, items_per_shard=1, worker_cmd=None, replay=replay,
                            replay_latency_ms=50, reviewer="t", timeout=10)
            t_serial = time.monotonic() - t0
            t0 = time.monotonic()
            par = rd.run(p, Path(tmp, "w4"), workers=4, items_per_shard=1, worker_cmd=None, replay=replay,
                         replay_latency_ms=50, reviewer="t", timeout=10)
            t_par = time.monotonic() - t0
            self.assertEqual(len(par["items"]), 8)
            self.assertEqual(serial["items"], par["items"])
            self.assertLess(t_par, t_serial * 0.6, (t_serial, t_par))

    def test_worker_cmd_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "r.json"); make_request(p, 2)
            script = Path(tmp, "w.py")
            script.write_text("import json,sys\nsh=json.load(open(sys.argv[1]))\n"
                              "json.dump({'items':[{'item_id':i['item_id'],'answers':{'q':'PASS'},'observation':'y'*30,'defects':[]} for i in sh['items']]},open(sys.argv[2],'w'))\n",
                              encoding="utf-8")
            merged = rd.run(p, Path(tmp, "w"), workers=2, items_per_shard=1,
                            worker_cmd=f"{sys.executable} {script} {{shard}} {{out}}", replay=None,
                            replay_latency_ms=0, reviewer="t", timeout=30)
            self.assertEqual(merged["dispatch"]["mode"], "WORKER_CMD")
            self.assertEqual(len(merged["items"]), 2)


if __name__ == "__main__":
    unittest.main()
