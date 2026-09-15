#!/usr/bin/env python3
"""video_sheets.py --videos <dir> --out <dir> [--fps 2] [--per-sheet 4] [--w 240]
2-fps frame strips per unit mp4 (row per unit, up to 16 frames), stacked N units per sheet — what the reviewer
actually looks at for the post-generation plot review."""
import argparse, glob, json, os, subprocess, tempfile
from PIL import Image, ImageDraw
ap = argparse.ArgumentParser(); ap.add_argument("--videos", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--fps", type=float, default=2.0); ap.add_argument("--per-sheet", type=int, default=4); ap.add_argument("--w", type=int, default=240)
ap.add_argument("--units", default="")
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
vids = sorted(glob.glob(os.path.join(a.videos, "*.mp4")))
if a.units: keep = set(a.units.split(",")); vids = [v for v in vids if os.path.basename(v)[:-4] in keep]
W = a.w; H = int(W * 16 / 9); MAXF = 16
rows = []
for v in vids:
    uid = os.path.basename(v)[:-4]
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["/opt/homebrew/bin/ffmpeg", "-loglevel", "error", "-y", "-i", v, "-vf", f"fps={a.fps},scale={W}:-1", os.path.join(td, "f%03d.png")], check=True)
        frames = sorted(glob.glob(os.path.join(td, "f*.png")))[:MAXF]
        strip = Image.new("RGB", (W * max(1, len(frames)), H + 20), "white"); d = ImageDraw.Draw(strip)
        d.text((4, 4), f"{uid}  {len(frames)} frames @ {a.fps}fps", fill="black")
        for i, f in enumerate(frames):
            im = Image.open(f).convert("RGB"); im.thumbnail((W, H)); strip.paste(im, (i * W, 20))
        rows.append((uid, strip))
sheets = []
for s in range(0, len(rows), a.per_sheet):
    chunk = rows[s:s + a.per_sheet]; width = max(r[1].width for r in chunk); height = sum(r[1].height for r in chunk)
    sheet = Image.new("RGB", (width, height), "white"); y = 0
    for uid, strip in chunk: sheet.paste(strip, (0, y)); y += strip.height
    p = os.path.join(a.out, f"sheet_{s // a.per_sheet + 1:02d}.jpg"); sheet.save(p, quality=80); sheets.append({"sheet": p, "units": [r[0] for r in chunk], "size": sheet.size})
print(json.dumps({"units": len(rows), "sheets": sheets}, ensure_ascii=False))
