from pathlib import Path

from tools.episode_launch_job_closer import matching_labels, verify_final_lock


def test_matching_labels_are_episode_scoped():
    labels = [
        "ai.qingshan.e33.agentcut.v1",
        "ai.qingshan.e33.video.r2",
        "ai.qingshan.e32.agentcut.v1",
        "com.nalumotion.qingshan.chrome-restart",
    ]
    assert matching_labels("E33", labels) == [
        "ai.qingshan.e33.agentcut.v1",
        "ai.qingshan.e33.video.r2",
    ]


def test_non_final_receipt_is_blocked(tmp_path: Path):
    final = tmp_path / "candidate.mp4"
    final.write_bytes(b"candidate")
    _, failures = verify_final_lock("E33", {
        "episode": "E33",
        "status": "ACTIVE",
        "final": str(final),
        "final_sha256": "wrong",
    })
    assert "receipt_not_final_locked" in failures
    assert "final_sha256_mismatch" in failures


def test_episode_mismatch_is_blocked(tmp_path: Path):
    final = tmp_path / "candidate.mp4"
    final.write_bytes(b"candidate")
    _, failures = verify_final_lock("E34", {
        "episode": "E33",
        "status": "FINAL_LOCKED_S3_AND_PLATFORM_ASYNC",
        "final": str(final),
        "final_sha256": "wrong",
    })
    assert "receipt_episode_mismatch" in failures
