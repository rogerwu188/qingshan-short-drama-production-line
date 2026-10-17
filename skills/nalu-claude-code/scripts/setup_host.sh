#!/usr/bin/env bash
# setup_host.sh — one-shot, idempotent host setup for the NALU line on an OpenClaw miniPC.
#
# The OpenClaw agent runs this on every wake-up.  On a ready host it only re-checks and exits in
# seconds; otherwise it does whatever is missing, with nobody at the terminal:
#   1. system deps   git / ffmpeg / ffprobe / CJK font / uv  (passwordless sudo apt if available,
#                    else user-space: static ffmpeg in ~/.local/bin, Noto CJK in ~/.local/share/fonts)
#   2. engine        clone ~/nalu_engine, or move an existing checkout to the pinned commit
#                    (a checkout with local changes is renamed ~/nalu_engine_old_<ts>, never deleted)
#   3. runtime       a ~/nalu_runtime this script did not create is renamed ~/nalu_runtime_old_<ts>
#   4. python        .qingshan-venv (uv, CPython 3.12) + core/media/QA deps, runtime bootstrap
#   5. codex         configure_codex.py --verify: install the Codex CLI (npm) and point it at the provider
#                    in ~/nalu_runtime/credentials/llm_provider.json (asked from the line owner once; the
#                    miniPCs produce with Codex + gpt-5.6 only since 2026-10-13; Claude Code is not installed)
# Result: ~/.nalu_setup_state.json and ONE final JSON line on stdout:
#   NALU_SETUP: {"status":"READY|NEEDS_PROVIDER|BLOCKED", "failed_step":..., "steps":{...}, ...}
#   NEEDS_PROVIDER: everything else is ready; the agent asks the owner for the provider URL + key, writes
#   the file, and runs this again.
#
# usage: setup_host.sh --pin <engine commit> [--force] [--skip-verify]
set -uo pipefail

ORIG_ARGS=("$@")
PIN="${NALU_ENGINE_PIN:-}"; FORCE=0; VERIFY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --pin) PIN="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --skip-verify) VERIFY=0; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
[ -n "$PIN" ] || { echo 'NALU_SETUP: {"status":"BLOCKED","failed_step":"args","reason":"--pin <commit> is required"}'; exit 2; }

S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO=https://github.com/rogerwu188/qingshan-short-drama-production-line.git
ENGINE="${NALU_ENGINE_ROOT:-$HOME/nalu_engine}"
RUNTIME="${NALU_RUNTIME_ROOT:-$HOME/nalu_runtime}"
STATE="$HOME/.nalu_setup_state.json"
LOG="$HOME/.nalu_setup.log"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
NOTES=()

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }
run() { log "\$ $*"; "$@" >>"$LOG" 2>&1; }
finish() {  # status failed_step
  local steps="" k
  for k in deps engine runtime python codex_install codex_config; do
    v="STEP_$k"; steps="$steps\"$k\":\"${!v:-NOT_RUN}\","
  done
  local notes="" n
  for n in "${NOTES[@]+"${NOTES[@]}"}"; do notes="$notes\"${n//\"/\'}\","; done
  notes="${notes%,}"
  local json="{\"status\":\"$1\",\"failed_step\":\"$2\",\"pin\":\"$PIN\",\"engine\":\"$ENGINE\",\"runtime\":\"$RUNTIME\",\"log\":\"$LOG\",\"steps\":{${steps%,}},\"notes\":[${notes}],\"at\":\"$TS\"}"
  printf '%s\n' "$json" >"$STATE"
  printf 'NALU_SETUP: %s\n' "$json"
  [ "$1" = READY ] && exit 0 || exit 3
}
[ "$(id -u)" != 0 ] || { NOTES+=("run as the OpenClaw user, not root"); finish BLOCKED preflight; }
log "==== setup_host.sh pin=$PIN force=$FORCE"

