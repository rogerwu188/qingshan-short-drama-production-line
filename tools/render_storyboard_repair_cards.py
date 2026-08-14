#!/usr/bin/env python3
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap

ROOT = Path("/Users/rogerwu/qingshan_short_drama")
OUT = ROOT / "storyboards" / "e05_repair_cards_20260703"
OUT.mkdir(parents=True, exist_ok=True)

FONT = "/Library/Fonts/Arial Unicode.ttf"
if not Path(FONT).exists():
    FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

title_font = ImageFont.truetype(FONT, 48)
head_font = ImageFont.truetype(FONT, 26)
body_font = ImageFont.truetype(FONT, 23)
small_font = ImageFont.truetype(FONT, 18)

cards = {
    "01": {
        "title": "旧蝉壳接上集｜道具接｜5秒",
        "visual": "冷蓝六楼病房，陈迹掌心旧蝉壳被暖白门光照亮，李青鸟站在病床旁。片头字幕：青山 第5集：李青鸟的梦门。",
        "dialogue": "李青鸟低声：十二岁的蝉，到了。",
        "sound": "医院空调被风声吞掉，旧蝉壳轻响。",
        "transition": "蝉壳轻响接暖光门缝。",
    },
    "02": {
        "title": "李青鸟抚眼｜动作接｜6秒",
        "visual": "李青鸟抬手覆上陈迹双眼；短发男性病人脸清楚，冷蓝病房边缘出现暖白门影。",
        "dialogue": "李青鸟：叹隙中驹，石中火，梦中身。",
        "sound": "归零主题短动机，风声变宽。",
        "transition": "手掌遮住镜头，切黑水。",
    },
    "03": {
        "title": "黑水渡口｜声桥｜6秒",
        "visual": "黑暗水面，一叶小船穿过低雾，船桨划水，远处云海裂开。真实电影质感，不做抽象空镜。",
        "dialogue": "无对白。",
        "sound": "船桨划水、风声、低鼓三下。",
        "transition": "水声压近，接陈迹古装借身惊醒。",
    },
    "05": {
        "title": "陈迹借身惊醒｜动作接｜6秒",
        "visual": "古装陈迹从地面猛然吸气坐起，灰布学徒长衫，束发，同脸参考；手摸腰侧发现伤不见了。",
        "dialogue": "陈迹低声：我……在哪？",
        "sound": "急促吸气、木地板轻响。",
        "transition": "吸气声惊动皎兔。",
    },
    "07": {
        "title": "云羊补刀规则｜关系接｜6秒",
        "visual": "云羊走近陈迹，袖口银针只露冷光，表情轻松，背后周府书房狼藉。",
        "dialogue": "云羊：不可能，肯定是他心长偏了。",
        "sound": "衣摆扫过碎瓷片，烛火声突然清楚。",
        "transition": "陈迹抬头接正反打。",
    },
    "13": {
        "title": "陈迹提出交易｜交易接｜8秒",
        "visual": "陈迹站在书房和院落交界，背后是周府家眷轮廓和散乱宣纸，眼神冷静。",
        "dialogue": "陈迹：我没有情报。但给我两刻钟，我把情报找出来。",
        "sound": "远处风吹梧桐叶。",
        "transition": "梧桐叶声接皎兔笑。",
    },
    "19": {
        "title": "一刻钟成交｜主钩子｜8秒",
        "visual": "云羊站在梧桐树下，黑衣剪影和月光；皎兔倚在门边看戏，陈迹站在两人中间。",
        "dialogue": "云羊：成交。但我只给你一刻钟。",
        "sound": "银针敲指节、风声压低。",
        "transition": "一刻钟三字接陈迹松开碎瓷片。",
    },
}


def draw_wrapped(draw, text, xy, font, width, fill=(32, 32, 32), line_gap=8):
    x, y = xy
    lines = []
    for para in text.split("\n"):
        lines.extend(textwrap.wrap(para, width=width) or [""])
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def render(num, data):
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(img)
    margin = 54
    d.rectangle((0, 0, w, 150), fill=(22, 27, 32))
    d.text((margin, 38), f"青山 E05 分镜 {num}", font=title_font, fill=(245, 245, 238))
    d.text((margin, 98), data["title"], font=head_font, fill=(197, 221, 185))

    y = 190
    table_x = margin
    table_w = w - margin * 2
    rows = [
        ("画面示意", data["visual"]),
        ("对白", data["dialogue"]),
        ("声音", data["sound"]),
        ("转场", data["transition"]),
        ("生成要求", "9:16 竖屏，中文对白，人物/场景/道具继承本集素材库；视频阶段必须平台有声同步生成。"),
    ]
    row_heights = [360, 260, 230, 230, 270]
    d.rectangle((table_x, y, table_x + table_w, y + 72), fill=(225, 228, 224), outline=(150, 150, 145), width=2)
    d.text((table_x + 18, y + 20), "栏目", font=head_font, fill=(30, 30, 30))
    d.text((table_x + 250, y + 20), "导演分镜内容", font=head_font, fill=(30, 30, 30))
    y += 72
    for (label, body), rh in zip(rows, row_heights):
        d.rectangle((table_x, y, table_x + table_w, y + rh), fill=(255, 255, 252), outline=(170, 170, 165), width=2)
        d.line((table_x + 220, y, table_x + 220, y + rh), fill=(170, 170, 165), width=2)
        d.text((table_x + 18, y + 24), label, font=head_font, fill=(45, 45, 45))
        draw_wrapped(d, body, (table_x + 250, y + 24), body_font, 24)
        y += rh

    d.rectangle((margin, h - 190, w - margin, h - 72), fill=(31, 35, 36), outline=(110, 130, 120), width=2)
    draw_wrapped(
        d,
        "QA锚点：不出现欧美人物、不出现英文对白、不出现静态空镜替代剧情；每个镜头必须有动作/声桥/道具接。",
        (margin + 22, h - 158),
        small_font,
        42,
        fill=(238, 238, 230),
        line_gap=6,
    )
    path = OUT / f"qingshan_E05_storyboard_repair_shot_{num}.png"
    img.save(path)
    return path


for num, data in cards.items():
    print(render(num, data))
