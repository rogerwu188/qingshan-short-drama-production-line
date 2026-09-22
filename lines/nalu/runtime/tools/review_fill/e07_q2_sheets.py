#!/usr/bin/env python3
"""Build two review sheets for the E07 Q2 pass.

  faces  — every face crop of the units the identity gate flagged, one row per unit
  ocr    — the full frames whose OCR produced a string, so the reviewer can see whether it is
           texture noise (declared NOISE:<text>) or real burned-in text
"""
import glob, os, sys
from PIL import Image, ImageDraw

Q2 = "/Users/rogerwu/nalu/workflow/nalu/E07/preproduction/reports/qa/q2"
OUT = "/tmp/e07_q2"
os.makedirs(OUT, exist_ok=True)

FLAGGED = ["E07-VU-002", "E07-VU-004", "E07-VU-005", "E07-VU-007", "E07-VU-008",
           "E07-VU-011", "E07-VU-016", "E07-VU-017", "E07-VU-018", "E07-VU-021",
           "E07-VU-026", "E07-VU-030"]
OCR_FRAMES = [
    ("E07-VU-001", "f05_2.543s"), ("E07-VU-011", "f09_4.803s"), ("E07-VU-013", "f02_0.681s"),
    ("E07-VU-014", "f08_5.069s"), ("E07-VU-015", "f01_0.393s"), ("E07-VU-021", "f03_1.690s"),
    ("E07-VU-027", "f08_5.882s"), ("E07-VU-017", "f05_3.041s"),
]


def faces_sheet() -> None:
    CW = 150
    rows = []
    for unit in FLAGGED:
        crops = sorted(glob.glob(os.path.join(Q2, unit, "face_crops", "*.png")))[:9]
        row = Image.new("RGB", (CW * 9, CW + 18), "white")
        draw = ImageDraw.Draw(row)
        draw.text((3, CW + 3), unit + "  " + str(len(crops)) + " crops", fill="black")
        for i, c in enumerate(crops):
            img = Image.open(c).convert("RGB").resize((CW, CW))
            row.paste(img, (i * CW, 0))
            name = os.path.basename(c)
            tag = name.split("__")[1][5:12] if "__" in name else ""
            draw.text((i * CW + 3, 3), tag, fill="yellow")
        rows.append(row)
    sheet = Image.new("RGB", (CW * 9, sum(r.height for r in rows)), "white")
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height
    sheet.save(os.path.join(OUT, "faces_flagged.png"))
    print("faces sheet", sheet.size)


def ocr_sheet() -> None:
    W = 340
    cells = []
    for unit, frag in OCR_FRAMES:
        hits = glob.glob(os.path.join(Q2, unit, "frames", f"*{frag}*.png"))
        if not hits:
            continue
        img = Image.open(hits[0]).convert("RGB")
        img = img.resize((W, int(img.height * W / img.width)))
        cells.append((unit + " " + frag, img))
    if not cells:
        return
    H = max(c[1].height for c in cells)
    sheet = Image.new("RGB", (W * len(cells), H + 18), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(cells):
        sheet.paste(img, (i * W, 0))
        draw.text((i * W + 3, H + 3), label, fill="black")
    sheet.save(os.path.join(OUT, "ocr_frames.png"))
    print("ocr sheet", sheet.size)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("faces", "both"):
        faces_sheet()
    if which in ("ocr", "both"):
        ocr_sheet()
