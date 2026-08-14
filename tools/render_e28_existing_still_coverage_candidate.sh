#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/rogerwu/qingshan_short_drama"
FFMPEG="$ROOT/.agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
BASE="$ROOT/exports/e28/agentcut_v1_cl2x517_u09_hold_20260721/E28_AGENTCUT_V1_CL2X517_U09_HOLD_NOT_FINAL.mp4"
OUT_DIR="$ROOT/exports/e28/agentcut_v2_cl2x517_existing_still_coverage_20260721"
SEG_DIR="$OUT_DIR/segments"
OUT="$OUT_DIR/E28_AGENTCUT_V2_EXISTING_STILL_COVERAGE_U09_HOLD_NOT_FINAL.mp4"

mkdir -p "$SEG_DIR"

make_pan() {
  local name="$1"
  local image="$2"
  local frames="$3"
  local direction="$4"
  local denominator=$((frames - 1))
  local x_expr
  local y_expr

  case "$direction" in
    lr)
      x_expr="(in_w-out_w)*n/$denominator"
      y_expr="(in_h-out_h)/2"
      ;;
    rl)
      x_expr="(in_w-out_w)*(1-n/$denominator)"
      y_expr="(in_h-out_h)/2"
      ;;
    up)
      x_expr="(in_w-out_w)/2"
      y_expr="(in_h-out_h)*(1-n/$denominator)"
      ;;
    down)
      x_expr="(in_w-out_w)/2"
      y_expr="(in_h-out_h)*n/$denominator"
      ;;
    diag_down)
      x_expr="(in_w-out_w)*n/$denominator"
      y_expr="(in_h-out_h)*n/$denominator"
      ;;
    diag_up)
      x_expr="(in_w-out_w)*n/$denominator"
      y_expr="(in_h-out_h)*(1-n/$denominator)"
      ;;
    *)
      printf 'Unsupported direction: %s\n' "$direction" >&2
      return 2
      ;;
  esac

  "$FFMPEG" -hide_banner -loglevel error -y \
    -loop 1 -framerate 24 -i "$image" \
    -vf "scale=900:1600:force_original_aspect_ratio=increase,crop=720:1280:x='$x_expr':y='$y_expr',fps=24,format=yuv420p" \
    -frames:v "$frames" -an -c:v libx264 -preset veryfast -crf 18 \
    "$SEG_DIR/$name.mp4"
}

concat_video() {
  local output="$1"
  shift
  local args=()
  local labels=""
  local index=0
  local input

  for input in "$@"; do
    args+=( -i "$input" )
    labels+="[$index:v]"
    index=$((index + 1))
  done

  "$FFMPEG" -hide_banner -loglevel error -y \
    "${args[@]}" \
    -filter_complex "${labels}concat=n=$index:v=1:a=0[v]" \
    -map "[v]" -an -c:v libx264 -preset veryfast -crf 18 \
    "$output"
}

make_pan r1_01 "$ROOT/working_assets/e28_multireference_still_completion_v3_20260721/candidates/E28_E28-CW-U01-C1-STILL-V3_28e38d36-374e-45cd-9aa3-81c912c17808.png" 36 lr
make_pan r1_02 "$ROOT/working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S01-SH01-STILL-R1_a8d296db-5f02-49e6-87af-dd13a9b021f0.png" 60 rl
make_pan r1_03 "$ROOT/working_assets/e28_multireference_still_completion_v3_20260721/candidates/E28_E28-CW-U01-C3-STILL-V3_9c856152-57e7-4741-96e9-7bafaaf6eff1.png" 48 up

make_pan r2_01 "$ROOT/working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S01-SH03-STILL-R1_2c0a401c-f6b3-45eb-a2a7-adc86e6738c6.png" 60 diag_down
make_pan r2_02 "$ROOT/working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S01-SH03-STILL-R1_2c0a401c-f6b3-45eb-a2a7-adc86e6738c6.png" 60 diag_up
make_pan r2_03 "$ROOT/working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH01-STILL-V1_ede8a971-69e6-4a50-af7c-fae3d8ad37b5.png" 48 lr
make_pan r2_04 "$ROOT/working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH01-STILL-V1_ede8a971-69e6-4a50-af7c-fae3d8ad37b5.png" 48 rl

