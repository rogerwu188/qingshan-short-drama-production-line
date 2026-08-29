import unittest
from pathlib import Path


class FullPerformanceAudioResumeTest(unittest.TestCase):
    def test_completed_transaction_rehydrates_wav_into_execution_receipt(self) -> None:
        source = Path("tools/execute_e40_full_performance_audio_refs.py").read_text(encoding="utf-8")
        self.assertIn('if tx.get("state") == "TERMINAL_COMPLETED_DOWNLOADED":', source)
        self.assertIn('"wav": wav, "wav_sha256": wav_sha256', source)
        self.assertIn("COMPLETED_TRANSACTION_OUTPUT_MISSING", source)

    def test_bound_completed_retry_can_replace_failed_canonical_audio_file(self) -> None:
        source = Path("tools/execute_e40_full_performance_audio_refs.py").read_text(encoding="utf-8")
        self.assertIn("_download(urls[0], mp3, overwrite=True)", source)
        self.assertIn("newly bound task is authoritatively completed", source)


if __name__ == "__main__":
    unittest.main()
