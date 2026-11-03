#!/usr/bin/env python3
"""Studio-level original-image asset library (content-addressed, versioned, per-project bound).

What this is
------------
One directory (the *studio root*, configured, never inside an engine clone or an episode
folder) that keeps the ORIGINAL bytes of every generated or approved reference image:

    <root>/objects/sha256/<2>/<sha256>.<ext>   original bytes, never re-encoded, never a link
    <root>/catalog/objects/<2>/<sha>.json      per-object record (size, type, origins)
    <root>/catalog/assets/<id>/vNNNN.json      IMMUTABLE version manifest (what an asset is)
    <root>/catalog/assets/<id>/vNNNN.review.json  review verdict + history (the only mutable part)
    <root>/catalog/bindings/<project>/<kind>__<role>.json   a project's own role binding
    <root>/catalog/legacy/<2>/<sha>.json       old path + sha -> asset compatibility map (local only)
    <root>/backup/{queue,receipts}/            per-object backup todo and verified receipts

Three identities are kept apart (requirement doc section 3):
  * studio asset      asset_id + version + content sha256 (this module's catalog)
  * project role      a binding: which asset version plays which role in ONE project; the project's
                      own name / relationship / wardrobe / voice live in ``project_fields`` and are
                      never copied from another project
  * episode usage     append-only usage records (which version an episode actually used)

Rules this module enforces
--------------------------
  * dedupe by BYTES only (same sha256); look-alikes are never merged, same name is not same person
  * an original is archived as UNREVIEWED; only an APPROVED version (with a review reference that
    carries a sha256) is selectable by default; REJECTED stays recorded as REJECTED
  * a version number is never reused for different content (VERSION_CONTENT_CONFLICT)
  * writes are temp file -> fsync -> atomic rename; locks are per object / per asset (flock), never
    a global lock and never a library scan on the production path
  * cross-project use is an explicit ``bind``; the target project_id is part of the binding path,
    so no lookup ever falls through to another project
  * the backup target is configured separately (see studio_asset_backup.py); with none configured
    every local feature works and the state is reported UNCONFIGURED, never "backed up"

No provider call exists anywhere in this module.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

try:  # POSIX advisory locks; the studio library is supported on macOS / Linux
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "STUDIO_ASSET_LIBRARY_V1.json"

SCHEMA_LIBRARY = "qingshan.studio_asset_library.v1"
SCHEMA_OBJECT = "qingshan.studio_asset_object.v1"
SCHEMA_VERSION = "qingshan.studio_asset_version.v1"
SCHEMA_REVIEW = "qingshan.studio_asset_review.v1"
SCHEMA_BINDING = "qingshan.studio_asset_binding.v1"
SCHEMA_BUNDLE = "qingshan.studio_asset_bundle.v1"

ENV_ROOT = "QINGSHAN_STUDIO_ASSET_ROOT"
ENV_CACHE = "QINGSHAN_STUDIO_CACHE_DIR"

REVIEW_STATUSES = ("UNREVIEWED", "APPROVED", "REJECTED")
KINDS = ("character", "prop", "creature", "scene")
CATEGORIES = ("characters", "props", "creatures", "scenes", "wardrobe", "reference_materials")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,95}$")
EXT_RE = re.compile(r"^[a-z0-9]{1,8}$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
               "gif": "image/gif", "bmp": "image/bmp"}
MAX_ORIGINS = 50
LOCK_TIMEOUT_S = 60.0
CHUNK = 1 << 20


class StudioError(RuntimeError):
    """Raised with a stable machine code as ``args[0]`` (``CODE`` or ``CODE:detail``)."""

    @property
    def code(self) -> str:
        return str(self.args[0]).split(":", 1)[0]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA_RE.match(value))


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:  # pragma: no cover - platform specific
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """temp file in the same directory -> flush + fsync -> atomic rename -> fsync directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(handle.name)
        raise
    _fsync_dir(path.parent)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        raise StudioError(f"JSON_UNREADABLE:{path}:{type(exc).__name__}") from exc


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """Cross-process exclusive lock on one small file (per object / per asset, never global)."""
    if fcntl is None:  # pragma: no cover
        raise StudioError("LOCKING_UNSUPPORTED_PLATFORM")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise StudioError(f"LOCK_TIMEOUT:{path.name}") from None
                time.sleep(0.01)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# --------------------------------------------------------------------------- #
# image facts without third-party libraries
# --------------------------------------------------------------------------- #
def sniff_extension(head: bytes) -> str:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "bin"