make_pan r3_01 "$ROOT/working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH04-STILL-V1_4221c7ab-cb13-4a6c-9a31-52489820e187.png" 60 diag_down
make_pan r3_02 "$ROOT/working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S02-SH04-STILL-V1_4221c7ab-cb13-4a6c-9a31-52489820e187.png" 12 rl
make_pan r3_03 "$ROOT/working_assets/e28_multireference_still_completion_v3_20260721/candidates/E28_E28-CW-U04-C3-STILL-V3_91476069-fff1-4341-a337-316299174d65.png" 36 down
make_pan r3_04 "$ROOT/working_assets/e28_multireference_still_completion_v3_20260721/candidates/E28_E28-CW-U04-C3-STILL-V3_91476069-fff1-4341-a337-316299174d65.png" 36 up
make_pan r3_05 "$ROOT/working_assets/e28_claude_writer_v1_new_stills_failed_only_r1_20260721/candidates/E28_E28-CW-S02-SH05-STILL-R1_da9c9ca2-fb2b-440f-82b6-8a0d1327226d.png" 24 diag_up

make_pan r4_01 "$ROOT/working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S03-SH01-STILL-V1_90177755-a63c-4bbd-b1b4-15b7392e18e3.png" 60 lr
make_pan r4_02 "$ROOT/working_assets/e28_claude_writer_v1_stills_20260721/candidates/E28_E28-CW-S03-SH01-STILL-V1_90177755-a63c-4bbd-b1b4-15b7392e18e3.png" 60 rl

concat_video "$SEG_DIR/replacement_00p5_06p5.mp4" \
  "$SEG_DIR/r1_01.mp4" "$SEG_DIR/r1_02.mp4" "$SEG_DIR/r1_03.mp4"
concat_video "$SEG_DIR/replacement_25_34.mp4" \
  "$SEG_DIR/r2_01.mp4" "$SEG_DIR/r2_02.mp4" "$SEG_DIR/r2_03.mp4" "$SEG_DIR/r2_04.mp4"
concat_video "$SEG_DIR/replacement_46_53.mp4" \
  "$SEG_DIR/r3_01.mp4" "$SEG_DIR/r3_02.mp4" "$SEG_DIR/r3_03.mp4" "$SEG_DIR/r3_04.mp4" "$SEG_DIR/r3_05.mp4"
concat_video "$SEG_DIR/replacement_64_69.mp4" \
  "$SEG_DIR/r4_01.mp4" "$SEG_DIR/r4_02.mp4"

"$FFMPEG" -hide_banner -loglevel error -y \
  -i "$BASE" \
  -i "$SEG_DIR/replacement_00p5_06p5.mp4" \
  -i "$SEG_DIR/replacement_25_34.mp4" \
  -i "$SEG_DIR/replacement_46_53.mp4" \
  -i "$SEG_DIR/replacement_64_69.mp4" \
  -filter_complex \
  "[0:v]trim=start=0:end=0.5,setpts=PTS-STARTPTS[v0];
   [0:v]trim=start=6.5:end=25,setpts=PTS-STARTPTS[v1];
   [0:v]trim=start=34:end=46,setpts=PTS-STARTPTS[v2];
   [0:v]trim=start=53:end=64,setpts=PTS-STARTPTS[v3];
   [0:v]trim=start=69:end=172,setpts=PTS-STARTPTS[v4];
   [v0][1:v][v1][2:v][v2][3:v][v3][4:v][v4]concat=n=9:v=1:a=0[outv]" \
  -map "[outv]" -map 0:a? \
  -c:v libx264 -preset veryfast -crf 18 -c:a copy -movflags +faststart \
  "$OUT"

printf '%s\n' "$OUT"