PROVIDER="$RUNTIME/credentials/llm_provider.json"
CODEX_CFG="$HOME/.codex/config.toml"
codex_ready() {  # installed, configured, and configured after the provider file last changed
  command -v codex >/dev/null && [ -f "$PROVIDER" ] && [ -f "$CODEX_CFG" ] && ! [ "$PROVIDER" -nt "$CODEX_CFG" ]
}
# fast path: ready host, same pin, codex configured for the current provider
if [ $FORCE = 0 ] && [ -f "$STATE" ] && grep -q "\"status\":\"READY\"" "$STATE" && grep -q "\"pin\":\"$PIN\"" "$STATE" \
   && [ "$(git -C "$ENGINE" rev-parse HEAD 2>/dev/null)" = "$PIN" ] && [ -x "$ENGINE/.qingshan-venv/bin/python" ] \
   && codex_ready; then
  for k in deps engine runtime python codex_install codex_config; do eval "STEP_$k=OK_CACHED"; done
  finish READY ""
fi

# an episode in flight (the executor running, or its last NALU_STATUS is anything but FINAL_CUT_READY / BLOCKED)
# keeps the engine + venv it started with; a new pin is applied on the first wake after it finishes.
IN_FLIGHT="$(python3 - "$RUNTIME" "$S" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
runtime, scripts = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, scripts)
import claude_production as cp
busy = []
for session in sorted((runtime / "claude_code").glob("*/session.json")):
    s = json.loads(session.read_text(encoding="utf-8"))
    state = ((cp.parse_log(Path(s.get("log") or "")).get("nalu_status")) or {}).get("state")
    # a stopped BLOCKED episode is waiting for a fix (often this very pin), not in flight
    if cp.alive(s.get("pid")) or state not in ("FINAL_CUT_READY", "BLOCKED"):
        busy.append(f"{session.parent.name}:{'RUNNING' if cp.alive(s.get('pid')) else state}")
print(",".join(busy))
PY
)"
CUR="$(git -C "$ENGINE" rev-parse HEAD 2>/dev/null)"
DEFER=0
if [ -n "$IN_FLIGHT" ] && [ -n "$CUR" ] && [ "$CUR" != "$PIN" ] && [ -x "$ENGINE/.qingshan-venv/bin/python" ]; then
  DEFER=1; NOTES+=("episode in flight ($IN_FLIGHT): engine stays at ${CUR:0:7}; ${PIN:0:7} applies after it reaches FINAL_CUT_READY")
  if codex_ready; then
    STEP_deps=OK_CACHED; STEP_engine=DEFERRED_IN_FLIGHT; STEP_runtime=OK_CACHED; STEP_python=DEFERRED_IN_FLIGHT
    STEP_codex_install=OK_CACHED; STEP_codex_config=OK_CACHED
    finish READY ""
  fi
fi

# ---------------------------------------------------------------- 1. system deps
SUDO=""; sudo -n true 2>/dev/null && SUDO="sudo -n"
if [ -n "$SUDO" ] && command -v apt-get >/dev/null; then
  run $SUDO apt-get update -qq
  run $SUDO apt-get install -y -qq git ffmpeg fonts-noto-cjk build-essential python3-dev curl xz-utils
fi
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/fonts"
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  tmp="$(mktemp -d)"
  if run curl -fsSL -o "$tmp/ff.tar.xz" https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
     && run tar -xJf "$tmp/ff.tar.xz" -C "$tmp"; then
    cp "$tmp"/ffmpeg-*-static/ffmpeg "$tmp"/ffmpeg-*-static/ffprobe "$HOME/.local/bin/" && NOTES+=("ffmpeg: user-space static build")
  fi
  rm -rf "$tmp"
fi
FONT="$(fc-list 2>/dev/null | grep -i -m1 -E 'Noto Sans CJK|NotoSansCJK' | cut -d: -f1)"
if [ -z "$FONT" ]; then
  FONT="$HOME/.local/share/fonts/NotoSansCJKsc-Regular.otf"
  [ -f "$FONT" ] || run curl -fsSL -o "$FONT" https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf
  command -v fc-cache >/dev/null && run fc-cache -f "$HOME/.local/share/fonts"
