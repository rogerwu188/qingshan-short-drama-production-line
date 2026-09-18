#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/durable_rename.py 的测试（F-R530-01）。

断言分两层：

1. **行为层**（负对照会红的那些）：`durable_replace` 确实对**父目录**调了 fsync，
   且次序是 `replace` 在前、目录 fsync 在后。把函数体换回裸 `os.replace`，这些必红。
2. **不可让步约束**：目录 fsync 失败**永不**改变调用方看到的控制流 —— 目标件已经
   是新字节，异常不外泄。这一条比 ① 更重要：它保证本次改动不会把一次成功的提交
   翻成失败。
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import durable_rename  # noqa: E402
from durable_rename import durable_replace, fsync_directory  # noqa: E402


class _Sandbox(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _staged(self, name: str = "target.json", body: str = "new\n"):
        target = self.root / name
        temporary = self.root / f".{name}.tmp"
        temporary.write_text(body, encoding="utf-8")
        return temporary, target


class DurableReplaceFsyncsTheDirectoryTests(_Sandbox):
    """①行为层：改名之后目录项也落盘。"""

    def _record_fsync(self):
        recorded: list[int] = []
        real_fsync = os.fsync

        def spy(fd):
            recorded.append(fd)
            return real_fsync(fd)

        self._patch(os, "fsync", spy)
        return recorded

    def _patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, original)

    def test_directory_is_fsynced_after_replace(self):
        temporary, target = self._staged()
        order: list[str] = []
        real_replace = os.replace
        real_fsync = os.fsync

        def replace_spy(src, dst):
            order.append("replace")
            return real_replace(src, dst)

        def fsync_spy(fd):
            order.append("fsync")
            return real_fsync(fd)

        self._patch(os, "replace", replace_spy)
        self._patch(os, "fsync", fsync_spy)

        self.assertTrue(durable_replace(temporary, target))
        # replace 必须在前：目录项还没改就刷目录毫无意义。
        self.assertEqual(order, ["replace", "fsync"])

    def test_the_fsynced_descriptor_is_the_parent_directory(self):
        temporary, target = self._staged()
        seen: list[str] = []
        real_fsync = os.fsync

        def fsync_spy(fd):
            # /proc 在本沙盒可用；退化时用 fstat 的目录位判定。
            mode = os.fstat(fd).st_mode
            seen.append("dir" if os.path.stat.S_ISDIR(mode) else "file")
            return real_fsync(fd)

        self._patch(os, "fsync", fsync_spy)
        durable_replace(temporary, target)
        self.assertIn("dir", seen)

    def test_bytes_and_commit_semantics_are_unchanged(self):
        temporary, target = self._staged(body="payload-bytes\n")
        target.write_text("old\n", encoding="utf-8")
        durable_replace(temporary, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "payload-bytes\n")
        self.assertFalse(temporary.exists())

    def test_replace_failure_still_propagates(self):
        """replace 自身失败＝提交没发生，异常必须原样上抛（调用方要跑清理阶梯）。"""
        missing = self.root / "nope.tmp"
        with self.assertRaises(OSError):
            durable_replace(missing, self.root / "target.json")


class DirectoryFsyncNeverChangesControlFlowTests(_Sandbox):
    """②不可让步：刷目录失败不得把一次成功的提交翻成异常。"""

    def _patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, original)

    def test_fsync_oserror_is_swallowed_and_the_commit_stands(self):
        temporary, target = self._staged(body="committed\n")
        real_fsync = os.fsync

        def failing_fsync(fd):
            mode = os.fstat(fd).st_mode
            if os.path.stat.S_ISDIR(mode):
                raise OSError(22, "fsync not supported on this directory")
            return real_fsync(fd)

        self._patch(os, "fsync", failing_fsync)

        # 不抛异常，返回 False，而字节已经提交。
        self.assertFalse(durable_replace(temporary, target))
        self.assertEqual(target.read_text(encoding="utf-8"), "committed\n")

    def test_open_oserror_is_swallowed(self):
        def failing_open(path, flags, *args):
            raise OSError(13, "permission denied")

        self._patch(os, "open", failing_open)
        self.assertFalse(fsync_directory(self.root))

    def test_missing_directory_returns_false_without_raising(self):
        self.assertFalse(fsync_directory(self.root / "does-not-exist"))

    def test_descriptor_is_closed_even_when_fsync_fails(self):
        closed: list[int] = []
        real_close = os.close
        real_fsync = os.fsync

        def close_spy(fd):
            closed.append(fd)
            return real_close(fd)

        def failing_fsync(fd):
            mode = os.fstat(fd).st_mode
            if os.path.stat.S_ISDIR(mode):
                raise OSError(22, "nope")
            return real_fsync(fd)

        self._patch(os, "close", close_spy)
        self._patch(os, "fsync", failing_fsync)

        self.assertFalse(fsync_directory(self.root))
        self.assertEqual(len(closed), 1, "目录 fd 必须关闭，否则失败路径会漏 fd")


class SingleImplementationIsActuallyUsedTests(unittest.TestCase):
    """③五处原子写共用这一处实现 —— 防的正是「同族风险抄五份、漏掉一处」。

    fsync 那次漏的偏偏是保护其余四处的 singleflight 闸；这组断言让下一次漂移
    在测试里先红，而不是在崩溃后才发现。
    """

    CALL_SITES = {
        "writer_singleflight_lock.py": ("durable_replace",),
        "canonical_writer_dispatcher.py": ("durable_replace", "fsync_directory"),
        "episode_stage_gate_runner.py": ("durable_replace",),
        "gate_result_contract.py": ("durable_replace",),
    }

    def test_every_writer_line_atomic_write_imports_the_shared_helper(self):
        tools = pathlib.Path(__file__).resolve().parents[1]
        for filename, expected in self.CALL_SITES.items():
            source = (tools / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn("from durable_rename import", source)
                for symbol in expected:
                    self.assertIn(symbol, source)

    def test_no_writer_line_atomic_write_still_calls_bare_os_replace(self):
        """裸 `os.replace(` 不得再出现在这四个模块的写盘路径上。

        例外：`episode_stage_gate_runner` 用 `Path.replace` 把上一份判决改名归档
        （那是搬走旧件，不是提交新件），不在本断言范围内。
        """
        tools = pathlib.Path(__file__).resolve().parents[1]
        for filename in self.CALL_SITES:
            source = (tools / filename).read_text(encoding="utf-8")
            offenders = [
                line.strip()
                for line in source.splitlines()
                if "os.replace(" in line and not line.strip().startswith("#")
            ]
            with self.subTest(filename=filename):
                self.assertEqual(
                    offenders,
                    [],
                    f"{filename} 仍有裸 os.replace：{offenders}",
                )

    def test_helper_module_has_no_dependencies_beyond_stdlib(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / "durable_rename.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import requests", source)
        self.assertIn("__all__", source)
        self.assertEqual(durable_rename.__all__, ["fsync_directory", "durable_replace"])


if __name__ == "__main__":
    unittest.main()
