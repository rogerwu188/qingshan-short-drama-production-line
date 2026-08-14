#!/usr/bin/env python3
"""Render exact E39 evidence plates locally so the video model never invents text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e39_video_v1/deterministic_text_plates"
FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canvas(seed: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    rng = random.Random(seed)
    image = Image.new("RGB", (1080, 1920), (205, 185, 145))
    pixels = image.load()
    for y in range(1920):
        for x in range(1080):
            grain = rng.randint(-5, 5)
            pixels[x, y] = (205 + grain, 185 + grain, 145 + grain)
    draw = ImageDraw.Draw(image)
    draw.rectangle((72, 72, 1008, 1848), outline=(65, 48, 31), width=5)
    return image, draw


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size=size)


def save(image: Image.Image, name: str) -> dict[str, str]:
    path = OUT / name
    image.save(path, format="PNG", optimize=False)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    assets = []

    image, draw = canvas(3904)
    draw.text((540, 155), "药柜更换日期", font=font(72), fill=(35, 25, 18), anchor="mm")
    for y in (360, 560, 760, 960, 1160):
        draw.line((150, y, 930, y), fill=(85, 62, 40), width=4)
    draw.text((365, 455), "三天", font=font(58), fill=(42, 29, 18), anchor="mm")
    draw.text((715, 455), "→", font=font(58), fill=(42, 29, 18), anchor="mm")
    draw.ellipse((770, 1350, 930, 1510), outline=(120, 36, 28), width=10)
    assets.append(save(image, "E39-U04-LEDGER-PLATE-V1.png"))

    image, draw = canvas(3910)
    draw.rectangle((120, 180, 500, 1710), outline=(65, 48, 31), width=4)
    draw.rectangle((580, 180, 960, 1710), outline=(65, 48, 31), width=4)
    draw.text((310, 280), "甲", font=font(72), fill=(35, 25, 18), anchor="mm")
    draw.text((770, 280), "乙", font=font(72), fill=(35, 25, 18), anchor="mm")
    for x in (310, 770):
        for index, value in enumerate(("1", "2", "3")):
            y = 520 + index * 260
            draw.text((x, y), value, font=font(54), fill=(42, 29, 18), anchor="mm")
            draw.line((x - 135, y + 70, x + 135, y + 70), fill=(85, 62, 40), width=3)
    assets.append(save(image, "E39-U10-TWO-PAGE-PLATE-V1.png"))

    image, draw = canvas(3911)
    for index, value in enumerate(("1", "2", "3")):
        x = 240 + index * 300
        draw.rectangle((x - 120, 300, x + 120, 540), outline=(65, 48, 31), width=4)
        draw.text((x, 420), value, font=font(42), fill=(42, 29, 18), anchor="mm")
    cx, cy = 540, 1260
    for dx, dy in ((0, -120), (114, -37), (70, 97), (-70, 97), (-114, -37)):
        draw.ellipse((cx + dx - 58, cy + dy - 78, cx + dx + 58, cy + dy + 78), outline=(120, 36, 28), width=12)
    draw.ellipse((cx - 58, cy - 58, cx + 58, cy + 58), outline=(120, 36, 28), width=12)
    assets.append(save(image, "E39-U11-DATE-SEAL-PLATE-V1.png"))

    receipt = OUT / "E39_DETERMINISTIC_TEXT_PLATES_V1.json"
    receipt.write_text(json.dumps({"schema": "qingshan.e39.deterministic_text_plates.v1", "status": "PASS_3_OF_3", "assets": assets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_3_OF_3", "receipt": str(receipt), "sha256": digest(receipt)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
