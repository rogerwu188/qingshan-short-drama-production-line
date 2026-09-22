#!/usr/bin/env python3
"""Build and verify release-bound offline dependency bundles for StoryClaw.

The StoryClaw host installer is intentionally network-free.  A publisher
resolves each supported Linux/Python profile ahead of time, stores only wheels,
and binds the exact wheel inventory and compact ``--require-hashes`` lock to the
immutable engine release.  The installer selects an exact profile from facts
reported by the *new virtual environment's* interpreter and fails closed for
every platform outside the supported matrix.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote


SCHEMA = "storyclaw.nalu.dependency_bundle.v1"
PROFILE_SCHEMA = "storyclaw.nalu.dependency_profile.v1"
GITHUB_REPOSITORY = "https://github.com/rogerwu188/qingshan-short-drama-production-line"
ARCHIVE_PREFIX = "storyclaw-dependencies/"
LOCK_NAME = "requirements.lock"
WHEELS_PREFIX = "wheels/"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2000
MAX_WHEEL_BYTES = 512 * 1024 * 1024
MAX_WHEEL_MEMBERS = 20000
MAX_WHEEL_EXPANDED_BYTES = 1024 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,199}\Z")
_PIN_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s\\;]+)\s*\\?\s*\Z")
_HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})\Z")
_NORMALIZE_NAME_RE = re.compile(r"[-_.]+")


class DependencyBundleBlocked(RuntimeError):
    """A fail-closed dependency-profile, bundle, or wheel refusal."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


@dataclass(frozen=True)
class Profile:
    profile_id: str
    python_major: int
    python_minor: int
    implementation: str = "cpython"
    system: str = "Linux"
    machine: str = "x86_64"
    libc: str = "glibc"
    min_libc: tuple[int, int] = (2, 31)
    accelerator: str = "cpu"

    @property
    def lock_filename(self) -> str:
        return f"{self.profile_id}.lock"


SUPPORTED_PROFILES: tuple[Profile, ...] = (
    Profile("storyclaw-linux-x86_64-cpython310-cpu-v1", 3, 10),
    Profile("storyclaw-linux-x86_64-cpython311-cpu-v1", 3, 11),
)
PROFILE_BY_ID = {profile.profile_id: profile for profile in SUPPORTED_PROFILES}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_distribution(value: str) -> str:
    return _NORMALIZE_NAME_RE.sub("-", value).lower()


