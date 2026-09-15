#!/usr/bin/env python3
"""contact_sheet.py --request <review_request.json> --out <sheet.jpg> [--cols 5] [--w 360] [--h 640] [--start N --count M]
Builds a labelled thumbnail sheet from a vlm_review_protocol request (items[].media[].path) so the reviewer can view it."""
import argparse, json, os
from PIL import Image, ImageDraw
ap = argparse.ArgumentParser(); ap.add_argument("--request", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--cols", type=int, default=5); ap.add_argument("--w", type=int, default=360); ap.add_argument("--h", type=int, default=640)
ap.add_argument("--start", type=int, default=0); ap.add_argument("--count", type=int, default=0)
a = ap.parse_args()
R = json.load(open(a.request))
rows = []
for it in R["items"]:
    for m in it.get("media") or []:
        p = m["path"] if isinstance(m, dict) else m
        if os.path.isfile(p):
            rows.append((it["item_id"], p))
rows = rows[a.start:(a.start + a.count) if a.count else None]
cols = a.cols; W, H = a.w, a.h; nrows = (len(rows) + cols - 1) // cols
sheet = Image.new("RGB", (cols * W, nrows * (H + 24)), "white"); d = ImageDraw.Draw(sheet)
for i, (iid, p) in enumerate(rows):
    im = Image.open(p).convert("RGB"); im.thumbnail((W, H))
    x = (i % cols) * W; y = (i // cols) * (H + 24)
    sheet.paste(im, (x, y + 24)); d.text((x + 4, y + 4), f"{a.start + i} {iid}", fill="black")
sheet.save(a.out, quality=85); print(json.dumps({"sheet": a.out, "size": sheet.size, "items": len(rows)}))
