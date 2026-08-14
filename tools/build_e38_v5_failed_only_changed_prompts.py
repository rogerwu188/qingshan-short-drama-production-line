#!/usr/bin/env python3
"""Build materially changed E38 retries for text and dialogue failures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804"
V4_PLAN = BASE / "E38_PRO_V4_EXPRESSIVE_CLEAN_RUN_PLAN.json"
PROMPT_DIR = BASE / "video_prompts_v5_failed_only_changed"
RUN_PLAN = BASE / "E38_PRO_V5_FAILED_ONLY_CHANGED_RUN_PLAN.json"


COMMON = """竖屏9:16，Seedance 2.0 Pro，原生1080p，实时1倍速，中国古装悬疑短剧。
固定机位；人物按真实重力、关节范围、接触点和遮挡行动。禁止推拉、摇移、环绕、漂移、慢动作、定格、重复动作和背景人物冻结。
【无文字成像协议】画面是干净的原始摄影素材，不含字幕、标题、贴纸、水印或任何屏幕文字。所有纸张、账页、药屉标签只允许空白纸面、无字格线、抽象污渍或不可构成文字的单一墨点；镜头内不得出现汉字、拼音、数字或伪文字。真实文字全部由后期合成。
【语音协议】对白只存在于同步音轨和对应人物口型中，绝不转成屏幕字幕。每句只说一次，不复诵，不改词，不漏词，不串词。非当前说话者闭口，但保持呼吸、视线和身体反应。
"""


PROMPTS = {
    "U01": COMMON + """【单元】E38-U01-R2，13秒。
【构图】全程固定半身中近景，陈迹的脸和双手清晰；账册只露出封面和纸边，绝不切到账页俯拍或文字特写。
【动作】0.0-2.0秒，陈迹右手悬停后压住合拢的旧账册，左手扶住书脊；纸边出现十二个彼此分开的细小霜点，仅是圆点，不是笔画。2.0-7.5秒，他看着霜点，肩背随克制呼吸微动。7.5-13.0秒，霜点向页边聚成一条无字冰线并在边缘断开，他抬眼确认线索。
【对白】2.2-7.4秒，陈迹用同一冻结声纹、压住痛意的警觉，只说一次：救我养我的地方，头一回拿查贼的眼看。地方后短停，头一回后轻停；重读救我养我的地方、查贼；前半慢沉，后半收紧。禁止重复前半句。
【终态】陈迹目光抬起，手仍压住账册，冰线停在纸边；无文字、无字幕。
""",
    "U03": COMMON + """【单元】E38-U03-R2，12秒。
【构图】门内固定中景，随后一次明确硬切到药柜前固定双人近景；不推镜。药柜抽屉均为无字木牌。
【动作】0.0-4.5秒，陈迹持续推门并压住一张空白报损纸的翘角；皎兔本体保持呼吸，睫毛颤动。4.5-8.0秒，淡蓝阴神逐屉扫过空柜后回归眉心。8.0-12.0秒，皎兔睁眼锁住陈迹，陈迹呼吸一顿并转向空柜。
【对白】8.3-10.6秒，皎兔用冻结声纹、寒意与戒备，慢半拍后冷硬地只说一次：一屉都没剩。重读一屉、没剩；一屉后极短停；末三字压低。陈迹全程闭口。
【终态】两人视线停在空柜，身体仍有呼吸余势；无文字、无字幕。
""",
    "U09": COMMON + """【单元】E38-U09-R2，7秒。
【构图】药案旁固定双人近景，陈迹、云羊和乌云都清晰；不展示尸体细节，不切镜。
【动作】0.0-1.0秒，陈迹从暗桩僵指间拈起无字药包；云羊压住喘息，乌云绕过药碾嗅药包。1.0-3.0秒，云羊看一眼暗桩再看陈迹，拳头收紧。3.0-7.0秒，陈迹拉开空屉，让无字药包与空屉同框，指尖检查封口；乌云警觉后缩鼻尖。
【对白时间窗一】1.05-2.85秒，仅云羊开口，以冻结声纹、压住怒火的震动只说一次：死士，进了你的家。死士后停半拍，重读死士、你的家。陈迹闭口。
【对白时间窗二】3.25-6.75秒，仅陈迹开口，以冻结声纹、冷静下的寒意只说一次：报损一笔，就是一声来取。报损一笔后短停，就是后微停，来取二字放慢并压低。云羊闭口。
【终态】陈迹指向空屉，云羊肩背仍随呼吸起伏，乌云耳尖转向陈迹；无文字、无字幕。
""",
    "U10": COMMON + """【单元】E38-U10-R2，13秒。
【构图】全程账桌固定中景，人物脸、手和乌云清晰；不拍笔尖特写，不拍可读纸面。纸张保持空白，仅允许一个不构成文字的圆形墨点。
【动作】0.0-4.5秒，陈迹蘸墨后在空白纸角落下一个圆墨点，停笔观察极淡霜痕；云羊在门边换脚承重并向前半步；乌云摆尾，灯芯爆响时耳朵后压。4.5-8.0秒，云羊眉头收紧质问。8.0-13.0秒，陈迹不抬头，收笔后回应，霜痕只沿圆墨点边缘扩散。
【对白时间窗一】4.7-7.2秒，仅云羊开口，以冻结声纹、急躁和不安只说一次：人都死了，还写什么？死了后短停，重读人都死了、还写什么，尾句上扬。陈迹闭口。
【对白时间窗二】8.6-11.9秒，仅陈迹开口，以冻结声纹、冷定反击只说一次：收货的那头，还在等。那头后短停，重读收货的那头、还在等，最后三字更实。云羊闭口。
【终态】陈迹笔尖离纸，云羊保持前倾呼吸，乌云注视墨点；无文字、无字幕。
""",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    rows = {row["shot_id"]: row for row in json.loads(V4_PLAN.read_text(encoding="utf-8"))}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    output = []
    for unit, prompt in PROMPTS.items():
        prompt_path = PROMPT_DIR / f"E38-{unit}-V5-FAILED-ONLY-CHANGED-PRO1080P.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        row = dict(rows[unit])
        row.update({
            "prompt_file": str(prompt_path),
            "prompt_sha256": digest(prompt_path),
            "out_dir": str(ROOT / f"working_assets/e38_replacement_v5_20260805/pro/{unit}"),
            "status": "READY_TO_SUBMIT",
            "retry_of_task_id": {
                "U01": "d8c959e8-e6ac-47fb-99df-3607c4c6c205",
                "U03": "cca578f1-fd4e-4a02-9d1e-daf93b078ee0",
                "U09": "6fcbaee8-e250-457d-9412-ce3d57e5e920",
                "U10": "149d22c4-e841-4728-a5e4-cbe0061457dd",
            }[unit],
            "material_change": "STRUCTURAL_TEXT_RENDER_REWRITE_AND_EXCLUSIVE_DIALOGUE_TIME_WINDOWS",
        })
        output.append(row)
    RUN_PLAN.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": sorted(PROMPTS), "plan": str(RUN_PLAN)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
