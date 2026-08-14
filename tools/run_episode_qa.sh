#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  tools/run_episode_qa.sh \
    --video /path/to/final.mp4 \
    --config configs/E##_continuity_config.json \
    --manifest configs/E##_asset_binding_manifest.json \
    --blocker-manifest workflow/E##_FINAL_PACKAGE_BLOCKERS.json \
    --speaker-evidence qa/E##_SPEAKER_IDENTITY_VOICE_EVIDENCE.json \
    --episode E## \
    --evidence-bundle workflow/tasks/E##_MANDATORY_GATE_EVIDENCE.json \
    [--render-plan configs/E##_final_render_plan.json] \
    --out qa/E##_final_qa

Runs the mandatory stage runner first (final + release), including regression
CI and every registered content/release gate, then the legacy package, audio,
asset, continuity, and character-anchor checks.

The script writes episode_qa_summary.json/md and exits non-zero when a machine
gate fails. Character anchor sheets are release-blocking evidence and must be
checked before publication until the face classifier gate is upgraded.
EOF
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT_DIR/.s3_relay_env_py312/bin/python3" ]]; then
  DEFAULT_PYTHON="$ROOT_DIR/.s3_relay_env_py312/bin/python3"
else
  DEFAULT_PYTHON="python3"
fi
PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON}"

VIDEO=""
CONFIG=""
MANIFEST=""
OUT_DIR=""
BLOCKER_MANIFEST=""
SPEAKER_EVIDENCE=""
RENDER_PLAN=""
EPISODE=""
EVIDENCE_BUNDLE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --video) VIDEO="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --manifest) MANIFEST="$2"; shift 2 ;;
    --blocker-manifest) BLOCKER_MANIFEST="$2"; shift 2 ;;
    --speaker-evidence) SPEAKER_EVIDENCE="$2"; shift 2 ;;
    --episode) EPISODE="$2"; shift 2 ;;
    --evidence-bundle) EVIDENCE_BUNDLE="$2"; shift 2 ;;
    --render-plan) RENDER_PLAN="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$VIDEO" || -z "$CONFIG" || -z "$MANIFEST" || -z "$BLOCKER_MANIFEST" || -z "$SPEAKER_EVIDENCE" || -z "$EPISODE" || -z "$EVIDENCE_BUNDLE" || -z "$OUT_DIR" ]]; then
  usage >&2
  exit 2
fi

export FFMPEG="$("$ROOT_DIR/tools/find_ffmpeg.sh" "$ROOT_DIR")"

mkdir -p "$OUT_DIR"

"$PYTHON_BIN" - "$ROOT_DIR" "$VIDEO" "$BLOCKER_MANIFEST" "$EVIDENCE_BUNDLE" <<'PY'
import json
import sys
from pathlib import Path

root, video, blocker, bundle = map(lambda value: Path(value).expanduser().resolve(), sys.argv[1:])
evidence = json.loads(bundle.read_text(encoding="utf-8"))

