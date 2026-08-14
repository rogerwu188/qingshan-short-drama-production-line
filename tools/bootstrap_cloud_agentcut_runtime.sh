#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WHEEL="$ROOT/workflow/cloud_factory_migration_v1_20260724/runtime_wheels_portable/agentcut-0.9.16-py3-none-any.whl"
VENV="${AGENTCUT_VENV:-$ROOT/.agentcut_env}"
OUT="${1:-$ROOT/runtime_receipts/agentcut_runtime_bootstrap.json}"

if [ -z "${PYTHON:-}" ]; then
  for name in python3.12 python3.11 python3.10 python3; do
    candidate=$(command -v "$name" || true)
    if [ -n "$candidate" ] \
      && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' \
      && "$candidate" -c 'import requests'; then
      PYTHON=$candidate
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ] || [ ! -x "$PYTHON" ]; then
  printf '%s\n' "Python >=3.10 with requests is required" >&2
  exit 78
fi
if [ ! -f "$WHEEL" ]; then
  printf '%s\n' "AgentCut wheel is missing: $WHEEL" >&2
  exit 78
fi

if [ ! -x "$VENV/bin/python" ] || ! grep -q '^include-system-site-packages = true$' "$VENV/pyvenv.cfg" 2>/dev/null; then
  rm -rf "$VENV"
  if ! "$PYTHON" -m venv --system-site-packages "$VENV"; then
    rm -rf "$VENV"
    "$PYTHON" -m venv --without-pip --system-site-packages "$VENV"
  fi
fi
if "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  "$VENV/bin/python" -m pip install --no-index --no-deps --force-reinstall "$WHEEL"
else
  SYSTEM_PIP=$(command -v pip3 || command -v pip || true)
  if [ -z "$SYSTEM_PIP" ]; then
    printf '%s\n' "Offline pip bootstrap is unavailable" >&2
    exit 78
  fi
  SITE_PACKAGES=$(
    "$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])'
  )
  rm -rf "$SITE_PACKAGES/agentcut" "$SITE_PACKAGES/agentcut-0.9.16.dist-info"
  "$SYSTEM_PIP" install --no-index --no-deps --target "$SITE_PACKAGES" "$WHEEL"
  printf '%s\n' '#!/bin/sh' 'HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)' 'exec "$HERE/python" -m agentcut "$@"' > "$VENV/bin/agentcut"
  chmod +x "$VENV/bin/agentcut"
fi

AGENTCUT_VERSION=$(
  "$VENV/bin/python" -c 'from importlib.metadata import version; print(version("agentcut"))'
)
if [ "$AGENTCUT_VERSION" != "0.9.16" ]; then
  printf '%s\n' "AgentCut version mismatch: $AGENTCUT_VERSION" >&2
  exit 78
fi
"$VENV/bin/python" -c 'import requests; import agentcut; from agentcut.release_gate import validate_release_output; from agentcut.engine import AgentCutEngine'
"$VENV/bin/python" -m agentcut --help >/dev/null
if [ ! -x "$VENV/bin/agentcut" ]; then
  printf '%s\n' "AgentCut console entrypoint is missing" >&2
  exit 78
fi

FFMPEG="${FFMPEG:-$(command -v ffmpeg || true)}"
FFPROBE="${FFPROBE:-$(command -v ffprobe || true)}"
if [ -z "$FFMPEG" ] || [ -z "$FFPROBE" ]; then
  printf '%s\n' "system ffmpeg and ffprobe are required" >&2
  exit 78
fi

mkdir -p "$(dirname -- "$OUT")"
"$VENV/bin/python" - "$OUT" "$WHEEL" "$VENV" "$FFMPEG" "$FFPROBE" <<'PY'
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

out, wheel, venv, ffmpeg, ffprobe = map(Path, sys.argv[1:])
digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
receipt = {
    "schema": "storyclaw.agentcut_runtime_bootstrap.v1",
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "status": "PASS",
    "agentcut_version": "0.9.16",
    "wheel": str(wheel),
    "wheel_sha256": digest,
    "venv": str(venv),
    "agentcut_executable": str(venv / "bin" / "agentcut"),
    "import_verified": True,
    "cli_verified": True,
    "ffmpeg": str(ffmpeg),
    "ffprobe": str(ffprobe),
    "network_install_used": False,
}
fd, partial = tempfile.mkstemp(prefix=out.name + ".", suffix=".partial", dir=out.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, out)
finally:
    if os.path.exists(partial):
        os.unlink(partial)
print(json.dumps(receipt, ensure_ascii=False))
PY
