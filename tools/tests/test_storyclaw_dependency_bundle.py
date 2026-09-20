"""Regression tests for release-bound offline StoryClaw dependencies."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import storyclaw_dependency_bundle as bundle


def _wheel(root: Path, name: str, version: str) -> Path:
    distribution = name.replace("-", "_")
    dist_info = f"{distribution}-{version}.dist-info"
    path = root / f"{distribution}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for relative, content in {
            f"{dist_info}/METADATA": (
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n"
            ).encode(),
            f"{dist_info}/WHEEL": (
                "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ).encode(),
            f"{dist_info}/RECORD": b"",
        }.items():
            info = zipfile.ZipInfo(relative, (2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return path


def _lock_for(wheels: list[Path], names: list[tuple[str, str]]) -> bytes:
    rows = []
    for wheel, (name, version) in zip(wheels, names, strict=True):
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        rows.append(f"{name}=={version} \\\n    --hash=sha256:{digest}")
    return ("\n".join(rows) + "\n").encode()


class StoryClawDependencyBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wheelhouse = self.root / "wheelhouse"
        self.wheelhouse.mkdir()
        self.names = [("alpha-pkg", "1.2.3"), ("bravo_pkg", "2.0")]
        self.wheels = [
            _wheel(self.wheelhouse, name, version) for name, version in self.names
        ]
        self.lock = self.root / "profile.lock"
        self.lock.write_bytes(_lock_for(self.wheels, self.names))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _facts(**overrides):
        values = {
            "schema": bundle.PROFILE_SCHEMA,
            "implementation": "cpython",
            "python_major": 3,
            "python_minor": 11,
            "system": "Linux",
            "machine": "x86_64",
            "libc": "glibc",
            "libc_version": "2.35",
        }
        values.update(overrides)
        return values

    def test_supported_matrix_is_exact_and_fails_closed(self):
        self.assertEqual(
            bundle.select_profile(self._facts()).profile_id,
            "storyclaw-linux-x86_64-cpython311-cpu-v1",
        )
        self.assertEqual(
            bundle.select_profile(self._facts(python_minor=10)).profile_id,
            "storyclaw-linux-x86_64-cpython310-cpu-v1",
        )
        for changes in (
            {"system": "Darwin"},
            {"machine": "aarch64"},
            {"implementation": "pypy"},
            {"libc": "musl"},
            {"libc_version": "2.30"},
            {"python_minor": 9},
            {"python_minor": 12},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                bundle.DependencyBundleBlocked
            ):
                bundle.select_profile(self._facts(**changes))

    def test_bundle_is_reproducible_exact_and_extracts_streaming(self):
        kwargs = {
            "profile_id": "storyclaw-linux-x86_64-cpython311-cpu-v1",
            "source_lock": self.lock,
            "wheelhouse": self.wheelhouse,
            "release_tag": "v2026.09.20-storyclaw",
            "git_commit": "a" * 40,
            "release_sequence": 77,
        }
        first_dir = self.root / "first"
        second_dir = self.root / "second"
        first_manifest_path, first_archive, first = bundle.build_bundle(
            output_dir=first_dir, **kwargs
        )
        second_manifest_path, second_archive, second = bundle.build_bundle(
            output_dir=second_dir, **kwargs
        )
        self.assertEqual(first_manifest_path.read_bytes(), second_manifest_path.read_bytes())
        self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
        validated = bundle.validate_manifest(
            first,
            release_tag=kwargs["release_tag"],
            git_commit=kwargs["git_commit"],
            release_sequence=kwargs["release_sequence"],
            expected_profile_id=kwargs["profile_id"],
        )
        extracted = bundle.extract_verified_bundle(
            validated, first_archive, self.root / "extracted"
        )
        self.assertEqual(extracted["status"], "PASS")
        self.assertEqual(extracted["package_count"], 2)
        lock_text = Path(extracted["lock"]).read_text()
        self.assertEqual(lock_text.count("--hash=sha256:"), 2)
        self.assertNotIn("https://", lock_text)

    def test_unlocked_missing_duplicate_and_tampered_wheels_are_rejected(self):
        extra = _wheel(self.wheelhouse, "extra", "1")
        with self.assertRaisesRegex(
            bundle.DependencyBundleBlocked, "DEPENDENCY_WHEEL_INVENTORY_MISMATCH"
        ):
            bundle.validate_wheelhouse(self.lock.read_bytes(), self.wheelhouse)
        extra.unlink()
        self.wheels[0].write_bytes(self.wheels[0].read_bytes() + b"tamper")
        with self.assertRaisesRegex(
            bundle.DependencyBundleBlocked, "DEPENDENCY_WHEEL_HASH_NOT_LOCKED"
        ):
            bundle.validate_wheelhouse(self.lock.read_bytes(), self.wheelhouse)

    def test_archive_traversal_and_binding_tamper_are_rejected(self):
        manifest_path, archive, manifest = bundle.build_bundle(
            profile_id="storyclaw-linux-x86_64-cpython310-cpu-v1",
            source_lock=self.lock,
            wheelhouse=self.wheelhouse,
            output_dir=self.root / "built",
            release_tag="v1",
            git_commit="b" * 40,
            release_sequence=1,
        )
        self.assertTrue(manifest_path.is_file())
        archive.write_bytes(archive.read_bytes() + b"tamper")
        with self.assertRaisesRegex(
            bundle.DependencyBundleBlocked, "DEPENDENCY_ARCHIVE_BINDING_MISMATCH"
        ):
            bundle.extract_verified_bundle(manifest, archive, self.root / "bad-binding")

        malicious = self.root / "traversal.tar.gz"
        with malicious.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as tar:
                    info = tarfile.TarInfo("../escape")
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b"x"))
        attack = json.loads(json.dumps(manifest))
        attack["archive"].update(
            size_bytes=malicious.stat().st_size,
            sha256=bundle.sha256_file(malicious),
            expanded_size_bytes=1,
            file_count=1,
        )
        with self.assertRaisesRegex(
            bundle.DependencyBundleBlocked, "DEPENDENCY_ARCHIVE_PATH_INVALID"
        ):
            bundle.extract_verified_bundle(attack, malicious, self.root / "bad-path")
        self.assertFalse((self.root / "escape").exists())

    def test_manifest_cannot_rebind_release_profile_or_url(self):
        _path, _archive, manifest = bundle.build_bundle(
            profile_id="storyclaw-linux-x86_64-cpython310-cpu-v1",
            source_lock=self.lock,
            wheelhouse=self.wheelhouse,
            output_dir=self.root / "built",
            release_tag="v1",
            git_commit="c" * 40,
            release_sequence=4,
        )
        for mutation, code in (
            (("release_sequence", 3), "SEQUENCE_MISMATCH"),
            (("release_tag", "v0"), "RELEASE_MISMATCH"),
        ):
            changed = json.loads(json.dumps(manifest))
            changed[mutation[0]] = mutation[1]
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                bundle.DependencyBundleBlocked, code
            ):
                bundle.validate_manifest(
                    changed,
                    release_tag="v1",
                    git_commit="c" * 40,
                    release_sequence=4,
                    expected_profile_id="storyclaw-linux-x86_64-cpython310-cpu-v1",
                )
        changed = json.loads(json.dumps(manifest))
        changed["archive"]["url"] = "https://attacker.invalid/bundle"
        with self.assertRaisesRegex(
            bundle.DependencyBundleBlocked, "ARCHIVE_URL_INVALID"
        ):
            bundle.validate_manifest(
                changed,
                release_tag="v1",
                git_commit="c" * 40,
                release_sequence=4,
            )

    def test_publisher_download_contract_is_hash_required_and_binary_only(self):
        wheelhouse = self.root / "download"
        shim_source = bundle.build_headless_opencv_shim(self.root / "shim-source")
        lock = self.root / "shim.lock"
        lock.write_bytes(
            _lock_for(
                [shim_source],
                [("opencv-python", "4.14.0.94+qingshanheadless1")],
            )
        )
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            # The real command sees the deterministic shim via --find-links;
            # no index download is needed for this one-package fixture.
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        report = bundle.download_profile_wheels(
            "storyclaw-linux-x86_64-cpython310-cpu-v1",
            lock,
            wheelhouse,
            runner=runner,
        )
        self.assertEqual(report["status"], "PASS")
        command = calls[0][0]
        self.assertIn("--require-hashes", command)
        self.assertIn("--only-binary=:all:", command)
        self.assertIn("--no-deps", command)
        self.assertIn("manylinux_2_31_x86_64", command)
        self.assertNotIn("--no-binary", command)


if __name__ == "__main__":
    unittest.main()