fi
if ! command -v uv >/dev/null; then run sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'; fi
missing=""
for c in git ffmpeg ffprobe uv curl; do command -v $c >/dev/null || missing="$missing $c"; done
[ -f "$FONT" ] || missing="$missing cjk-font"
if [ -n "$missing" ]; then STEP_deps="MISSING:${missing# }"; finish BLOCKED deps; fi
STEP_deps=OK

# ---------------------------------------------------------------- 2. engine at the pinned commit
if [ -d "$ENGINE/.git" ]; then
  run git -C "$ENGINE" fetch -q origin
  if [ -n "$(git -C "$ENGINE" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    # keep the exact local patch outside the engine too (the executor must not patch the engine; this is
    # evidence for the maintainer, and a stash is easy to lose)
    mkdir -p "$RUNTIME/engine_patches" && git -C "$ENGINE" diff HEAD >"$RUNTIME/engine_patches/setup_$TS.patch" 2>/dev/null \
      && NOTES+=("engine local changes saved to $RUNTIME/engine_patches/setup_$TS.patch")
    # keep local edits recoverable without moving .env / workflow state away from the engine
    run git -C "$ENGINE" -c user.name=setup -c user.email=setup@localhost stash push -m "setup_host $TS" \
      && NOTES+=("engine local changes stashed: git -C $ENGINE stash list")
  fi
elif [ -e "$ENGINE" ]; then
  mv "$ENGINE" "${ENGINE}_old_$TS" && NOTES+=("non-git $ENGINE kept as ${ENGINE}_old_$TS")
fi
[ -d "$ENGINE/.git" ] || run git clone -q "$REPO" "$ENGINE" || { STEP_engine=CLONE_FAILED; finish BLOCKED engine; }
before="$(git -C "$ENGINE" rev-parse HEAD)"
if [ $DEFER = 1 ]; then PIN_EFFECTIVE="$before"; else PIN_EFFECTIVE="$PIN"; fi
run git -C "$ENGINE" checkout -q --detach "$PIN_EFFECTIVE" || { STEP_engine=CHECKOUT_FAILED; finish BLOCKED engine; }
[ "$before" = "$PIN_EFFECTIVE" ] || NOTES+=("engine moved ${before:0:7} -> ${PIN_EFFECTIVE:0:7}")
[ $DEFER = 1 ] || [ -d "$ENGINE/skills/nalu-claude-code/scripts" ] || { STEP_engine=SKILL_DIR_MISSING_AT_PIN; finish BLOCKED engine; }
# the setup script itself follows the pin: if the pinned engine carries a different setup_host.sh than
# the (possibly stale, TalentHub-installed) copy running now, hand over to it once.
PINNED_SETUP="$ENGINE/skills/nalu-claude-code/scripts/setup_host.sh"
if [ $DEFER = 0 ] && [ -z "${NALU_SETUP_REEXEC:-}" ] && [ -f "$PINNED_SETUP" ] \
   && ! cmp -s "${BASH_SOURCE[0]}" "$PINNED_SETUP"; then
  log "handing over to the pinned setup_host.sh ($PINNED_SETUP)"
  NALU_SETUP_REEXEC=1 exec bash "$PINNED_SETUP" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}
fi
STEP_engine=OK; [ $DEFER = 1 ] && STEP_engine=DEFERRED_IN_FLIGHT

# ---------------------------------------------------------------- 3. runtime (keep ours, set aside foreign ones)
if [ -d "$RUNTIME" ] && [ ! -f "$RUNTIME/.nalu_setup_owner" ]; then
  mv "$RUNTIME" "${RUNTIME}_old_$TS" && NOTES+=("pre-existing runtime kept as ${RUNTIME}_old_$TS")
fi
STEP_runtime=OK

