# Continuity Auditor CLI

Purpose: inspect a local episode MP4 without using Chrome or Giggle pages, then output actionable scene/person/prop consistency issues.

## Requirements

- Python 3.8+
- `ffmpeg`

This repo already includes a portable Mac ffmpeg binary at:

```bash
/Users/rogerwu/qingshan_short_drama/.video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1
```

On another machine, either install ffmpeg or pass `--ffmpeg /path/to/ffmpeg`.

Thresholds can live inside the episode config under `thresholds`, so a portable
handoff does not need long command flags.

## Run

```bash
python3 /Users/rogerwu/qingshan_short_drama/tools/continuity_auditor.py \
  --video /path/to/episode.mp4 \
  --config /Users/rogerwu/qingshan_short_drama/configs/e04_v5_continuity_config.json \
  --out /Users/rogerwu/qingshan_short_drama/qa/e04_v5_continuity_audit
```

## Outputs

- `continuity_report.json`: machine-readable issues.
- `continuity_report.md`: human-readable issue list.
- `repair_plan.json`: one executable repair task per affected shot, with evidence frame, platform action, prompt, and API fallback payload draft.
- `repair_prompts.md`: exact repair prompts for affected shots.
- `contact_sheet.html`: visual grid, red border on suspect shots.
- `frames/`: evidence frames.

## Workflow Integration

1. Export or download the current episode candidate MP4.
2. Run this CLI before publication.
3. For each `fail` issue:
   - `scene_room_continuity`: return to Giggle `故事板` or source material first.
   - `character_visual_drift`: repair character material/storyboard reference.
   - `prop_visual_drift`: repair prop material/storyboard frame.
4. Open `repair_plan.json` and work through the affected shots. Regenerate affected shots in the platform. Use official API fallback only when UI task creation/reference upload is blocked.
5. Re-export and rerun this CLI until no blocking issue remains.

This is a local portable auditor, not a final artistic judge. It is a fast gate that prevents obvious continuity drift from reaching publication.
