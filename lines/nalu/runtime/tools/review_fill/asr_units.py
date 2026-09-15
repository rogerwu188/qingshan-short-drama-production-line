#!/usr/bin/env python3
"""asr_units.py --videos <dir> --out <json>: local faster-whisper (small, cpu int8, zh) transcript per unit mp4."""
import argparse, glob, json, os
ap = argparse.ArgumentParser(); ap.add_argument("--videos", required=True); ap.add_argument("--out", required=True); ap.add_argument("--units", default="")
a = ap.parse_args()
from faster_whisper import WhisperModel
m = WhisperModel("small", device="cpu", compute_type="int8")
vids = sorted(glob.glob(os.path.join(a.videos, "*.mp4")))
if a.units: keep = set(a.units.split(",")); vids = [v for v in vids if os.path.basename(v)[:-4] in keep]
out = json.load(open(a.out)) if os.path.exists(a.out) else {}
for v in vids:
    uid = os.path.basename(v)[:-4]
    if uid in out: continue
    segs, _ = m.transcribe(v, language="zh", vad_filter=True)
    out[uid] = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: " / ".join(x["text"] for x in v) for k, v in out.items()}, ensure_ascii=False)[:3000])
