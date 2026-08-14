import threading
import time
import unittest
from unittest.mock import patch

from tools import episode_parallel_batch_supervisor as supervisor


class DependencyLaneConcurrencyTest(unittest.TestCase):
    def test_wave_selects_independent_tasks_and_one_head_per_chain(self):
        tasks = [
            {"task_key": "A2", "generation_schedule_mode": "TAIL_CHAINED_SERIAL", "action_sequence_contract": {"chain_id": "A", "sequence_index": 2}},
            {"task_key": "B1", "generation_schedule_mode": "TAIL_CHAINED_SERIAL", "action_sequence_contract": {"chain_id": "B", "sequence_index": 1}},
            {"task_key": "FREE", "generation_schedule_mode": "INDEPENDENT_PARALLEL"},
            {"task_key": "A1", "generation_schedule_mode": "TAIL_CHAINED_SERIAL", "action_sequence_contract": {"chain_id": "A", "sequence_index": 1}},
        ]

        selected, deferred = supervisor.select_parallel_submission_wave(tasks)

        self.assertEqual({task["task_key"] for task in selected}, {"A1", "B1", "FREE"})
        self.assertEqual([task["task_key"] for task in deferred], ["A2"])

    def test_completed_outputs_enter_qa_concurrently(self):
        receipt = {
            "tasks": [
                {"task_key": "A", "task_id": "ta", "state": "remote_running"},
                {"task_key": "B", "task_id": "tb", "state": "remote_running"},
            ],
            "max_poll_workers": 2,
            "max_qa_workers": 2,
        }
        active = 0
        maximum = 0
        lock = threading.Lock()

        def poll(task):
            return {"task_key": task["task_key"], "remote_status": "completed", "data": {}}

        def harvest(task, result, batch):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.04)
            with lock:
                active -= 1

        with patch.object(supervisor, "poll_one", side_effect=poll), patch.object(supervisor, "settle_credit_attempt"), patch.object(supervisor, "reconcile_completed_image_credits"), patch.object(supervisor, "harvest_completed_task", side_effect=harvest):
            supervisor.poll_and_harvest(receipt)

        self.assertEqual(maximum, 2)


if __name__ == "__main__":
    unittest.main()
