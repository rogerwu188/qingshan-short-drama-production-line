#!/bin/sh
# Install the AgentCut runtime (S4 voice references, S7 selective BGM) into a private venv.
#
# Source, in order of preference:
#   1. AGENTCUT_WHEEL / an offline wheel under workflow/.../runtime_wheels_portable (no network)
#   2. the public repository at the pinned tag  (git+https, network)
# Never installs from an unpinned branch.  Writes a JSON receipt.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AGENTCUT_REPO="${AGENTCUT_REPO:-https://github.com/rogerwu188/agentcut.git}"
AGENTCUT_TAG="${AGENTCUT_TAG:-v0.9.22}"
AGENTCUT_EXPECTED_VERSION="${AGENTCUT_EXPECTED_VERSION:-${AGENTCUT_TAG#v}}"
VENV="${AGENTCUT_VENV:-$ROOT/.agentcut_env}"
OUT="${1:-$ROOT/runtime_receipts/agentcut_runtime_bootstrap.json}"
WHEEL="${AGENTCUT_WHEEL:-}"
if [ -z "$WHEEL" ]; then
  for candidate in "$ROOT"/workflow/cloud_factory_migration_v1_20260724/runtime_wheels_portable/agentcut-"$AGENTCUT_EXPECTED_VERSION"-py3-none-any.whl; do
    [ -f "$candidate" ] && WHEEL="$candidate"
  done
fi

if [ -z "${PYTHON:-}" ]; then
  for name in python3.12 python3.11 python3.10 python3; do
    candidate=$(command -v "$name" || true)
    if [ -n "$candidate" ] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
      PYTHON=$candidate
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ] || [ ! -x "$PYTHON" ]; then
  printf '%s\n' "Python >=3.10 is required" >&2
  exit 78
fi

if [ ! -x "$VENV/bin/python" ]; then
  rm -rf "$VENV"
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

if [ -n "$WHEEL" ] && [ -f "$WHEEL" ]; then
  SOURCE="wheel:$WHEEL"
  NETWORK=false
  "$VENV/bin/python" -m pip install --quiet --no-index --force-reinstall "$WHEEL" \
    || "$VENV/bin/python" -m pip install --quiet --force-reinstall "$WHEEL"
else
  SOURCE="git:$AGENTCUT_REPO@$AGENTCUT_TAG"
  NETWORK=true
  if ! "$VENV/bin/python" -m pip install --quiet --force-reinstall "agentcut @ git+$AGENTCUT_REPO@$AGENTCUT_TAG"; then
    printf '%s\n' "AgentCut install failed from $SOURCE (network or tag missing); set AGENTCUT_WHEEL=<path> for an offline install" >&2
    exit 78
  fi
fi

AGENTCUT_VERSION=$("$VENV/bin/python" -c 'from importlib.metadata import version; print(version("agentcut"))')
if [ "$AGENTCUT_VERSION" != "$AGENTCUT_EXPECTED_VERSION" ]; then
  printf '%s\n' "AgentCut version mismatch: got $AGENTCUT_VERSION, expected $AGENTCUT_EXPECTED_VERSION" >&2
  exit 78
fi
"$VENV/bin/python" -c 'import agentcut; from agentcut.release_gate import validate_release_output; from agentcut.engine import AgentCutEngine'
"$VENV/bin/python" -m agentcut --help >/dev/null
if [ ! -x "$VENV/bin/agentcut" ]; then
  printf '%s\n' '#!/bin/sh' 'HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)' 'exec "$HERE/python" -m agentcut "$@"' > "$VENV/bin/agentcut"
  chmod +x "$VENV/bin/agentcut"
fi

FFMPEG="${FFMPEG:-$(command -v ffmpeg || true)}"
FFPROBE="${FFPROBE:-$(command -v ffprobe || true)}"
if [ -z "$FFMPEG" ] || [ -z "$FFPROBE" ]; then
  printf '%s\n' "system ffmpeg and ffprobe are required" >&2
  exit 78
fi

mkdir -p "$(dirname -- "$OUT")"
"$VENV/bin/python" - "$OUT" "$SOURCE" "$VENV" "$FFMPEG" "$FFPROBE" "$AGENTCUT_VERSION" "$NETWORK" <<'PY'
import hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

out, source, venv, ffmpeg, ffprobe, version, network = sys.argv[1:]
out = Path(out)
receipt = {
    "schema": "storyclaw.agentcut_runtime_bootstrap.v2",
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "status": "PASS",
    "agentcut_version": version,
    "source": source,
    "wheel_sha256": (hashlib.sha256(Path(source[6:]).read_bytes()).hexdigest() if source.startswith("wheel:") else None),
    "venv": venv,
    "agentcut_executable": str(Path(venv) / "bin" / "agentcut"),
    "import_verified": True,
    "cli_verified": True,
    "ffmpeg": ffmpeg,
    "ffprobe": ffprobe,
    "network_install_used": network == "true",
}
fd, partial = tempfile.mkstemp(prefix=out.name + ".", suffix=".partial", dir=out.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(partial, out)
finally:
    if os.path.exists(partial):
        os.unlink(partial)
print(json.dumps(receipt, ensure_ascii=False))
PY