# ---------------------------------------------------------------- 4. python env + runtime bootstrap
cd "$ENGINE" || finish BLOCKED python
if [ ! -x .qingshan-venv/bin/python ] || [ "$before" != "$PIN_EFFECTIVE" ] || [ $FORCE = 1 ]; then
  run uv python install 3.12 && run uv venv --allow-existing -q --python 3.12 --seed .qingshan-venv || { STEP_python=VENV_FAILED; finish BLOCKED python; }
  export VIRTUAL_ENV="$ENGINE/.qingshan-venv"
  run uv pip install -q -r requirements-core.txt -r requirements-media.txt && run uv pip install -q -e . \
    || { STEP_python=CORE_DEPS_FAILED; finish BLOCKED python; }
  run uv pip install -q insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc "av==18.1.0" \
    || { STEP_python="QA_DEPS_FAILED(insightface needs build-essential+python3-dev: passwordless sudo or a preinstalled compiler)"; finish BLOCKED python; }
fi
.qingshan-venv/bin/python -c "import insightface, faster_whisper, rapidocr_onnxruntime, opencc" >>"$LOG" 2>&1 \
  || { STEP_python=IMPORT_CHECK_FAILED; finish BLOCKED python; }
[ -f .env ] || cp .env.example .env; chmod 600 .env
if [ ! -f "$RUNTIME/.nalu_setup_owner" ]; then
  run python3 lines/nalu/runtime/tools/bootstrap_runtime_root.py --runtime-root "$RUNTIME" --line-id nalu-minipc --work "短剧工作流" \
    || { STEP_python=RUNTIME_BOOTSTRAP_FAILED; finish BLOCKED python; }
  [ -f "$RUNTIME/qingshan.json" ] || cp configs/pipeline.example.json "$RUNTIME/qingshan.json"
  run .qingshan-venv/bin/python "$S/apply_runtime_fixups.py" --runtime-root "$RUNTIME"
  printf '{"created_by":"setup_host.sh","at":"%s","pin":"%s"}\n' "$TS" "$PIN" >"$RUNTIME/.nalu_setup_owner"
fi
grep -q 'NALU_ENGINE_ROOT=' "$HOME/.bashrc" 2>/dev/null || cat >>"$HOME/.bashrc" <<EOF
# NALU line (setup_host.sh)
export NALU_ENGINE_ROOT="$ENGINE" NALU_RUNTIME_ROOT="$RUNTIME" NALU_WORK_ROOT="$ENGINE/workflow/nalu"
export NALU_QA_WORKERS=1 NALU_Q2_WORKERS=1 QINGSHAN_CJK_FONT="$FONT"
export PATH="\$HOME/.local/bin:\$HOME/.npm-global/bin:\$PATH"
EOF
STEP_python=OK

# ---------------------------------------------------------------- 5. codex + provider
command -v npm >/dev/null || { [ -n "$SUDO" ] && command -v apt-get >/dev/null && run $SUDO apt-get install -y -qq nodejs npm; }
args=(); [ $VERIFY = 1 ] && args+=(--verify)
out="$(NALU_RUNTIME_ROOT="$RUNTIME" NALU_ENGINE_ROOT="$ENGINE" python3 "$S/configure_codex.py" ${args[@]+"${args[@]}"} 2>>"$LOG" | tail -1)"
log "configure_codex: $(printf '%s' "$out" | cut -c1-400)"
status="$(printf '%s' "${out#CODEX_CONFIG: }" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)"
command -v codex >/dev/null && STEP_codex_install="OK:$(codex --version 2>/dev/null | head -1)" || STEP_codex_install=NOT_INSTALLED
STEP_codex_config="${status:-FAILED}"
case "$status" in
  VERIFIED) ;;
  CONFIGURED) [ $VERIFY = 0 ] || finish BLOCKED codex_config ;;
  NEEDS_PROVIDER) finish NEEDS_PROVIDER codex_config ;;
  *) [ "$STEP_codex_install" = NOT_INSTALLED ] && finish BLOCKED codex_install; finish BLOCKED codex_config ;;
esac
finish READY ""