def resolve(value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()

if resolve(evidence.get("final_video", "")) != video:
    raise SystemExit("evidence bundle final_video does not match --video")
if resolve(evidence.get("final_package_manifest", "")) != blocker:
    raise SystemExit("evidence bundle final_package_manifest does not match --blocker-manifest")
PY

"$PYTHON_BIN" "$ROOT_DIR/tools/episode_stage_gate_runner.py" \
  --episode "$EPISODE" \
  --phase final \
  --phase release \
  --evidence-bundle "$EVIDENCE_BUNDLE" \
  --out-dir "$OUT_DIR/mandatory_stage_gates"

"$PYTHON_BIN" "$ROOT_DIR/tools/speaker_identity_voice_release_gate.py" \
  --evidence "$SPEAKER_EVIDENCE" \
  --out "$OUT_DIR/speaker_identity_voice_release_gate.json"

"$PYTHON_BIN" "$ROOT_DIR/tools/final_package_blocker_gate.py" \
  --manifest "$BLOCKER_MANIFEST" \
  --out "$OUT_DIR/final_package_blocker_gate.json"

"$PYTHON_BIN" "$ROOT_DIR/tools/dialogue_audio_release_gate.py" \
  --video "$VIDEO" \
  --blocker-manifest "$BLOCKER_MANIFEST" \
  --out "$OUT_DIR/dialogue_audio_release_gate.json"

CADENCE_ARGS=(
  --video "$VIDEO"
  --out "$OUT_DIR/frame_cadence_audit.json"
)
if [[ -n "$RENDER_PLAN" ]]; then
  CADENCE_ARGS+=(--render-plan "$RENDER_PLAN")
fi
"$PYTHON_BIN" "$ROOT_DIR/tools/frame_cadence_audit.py" "${CADENCE_ARGS[@]}"

ASSET_OUT="$OUT_DIR/asset_binding_report.json"
CONT_OUT="$OUT_DIR/continuity"
ANCHOR_OUT="$OUT_DIR/character_anchors"

"$PYTHON_BIN" "$ROOT_DIR/tools/asset_binding_validator.py" \
  --config "$CONFIG" \
  --manifest "$MANIFEST" \
  --out "$ASSET_OUT"

"$ROOT_DIR/tools/run_continuity_audit.sh" \
  --video "$VIDEO" \
  --config "$CONFIG" \
  --out "$CONT_OUT"

"$PYTHON_BIN" - "$VIDEO" "$CONFIG" "$MANIFEST" "$ANCHOR_OUT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

video, config, manifest, out_dir = map(Path, sys.argv[1:])
data = json.loads(manifest.read_text(encoding="utf-8"))
characters = data.get("characters", {})
out_dir.mkdir(parents=True, exist_ok=True)

for char_id, anchor in characters.items():
    level = anchor.get("level") or anchor.get("priority")
    if level not in {"S", "A", "A+"}:
        continue
    ref = anchor.get("reference_image") or anchor.get("main_reference_image")
    if not ref:
        continue
    ref_path = Path(ref)
    if not ref_path.is_absolute():
        ref_path = manifest.resolve().parents[1] / ref_path
    if not ref_path.exists():
        continue
    cmd = [
        sys.executable,
        str(manifest.resolve().parents[1] / "tools/character_anchor_auditor.py"),
        "--video",
        str(video),
        "--config",
        str(config),
        "--character",
        char_id,
        "--reference",
        str(ref_path),
        "--out",
        str(out_dir / char_id),
    ]
    subprocess.run(cmd, check=True)
PY

"$PYTHON_BIN" - "$VIDEO" "$ASSET_OUT" "$CONT_OUT/continuity_report.json" "$ANCHOR_OUT" "$OUT_DIR" <<'PY'
import json
import sys
from pathlib import Path

video, asset_path, continuity_path, anchor_dir, out_dir = map(Path, sys.argv[1:])
asset = json.loads(asset_path.read_text(encoding="utf-8"))
continuity = json.loads(continuity_path.read_text(encoding="utf-8"))
anchor_reports = sorted(anchor_dir.glob("*/*_anchor_report.json"))

machine_failures = []
if asset.get("status") != "PASS":
    machine_failures.append("asset_binding")
if continuity.get("fail_count", 0) > 0:
    machine_failures.append("continuity")

summary = {
    "video": str(video),
    "asset_binding_status": asset.get("status"),
    "continuity_fail_count": continuity.get("fail_count", 0),
    "continuity_warn_count": continuity.get("warn_count", 0),
    "character_anchor_report_count": len(anchor_reports),
    "character_anchor_reports": [str(p) for p in anchor_reports],
    "status": "FAIL" if machine_failures else ("REVIEW_REQUIRED_BLOCKING" if anchor_reports else "PASS"),
    "machine_failures": machine_failures,
    "release_rule": "Do not publish until continuity PASS and every S/A character anchor sheet has explicit pass evidence against the role reference. REVIEW_REQUIRED is blocking, not a pass.",
    "standard_stage": "script/assets/grid_storyboard/platform_sound/local_qa/publish",
}
(out_dir / "episode_qa_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

lines = [
    "# Episode QA Summary",
    "",
    f"- Video: `{video}`",
    f"- Asset binding: `{summary['asset_binding_status']}`",
    f"- Continuity fails: `{summary['continuity_fail_count']}`",
    f"- Continuity warns: `{summary['continuity_warn_count']}`",
    f"- Character anchor reports: `{summary['character_anchor_report_count']}`",
    f"- Status: `{summary['status']}`",
    "",
    "## Character Anchor Evidence",
    "",
]
if anchor_reports:
    for path in anchor_reports:
        lines.append(f"- `{path}`")
else:
    lines.append("- No S/A character anchor reports generated.")
lines.extend(["", "## Release Rule", "", summary["release_rule"], ""])
(out_dir / "episode_qa_summary.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
sys.exit(1 if machine_failures or anchor_reports else 0)
PY