def image_size(path: Path) -> tuple[int | None, int | None]:
    """(width, height) for PNG / JPEG / WebP / GIF, read from headers only; (None, None) otherwise."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
                return struct.unpack("<HH", head[6:10])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                kind = head[12:16]
                if kind == b"VP8X" and len(head) >= 30:
                    return (int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1)
                if kind == b"VP8L" and len(head) >= 25:
                    bits = int.from_bytes(head[21:25], "little")
                    return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
                if kind == b"VP8 " and len(head) >= 30:
                    return struct.unpack("<HH", head[26:30])[0] & 0x3FFF, struct.unpack("<HH", head[26:30])[1] & 0x3FFF
                return None, None
            if head.startswith(b"\xff\xd8"):
                handle.seek(2)
                while True:
                    marker = handle.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None, None
                    code = marker[1]
                    if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                        continue
                    length_raw = handle.read(2)
                    if len(length_raw) < 2:
                        return None, None
                    length = struct.unpack(">H", length_raw)[0]
                    if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        body = handle.read(5)
                        if len(body) < 5:
                            return None, None
                        height, width = struct.unpack(">HH", body[1:5])
                        return width, height
                    handle.seek(length - 2, os.SEEK_CUR)
    except (OSError, struct.error):
        return None, None
    return None, None


# --------------------------------------------------------------------------- #
# configuration (documented env var, repo template, sensible default)
# --------------------------------------------------------------------------- #
def load_config(path: Path | None = None) -> dict[str, Any]:
    data = read_json(path or CONFIG_PATH, {}) or {}
    return data if isinstance(data, dict) else {}


def default_root(config: dict[str, Any] | None = None) -> Path:
    config = load_config() if config is None else config
    relative = str(config.get("default_root_relative_to_home") or ".qingshan/studio_asset_library")
    return Path.home() / relative


def resolve_root(explicit: str | Path | None = None, *, env: dict[str, str] | None = None,
                 config: dict[str, Any] | None = None, allow_default: bool = True) -> Path | None:
    """--root > $QINGSHAN_STUDIO_ASSET_ROOT > (config.enabled or explicit CLI use) default under $HOME."""
    env = os.environ if env is None else env
    if explicit:
        return Path(explicit).expanduser()
    value = (env.get(ENV_ROOT) or "").strip()
    if value:
        return Path(value).expanduser()
    config = load_config() if config is None else config
    if allow_default and bool(config.get("enabled")):
        return default_root(config)
    return None


def active_root(*, env: dict[str, str] | None = None) -> Path | None:
    """The root the production hooks use.  None = the studio library is not enabled (hooks no-op).

    Enabling is deliberate: set $QINGSHAN_STUDIO_ASSET_ROOT, or ship ``enabled: true`` in the config.
    """
    return resolve_root(env=env)


def hook_enabled(name: str, config: dict[str, Any] | None = None) -> bool:
    config = load_config() if config is None else config
    return bool((config.get("auto_archive") or {}).get(name, True))


# --------------------------------------------------------------------------- #
# origin scrubbing: no absolute local paths, no signed URLs in anything shareable
# --------------------------------------------------------------------------- #
_ABS_RE = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"url", "signed_url", "download_url", "presigned_url"} or "secret" in lowered \
                    or "access_key" in lowered or "api_key" in lowered or "token" in lowered:
                out[f"{key}_redacted"] = True
                continue
            out[str(key)] = scrub(item)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        if "X-Amz-Signature" in value or "x-amz-signature" in value:
            return "REDACTED_SIGNED_URL"
        if _ABS_RE.match(value):
            return "LOCAL_PATH_REDACTED:" + re.split(r"[\\/]", value.rstrip("\\/"))[-1]
        return value
    return value


# --------------------------------------------------------------------------- #
# the library
# --------------------------------------------------------------------------- #
class Library:
    """One studio root.  Cheap to construct; every method touches only the files it names."""

    def __init__(self, root: str | Path, *, create: bool = True) -> None:
        self.root = Path(root).expanduser()
        self.objects_dir = self.root / "objects" / "sha256"
        self.catalog = self.root / "catalog"
        self.tmp_dir = self.root / "tmp"
        self.locks_dir = self.root / "locks"
        self._verified: dict[tuple[str, int, int], str] = {}
        self._verified_lock = threading.Lock()
        if create:
            self.init()
        elif not (self.root / "library.json").is_file():
            raise StudioError(f"LIBRARY_NOT_INITIALISED:{self.root.name}")

    # -- layout ------------------------------------------------------------- #
    def init(self) -> dict[str, Any]:
        for sub in ("objects/sha256", "catalog/objects", "catalog/assets", "catalog/bindings",
                    "catalog/legacy", "catalog/usage", "catalog/used_by", "backup/queue",
                    "backup/receipts", "backup/restore_requests", "tmp", "locks", "thumbs", "index",
                    "work_cache", "reports"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        meta = self.root / "library.json"
        with file_lock(self.locks_dir / "library_meta.lock"):
            record = read_json(meta)
            if record is None:
                record = {"schema": SCHEMA_LIBRARY, "library_id": uuid.uuid4().hex, "created_at": utc_now(),
                          "layout": "objects/sha256/<2>/<sha>.<ext>"}
                atomic_write_json(meta, record)
        return record

    @property
    def library_id(self) -> str:
        return str((read_json(self.root / "library.json", {}) or {}).get("library_id") or "")

    def lock(self, key: str) -> contextlib.AbstractContextManager[None]:
        digest = sha256_bytes(key.encode("utf-8"))
        return file_lock(self.locks_dir / digest[:2] / f"{digest}.lock")

    def object_dir(self, sha: str) -> Path:
        return self.objects_dir / sha[:2]

    def object_record_path(self, sha: str) -> Path:
        return self.catalog / "objects" / sha[:2] / f"{sha}.json"

    def find_object(self, sha: str) -> Path | None:
        directory = self.object_dir(sha)
        if not directory.is_dir():
            return None
        for entry in sorted(directory.iterdir()):
            if entry.name.startswith(sha + ".") and not entry.name.endswith(".tmp"):
                return entry
        return None

    def object_key_for(self, sha: str, ext: str) -> str:
        return f"objects/sha256/{sha[:2]}/{sha}.{ext}"

    # -- originals ---------------------------------------------------------- #
    def ingest_file(self, source: str | Path, *, origin: dict[str, Any] | None = None) -> dict[str, Any]:
        """Archive the ORIGINAL bytes of ``source`` (copied, never linked, never re-encoded).

        Safe to call concurrently for the same bytes from independent processes: the copy goes to a
        private temp file first, then a per-object lock decides who places it; the loser verifies
        the placed object instead of writing a second one.
        """
        source = Path(source)
        if not source.is_file():
            raise StudioError(f"SOURCE_NOT_A_FILE:{source.name}")
        # Fast path (incremental, no copy): bytes already archived and verified in this process.
        size_now = source.stat().st_size
        source_sha = sha256_file(source)
        existing = self.find_object(source_sha)
        if existing is not None and not existing.is_symlink() and existing.stat().st_size == size_now:
            stat = existing.stat()
            with self._verified_lock:
                known = (source_sha, stat.st_mtime_ns, stat.st_size) in self._verified
            if known or sha256_file(existing) == source_sha:
                with self._verified_lock:
                    self._verified[(source_sha, stat.st_mtime_ns, stat.st_size)] = source_sha
                with self.lock(f"obj:{source_sha}"):
                    record = self._merge_object_record(source_sha, existing.suffix.lstrip("."), size_now, origin)
                self._enqueue_object(source_sha)
                return {**record, "created": False, "repaired": False, "object_path": str(existing)}
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        head = b""
        handle = tempfile.NamedTemporaryFile(dir=self.tmp_dir, prefix="ingest-", suffix=".part", delete=False)
        tmp_path = Path(handle.name)
        try:
            with handle, open(source, "rb") as reader:
                for chunk in iter(lambda: reader.read(CHUNK), b""):
                    if not head:
                        head = chunk[:32]
                    digest.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise StudioError("EMPTY_SOURCE_REFUSED")
            sha = digest.hexdigest()
            if sha != source_sha:
                raise StudioError("SOURCE_CHANGED_DURING_INGEST")
            suffix = source.suffix.lower().lstrip(".")
            ext = suffix if EXT_RE.match(suffix) else sniff_extension(head)
            repaired = False
            with self.lock(f"obj:{sha}"):
                existing = self.find_object(sha)
                if existing is not None and not existing.is_symlink() and existing.stat().st_size == size \
                        and sha256_file(existing) == sha:
                    ext = existing.suffix.lstrip(".")
                    created = False
                else:
                    if existing is not None:  # damaged / linked / truncated: heal from the verified source copy
                        repaired = True
                        with contextlib.suppress(OSError):
                            existing.unlink()
                    final = self.object_dir(sha) / f"{sha}.{ext}"
                    final.parent.mkdir(parents=True, exist_ok=True)
                    os.chmod(tmp_path, 0o444)
                    os.replace(tmp_path, final)
                    _fsync_dir(final.parent)
                    created = True
                record = self._merge_object_record(sha, ext, size, origin)
            self._enqueue_object(sha)  # durable per-object todo; a no-op while no backup target is configured
            return {**record, "created": created, "repaired": repaired,
                    "object_path": str(self.object_dir(sha) / f"{sha}.{record['ext']}")}
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink()

    def _merge_object_record(self, sha: str, ext: str, size: int, origin: dict[str, Any] | None) -> dict[str, Any]:
        path = self.object_record_path(sha)
        record = read_json(path)
        if record is None:
            width, height = image_size(self.object_dir(sha) / f"{sha}.{ext}")
            record = {"schema": SCHEMA_OBJECT, "content_sha256": sha, "bytes": size, "ext": ext,
                      "media_type": MEDIA_TYPES.get(ext, "application/octet-stream"), "width": width,
                      "height": height, "object_key": self.object_key_for(sha, ext),
                      "first_seen_at": utc_now(), "origins": []}
        elif record.get("bytes") != size:
            raise StudioError(f"OBJECT_RECORD_SIZE_CONFLICT:{sha[:12]}")
        changed = False
        if origin:
            clean = scrub(origin)
            key = sha256_bytes(canonical(clean).encode("utf-8"))
            if key not in {sha256_bytes(canonical(item).encode("utf-8")) for item in record["origins"]} \
                    and len(record["origins"]) < MAX_ORIGINS:
                record["origins"].append(clean)
                changed = True
        if changed or not path.is_file():
            atomic_write_json(path, record)
        return record

    def object_record(self, sha: str) -> dict[str, Any] | None:
        return read_json(self.object_record_path(sha))

    def verify_object(self, sha: str) -> tuple[Path | None, str]:
        """(path, state) with state OK / MISSING / CORRUPT / LINKED.  Hashes the bytes."""
        path = self.find_object(sha)
        if path is None:
            return None, "MISSING"
        if path.is_symlink():
            return path, "LINKED"
        record = self.object_record(sha)
        if record and record.get("bytes") != path.stat().st_size:
            return path, "CORRUPT"
        return (path, "OK") if sha256_file(path) == sha else (path, "CORRUPT")

    def _verified_path(self, sha: str) -> Path:
        """Object path whose bytes were verified in this process (mtime+size memo keeps S5 loops cheap)."""
        path = self.find_object(sha)
        if path is None:
            self.request_restore(sha, reason="OBJECT_MISSING_ON_RESOLVE")
            raise StudioError(f"OBJECT_MISSING:{sha[:12]}")
        stat = path.stat()
        key = (sha, stat.st_mtime_ns, stat.st_size)
        with self._verified_lock:
            if key in self._verified and not path.is_symlink():
                return path
        if path.is_symlink() or sha256_file(path) != sha:
            self.request_restore(sha, reason="OBJECT_CORRUPT_ON_RESOLVE")
            raise StudioError(f"OBJECT_CORRUPT:{sha[:12]}")
        with self._verified_lock:
            self._verified[key] = sha
        return path

    def request_restore(self, sha: str, *, reason: str) -> None:
        """Record that this object is needed locally.  Never a provider call; never a regeneration."""
        path = self.root / "backup" / "restore_requests" / f"{sha}.json"
        if not path.exists():
            atomic_write_json(path, {"content_sha256": sha, "reason": reason, "requested_at": utc_now(),
                                     "action": "RESTORE_FROM_VERIFIED_BACKUP_OR_PROVIDE_SOURCE",
                                     "automatic_regeneration": False})

    def materialize(self, sha: str, cache_dir: str | Path | None = None, *, name: str | None = None) -> Path:
        """A working COPY of the original (never a link) under ``cache_dir``; re-copied if damaged."""
        if not is_sha256(sha):
            raise StudioError("SHA_INVALID")
        master = self._verified_path(sha)
        base = Path(cache_dir) if cache_dir else Path(os.environ.get(ENV_CACHE) or (self.root / "work_cache"))
        file_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name or master.name) or master.name
        dest = base / sha[:12] / file_name
        if dest.is_file() and not dest.is_symlink() and dest.stat().st_size == master.stat().st_size \
                and sha256_file(dest) == sha:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            shutil.copyfile(master, tmp)
            if sha256_file(tmp) != sha:
                raise StudioError(f"COPY_VERIFY_FAILED:{sha[:12]}")
            os.replace(tmp, dest)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return dest

    # -- assets and versions ------------------------------------------------ #
    def asset_dir(self, asset_id: str) -> Path:
        return self.catalog / "assets" / asset_id

    @staticmethod
    def _version_name(version: int) -> str:
        return f"v{version:04d}"

    def version_path(self, asset_id: str, version: int) -> Path:
        return self.asset_dir(asset_id) / f"{self._version_name(version)}.json"

    def review_path(self, asset_id: str, version: int) -> Path:
        return self.asset_dir(asset_id) / f"{self._version_name(version)}.review.json"

    def versions_of(self, asset_id: str) -> list[int]:
        directory = self.asset_dir(asset_id)
        if not directory.is_dir():
            return []
        found = []
        for entry in directory.iterdir():
            match = re.fullmatch(r"v(\d{4})\.json", entry.name)
            if match:
                found.append(int(match.group(1)))
        return sorted(found)

    def get_version(self, asset_id: str, version: int) -> dict[str, Any]:
        manifest = read_json(self.version_path(asset_id, version))
        if manifest is None:
            raise StudioError(f"VERSION_NOT_FOUND:{asset_id}@v{version}")
        return manifest

    def get_review(self, asset_id: str, version: int) -> dict[str, Any]:
        review = read_json(self.review_path(asset_id, version))
        if review is None:
            return {"schema": SCHEMA_REVIEW, "asset_id": asset_id, "version": version,
                    "review_status": "UNREVIEWED", "review_ref": None, "history": []}
        return review

    @staticmethod
    def content_set_sha(category: str, artifacts: list[dict[str, Any]]) -> str:
        rows = sorted([str(a["usage"]), str(a["content_sha256"])] for a in artifacts)
        return sha256_bytes(canonical({"category": category, "artifacts": rows}).encode("utf-8"))

    def register_version(self, *, category: str, label: str, artifacts: Iterable[dict[str, Any]],
                         tags: Iterable[str] = (), origin: dict[str, Any] | None = None,
                         parent_asset: dict[str, Any] | None = None,
                         transformation: dict[str, Any] | None = None,
                         asset_id: str | None = None, version: int | None = None,
                         kind: str = "GROUP", review: dict[str, Any] | None = None,
                         created_at: str | None = None) -> dict[str, Any]:
        """Create (or find) an immutable asset version.

        ``artifacts`` rows: {usage, path | sha256, view?}.  Same bytes set under the same asset id is
        the same version (idempotent, concurrent-safe).  A different content set under an explicit,
        already-used version number is a conflict.
        """
        if category not in CATEGORIES:
            raise StudioError(f"CATEGORY_INVALID:{category}")
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(artifacts):
            usage = str(item.get("usage") or "").strip()
            if not usage:
                raise StudioError(f"ARTIFACT_USAGE_REQUIRED:{index}")
            sha = item.get("sha256")
            if item.get("path"):
                record = self.ingest_file(item["path"], origin=origin)
                if sha and sha != record["content_sha256"]:
                    raise StudioError(f"ARTIFACT_SHA_MISMATCH:{usage}")
                sha = record["content_sha256"]
            if not is_sha256(sha):
                raise StudioError(f"ARTIFACT_SHA_REQUIRED:{usage}")
            record = self.object_record(sha)
            if record is None or self.find_object(sha) is None:
                raise StudioError(f"ARTIFACT_OBJECT_NOT_IN_LIBRARY:{usage}:{sha[:12]}")
            rows.append({"usage": usage, "view": item.get("view") or usage, "content_sha256": sha,
                         "bytes": record["bytes"], "media_type": record["media_type"],
                         "width": record.get("width"), "height": record.get("height"),
                         "object_key": record["object_key"]})
        if not rows:
            raise StudioError("ARTIFACTS_REQUIRED")
        seen = set()
        for row in rows:
            key = (row["usage"], row["content_sha256"])
            if key in seen:
                raise StudioError(f"ARTIFACT_DUPLICATE:{row['usage']}")
            seen.add(key)
        if parent_asset is not None:
            self._check_parent(parent_asset)
        asset_id = asset_id or f"AST-{rows[0]['content_sha256'][:16]}"
        if not ID_RE.match(asset_id):
            raise StudioError(f"ASSET_ID_INVALID:{asset_id}")
        content_set = self.content_set_sha(category, rows)
        with self.lock(f"asset:{asset_id}"):
            existing = self.versions_of(asset_id)
            for number in existing:
                manifest = self.get_version(asset_id, number)
                if manifest.get("content_set_sha256") == content_set:
                    if version not in (None, number):
                        raise StudioError(f"CONTENT_ALREADY_REGISTERED_AT_OTHER_VERSION:{asset_id}@v{number}")
                    return {"asset_id": asset_id, "version": number, "created": False, "manifest": manifest,
                            "review": self.get_review(asset_id, number)}
            if existing and self.get_version(asset_id, existing[0]).get("category") != category:
                raise StudioError(f"ASSET_CATEGORY_MISMATCH:{asset_id}")
            if version is not None:
                if version in existing:
                    raise StudioError(f"VERSION_CONTENT_CONFLICT:{asset_id}@v{version}")
                number = int(version)
            else:
                number = (existing[-1] + 1) if existing else 1
            for position, row in enumerate(rows, 1):
                row["artifact_id"] = f"{asset_id}/{self._version_name(number)}/{position:02d}-{row['usage']}"
            manifest = {"schema": SCHEMA_VERSION, "asset_id": asset_id, "version": number, "kind": kind,
                        "category": category, "label": str(label or asset_id), "tags": sorted({str(t) for t in tags}),
                        "content_set_sha256": content_set, "artifacts": rows,
                        "origin": scrub(origin or {}), "parent_asset": scrub(parent_asset) if parent_asset else None,
                        "transformation": scrub(transformation) if transformation else None,
                        "created_at": created_at or utc_now(), "library_id": self.library_id}
            atomic_write_json(self.version_path(asset_id, number), manifest)
            initial = review or {}
            self._write_review(asset_id, number, initial.get("status") or "UNREVIEWED", initial.get("ref"),
                               initial.get("reviewer"), "REGISTERED", None)
        self._enqueue_catalog(self.version_path(asset_id, number))
        self._enqueue_catalog(self.review_path(asset_id, number), snapshot=True)
        return {"asset_id": asset_id, "version": number, "created": True, "manifest": manifest,
                "review": self.get_review(asset_id, number)}

    def _check_parent(self, parent: dict[str, Any]) -> None:
        asset_id, version = parent.get("asset_id"), parent.get("version")
        if not asset_id or not isinstance(version, int):
            raise StudioError("PARENT_REFERENCE_INVALID")
        manifest = read_json(self.version_path(str(asset_id), version))
        if manifest is None:
            raise StudioError(f"PARENT_NOT_FOUND:{asset_id}@v{version}")
        sha = parent.get("artifact_sha256")
        if sha and sha not in {a["content_sha256"] for a in manifest["artifacts"]}:
            raise StudioError("PARENT_ARTIFACT_NOT_IN_PARENT_VERSION")

    def register_derivative(self, parent_sha: str, source: str | Path, transformation: dict[str, Any], *,
                            usage: str = "DERIVED", label: str | None = None,
                            origin: dict[str, Any] | None = None) -> dict[str, Any]:
        """A crop / resize / re-encode / re-pose output: its own asset, parent kept, never overwrites."""
        if not is_sha256(parent_sha) or self.object_record(parent_sha) is None:
            raise StudioError("PARENT_OBJECT_NOT_IN_LIBRARY")
        if not isinstance(transformation, dict) or not transformation.get("operation"):
            raise StudioError("TRANSFORMATION_OPERATION_REQUIRED")
        found = self.assets_containing(parent_sha)
        parent = ({"asset_id": found[0][0], "version": found[0][1], "artifact_sha256": parent_sha}
                  if found else {"asset_id": None, "version": None, "artifact_sha256": parent_sha})
        record = self.ingest_file(source, origin=origin)
        if record["content_sha256"] == parent_sha:
            raise StudioError("DERIVATIVE_IDENTICAL_TO_PARENT_BYTES")
        transformation = {**transformation, "source_sha256": parent_sha}
        if parent["asset_id"] is None:  # parent bytes exist but belong to no asset yet: keep the sha lineage
            manifest_parent = None
            transformation["parent_artifact_sha256"] = parent_sha
        else:
            manifest_parent = parent
        return self.register_version(category="reference_materials", label=label or "derived", kind="DERIVATIVE",
                                     artifacts=[{"usage": usage, "sha256": record["content_sha256"]}],
                                     origin=origin, parent_asset=manifest_parent, transformation=transformation)

    def assets_containing(self, sha: str) -> list[tuple[str, int]]:
        """Assets whose versions list this sha (admin lookup; scans catalog/assets)."""
        out: list[tuple[str, int]] = []
        for asset_id, version, manifest in self.iter_versions():
            if any(a["content_sha256"] == sha for a in manifest["artifacts"]):
                out.append((asset_id, version))
        return out

    def iter_versions(self) -> Iterator[tuple[str, int, dict[str, Any]]]:
        base = self.catalog / "assets"
        if not base.is_dir():
            return
        for asset_dir in sorted(base.iterdir()):
            if not asset_dir.is_dir():
                continue
            for version in self.versions_of(asset_dir.name):
                manifest = read_json(self.version_path(asset_dir.name, version))
                if manifest:
                    yield asset_dir.name, version, manifest

    # -- review ------------------------------------------------------------- #
    def _write_review(self, asset_id: str, version: int, status: str, ref: dict[str, Any] | None,
                      reviewer: str | None, note: str, mirrored_into: dict[str, Any] | None) -> dict[str, Any]:
        if status not in REVIEW_STATUSES:
            raise StudioError(f"REVIEW_STATUS_INVALID:{status}")
        if status == "APPROVED":
            if not isinstance(ref, dict) or not ref.get("kind") or not is_sha256(ref.get("sha256")):
                raise StudioError("APPROVAL_REQUIRES_REVIEW_REFERENCE_WITH_SHA256")
        path = self.review_path(asset_id, version)
        current = read_json(path)
        ref = scrub(ref) if ref else None
        if current is not None and current.get("review_status") == status and current.get("review_ref") == ref:
            return current
        history = list((current or {}).get("history") or [])
        history.append({"status": status, "at": utc_now(), "reviewer": reviewer, "note": note, "ref": ref})
        review = {"schema": SCHEMA_REVIEW, "asset_id": asset_id, "version": version, "review_status": status,
                  "review_ref": ref, "reviewer": reviewer, "history": history, "updated_at": utc_now()}
        if mirrored_into:
            review["mirrored_into"] = mirrored_into
        atomic_write_json(path, review)
        return review

    def set_review(self, asset_id: str, version: int, status: str, ref: dict[str, Any] | None = None,
                   reviewer: str | None = None, note: str = "") -> dict[str, Any]:
        self.get_version(asset_id, version)
        with self.lock(f"asset:{asset_id}"):
            review = self._write_review(asset_id, version, status, ref, reviewer, note, None)
        self._enqueue_catalog(self.review_path(asset_id, version), snapshot=True)
        return review

    def mirror_pending_singles(self, artifact_shas: Iterable[str], status: str, ref: dict[str, Any] | None,
                               into: dict[str, Any]) -> list[str]:
        """Harvest-time single-image records (PND-<sha16>) follow the verdict of the group that adopted them."""
        touched = []
        for sha in artifact_shas:
            pid = f"PND-{sha[:16]}"
            for version in self.versions_of(pid):
                with self.lock(f"asset:{pid}"):
                    self._write_review(pid, version, status, ref, "studio_hook", "MIRRORED_FROM_GROUP", into)
                touched.append(f"{pid}@v{version}")
        return touched

    # -- project bindings --------------------------------------------------- #
    def binding_path(self, project_id: str, kind: str, role_id: str) -> Path:
        return self.catalog / "bindings" / project_id / f"{kind}__{role_id}.json"

    @staticmethod
    def _check_ids(project_id: str, kind: str, role_id: str) -> None:
        if not ID_RE.match(str(project_id or "")):
            raise StudioError(f"PROJECT_ID_INVALID:{project_id}")
        if kind not in KINDS:
            raise StudioError(f"BINDING_KIND_INVALID:{kind}")
        if not ID_RE.match(str(role_id or "")):
            raise StudioError(f"ROLE_ID_INVALID:{role_id}")

    def bind(self, project_id: str, kind: str, role_id: str, asset_id: str, version: int, *,
             usages: Iterable[str] | None = None, project_fields: dict[str, Any] | None = None,
             rebind: bool = False, allow_unapproved: bool = False) -> dict[str, Any]:
        """Bind one asset VERSION to one role of ONE project.  Pins the artifact shas.

        Nothing from another project is inherited: ``project_fields`` is whatever THIS project says
        about the role (name, relationship, wardrobe, voice) and starts empty.
        """
        self._check_ids(project_id, kind, role_id)
        manifest = self.get_version(asset_id, version)
        review = self.get_review(asset_id, version)
        if review["review_status"] != "APPROVED" and not allow_unapproved:
            raise StudioError(f"VERSION_NOT_APPROVED:{asset_id}@v{version}:{review['review_status']}")
        wanted = set(usages) if usages else None
        pins = [{"artifact_id": a["artifact_id"], "usage": a["usage"], "content_sha256": a["content_sha256"]}
                for a in manifest["artifacts"] if wanted is None or a["usage"] in wanted]
        if wanted and {p["usage"] for p in pins} != wanted:
            raise StudioError(f"USAGE_NOT_IN_VERSION:{sorted(wanted - {p['usage'] for p in pins})}")
        if not pins:
            raise StudioError("NO_ARTIFACT_PINNED")
        origin_projects = sorted({str(manifest.get("origin", {}).get("project_id"))}
                                 - {"None", ""}) if manifest.get("origin") else []
        path = self.binding_path(project_id, kind, role_id)
        with self.lock(f"binding:{project_id}:{kind}:{role_id}"):
            current = read_json(path)
            same = (current is not None and current["asset_id"] == asset_id and current["version"] == version
                    and current["pins"] == pins)
            if current is not None and not same and not rebind:
                raise StudioError(f"BINDING_CONFLICT_REBIND_REQUIRED:{project_id}:{kind}:{role_id}")
            fields = dict(project_fields) if project_fields is not None else dict((current or {}).get("project_fields") or {})
            history = list((current or {}).get("history") or [])
            if not same:
                if current is not None:
                    history.append({"asset_id": current["asset_id"], "version": current["version"],
                                    "replaced_at": utc_now()})
            elif current.get("project_fields") == fields:
                return current
            binding = {"schema": SCHEMA_BINDING, "project_id": project_id, "kind": kind, "role_id": role_id,
                       "asset_id": asset_id, "version": version, "pins": pins, "project_fields": fields,
                       "provenance": {"origin_projects": origin_projects,
                                      "cross_project": bool(origin_projects and project_id not in origin_projects),
                                      "inherits_nothing_but_the_pinned_original": True},
                       "revision": (int(current.get("revision") or 1) + (0 if same else 1)) if current else 1,
                       "history": history, "bound_at": (current or {}).get("bound_at") if same else utc_now(),
                       "updated_at": utc_now()}
            atomic_write_json(path, binding)
            atomic_write_json(self.catalog / "used_by" / asset_id / f"{project_id}__{kind}__{role_id}.json",
                              {"asset_id": asset_id, "version": version, "project_id": project_id,
                               "kind": kind, "role_id": role_id, "bound_at": binding["bound_at"]})
        self._enqueue_catalog(path, snapshot=True)
        return binding

    def get_binding(self, project_id: str, kind: str, role_id: str) -> dict[str, Any] | None:
        self._check_ids(project_id, kind, role_id)
        return read_json(self.binding_path(project_id, kind, role_id))

    def resolve_binding(self, project_id: str, kind: str, role_id: str, *, usage: str | None = None,
                        cache_dir: str | Path | None = None, copy: bool = True) -> list[dict[str, Any]]:
        """Pinned originals for ONE project's role: local path + sha.  Only the pinned version is
        ever returned (a newer recommended version never leaks in) and a usage that was not pinned
        is an error, never a substitute."""
        binding = self.get_binding(project_id, kind, role_id)
        if binding is None:
            raise StudioError(f"BINDING_NOT_FOUND:{project_id}:{kind}:{role_id}")
        pins = binding["pins"]
        if usage is not None:
            pins = [p for p in pins if p["usage"] == usage]
            if not pins:
                raise StudioError(f"USAGE_NOT_PINNED:{usage}")
        out = []
        for pin in pins:
            sha = pin["content_sha256"]
            path = self.materialize(sha, cache_dir) if copy else self._verified_path(sha)
            out.append({**pin, "asset_id": binding["asset_id"], "version": binding["version"],
                        "path": str(path), "source": "STUDIO_OBJECT_COPY" if copy else "STUDIO_OBJECT"})
        return out

    def recommended_version(self, asset_id: str) -> int | None:
        """Highest APPROVED version.  Informational: bindings pin versions and never follow this."""
        approved = [v for v in self.versions_of(asset_id) if self.get_review(asset_id, v)["review_status"] == "APPROVED"]
        return approved[-1] if approved else None

    def used_by(self, asset_id: str) -> list[dict[str, Any]]:
        base = self.catalog / "used_by" / asset_id
        return [read_json(p) for p in sorted(base.glob("*.json"))] if base.is_dir() else []

    def record_usage(self, project_id: str, episode: str, asset_id: str, version: int, artifact_id: str,
                     purpose: str) -> None:
        """Append one episode-usage row (O_APPEND: a single small write is atomic)."""
        if not ID_RE.match(str(project_id)) or not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", str(episode)):
            raise StudioError("USAGE_IDS_INVALID")
        path = self.catalog / "usage" / project_id / f"{episode}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical({"at": utc_now(), "asset_id": asset_id, "version": version, "artifact_id": artifact_id,
                          "purpose": purpose}) + "\n"
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    # -- legacy compatibility map ------------------------------------------- #
    def legacy_path(self, sha: str) -> Path:
        return self.catalog / "legacy" / sha[:2] / f"{sha}.json"

    def add_legacy_entry(self, sha: str, old_path: str, *, project_id: str | None, asset_id: str | None,
                         version: int | None, artifact_id: str | None, source: str) -> None:
        """old path + sha -> asset (local-only index; never exported, never rewrites the old record)."""
        with self.lock(f"legacy:{sha}"):
            path = self.legacy_path(sha)
            record = read_json(path) or {"content_sha256": sha, "entries": []}
            entry = {"old_path": str(old_path), "project_id": project_id, "asset_id": asset_id,
                     "version": version, "artifact_id": artifact_id, "source": source}
            keys = {(e["old_path"], e.get("asset_id"), e.get("version")) for e in record["entries"]}
            if (entry["old_path"], asset_id, version) not in keys:
                record["entries"].append({**entry, "recorded_at": utc_now()})
                atomic_write_json(path, record)

    def resolve_legacy(self, old_path: str | Path | None, sha: str, *, cache_dir: str | Path | None = None,
                       name: str | None = None) -> dict[str, Any]:
        """Same bytes as the old record, from wherever they still are.  Only a matching sha is accepted."""
        if not is_sha256(sha):
            raise StudioError("SHA_INVALID")
        if old_path:
            candidate = Path(str(old_path))
            if candidate.is_file() and not candidate.is_symlink() and sha256_file(candidate) == sha:
                return {"status": "OLD_PATH_VERIFIED", "path": str(candidate), "sha256": sha}
        base_name = name or (Path(str(old_path)).name if old_path else None)
        try:
            path = self.materialize(sha, cache_dir, name=base_name)
        except StudioError as exc:
            return {"status": "UNRESOLVED", "reason": exc.code, "sha256": sha}
        record = read_json(self.legacy_path(sha)) or {}
        registered = any(e["old_path"] == str(old_path) for e in record.get("entries", [])) if old_path else False
        return {"status": "STUDIO_OBJECT_COPY", "path": str(path), "sha256": sha,
                "old_path_registered": registered, "assets": [
                    {"asset_id": e.get("asset_id"), "version": e.get("version")} for e in record.get("entries", [])]}

    # -- search / show ------------------------------------------------------ #
    def search(self, *, text: str | None = None, category: str | None = None, tags: Iterable[str] = (),
               usage: str | None = None, status: str = "APPROVED", project: str | None = None,
               include_pending_singles: bool = False) -> list[dict[str, Any]]:
        """Latest matching version per asset.  Default = APPROVED only (selectable)."""
        wanted_tags = {t.lower() for t in tags}
        needle = (text or "").lower()
        rows: list[dict[str, Any]] = []
        for asset_id, version, manifest in self.iter_versions():
            review = self.get_review(asset_id, version)
            if status != "ANY" and review["review_status"] != status:
                continue
            if manifest.get("kind") == "HARVEST_PENDING" and not include_pending_singles and status == "APPROVED":
                continue
            if category and manifest["category"] != category:
                continue
            if usage and usage not in {a["usage"] for a in manifest["artifacts"]}:
                continue
            haystack = " ".join([asset_id, manifest["label"], " ".join(manifest["tags"]),
                                 " ".join(a["usage"] for a in manifest["artifacts"])]).lower()
            if needle and needle not in haystack:
                continue
            if wanted_tags and not wanted_tags <= {t.lower() for t in manifest["tags"]}:
                continue
            used = self.used_by(asset_id)
            if project and project not in {u["project_id"] for u in used}:
                continue
            rows.append({"asset_id": asset_id, "version": version, "label": manifest["label"],
                         "category": manifest["category"], "tags": manifest["tags"], "kind": manifest.get("kind"),
                         "review_status": review["review_status"], "usages": [a["usage"] for a in manifest["artifacts"]],
                         "primary_sha256": manifest["artifacts"][0]["content_sha256"],
                         "used_by_projects": sorted({u["project_id"] for u in used}),
                         "recommended": self.recommended_version(asset_id) == version})
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest[row["asset_id"]] = row
        return sorted(latest.values(), key=lambda r: (r["category"], r["label"], r["asset_id"]))

    # -- integrity ---------------------------------------------------------- #
    def verify(self, *, full: bool = True) -> dict[str, Any]:
        """Whole-library check (admin command; never run on the production path)."""
        report: dict[str, Any] = {"objects_checked": 0, "ok": 0, "missing": [], "corrupt": [], "linked": [],
                                  "unrecorded_files": [], "manifest_problems": [], "binding_problems": []}
        recorded: set[str] = set()
        for record_file in sorted((self.catalog / "objects").glob("*/*.json")):
            record = read_json(record_file) or {}
            sha = str(record.get("content_sha256") or "")
            recorded.add(sha)
            report["objects_checked"] += 1
            path, state = self.verify_object(sha) if full else (self.find_object(sha), "OK")
            if state == "OK" and path is not None:
                report["ok"] += 1
            elif state == "MISSING" or path is None:
                report["missing"].append(sha)
            elif state == "LINKED":
                report["linked"].append(sha)
            else:
                report["corrupt"].append(sha)
        if self.objects_dir.is_dir():
            for entry in self.objects_dir.glob("*/*"):
                if entry.is_file() and entry.name.split(".")[0] not in recorded:
                    report["unrecorded_files"].append(entry.name)
        for asset_id, version, manifest in self.iter_versions():
            recomputed = self.content_set_sha(manifest["category"], manifest["artifacts"])
            if recomputed != manifest.get("content_set_sha256"):
                report["manifest_problems"].append(f"{asset_id}@v{version}:CONTENT_SET_SHA_MISMATCH")
            for artifact in manifest["artifacts"]:
                if artifact["content_sha256"] not in recorded:
                    report["manifest_problems"].append(f"{asset_id}@v{version}:OBJECT_RECORD_ABSENT")
        for binding_file in sorted((self.catalog / "bindings").glob("*/*.json")):
            binding = read_json(binding_file) or {}
            try:
                manifest = self.get_version(binding["asset_id"], binding["version"])
            except StudioError:
                report["binding_problems"].append(f"{binding_file.name}:PINNED_VERSION_MISSING")
                continue
            shas = {a["content_sha256"] for a in manifest["artifacts"]}
            if any(p["content_sha256"] not in shas for p in binding["pins"]):
                report["binding_problems"].append(f"{binding_file.name}:PIN_NOT_IN_VERSION")
        report["status"] = "PASS" if not (report["missing"] or report["corrupt"] or report["linked"]
                                         or report["manifest_problems"] or report["binding_problems"]) else "FAIL"
        return report

    def repair_object(self, sha: str, candidates: Iterable[str | Path]) -> dict[str, Any]:
        """Replace a damaged / missing master from candidate files.  Only a sha match is accepted."""
        rejected: list[dict[str, str]] = []
        for candidate in candidates:
            candidate = Path(candidate)
            if not candidate.is_file():
                rejected.append({"candidate": candidate.name, "reason": "NOT_A_FILE"})
                continue
            if sha256_file(candidate) != sha:
                rejected.append({"candidate": candidate.name, "reason": "SHA_MISMATCH_REJECTED"})
                continue
            record = self.ingest_file(candidate)
            return {"status": "REPAIRED", "content_sha256": sha, "repaired": record["repaired"],
                    "created": record["created"], "rejected": rejected}
        return {"status": "NOT_REPAIRED", "content_sha256": sha, "rejected": rejected}

    # -- hooks into the backup subsystem (local queue only; no network here) -- #
    def _enqueue_catalog(self, path: Path, *, snapshot: bool = False) -> None:
        try:
            from tools import studio_asset_backup as backup  # noqa: PLC0415
        except ImportError:  # pragma: no cover - flat tools/ on sys.path
            import studio_asset_backup as backup  # type: ignore[no-redef]
        backup.enqueue_catalog_file(self, path, snapshot=snapshot)

    def _enqueue_object(self, sha: str) -> None:
        try:
            from tools import studio_asset_backup as backup  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            import studio_asset_backup as backup  # type: ignore[no-redef]
        backup.enqueue_object(self, sha)

    # -- thumbnails and the openable index ---------------------------------- #
    def thumbnail(self, sha: str, size: int = 256) -> Path | None:
        out = self.root / "thumbs" / f"{sha}.jpg"
        if out.is_file():
            return out
        source = self.find_object(sha)
        if source is None:
            return None
        tmp = out.with_suffix(".tmp.jpg")
        commands = []
        if shutil.which("ffmpeg"):
            commands.append(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vf",
                             f"scale='min({size},iw)':-2", "-frames:v", "1", str(tmp)])
        if shutil.which("sips"):
            commands.append(["sips", "-Z", str(size), "-s", "format", "jpeg", str(source), "--out", str(tmp)])
        for command in commands:
            try:
                done = subprocess.run(command, capture_output=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if done.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
                os.replace(tmp, out)
                return out
            with contextlib.suppress(OSError):
                tmp.unlink()
        return None

    def build_index(self, out_dir: str | Path | None = None, *, status: str = "APPROVED",
                    thumbnails: bool = True) -> Path:
        """A static, openable HTML catalogue with thumbnails.  The thumbnail is a derivative for
        looking at; the original is the object it links to, never replaced by the thumbnail."""
        out_dir = Path(out_dir) if out_dir else self.root / "index"
        out_dir.mkdir(parents=True, exist_ok=True)
        rows = self.search(status=status, include_pending_singles=(status != "APPROVED"))
        cards = []
        for row in rows:
            sha = row["primary_sha256"]
            thumb = self.thumbnail(sha) if thumbnails else None
            original = self.find_object(sha)
            rel_original = os.path.relpath(original, out_dir) if original else ""
            rel_thumb = os.path.relpath(thumb, out_dir) if thumb else rel_original
            safe = {k: html.escape(str(v)) for k, v in row.items() if not isinstance(v, (list, bool))}
            cards.append(
                f'<div class="card" data-text="{html.escape(" ".join([row["label"], row["asset_id"], row["category"], *row["tags"], *row["usages"]]).lower())}">'
                f'<a href="{html.escape(rel_original)}"><img loading="lazy" src="{html.escape(rel_thumb)}" alt=""></a>'
                f'<b>{safe["label"]}</b><div>{safe["category"]} &middot; v{row["version"]} &middot; {safe["review_status"]}</div>'
                f'<div class="m">{html.escape(", ".join(row["usages"]))}</div>'
                f'<div class="m">{html.escape(row["asset_id"])} &middot; {sha[:12]}</div>'
                f'<div class="m">{html.escape(", ".join(row["used_by_projects"]) or "-")}</div></div>')
        page = ("<!doctype html><meta charset='utf-8'><title>Studio asset library</title>"
                "<style>body{font:14px system-ui;margin:16px;background:#fafafa;color:#222}"
                ".g{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}"
                ".card{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px}"
                ".card img{width:100%;height:220px;object-fit:contain;background:#eee}"
                ".m{color:#666;font-size:12px;word-break:break-all}input{padding:6px;width:320px}</style>"
                f"<h1>Studio asset library ({len(rows)} {html.escape(status)})</h1>"
                "<input id=q placeholder='filter label / tag / usage' oninput=\"for(const c of document.querySelectorAll('.card'))"
                "c.style.display=c.dataset.text.includes(this.value.toLowerCase())?'':'none'\">"
                f"<div class=g>{''.join(cards)}</div>")
        target = out_dir / "index.html"
        atomic_write_bytes(target, page.encode("utf-8"))
        return target

    # -- explicit cleanup boundary ------------------------------------------ #
    def episode_cache_cleanup_plan(self, episode_dir: str | Path, *, protect: Iterable[str | Path] = ()) -> dict[str, Any]:
        """Which files in an episode folder are regenerable cache: ONLY those whose bytes are
        verified in the library.  Library originals are never listed; unique files are KEPT."""
        episode_dir = Path(episode_dir).resolve()
        if self.root.resolve() in (episode_dir, *episode_dir.parents) or episode_dir in (self.root.resolve(),) \
                or self.root.resolve() in episode_dir.parents:
            raise StudioError("CLEANUP_REFUSED_INSIDE_LIBRARY_ROOT")
        protected = {Path(p).resolve() for p in protect}
        candidates, kept = [], []
        for entry in sorted(episode_dir.rglob("*")):
            if not entry.is_file() or entry.is_symlink():
                continue
            if entry.resolve() in protected:
                kept.append({"file": str(entry.relative_to(episode_dir)), "reason": "PROTECTED_IN_USE"})
                continue
            if entry.suffix.lower().lstrip(".") not in MEDIA_TYPES:
                continue
            sha = sha256_file(entry)
            _, state = self.verify_object(sha)
            if state == "OK":
                candidates.append({"file": str(entry.relative_to(episode_dir)), "content_sha256": sha,
                                   "reason": "MASTER_VERIFIED_IN_LIBRARY"})
            else:
                kept.append({"file": str(entry.relative_to(episode_dir)), "reason": f"NOT_VERIFIED_IN_LIBRARY:{state}"})
        return {"episode_dir_name": episode_dir.name, "cache_candidates": candidates, "kept": kept,
                "library_objects_touched": 0}

    def apply_episode_cache_cleanup(self, episode_dir: str | Path, plan: dict[str, Any]) -> list[str]:
        removed = []
        base = Path(episode_dir).resolve()
        for item in plan["cache_candidates"]:
            target = (base / item["file"]).resolve()
            if self.root.resolve() in target.parents or base not in target.parents:
                raise StudioError("CLEANUP_REFUSED_OUTSIDE_EPISODE_DIR")
            _, state = self.verify_object(item["content_sha256"])
            if state == "OK" and target.is_file() and sha256_file(target) == item["content_sha256"]:
                target.unlink()
                removed.append(item["file"])
        return removed

    def library_release_plan(self) -> dict[str, Any]:
        """Local originals that COULD be released: only with a backup receipt whose sha matches AND
        a catalog that is itself backed up.  Without that nothing is listed (and nothing is deleted
        by any command in this module)."""
        try:
            from tools import studio_asset_backup as backup  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            import studio_asset_backup as backup  # type: ignore[no-redef]
        releasable, held = [], []
        for record_file in sorted((self.catalog / "objects").glob("*/*.json")):
            sha = (read_json(record_file) or {}).get("content_sha256")
            state = backup.object_storage_state(self, sha)
            (releasable if state == "LOCAL_BACKUP_VERIFIED" else held).append({"content_sha256": sha, "state": state})
        catalog_pending = backup.pending_catalog_count(self)
        if catalog_pending:
            held.extend(releasable)
            releasable = []
        return {"releasable": releasable, "held": held, "catalog_backup_pending": catalog_pending,
                "deletes_anything": False}


# --------------------------------------------------------------------------- #
# bundles: export / import with verification, no absolute paths
# --------------------------------------------------------------------------- #
def export_bundle(lib: Library, selections: list[tuple[str, int]], out_dir: str | Path, *,
                  include_unapproved: bool = False) -> dict[str, Any]:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise StudioError("BUNDLE_DIR_NOT_EMPTY")
    assets, objects = [], {}
    for asset_id, version in selections:
        manifest = lib.get_version(asset_id, version)
        review = lib.get_review(asset_id, version)
        if review["review_status"] != "APPROVED" and not include_unapproved:
            raise StudioError(f"EXPORT_REFUSED_NOT_APPROVED:{asset_id}@v{version}")
        assets.append({"manifest": manifest, "review": {"review_status": review["review_status"],
                                                        "review_ref": review["review_ref"]}})
        for artifact in manifest["artifacts"]:
            record = lib.object_record(artifact["content_sha256"]) or {}
            objects[artifact["content_sha256"]] = {"content_sha256": artifact["content_sha256"],
                                                   "bytes": artifact["bytes"], "ext": record.get("ext", "bin"),
                                                   "media_type": artifact["media_type"], "origins": record.get("origins", [])}
    for sha, info in objects.items():
        src = lib._verified_path(sha)
        dest = out_dir / "objects" / "sha256" / sha[:2] / f"{sha}.{info['ext']}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    body = {"assets": assets, "objects": sorted(objects.values(), key=lambda o: o["content_sha256"])}
    bundle = {"schema": SCHEMA_BUNDLE, "created_at": utc_now(), "source_library_id": lib.library_id,
              "body_sha256": sha256_bytes(canonical(body).encode("utf-8")), **body}
    if re.search(r"(?<![A-Za-z0-9])/(?:Users|home|private|var|tmp)/", json.dumps(bundle, ensure_ascii=False)):
        raise StudioError("BUNDLE_WOULD_CARRY_LOCAL_ABSOLUTE_PATH")
    atomic_write_json(out_dir / "bundle.json", bundle)
    return {"status": "EXPORTED", "assets": len(assets), "objects": len(objects), "bundle_sha256": bundle["body_sha256"]}


def import_bundle(lib: Library, bundle_dir: str | Path) -> dict[str, Any]:
    """Verify every byte against the bundle's own shas, then register.  Existing identical content is
    a no-op; the same asset@version with different content is VERSION_CONTENT_CONFLICT."""
    bundle_dir = Path(bundle_dir)
    bundle = read_json(bundle_dir / "bundle.json")
    if not bundle or bundle.get("schema") != SCHEMA_BUNDLE:
        raise StudioError("BUNDLE_SCHEMA_INVALID")
    body = {"assets": bundle["assets"], "objects": bundle["objects"]}
    if sha256_bytes(canonical(body).encode("utf-8")) != bundle.get("body_sha256"):
        raise StudioError("BUNDLE_MANIFEST_SHA_MISMATCH")
    for info in bundle["objects"]:
        path = bundle_dir / "objects" / "sha256" / info["content_sha256"][:2] / f"{info['content_sha256']}.{info['ext']}"
        if not path.is_file() or sha256_file(path) != info["content_sha256"] or path.stat().st_size != info["bytes"]:
            raise StudioError(f"BUNDLE_OBJECT_REJECTED:{info['content_sha256'][:12]}")
    ingested = 0
    for info in bundle["objects"]:
        path = bundle_dir / "objects" / "sha256" / info["content_sha256"][:2] / f"{info['content_sha256']}.{info['ext']}"
        record = lib.ingest_file(path, origin={"kind": "IMPORTED_BUNDLE", "source_library_id": bundle.get("source_library_id"),
                                               "bundle_body_sha256": bundle["body_sha256"]})
        ingested += 1 if record["created"] else 0
    registered, existing = [], []
    for item in bundle["assets"]:
        manifest = item["manifest"]
        if lib.content_set_sha(manifest["category"], manifest["artifacts"]) != manifest["content_set_sha256"]:
            raise StudioError("BUNDLE_CONTENT_SET_SHA_MISMATCH")
        result = lib.register_version(
            category=manifest["category"], label=manifest["label"], tags=manifest["tags"], kind=manifest.get("kind", "GROUP"),
            artifacts=[{"usage": a["usage"], "view": a.get("view"), "sha256": a["content_sha256"]} for a in manifest["artifacts"]],
            origin=manifest.get("origin"), parent_asset=manifest.get("parent_asset"),
            transformation=manifest.get("transformation"), asset_id=manifest["asset_id"],
            version=manifest["version"], created_at=manifest.get("created_at"))
        review = item["review"]
        local = lib.get_review(manifest["asset_id"], manifest["version"])
        if local["review_status"] == "UNREVIEWED" and review["review_status"] != "UNREVIEWED":
            ref = dict(review["review_ref"] or {})
            ref["imported_from_library"] = bundle.get("source_library_id")
            lib.set_review(manifest["asset_id"], manifest["version"], review["review_status"], ref,
                           reviewer="bundle_import", note="REVIEW_STATUS_ASSERTED_BY_EXPORTING_LIBRARY")
        (registered if result["created"] else existing).append(f"{manifest['asset_id']}@v{manifest['version']}")
    return {"status": "IMPORTED", "objects_new": ingested, "objects_total": len(bundle["objects"]),
            "versions_registered": registered, "versions_already_present": existing}


# --------------------------------------------------------------------------- #
# production hooks (called from the real harvest / lock / reuse / keyframe / video paths)
# --------------------------------------------------------------------------- #
_LIBRARIES: dict[str, Library] = {}
_LIBRARIES_LOCK = threading.Lock()


def _hook_library() -> Library | None:
    """One Library per root per process, so the per-object verification memo survives poll ticks."""
    root = active_root()
    if root is None:
        return None
    key = str(Path(root).expanduser())
    with _LIBRARIES_LOCK:
        if key not in _LIBRARIES:
            _LIBRARIES[key] = Library(root)
        return _LIBRARIES[key]


def archive_harvested_image(path: str | Path, *, episode: str | None, row: dict[str, Any] | None = None,
                            project_id: str | None = None, raw_response: str | Path | None = None) -> dict[str, Any]:
    """Real S3 harvest point.  Archives the downloaded original as UNREVIEWED.  Never raises into the
    harvest (the image is already on disk; ``sweep`` retries), never calls a provider."""
    try:
        if not hook_enabled("harvest"):
            return {"status": "HOOK_DISABLED_BY_CONFIG"}
        lib = _hook_library()
        if lib is None:
            return {"status": "STUDIO_LIBRARY_NOT_ENABLED"}
        row = row or {}
        origin: dict[str, Any] = {"kind": "PROVIDER_HARVEST", "project_id": project_id, "episode": episode,
                                  "task_key": row.get("task_key"), "task_id": row.get("task_id"),
                                  "model": row.get("model"), "prompt_sha256": row.get("prompt_sha256"),
                                  "harvested_at": utc_now()}
        if raw_response and Path(raw_response).is_file():
            origin["raw_response_sha256"] = sha256_file(raw_response)
        origin = {k: v for k, v in origin.items() if v not in (None, "")}
        record = lib.ingest_file(path, origin=origin)
        sha = record["content_sha256"]
        expected = row.get("sha256")
        if expected and expected != sha:
            return {"status": "ARCHIVE_REFUSED_SHA_DIFFERS_FROM_HARVEST_RECORD", "content_sha256": sha}
        pending = lib.register_version(category="reference_materials", label=str(row.get("task_key") or "harvested"),
                                       artifacts=[{"usage": "HARVESTED_ORIGINAL", "sha256": sha}], origin=origin,
                                       asset_id=f"PND-{sha[:16]}", kind="HARVEST_PENDING")
        lib._enqueue_object(sha)
        return {"status": "ARCHIVED_UNREVIEWED", "content_sha256": sha, "object_key": record["object_key"],
                "pending_asset": f"{pending['asset_id']}@v{pending['version']}", "created": record["created"]}
    except Exception as exc:  # noqa: BLE001 - production path must not be broken by archiving
        return {"status": "ARCHIVE_FAILED_RETRY_WITH_SWEEP", "error": f"{type(exc).__name__}:{exc}"}


def on_identity_lock(*, project_id: str, category: str, asset_id: str, label: str, plates: list[dict[str, Any]],
                     qa_status: str, review: dict[str, Any], episode: str | None) -> dict[str, Any]:
    """Real lock point (identity_qa_lock.materialise).  Links the genuine review verdict to the original
    versions and updates THIS project's binding.  PASS -> APPROVED + bound; anything else is recorded
    REJECTED and never bound.  ``plates`` rows: {path, usage, sha256}."""
    try:
        if not hook_enabled("identity_lock"):
            return {"status": "HOOK_DISABLED_BY_CONFIG"}
        lib = _hook_library()
        if lib is None:
            return {"status": "STUDIO_LIBRARY_NOT_ENABLED"}
        if not plates:
            return {"status": "NO_PLATES"}
        kind = {"characters": "character", "props": "prop", "creatures": "creature", "scenes": "scene"}.get(category)
        origin = {"kind": "IDENTITY_LOCK", "project_id": project_id, "episode": episode, "library_asset_id": asset_id}
        result = lib.register_version(
            category=category if category in CATEGORIES else "reference_materials", label=label or asset_id,
            artifacts=[{"usage": p["usage"], "path": p["path"], "sha256": p.get("sha256")} for p in plates],
            origin=origin, tags=[category])
        status = "APPROVED" if qa_status == "PASS" else "REJECTED"
        ref = {"kind": review.get("kind") or "IDENTITY_QA_MACHINE_REVIEW", "sha256": review.get("sha256"),
               "label": review.get("label"), "reviewer": review.get("reviewer")}
        if status == "APPROVED" and not is_sha256(ref["sha256"]):
            status = "UNREVIEWED"  # no evidence hash: stay recorded as unapproved rather than invent one
        lib.set_review(result["asset_id"], result["version"], status, ref if status != "UNREVIEWED" else None,
                       reviewer=review.get("reviewer"), note="IDENTITY_LOCK_HOOK")
        lib.mirror_pending_singles([a["content_sha256"] for a in result["manifest"]["artifacts"]], status,
                                   ref if status != "UNREVIEWED" else None,
                                   {"asset_id": result["asset_id"], "version": result["version"]})
        binding = None
        if status == "APPROVED" and kind:
            binding = lib.bind(project_id, kind, asset_id, result["asset_id"], result["version"], rebind=True,
                               project_fields=None)
        for artifact in result["manifest"]["artifacts"]:
            lib._enqueue_object(artifact["content_sha256"])
        return {"status": f"LINKED_{status}", "asset": f"{result['asset_id']}@v{result['version']}",
                "bound": bool(binding)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "LOCK_LINK_FAILED", "error": f"{type(exc).__name__}:{exc}"}


def resolve_reference(path: str | Path | None, sha: str | None, *, cache_dir: str | Path | None = None) -> Path | None:
    """The consumption point for S2 reuse, the S5 keyframe manifest and S6 video references.

    Returns a local path whose bytes are exactly ``sha``: the old path when it still verifies, else a
    COPY of the library original.  None when neither exists.  Never generates anything.  Raises
    StudioError('RESTORE_PENDING') only when the library knows the bytes but the master is damaged.
    """
    if not is_sha256(sha):
        return None
    if path:
        candidate = Path(str(path))
        if candidate.is_file() and not candidate.is_symlink() and sha256_file(candidate) == sha:
            return candidate
    try:
        if not hook_enabled("resolve_missing_reference"):
            return None
        lib = _hook_library()
        if lib is None:
            return None
        found = lib.resolve_legacy(path, sha, cache_dir=cache_dir)
        if found["status"] == "UNRESOLVED":
            if found.get("reason") in {"OBJECT_CORRUPT", "OBJECT_MISSING"} and lib.object_record(sha):
                raise StudioError("RESTORE_PENDING:" + sha[:12])
            return None
        return Path(found["path"])
    except StudioError as exc:
        if exc.code == "RESTORE_PENDING":
            raise
        return None


def artifact_present(artifact: dict[str, Any], *, cache_dir: str | Path | None = None) -> bool:
    """True when the artifact's bytes can be had locally (old path or library original)."""
    return resolve_reference(artifact.get("path"), artifact.get("sha256"), cache_dir=cache_dir) is not None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _parse_selection(values: list[str], lib: Library) -> list[tuple[str, int]]:
    out = []
    for value in values:
        asset_id, _, version = value.partition("@v")
        if version:
            out.append((asset_id, int(version)))
        else:
            chosen = lib.recommended_version(asset_id)
            if chosen is None:
                raise StudioError(f"NO_APPROVED_VERSION:{asset_id}")
            out.append((asset_id, chosen))
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", help=f"studio root (default: ${ENV_ROOT}, else config default under $HOME)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("config")
    p = sub.add_parser("ingest")
    p.add_argument("file")
    p.add_argument("--project")
    p.add_argument("--episode")
    p = sub.add_parser("register")
    p.add_argument("--category", required=True, choices=CATEGORIES)
    p.add_argument("--label", required=True)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--artifact", action="append", required=True, help="USAGE=path")
    p.add_argument("--project")
    p.add_argument("--asset-id")
    p.add_argument("--parent", help="asset_id@vN")
    p.add_argument("--transformation", help="JSON")
    p = sub.add_parser("review")
    p.add_argument("asset")
    p.add_argument("--status", required=True, choices=REVIEW_STATUSES)
    p.add_argument("--ref-kind")
    p.add_argument("--ref-sha256")
    p.add_argument("--ref-label")
    p.add_argument("--reviewer")
    p = sub.add_parser("search")
    p.add_argument("--text")
    p.add_argument("--category", choices=CATEGORIES)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--usage")
    p.add_argument("--status", default="APPROVED", choices=[*REVIEW_STATUSES, "ANY"])
    p.add_argument("--project")
    p = sub.add_parser("show")
    p.add_argument("asset")
    p = sub.add_parser("bind", help="explicit cross-project (or same-project) role binding")
    p.add_argument("--project", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--role-id", required=True)
    p.add_argument("--asset", required=True, help="asset_id@vN")
    p.add_argument("--usage", action="append")
    p.add_argument("--field", action="append", default=[], help="KEY=VALUE about the role IN THIS PROJECT")
    p.add_argument("--rebind", action="store_true")
    p = sub.add_parser("resolve")
    p.add_argument("--project", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--role-id", required=True)
    p.add_argument("--usage")
    p.add_argument("--cache-dir")
    p = sub.add_parser("legacy-resolve")
    p.add_argument("--path")
    p.add_argument("--sha256", required=True)
    p.add_argument("--cache-dir")
    p = sub.add_parser("export")
    p.add_argument("asset", nargs="+")
    p.add_argument("--out", required=True)
    p = sub.add_parser("import-bundle")
    p.add_argument("bundle")
    p = sub.add_parser("verify")
    p.add_argument("--quick", action="store_true")
    p = sub.add_parser("repair")
    p.add_argument("--sha256", required=True)
    p.add_argument("--from", dest="candidates", action="append", default=[])
    p = sub.add_parser("index")
    p.add_argument("--out")
    p.add_argument("--status", default="APPROVED", choices=[*REVIEW_STATUSES, "ANY"])
    p.add_argument("--no-thumbnails", action="store_true")
    p = sub.add_parser("cleanup-plan")
    p.add_argument("--episode-dir", required=True)
    p.add_argument("--protect", action="append", default=[])
    p.add_argument("--apply", action="store_true")
    sub.add_parser("release-plan")
    p = sub.add_parser("migrate")
    p.add_argument("--library", action="append", default=[], help="asset_library.json (repeatable)")
    p.add_argument("--source-map", action="append", default=[], help="character_source_map.json")
    p.add_argument("--harvest-status", action="append", default=[], help="*IDENTITY_HARVEST_STATUS.json")
    p.add_argument("--apply", action="store_true", help="copy originals in (default is a read-only preview)")
    p.add_argument("--limit", type=int, help="batch: at most this many unique objects")
    p.add_argument("--report")
    p = sub.add_parser("backup")
    p.add_argument("action", choices=["status", "run", "enqueue-all", "restore", "restore-catalog"])
    p.add_argument("--sha256")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_root(args.root, allow_default=True) or default_root()
    try:
        if args.cmd == "config":
            try:
                from tools import studio_asset_backup as backup  # noqa: PLC0415
            except ImportError:
                import studio_asset_backup as backup  # type: ignore[no-redef]
            _print({"root_resolved_from": "--root" if args.root else (ENV_ROOT if os.environ.get(ENV_ROOT) else "default"),
                    "root_name": root.name, "hooks_active": active_root() is not None,
                    "backup": backup.backup_state()})
            return 0
        if args.cmd == "migrate":
            try:
                from tools import studio_asset_migrate as migrate  # noqa: PLC0415
            except ImportError:
                import studio_asset_migrate as migrate  # type: ignore[no-redef]
            report = migrate.run(root, libraries=args.library, source_maps=args.source_map,
                                 harvest_statuses=args.harvest_status, apply=args.apply, limit=args.limit)
            if args.report:
                atomic_write_json(Path(args.report), report)
            _print(report)
            return 0 if report["status"] in {"PREVIEW", "APPLIED"} else 2
        lib = Library(root, create=args.cmd in {"init", "ingest", "register", "import-bundle", "backup"})
        if args.cmd == "init":
            _print({"status": "READY", "library_id": lib.library_id})
        elif args.cmd == "ingest":
            origin = {"kind": "MANUAL_INGEST", "project_id": args.project, "episode": args.episode}
            record = lib.ingest_file(args.file, origin={k: v for k, v in origin.items() if v})
            lib._enqueue_object(record["content_sha256"])
            record.pop("object_path", None)
            _print(record)
        elif args.cmd == "register":
            artifacts = []
            for item in args.artifact:
                usage, _, path = item.partition("=")
                artifacts.append({"usage": usage, "path": path})
            parent = None
            if args.parent:
                parent_id, _, parent_version = args.parent.partition("@v")
                parent = {"asset_id": parent_id, "version": int(parent_version)}
            result = lib.register_version(
                category=args.category, label=args.label, tags=args.tag, artifacts=artifacts, asset_id=args.asset_id,
                origin={"kind": "MANUAL_REGISTER", "project_id": args.project} if args.project else {"kind": "MANUAL_REGISTER"},
                parent_asset=parent, transformation=json.loads(args.transformation) if args.transformation else None)
            for a in result["manifest"]["artifacts"]:
                lib._enqueue_object(a["content_sha256"])
            _print({k: result[k] for k in ("asset_id", "version", "created")})
        elif args.cmd == "review":
            asset_id, version = _parse_selection([args.asset], lib)[0] if "@v" in args.asset else (args.asset, lib.versions_of(args.asset)[-1])
            ref = {"kind": args.ref_kind, "sha256": args.ref_sha256, "label": args.ref_label} if args.ref_kind else None
            _print(lib.set_review(asset_id, version, args.status, ref, reviewer=args.reviewer, note="CLI"))
        elif args.cmd == "search":
            _print(lib.search(text=args.text, category=args.category, tags=args.tag, usage=args.usage,
                              status=args.status, project=args.project))
        elif args.cmd == "show":
            asset_id, _, version = args.asset.partition("@v")
            number = int(version) if version else lib.versions_of(asset_id)[-1]
            _print({"manifest": lib.get_version(asset_id, number), "review": lib.get_review(asset_id, number),
                    "used_by": lib.used_by(asset_id), "recommended_version": lib.recommended_version(asset_id)})
        elif args.cmd == "bind":
            asset_id, _, version = args.asset.partition("@v")
            fields = dict(item.partition("=")[::2] for item in args.field)
            _print(lib.bind(args.project, args.kind, args.role_id, asset_id, int(version), usages=args.usage,
                            project_fields=fields or None, rebind=args.rebind))
        elif args.cmd == "resolve":
            _print(lib.resolve_binding(args.project, args.kind, args.role_id, usage=args.usage, cache_dir=args.cache_dir))
        elif args.cmd == "legacy-resolve":
            _print(lib.resolve_legacy(args.path, args.sha256, cache_dir=args.cache_dir))
        elif args.cmd == "export":
            _print(export_bundle(lib, _parse_selection(args.asset, lib), args.out))
        elif args.cmd == "import-bundle":
            _print(import_bundle(lib, args.bundle))
        elif args.cmd == "verify":
            report = lib.verify(full=not args.quick)
            _print(report)
            return 0 if report["status"] == "PASS" else 2
        elif args.cmd == "repair":
            report = lib.repair_object(args.sha256, args.candidates)
            _print(report)
            return 0 if report["status"] == "REPAIRED" else 2
        elif args.cmd == "index":
            _print({"index": str(lib.build_index(args.out, status=args.status, thumbnails=not args.no_thumbnails))})
        elif args.cmd == "cleanup-plan":
            plan = lib.episode_cache_cleanup_plan(args.episode_dir, protect=args.protect)
            if args.apply:
                plan["removed"] = lib.apply_episode_cache_cleanup(args.episode_dir, plan)
            _print(plan)
        elif args.cmd == "release-plan":
            _print(lib.library_release_plan())
        elif args.cmd == "backup":
            try:
                from tools import studio_asset_backup as backup  # noqa: PLC0415
            except ImportError:
                import studio_asset_backup as backup  # type: ignore[no-redef]
            if args.action == "status":
                _print(backup.status_report(lib))
            elif args.action == "enqueue-all":
                _print(backup.enqueue_all(lib))
            elif args.action == "run":
                report = backup.run(lib, limit=args.limit, workers=args.workers)
                _print(report)
                return 0 if report["status"] in {"DONE", "UNCONFIGURED", "NOTHING_QUEUED"} else 2
            elif args.action == "restore":
                report = backup.restore_object(lib, args.sha256)
                _print(report)
                return 0 if report["status"] == "RESTORED" else 2
            elif args.action == "restore-catalog":
                _print(backup.restore_catalog(lib))
    except StudioError as exc:
        _print({"status": "REFUSED", "code": exc.code, "detail": str(exc)})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