def _version_tuple(value: object, code: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", str(value or "").strip())
    if not match:
        raise DependencyBundleBlocked(code, str(value))
    return int(match.group(1)), int(match.group(2))


def local_interpreter_facts() -> dict[str, Any]:
    libc_name, libc_version = platform.libc_ver()
    return {
        "schema": PROFILE_SCHEMA,
        "implementation": platform.python_implementation().lower(),
        "python_major": sys.version_info.major,
        "python_minor": sys.version_info.minor,
        "system": platform.system(),
        "machine": platform.machine().lower(),
        "libc": libc_name.lower(),
        "libc_version": libc_version,
    }


def probe_interpreter(
    python: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Read platform facts from the interpreter that will execute NALU."""
    program = (
        "import json,platform,sys;"
        "n,v=platform.libc_ver();"
        "print(json.dumps({'schema':'storyclaw.nalu.dependency_profile.v1',"
        "'implementation':platform.python_implementation().lower(),"
        "'python_major':sys.version_info.major,'python_minor':sys.version_info.minor,"
        "'system':platform.system(),'machine':platform.machine().lower(),"
        "'libc':n.lower(),'libc_version':v},sort_keys=True))"
    )
    try:
        result = runner(
            [str(python), "-I", "-c", program],
            check=False,
            capture_output=True,
            text=True,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except OSError as exc:
        raise DependencyBundleBlocked("DEPENDENCY_PYTHON_UNAVAILABLE", str(python)) from exc
    if result.returncode != 0:
        raise DependencyBundleBlocked("DEPENDENCY_PROFILE_PROBE_FAILED", str(result.returncode))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DependencyBundleBlocked("DEPENDENCY_PROFILE_PROBE_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("schema") != PROFILE_SCHEMA:
        raise DependencyBundleBlocked("DEPENDENCY_PROFILE_PROBE_INVALID")
    return payload


def select_profile(facts: Mapping[str, Any]) -> Profile:
    """Select the sole compatible profile; unsupported hosts never fall back."""
    system = str(facts.get("system") or "")
    machine = str(facts.get("machine") or "").lower()
    implementation = str(facts.get("implementation") or "").lower()
    libc = str(facts.get("libc") or "").lower()
    if system != "Linux":
        raise DependencyBundleBlocked("DEPENDENCY_PLATFORM_UNSUPPORTED", f"system={system}")
    if machine not in {"x86_64", "amd64"}:
        raise DependencyBundleBlocked("DEPENDENCY_PLATFORM_UNSUPPORTED", f"machine={machine}")
    if implementation != "cpython":
        raise DependencyBundleBlocked(
            "DEPENDENCY_PLATFORM_UNSUPPORTED", f"implementation={implementation}"
        )
    if libc != "glibc":
        raise DependencyBundleBlocked("DEPENDENCY_PLATFORM_UNSUPPORTED", f"libc={libc}")
    libc_version = _version_tuple(
        facts.get("libc_version"), "DEPENDENCY_LIBC_VERSION_INVALID"
    )
    major = facts.get("python_major")
    minor = facts.get("python_minor")
    if type(major) is not int or type(minor) is not int:
        raise DependencyBundleBlocked("DEPENDENCY_PYTHON_VERSION_INVALID")
    matches = [
        profile
        for profile in SUPPORTED_PROFILES
        if (profile.python_major, profile.python_minor) == (major, minor)
        and libc_version >= profile.min_libc
    ]
    if len(matches) != 1:
        raise DependencyBundleBlocked(
            "DEPENDENCY_PROFILE_UNSUPPORTED",
            f"cpython={major}.{minor},glibc={libc_version[0]}.{libc_version[1]}",
        )
    return matches[0]


def parse_hash_lock(data: bytes) -> dict[str, dict[str, Any]]:
    """Parse the constrained uv/pip lock grammar used by release bundles."""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise DependencyBundleBlocked("DEPENDENCY_LOCK_ENCODING_INVALID") from exc
    requirements: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pin = _PIN_RE.fullmatch(line)
        if pin:
            name, version = pin.groups()
            normalized = normalize_distribution(name)
            if normalized in requirements:
                raise DependencyBundleBlocked(
                    "DEPENDENCY_LOCK_DUPLICATE", f"{normalized}:{line_number}"
                )
            current = {"name": name, "normalized_name": normalized, "version": version, "hashes": []}
            requirements[normalized] = current
            continue
        token = line[:-1].strip() if line.endswith("\\") else line
        hash_match = _HASH_RE.fullmatch(token)
        if current is None or hash_match is None:
            raise DependencyBundleBlocked(
                "DEPENDENCY_LOCK_SYNTAX_INVALID", f"line={line_number}"
            )
        current["hashes"].append(hash_match.group(1))
    if not requirements:
        raise DependencyBundleBlocked("DEPENDENCY_LOCK_EMPTY")
    for requirement in requirements.values():
        hashes = sorted(set(requirement["hashes"]))
        if not hashes:
            raise DependencyBundleBlocked(
                "DEPENDENCY_LOCK_HASH_MISSING", requirement["normalized_name"]
            )
        requirement["hashes"] = hashes
    return requirements


def _safe_member_name(name: str, *, code: str) -> str:
    pure = PurePosixPath(name)
    if (
        not name
        or name.startswith(("/", "\\"))
        or "\\" in name
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise DependencyBundleBlocked(code, name)
    return pure.as_posix()


def inspect_wheel(path: Path) -> dict[str, Any]:
    """Verify a wheel before trusting its filename or metadata."""
    try:
        lstat = path.lstat()
    except OSError as exc:
        raise DependencyBundleBlocked("DEPENDENCY_WHEEL_MISSING", str(path)) from exc
    if path.is_symlink() or not stat.S_ISREG(lstat.st_mode):
        raise DependencyBundleBlocked("DEPENDENCY_WHEEL_NOT_REGULAR", str(path))
    if lstat.st_size <= 0 or lstat.st_size > MAX_WHEEL_BYTES:
        raise DependencyBundleBlocked("DEPENDENCY_WHEEL_SIZE_INVALID", path.name)
    expanded = 0
    metadata_names: list[str] = []
    try:
        with zipfile.ZipFile(path) as wheel:
            rows = wheel.infolist()
            if not rows or len(rows) > MAX_WHEEL_MEMBERS:
                raise DependencyBundleBlocked("DEPENDENCY_WHEEL_MEMBER_LIMIT", path.name)
            for row in rows:
                name = _safe_member_name(row.filename, code="DEPENDENCY_WHEEL_PATH_INVALID")
                if row.is_dir():
                    continue
                expanded += row.file_size
                if row.file_size > MAX_WHEEL_EXPANDED_BYTES or expanded > MAX_WHEEL_EXPANDED_BYTES:
                    raise DependencyBundleBlocked("DEPENDENCY_WHEEL_EXPANDED_LIMIT", path.name)
                # Vendored projects (notably setuptools) may retain nested
                # ``*.dist-info/METADATA`` files.  Only the wheel's root
                # distribution metadata establishes its identity.
                if name.endswith(".dist-info/METADATA") and len(PurePosixPath(name).parts) == 2:
                    metadata_names.append(name)
            if len(metadata_names) != 1:
                raise DependencyBundleBlocked("DEPENDENCY_WHEEL_METADATA_INVALID", path.name)
            metadata_bytes = wheel.read(metadata_names[0])
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, DependencyBundleBlocked):
            raise
        raise DependencyBundleBlocked("DEPENDENCY_WHEEL_ZIP_INVALID", path.name) from exc
    try:
        metadata = Parser().parsestr(metadata_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DependencyBundleBlocked("DEPENDENCY_WHEEL_METADATA_INVALID", path.name) from exc
    name = str(metadata.get("Name") or "").strip()
    version = str(metadata.get("Version") or "").strip()
    if not name or not version:
        raise DependencyBundleBlocked("DEPENDENCY_WHEEL_METADATA_INVALID", path.name)
    return {
        "name": name,
        "normalized_name": normalize_distribution(name),
        "version": version,
        "filename": path.name,
        "size_bytes": lstat.st_size,
        "sha256": sha256_file(path),
        "expanded_bytes": expanded,
    }


def _wheel_record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def build_headless_opencv_shim(destination: Path) -> Path:
    """Create a deterministic metadata-only wheel satisfying InsightFace.

    InsightFace declares the GUI ``opencv-python`` distribution even though
    NALU uses the ABI-compatible headless build.  Installing both overwrites
    the same ``cv2`` package.  This wheel contains no importable code and
    depends on the exact headless wheel instead.
    """
    destination.mkdir(parents=True, exist_ok=True)
    version = "4.14.0.94+qingshanheadless1"
    distribution = "opencv_python"
    dist_info = f"{distribution}-{version}.dist-info"
    files = {
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            "Name: opencv-python\n"
            f"Version: {version}\n"
            "Summary: Qingshan StoryClaw headless OpenCV dependency shim\n"
            "Requires-Dist: opencv-python-headless == 4.14.0.94\n\n"
        ).encode("utf-8"),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: qingshan-storyclaw-dependency-bundle\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode("utf-8"),
        f"{dist_info}/top_level.txt": b"",
    }
    record = f"{dist_info}/RECORD"
    record_rows = [
        [name, _wheel_record_hash(data), str(len(data))]
        for name, data in sorted(files.items())
    ]
    record_rows.append([record, "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(record_rows)
    files[record] = output.getvalue().encode("utf-8")
    path = destination / f"{distribution}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_STORED)
    return path


def _compact_lock(
    requirements: Mapping[str, Mapping[str, Any]], wheels: Sequence[Mapping[str, Any]]
) -> bytes:
    wheel_by_name = {str(row["normalized_name"]): row for row in wheels}
    lines: list[str] = []
    for normalized in sorted(requirements):
        requirement = requirements[normalized]
        wheel = wheel_by_name[normalized]
        lines.append(
            f"{requirement['name']}=={requirement['version']} \\\n    --hash=sha256:{wheel['sha256']}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def validate_wheelhouse(lock_bytes: bytes, wheelhouse: Path) -> tuple[bytes, list[dict[str, Any]]]:
    requirements = parse_hash_lock(lock_bytes)
    if not wheelhouse.is_dir() or wheelhouse.is_symlink():
        raise DependencyBundleBlocked("DEPENDENCY_WHEELHOUSE_INVALID", str(wheelhouse))
    children = sorted(wheelhouse.iterdir(), key=lambda path: path.name)
    if not children:
        raise DependencyBundleBlocked("DEPENDENCY_WHEELHOUSE_EMPTY")
    if any(path.suffix != ".whl" or not path.is_file() for path in children):
        raise DependencyBundleBlocked("DEPENDENCY_WHEELHOUSE_EXTRA_FILE")
    wheels = [inspect_wheel(path) for path in children]
    wheel_by_name: dict[str, dict[str, Any]] = {}
    for wheel in wheels:
        normalized = wheel["normalized_name"]
        if normalized in wheel_by_name:
            raise DependencyBundleBlocked("DEPENDENCY_WHEEL_DUPLICATE", normalized)
        wheel_by_name[normalized] = wheel
    if set(wheel_by_name) != set(requirements):
        missing = sorted(set(requirements) - set(wheel_by_name))
        extra = sorted(set(wheel_by_name) - set(requirements))
        raise DependencyBundleBlocked(
            "DEPENDENCY_WHEEL_INVENTORY_MISMATCH",
            f"missing={','.join(missing)};extra={','.join(extra)}",
        )
    for normalized, requirement in requirements.items():
        wheel = wheel_by_name[normalized]
        if wheel["version"] != requirement["version"]:
            raise DependencyBundleBlocked(
                "DEPENDENCY_WHEEL_VERSION_MISMATCH",
                f"{normalized}:{wheel['version']}!={requirement['version']}",
            )
        if wheel["sha256"] not in requirement["hashes"]:
            raise DependencyBundleBlocked("DEPENDENCY_WHEEL_HASH_NOT_LOCKED", wheel["filename"])
    ordered = [wheel_by_name[name] for name in sorted(wheel_by_name)]
    return _compact_lock(requirements, ordered), ordered


def dependency_archive_filename(tag: str, profile_id: str) -> str:
    return f"qingshan-storyclaw-dependencies-{profile_id}-{tag}.tar.gz"


def dependency_manifest_filename(tag: str, profile_id: str) -> str:
    return f"qingshan-storyclaw-dependencies-{profile_id}-{tag}.json"


def github_asset_url(tag: str, filename: str) -> str:
    return f"{GITHUB_REPOSITORY}/releases/download/{quote(tag)}/{quote(filename)}"


def release_binding(
    manifest_path: Path, archive_path: Path, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the compact row embedded in channel and TalentHub manifests."""
    tag = str(manifest.get("release_tag") or "")
    profile_id = str((manifest.get("profile") or {}).get("id") or "")
    manifest_name = dependency_manifest_filename(tag, profile_id)
    archive_name = dependency_archive_filename(tag, profile_id)
    if manifest_path.name != manifest_name or archive_path.name != archive_name:
        raise DependencyBundleBlocked("DEPENDENCY_RELEASE_ASSET_NAME_INVALID", profile_id)
    return {
        "profile_id": profile_id,
        "manifest_url": github_asset_url(tag, manifest_name),
        "manifest_size_bytes": manifest_path.stat().st_size,
        "manifest_sha256": sha256_file(manifest_path),
        "archive_url": github_asset_url(tag, archive_name),
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
    }


def validate_release_bindings(
    value: object, *, release_tag: str
) -> dict[str, dict[str, Any]]:
    """Validate the exact supported-profile binding set in a release manifest."""
    if not isinstance(value, list) or len(value) != len(SUPPORTED_PROFILES):
        raise DependencyBundleBlocked("DEPENDENCY_RELEASE_BINDINGS_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise DependencyBundleBlocked("DEPENDENCY_RELEASE_BINDING_INVALID")
        profile_id = str(item.get("profile_id") or "")
        if profile_id not in PROFILE_BY_ID or profile_id in result:
            raise DependencyBundleBlocked("DEPENDENCY_RELEASE_BINDING_INVALID", profile_id)
        manifest_name = dependency_manifest_filename(release_tag, profile_id)
        archive_name = dependency_archive_filename(release_tag, profile_id)
        exact = {
            "manifest_url": github_asset_url(release_tag, manifest_name),
            "archive_url": github_asset_url(release_tag, archive_name),
        }
        if any(item.get(key) != expected for key, expected in exact.items()):
            raise DependencyBundleBlocked("DEPENDENCY_RELEASE_BINDING_URL_INVALID", profile_id)
        for prefix in ("manifest", "archive"):
            size = item.get(f"{prefix}_size_bytes")
            digest = str(item.get(f"{prefix}_sha256") or "")
            if type(size) is not int or size <= 0 or not _SHA256_RE.fullmatch(digest):
                raise DependencyBundleBlocked(
                    "DEPENDENCY_RELEASE_BINDING_DIGEST_INVALID", profile_id
                )
        if item["manifest_size_bytes"] > 1024 * 1024 or item["archive_size_bytes"] > MAX_ARCHIVE_BYTES:
            raise DependencyBundleBlocked("DEPENDENCY_RELEASE_BINDING_SIZE_INVALID", profile_id)
        result[profile_id] = dict(item)
    if set(result) != set(PROFILE_BY_ID):
        raise DependencyBundleBlocked("DEPENDENCY_RELEASE_BINDINGS_INVALID")
    return result


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def build_bundle(
    *,
    profile_id: str,
    source_lock: Path,
    wheelhouse: Path,
    output_dir: Path,
    release_tag: str,
    git_commit: str,
    release_sequence: int,
) -> tuple[Path, Path, dict[str, Any]]:
    profile = PROFILE_BY_ID.get(profile_id)
    if profile is None:
        raise DependencyBundleBlocked("DEPENDENCY_PROFILE_UNKNOWN", profile_id)
    if not _TAG_RE.fullmatch(release_tag):
        raise DependencyBundleBlocked("DEPENDENCY_RELEASE_TAG_INVALID", release_tag)
    if not _COMMIT_RE.fullmatch(git_commit):
        raise DependencyBundleBlocked("DEPENDENCY_RELEASE_COMMIT_INVALID", git_commit)
    if type(release_sequence) is not int or release_sequence <= 0:
        raise DependencyBundleBlocked("DEPENDENCY_RELEASE_SEQUENCE_INVALID")
    try:
        source_lock_bytes = source_lock.read_bytes()
    except OSError as exc:
        raise DependencyBundleBlocked("DEPENDENCY_SOURCE_LOCK_UNAVAILABLE", str(source_lock)) from exc
    compact_lock, wheels = validate_wheelhouse(source_lock_bytes, wheelhouse)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / dependency_archive_filename(release_tag, profile_id)
    expanded = len(compact_lock) + sum(int(row["size_bytes"]) for row in wheels)
    if expanded > MAX_EXPANDED_BYTES:
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_EXPANDED_LIMIT")
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                archive.addfile(_tar_info(ARCHIVE_PREFIX + LOCK_NAME, len(compact_lock)), io.BytesIO(compact_lock))
                for wheel in wheels:
                    path = wheelhouse / str(wheel["filename"])
                    info = _tar_info(ARCHIVE_PREFIX + WHEELS_PREFIX + path.name, path.stat().st_size)
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        archive_path.unlink(missing_ok=True)
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_SIZE_LIMIT")
    archive_sha = sha256_file(archive_path)
    archive_name = archive_path.name
    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "release_tag": release_tag,
        "git_commit": git_commit,
        "release_sequence": release_sequence,
        "profile": {
            "id": profile.profile_id,
            "system": profile.system,
            "machine": profile.machine,
            "implementation": profile.implementation,
            "python_major": profile.python_major,
            "python_minor": profile.python_minor,
            "libc": profile.libc,
            "min_libc_version": f"{profile.min_libc[0]}.{profile.min_libc[1]}",
            "accelerator": profile.accelerator,
        },
        "lock": {
            "path": LOCK_NAME,
            "size_bytes": len(compact_lock),
            "sha256": sha256_bytes(compact_lock),
            "require_hashes": True,
            "package_count": len(wheels),
        },
        "archive": {
            "filename": archive_name,
            "url": github_asset_url(release_tag, archive_name),
            "size_bytes": archive_path.stat().st_size,
            "sha256": archive_sha,
            "file_count": len(wheels) + 1,
            "expanded_size_bytes": expanded,
        },
        "engine_install": {
            "no_index": True,
            "no_dependencies": True,
            "no_build_isolation": True,
        },
        "wheels": wheels,
    }
    manifest_path = output_dir / dependency_manifest_filename(release_tag, profile_id)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, archive_path, manifest


def validate_manifest(
    payload: Mapping[str, Any],
    *,
    release_tag: str,
    git_commit: str,
    release_sequence: int,
    expected_profile_id: str | None = None,
) -> dict[str, Any]:
    if payload.get("schema") != SCHEMA or payload.get("status") != "PASS":
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_SCHEMA_INVALID")
    if payload.get("release_tag") != release_tag or payload.get("git_commit") != git_commit:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_RELEASE_MISMATCH")
    if payload.get("release_sequence") != release_sequence:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_SEQUENCE_MISMATCH")
    profile_row = payload.get("profile")
    if not isinstance(profile_row, dict):
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_PROFILE_INVALID")
    profile_id = str(profile_row.get("id") or "")
    profile = PROFILE_BY_ID.get(profile_id)
    if profile is None or (expected_profile_id is not None and profile_id != expected_profile_id):
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_PROFILE_INVALID", profile_id)
    exact_profile = {
        "system": profile.system,
        "machine": profile.machine,
        "implementation": profile.implementation,
        "python_major": profile.python_major,
        "python_minor": profile.python_minor,
        "libc": profile.libc,
        "min_libc_version": f"{profile.min_libc[0]}.{profile.min_libc[1]}",
        "accelerator": profile.accelerator,
    }
    if any(profile_row.get(key) != value for key, value in exact_profile.items()):
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_PROFILE_INVALID", profile_id)
    lock = payload.get("lock")
    archive = payload.get("archive")
    wheels = payload.get("wheels")
    engine_install = payload.get("engine_install")
    if not isinstance(lock, dict) or not isinstance(archive, dict) or not isinstance(wheels, list):
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_STRUCTURE_INVALID")
    if lock.get("path") != LOCK_NAME or lock.get("require_hashes") is not True:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_LOCK_INVALID")
    if engine_install != {"no_index": True, "no_dependencies": True, "no_build_isolation": True}:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_ENGINE_INSTALL_INVALID")
    for row, prefix in ((lock, "LOCK"), (archive, "ARCHIVE")):
        if type(row.get("size_bytes")) is not int or row["size_bytes"] <= 0:
            raise DependencyBundleBlocked(f"DEPENDENCY_MANIFEST_{prefix}_SIZE_INVALID")
        if not _SHA256_RE.fullmatch(str(row.get("sha256") or "")):
            raise DependencyBundleBlocked(f"DEPENDENCY_MANIFEST_{prefix}_SHA_INVALID")
    if archive["size_bytes"] > MAX_ARCHIVE_BYTES:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_ARCHIVE_SIZE_INVALID")
    if (
        type(archive.get("expanded_size_bytes")) is not int
        or archive["expanded_size_bytes"] <= 0
        or archive["expanded_size_bytes"] > MAX_EXPANDED_BYTES
    ):
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_ARCHIVE_EXPANDED_INVALID")
    if type(archive.get("file_count")) is not int or not 1 <= archive["file_count"] <= MAX_ARCHIVE_MEMBERS:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_ARCHIVE_COUNT_INVALID")
    expected_archive_name = dependency_archive_filename(release_tag, profile_id)
    if archive.get("filename") != expected_archive_name or archive.get("url") != github_asset_url(
        release_tag, expected_archive_name
    ):
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_ARCHIVE_URL_INVALID")
    if lock.get("package_count") != len(wheels) or archive["file_count"] != len(wheels) + 1:
        raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_COUNT_MISMATCH")
    names: set[str] = set()
    filenames: set[str] = set()
    for row in wheels:
        if not isinstance(row, dict):
            raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_WHEEL_INVALID")
        name = normalize_distribution(str(row.get("name") or ""))
        filename = str(row.get("filename") or "")
        if (
            not name
            or name != row.get("normalized_name")
            or name in names
            or filename in filenames
            or Path(filename).name != filename
            or not filename.endswith(".whl")
            or type(row.get("size_bytes")) is not int
            or row["size_bytes"] <= 0
            or not _SHA256_RE.fullmatch(str(row.get("sha256") or ""))
        ):
            raise DependencyBundleBlocked("DEPENDENCY_MANIFEST_WHEEL_INVALID", filename)
        names.add(name)
        filenames.add(filename)
    return dict(payload)


def extract_verified_bundle(
    manifest: Mapping[str, Any], archive_path: Path, destination: Path
) -> dict[str, Any]:
    """Verify and stream-extract an exact dependency bundle inventory."""
    archive_row = manifest["archive"]
    if archive_path.is_symlink() or not archive_path.is_file():
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_INVALID", str(archive_path))
    size = archive_path.stat().st_size
    if size != archive_row["size_bytes"] or sha256_file(archive_path) != archive_row["sha256"]:
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_BINDING_MISMATCH")
    if destination.exists() and (destination.is_symlink() or any(destination.iterdir())):
        raise DependencyBundleBlocked("DEPENDENCY_EXTRACTION_TARGET_NOT_EMPTY", str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    expected = {ARCHIVE_PREFIX + LOCK_NAME: manifest["lock"]}
    for wheel in manifest["wheels"]:
        expected[ARCHIVE_PREFIX + WHEELS_PREFIX + wheel["filename"]] = wheel
    seen: set[str] = set()
    expanded = 0
    try:
        with tarfile.open(archive_path, "r|gz") as archive:
            for index, member in enumerate(archive, 1):
                if index > MAX_ARCHIVE_MEMBERS:
                    raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_MEMBER_LIMIT")
                name = _safe_member_name(member.name, code="DEPENDENCY_ARCHIVE_PATH_INVALID")
                if not member.isfile() or name not in expected or name in seen:
                    raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_MEMBER_INVALID", name)
                row = expected[name]
                if member.size != row["size_bytes"]:
                    raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_MEMBER_SIZE_MISMATCH", name)
                expanded += member.size
                if expanded > MAX_EXPANDED_BYTES or expanded > archive_row["expanded_size_bytes"]:
                    raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_EXPANDED_LIMIT")
                source = archive.extractfile(member)
                if source is None:
                    raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_MEMBER_INVALID", name)
                relative = name.removeprefix(ARCHIVE_PREFIX)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                actual = 0
                with target.open("xb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        actual += len(chunk)
                        if actual > member.size:
                            raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_MEMBER_SIZE_MISMATCH", name)
                        digest.update(chunk)
                        output.write(chunk)
                if actual != member.size or digest.hexdigest() != row["sha256"]:
                    raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_MEMBER_HASH_MISMATCH", name)
                seen.add(name)
    except (OSError, tarfile.TarError) as exc:
        if isinstance(exc, DependencyBundleBlocked):
            raise
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_INVALID", str(archive_path)) from exc
    if seen != set(expected) or expanded != archive_row["expanded_size_bytes"]:
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_INVENTORY_MISMATCH")
    lock_path = destination / LOCK_NAME
    wheelhouse = destination / WHEELS_PREFIX.rstrip("/")
    compact_lock, wheels = validate_wheelhouse(lock_path.read_bytes(), wheelhouse)
    if compact_lock != lock_path.read_bytes():
        raise DependencyBundleBlocked("DEPENDENCY_COMPACT_LOCK_MISMATCH")
    manifest_wheels = {
        row["normalized_name"]: (row["version"], row["filename"], row["sha256"])
        for row in manifest["wheels"]
    }
    actual_wheels = {
        row["normalized_name"]: (row["version"], row["filename"], row["sha256"])
        for row in wheels
    }
    if actual_wheels != manifest_wheels:
        raise DependencyBundleBlocked("DEPENDENCY_ARCHIVE_WHEEL_METADATA_MISMATCH")
    return {
        "status": "PASS",
        "root": str(destination),
        "lock": str(lock_path),
        "wheelhouse": str(wheelhouse),
        "profile_id": manifest["profile"]["id"],
        "archive_sha256": archive_row["sha256"],
        "lock_sha256": manifest["lock"]["sha256"],
        "package_count": len(wheels),
    }


def download_profile_wheels(
    profile_id: str,
    source_lock: Path,
    destination: Path,
    *,
    python: Path = Path(sys.executable),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Resolve one checked-in hash lock to an exact wheel set at publish time."""
    profile = PROFILE_BY_ID.get(profile_id)
    if profile is None:
        raise DependencyBundleBlocked("DEPENDENCY_PROFILE_UNKNOWN", profile_id)
    if destination.exists() and (destination.is_symlink() or any(destination.iterdir())):
        raise DependencyBundleBlocked("DEPENDENCY_WHEELHOUSE_NOT_EMPTY", str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    shim = build_headless_opencv_shim(destination)
    platforms = (
        "manylinux_2_31_x86_64", "manylinux_2_28_x86_64", "manylinux_2_27_x86_64",
        "manylinux_2_24_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64",
        "manylinux2010_x86_64", "manylinux1_x86_64", "linux_x86_64",
    )
    version = f"{profile.python_major}.{profile.python_minor}"
    command = [
        str(python), "-m", "pip", "download", "--dest", str(destination),
        "--require-hashes", "--only-binary=:all:", "--no-deps",
        "--find-links", str(destination), "--implementation", "cp",
        "--python-version", version,
        "--abi", f"cp{profile.python_major}{profile.python_minor}",
        "--abi", "abi3", "--abi", "none",
    ]
    for tag in platforms:
        command.extend(["--platform", tag])
    command.extend(["-r", str(source_lock)])
    environment = os.environ.copy()
    environment.update({
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
    })
    result = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if result.returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        raise DependencyBundleBlocked(
            "DEPENDENCY_WHEEL_DOWNLOAD_FAILED",
            "\n".join((result.stderr or result.stdout or "").splitlines()[-8:]),
        )
    compact_lock, wheels = validate_wheelhouse(source_lock.read_bytes(), destination)
    return {
        "status": "PASS",
        "profile_id": profile_id,
        "wheelhouse": str(destination),
        "shim": str(shim),
        "package_count": len(wheels),
        "compact_lock_sha256": sha256_bytes(compact_lock),
        "network_used": True,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--python", type=Path, default=Path(sys.executable))
    build = subparsers.add_parser("build")
    build.add_argument("--profile", choices=sorted(PROFILE_BY_ID), required=True)
    build.add_argument("--source-lock", type=Path, required=True)
    build.add_argument("--wheelhouse", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--release-tag", required=True)
    build.add_argument("--git-commit", required=True)
    build.add_argument("--release-sequence", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "probe":
            facts = probe_interpreter(args.python)
            profile = select_profile(facts)
            result = {"status": "PASS", "facts": facts, "profile_id": profile.profile_id}
        else:
            manifest_path, archive_path, manifest = build_bundle(
                profile_id=args.profile,
                source_lock=args.source_lock,
                wheelhouse=args.wheelhouse,
                output_dir=args.output_dir,
                release_tag=args.release_tag,
                git_commit=args.git_commit,
                release_sequence=args.release_sequence,
            )
            result = {
                "status": "PASS",
                "manifest": str(manifest_path),
                "archive": str(archive_path),
                "profile_id": manifest["profile"]["id"],
            }
    except DependencyBundleBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code, "detail": exc.detail}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
