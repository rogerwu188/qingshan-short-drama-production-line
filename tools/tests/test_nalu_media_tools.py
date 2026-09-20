from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
if str(NALU_TOOLS) not in sys.path:
    sys.path.insert(0, str(NALU_TOOLS))

import nalu_media_tools as media  # noqa: E402


class NaluMediaToolResolutionTests(unittest.TestCase):
    @staticmethod
    def executable(folder: Path, name: str) -> Path:
        path = folder / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_qingshan_override_wins_over_nalu_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chosen = self.executable(root, "chosen-ffmpeg")
            other = self.executable(root, "other-ffmpeg")
            path, source = media.resolve_media_tool(
                "ffmpeg",
                environ={
                    "QINGSHAN_FFMPEG": str(chosen),
                    "NALU_FFMPEG": str(other),
                },
                which=lambda _name: str(other),
                legacy_paths=(),
            )
            self.assertEqual(Path(path), chosen.resolve())
            self.assertEqual(source, "QINGSHAN_FFMPEG")

    def test_nalu_override_supports_linux_style_install_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # mkdir explicitly so this remains a normal POSIX bin layout rather
            # than depending on a Homebrew prefix.
            bin_dir = Path(tmp) / "usr" / "bin"
            bin_dir.mkdir(parents=True)
            binary = self.executable(bin_dir, "ffprobe")
            path, source = media.resolve_media_tool(
                "ffprobe",
                environ={"NALU_FFPROBE": str(binary)},
                which=lambda _name: None,
                legacy_paths=(),
            )
            self.assertEqual(Path(path), binary.resolve())
            self.assertEqual(source, "NALU_FFPROBE")

    def test_path_is_used_before_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_binary = self.executable(root, "path-ffmpeg")
            legacy_binary = self.executable(root, "legacy-ffmpeg")
            path, source = media.resolve_media_tool(
                "ffmpeg",
                environ={},
                which=lambda name: str(path_binary) if name == "ffmpeg" else None,
                legacy_paths=(legacy_binary,),
            )
            self.assertEqual(Path(path), path_binary.resolve())
            self.assertEqual(source, "PATH")

    def test_existing_legacy_path_is_last_resort_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy_binary = self.executable(Path(tmp), "ffmpeg")
            path, source = media.resolve_media_tool(
                "ffmpeg", environ={}, which=lambda _name: None,
                legacy_paths=(legacy_binary,),
            )
            self.assertEqual(Path(path), legacy_binary.resolve())
            self.assertEqual(source, "LEGACY_EXISTING_PATH")

    def test_invalid_explicit_override_blocks_instead_of_falling_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path_binary = self.executable(Path(tmp), "ffmpeg")
            with self.assertRaisesRegex(media.MediaToolBlocked, "^BLOCKED_MEDIA_TOOL:ffmpeg"):
                media.resolve_media_tool(
                    "ffmpeg",
                    environ={"QINGSHAN_FFMPEG": "/missing/deployment/ffmpeg"},
                    which=lambda _name: str(path_binary),
                    legacy_paths=(),
                )

    def test_missing_binary_fails_closed_with_actionable_blocker(self) -> None:
        with self.assertRaisesRegex(
            media.MediaToolBlocked,
            "BLOCKED_MEDIA_TOOL:ffprobe: executable unavailable; set QINGSHAN_FFPROBE/NALU_FFPROBE",
        ):
            media.resolve_media_tool(
                "ffprobe", environ={}, which=lambda _name: None, legacy_paths=(),
            )

    def test_cjk_font_explicit_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected = root / "selected.ttc"
            selected.write_bytes(b"test-font-placeholder")
            fallback = root / "fallback.ttc"
            fallback.write_bytes(b"test-font-placeholder")
            path, source = media.resolve_cjk_font(
                environ={"QINGSHAN_CJK_FONT": str(selected)},
                candidates=(fallback,),
            )
            self.assertEqual(Path(path), selected.resolve())
            self.assertEqual(source, "QINGSHAN_CJK_FONT")

    def test_cjk_font_uses_existing_linux_or_mac_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "NotoSansCJK-Regular.ttc"
            candidate.write_bytes(b"test-font-placeholder")
            path, source = media.resolve_cjk_font(environ={}, candidates=(candidate,))
            self.assertEqual(Path(path), candidate.resolve())
            self.assertEqual(source, "COMMON_EXISTING_PATH")

    def test_invalid_cjk_font_override_blocks_instead_of_using_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "NotoSansCJK-Regular.ttc"
            fallback.write_bytes(b"test-font-placeholder")
            with self.assertRaisesRegex(media.MediaToolBlocked, "^BLOCKED_CJK_FONT:"):
                media.resolve_cjk_font(
                    environ={"NALU_CJK_FONT": "/missing/NotoSansCJK-Regular.ttc"},
                    candidates=(fallback,),
                )

    def test_missing_cjk_font_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            media.MediaToolBlocked,
            "BLOCKED_CJK_FONT:no CJK font found",
        ):
            media.resolve_cjk_font(environ={}, candidates=())

    def test_runtime_callers_do_not_embed_homebrew_binary_paths(self) -> None:
        callers = (
            "nalu_pipeline.py",
            "nalu_qa_common.py",
            "library_lock_non_plate.py",
            "build_burnin_subtitles.py",
            "nalu_selective_bgm.py",
            "final_cut_shot_plan_parity.py",
            "review_fill/video_sheets.py",
        )
        for relative in callers:
            text = (NALU_TOOLS / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertNotIn("/opt/homebrew/bin/ffmpeg", text)
                self.assertNotIn("/opt/homebrew/bin/ffprobe", text)
        subtitle_builder = (NALU_TOOLS / "build_burnin_subtitles.py").read_text(encoding="utf-8")
        self.assertNotIn("/System/Library/Fonts/", subtitle_builder)


if __name__ == "__main__":
    unittest.main()
