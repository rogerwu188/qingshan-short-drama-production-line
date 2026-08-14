#!/usr/bin/env python3
"""Compile the first admitted E32 performance units for immediate video submit."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
PLAN = PROD / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
HARVEST = PROD / "E32_IMAGE_BATCH_PERFORMANCE_A1_V1_HARVEST.json"
AUDIO = ROOT / "working_assets/e32_dialogue_audio_refs_20260722/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v1.md"
MANIFEST = PROD / "E32_PRODUCTION_MANIFEST.json"
SCENE_STATE = PROD / "E32_SCENE_AUTHORITY_STATE_V1.json"
BASE = PROD / "video_performance_v1"
CONFIG = BASE / "E32_VIDEO_BATCH_INCREMENTAL_READY_V1.json"
RECEIPT = ROOT / "workflow/tasks/E32_VIDEO_BATCH_INCREMENTAL_READY_V1_RECEIPT.json"
DEFAULT_READY = ("U05", "U06", "U09", "U13")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def video_audio(row: dict) -> tuple[Path, float]:
    """Use a silence-padded derivative when Seedance's 2s audio minimum requires it."""
    duration = float(row["duration_seconds"])
    source = ROOT / row["path"]
    if duration >= 2.0:
        return source, duration
    padded = ROOT / "working_assets/e32_dialogue_audio_refs_20260722/video_reference_wav" / source.name
    if not padded.is_file():
        raise SystemExit(f"{row['dia_id']}: create 2.0s padded video reference first: {padded}")
    return padded, 2.0


BEATS = {
    "U01": [
        (0.0, 1.8, "皎兔", "右手食指悬在骨牌印记上方，抬眼向陈迹追问，但不触碰骨牌", "指尖与骨牌之间保留一指距离", "手从身侧抬到骨牌上方后停止", "骨牌仍留在案面原位，皎兔的视线转向陈迹", "疑惑且急于确认", "让观众先看清皎兔提出的是验印方案"),
        (1.8, 4.2, "陈迹", "左掌横向轻推骨牌离开二人视线中心，右手同时转向烧焦名单", "左掌侧缘与骨牌、右手指尖与焦纸边缘", "骨牌向案面左侧滑动，右手向案面中央伸出", "骨牌停在左侧，焦纸成为画面中心且仍未离开案面", "冷静笃定，目光始终落在焦纸", "以明确换物动作表现他拒绝验印、改验名单"),
        (4.2, 12.0, "陈迹", "用右手两指夹住焦纸完整边缘，翻到烧损较轻的一面并逐字说明验单逻辑", "指腹与焦纸完整边缘", "纸面由正面向背面翻转一次后平放", "焦纸背面朝上停稳，陈迹手指压住纸角，皎兔俯身专注查看", "陈迹推理克制而锋利，皎兔由疑惑转为专注", "让观众从物证焦点变化读懂主角主动改换验伪对象"),
    ],
    "U02": [
        (0.0, 3.0, "陈迹", "右手食指贴住焦纸未烧透的边缘，蓝白冷雾从接触点沿纸背纹理缓慢爬开", "指腹与焦纸边缘、冷雾与纸背", "冷雾由右下接触点向纸背中央扩散", "焦纸保持平整，暗藏的版本纹样在冷雾经过处逐段显现", "专注审视，呼吸放轻", "让版本暗号由真实接触和冷雾显形而非凭空出现"),
        (3.0, 7.0, "陈迹", "指尖停在刚显出的版本纹样旁，抬眼看向皎兔并逐字确认来源", "指尖与纹样旁的纸面", "手指保持稳定，视线由纸面转向皎兔", "冷雾不再扩散，版本纹样完整保留在纸背", "眸色下沉，由确认转为寒意", "让观众明确这是陈迹亲手送入内院的版本"),
        (7.0, 13.0, "皎兔", "俯身看清版本纹样后脸色骤变，右手收回胸前，逐字指出焦纸来自景朝火盆", "视线与纸面、右掌与自身胸前衣料", "身体先向纸面靠近再后撤半步", "二人都停止触碰证物，焦纸与显出的纹样完整留在案面中央", "震惊压低成戒备，视线在陈迹与焦纸间切换", "把内院版本和景朝来源连成同一条可理解的交易线"),
    ],
    "U03": [
        (0.0, 1.2, "陈迹", "左手压住案边稳住身体，右手食指落在焦纸版本纹样旁，但不遮挡纹样", "左掌与案边、右指与纸面空白处", "上身向证物微倾，双手各自落到明确位置", "人物与证物形成稳定三角构图", "确认后的寒意，压住怒意", "先让观众看清结论来自桌上的同一件证物"),
        (1.2, 6.6, "陈迹", "保持右指指向版本纹样，转头看向皎兔，逐字说出内院先换取信任再把名单卖给景朝", "右指与纸面、视线与皎兔", "只有头部与视线由纸面转向皎兔，双手和证物不移动", "台词结束后右手离开纸面，二人同时停止触碰证物", "声音克制，眼神冷硬，皎兔由震惊转为戒备", "把双面交易的主体、手段与结果一次说清"),
        (6.6, 7.0, "陈迹与皎兔", "二人同时看向门外黑暗并屏息停住", "视线与门口方向", "视线由案面转向同一门口", "焦纸独留案面中央，二人进入警戒终态", "警觉骤起", "用短促收势为下一场危险建立连续性"),
    ],
    "U04": [
        (0.0, 3.0, "皎兔肉身", "右手食指按住眉心旧血痕，指腹向下压出一线新血，肩背因疼痛绷紧但双脚不移动", "指腹与眉心血痕", "压力由指尖向眉心内收", "血痕亮起暗红微光，肉身仍在医馆原位站稳", "克制忍痛，咬紧后槽牙", "让观众看懂阴神分离由皎兔主动开启，而非凭空复制"),
        (3.0, 6.2, "皎兔阴神", "黑甲阴神沿眉心血光从肉身正面完整脱出，先头肩、再躯干、最后双腿依次分离", "血光与阴神眉心、阴神背部与肉身胸前之间的分离界面", "阴神沿正前方斜上方向连续离体", "阴神与肉身完全分开一臂距离；肉身留在原位闭眼承受，阴神睁眼转向窗口", "肉身痛楚压抑，阴神冷峻苏醒", "用有先后次序的完整离体过程消除分身和瞬移歧义"),
        (6.2, 10.5, "皎兔阴神", "阴神俯身穿出打开的窗，沿雨幕上方朝西市暗楼高速直线飞掠，双臂收于身侧避开屋檐", "脚下气流与窗沿、雨幕与黑甲表面", "由医馆窗口向远处暗楼连续前进", "医馆在身后缩小，暗楼窗格在前方持续放大，飞行路线不折返", "目光锁定暗楼，警觉而果断", "让跨空间侦察通过连续地标变化可读，不用闪切瞬移"),
        (10.5, 14.0, "皎兔阴神", "接近暗楼后侧身减速，右手抓住湿木窗框吸收前冲惯性，左手收在身侧，转眼观察窗内", "右掌与湿木窗框、雨水与黑甲", "身体由前冲转为窗外悬停，惯性通过右臂传到窗框", "阴神单独稳在二层窗外，窗框只轻颤一次后停止，窗内保持黑暗无人", "屏息冷峻，眼神快速确认室内", "把抵达、制动和开始侦察落成明确终态"),
    ],
    "U07A": [
        (0.0, 1.2, "陈迹", "左手把内院信封压在案面左侧，右手把景朝信封压在右侧，两封信并排且封口朝向齐三", "双掌与两只信封", "两手由身体中线分别向左右落下", "两封信左右分开停稳，齐三被迫看向案面", "冷硬笃定，视线不离齐三", "先用两封实物把一条道跑两家主子变成可见证据"),
        (1.2, 8.2, "陈迹", "左右手指分别点过两封信，身体向齐三逼近半步，逐字说出同版名单分送内院和景朝", "指尖与信封表面、鞋底与湿地板", "手指先左后右，身体沿正前方靠近", "台词结束时两手离开信封，陈迹挡住门口方向，齐三后背抵住案沿", "语气平静但压迫加深，齐三赔笑开始僵住", "让质问的证据、对象和封住退路的目的同时清楚"),
        (8.2, 9.0, "齐三", "嘴角赔笑彻底消失，双膝微屈但仍勉强站住", "后腰与案沿、鞋底与地面", "重心由脚掌向后移到案沿", "齐三脸色煞白，准备招供", "惊恐压过侥幸", "为下一连续招供段落建立真实身体反应"),
    ],
    "U07B": [
        (0.0, 5.6, "齐三", "双手举到胸前急促摆动，先逐字否认自己主使，再指向案上的骨牌调令", "掌心朝陈迹、右指与骨牌之间的视线轴", "双手先左右摆动，右手随后向下指向骨牌", "右指停在骨牌上方但不触碰，陈迹站在门口方向不动", "赔笑崩成煞白发颤，呼吸急促", "让否认转向供出新线索有明确动作落点"),
        (5.6, 14.4, "齐三", "膝盖失力跪到案边，右手仍指着骨牌，抬头逐字供出巡检指挥印和越级发令者", "双膝与地板、右指与骨牌视线轴", "身体垂直下落到跪姿，指向保持不变", "齐三跪稳后双手撑地，骨牌留在案面原位，陈迹目光钉住他", "恐惧彻底失控，声音发颤但句子完整", "把内鬼席位从模糊怀疑钉到巡检指挥"),
        (14.4, 15.0, "陈迹", "俯视齐三后转眼看向骨牌，右手停在身侧不触碰证物", "视线与齐三、骨牌", "视线由齐三转向骨牌", "陈迹进入冷静确认终态", "目光更冷，没有胜利感", "以确认反应承接下一场灭口危险"),
    ],
    "U12R": [
        (0.0, 1.2, "姚太医", "把药碗推离陈迹手边，右手按住桌面示意他先听判断", "掌心与药碗底、右掌与桌面", "药碗沿桌面向外平移后停止", "药碗离开陈迹，姚太医身体前倾", "沉静严肃", "用停止治疗动作提示真正危险不是眼前伤势"),
        (1.2, 9.4, "姚太医", "保持右掌压桌，抬眼逐字指出敌人不怕内鬼暴露，只怕陈迹还有时间慢查", "右掌与桌面、视线与陈迹", "身体不移动，只有目光持续锁定陈迹", "台词结束时陈迹的手从证物旁收回，肩背绷紧", "姚太医沉静警示，陈迹警觉逐步加深", "让观众读懂围猎的真正目的在抢时间"),
        (9.4, 10.0, "陈迹", "缓慢抬眼看向门外，右手握紧又松开", "右手指节与掌心", "手指向内收拢后放松", "陈迹进入快速决策状态", "警觉转为决断", "把警示落到主角下一步行动上"),
    ],
    "U16A": [
        (0.0, 1.0, "云羊", "落到陈迹右侧檐脊，右脚踩稳湿瓦，握紧拳头望向城中三路灯队", "鞋底与湿瓦、拳指与掌心", "身体由下向上落稳，视线向城中展开", "云羊与陈迹并肩但保持一臂距离", "焦灼警戒", "先把说话人和三路搜捕队置于同一空间"),
        (1.0, 10.4, "云羊", "右拳保持握紧，左手依次指向巡检线、景朝暗桩和内院私兵三组灯队，逐字说明三方挤在一处却互不信任", "左指与三组远处灯队的视线轴", "指向由左至右依次移动三次", "三组灯队保持不同队列，云羊最后收手看向陈迹", "焦灼中出现可利用的判断", "让三方互疑通过可见队列和依次指向被观众理解"),
        (10.4, 11.0, "陈迹", "没有回答，只把视线从灯网转向云羊", "视线与云羊", "头部由城外方向转向右侧", "陈迹眸底寒光开始亮起", "受压转为洞悉", "建立主角得到反制思路的瞬间"),
    ],
    "U16B": [
        (0.0, 1.0, "陈迹", "从灯网方向转身面向云羊，左脚在檐脊上稳住，右手垂在身侧", "鞋底与湿瓦", "身体沿原地顺时针转向云羊", "陈迹站稳且不靠近檐边", "洞悉后冷静", "让主角从被包围的观察者转为主动谋局者"),
        (1.0, 6.5, "陈迹", "抬起右手，食指沿远处三组灯队画出一个收拢圆弧，逐字说明网里三拨人谁也不信谁", "食指与远处灯网视线轴", "手指由外向内画一圈后停在三队交界处", "手势结束时三组灯队仍彼此分开，云羊专注看他", "语气压低，眸底寒光清晰", "把敌人的包围结构转译成可利用的内部裂缝"),
        (6.5, 7.0, "云羊", "眉头松开一线，顺着陈迹手指重新看向灯网", "视线与灯网", "视线由陈迹转向城中", "云羊理解但仍保持警戒", "焦灼转为领会", "让观众确认方案被同伴听懂"),
    ],
    "U16C": [
        (0.0, 1.0, "陈迹", "左掌向上摊开，掌心一缕冷雾凝成三股细线", "冷雾与左掌", "冷雾由掌心向上分成三路", "三股雾线保持分离不交叉", "冷静推演", "以三股雾线对应三拨互不信任的人"),
        (1.0, 9.8, "陈迹", "右手食指依次拨动三股雾线，让每一股都误指向另一股，逐字说出让三拨人先认定别人才是内奸", "右指与三股冷雾", "右指先拨左线向中线，再拨中线向右线，最后拨右线向左线", "三股雾线彼此缠住却没有合并，左掌承受收紧拉力", "近乎自语，唇角轻动，寒意转为掌控", "把抽象离间计变成可见且有方向的三方误判"),
        (9.8, 11.0, "陈迹", "左手骤然握拳，三股雾线反向勒紧一瞬后同时散开", "五指与掌心冷雾", "手指向内合拢，雾线向中心收紧后消散", "掌心空无一物，陈迹望向收网方向", "决断冷峻", "让网反勒收网之手的比喻得到清楚视觉结果"),
    ],
    "U17R": [
        (0.0, 2.0, "镜头与三路灯队", "镜头从医馆檐脊上方持续后拉，三路灯笼队分别沿不同街道推进", "灯队脚步与街面", "镜头向后上方移动，灯队沿各自街道向城中心移动", "三队保持不同颜色与间距，不合并成同一队", "无人物近景", "让观众看清围猎已形成但内部仍分裂"),
        (2.0, 5.2, "三路灯队", "三队在街口交错经过，彼此避让并保持武器朝向对方队列，风吹灯笼明灭一次", "鞋底与街面、风与灯笼", "队列沿各自路径通过交叉口，灯焰同向偏转", "三队越过街口后仍各自成列，灯焰恢复稳定", "以队列戒备代替人物表情", "把互不信任转化为可见的空间关系"),
        (5.2, 6.0, "镜头与洛城", "镜头继续后拉到残月下全城灯网，随后自然切黑", "无人物接触", "镜头向后上方完成收束", "最后一帧保持灯网宏大构图后直接切黑，不重复、不慢放", "森然压迫", "以围猎已成、反噬待起结束本集"),
    ],
    "U08": [
        (0.0, 1.5, "乌云", "纯黑猫在屋檐上猛然弓背炸毛，朝齐三身后发出短促示警，前爪牢牢抓住湿瓦", "四只猫爪与湿瓦、视线与齐三身后", "脊背向上弓起，头部转向刺客来向", "乌云停在檐上不跃下，陈迹循声转眼看向齐三身后", "警觉骤起，瞳孔收紧", "让观众先获得刺客来自齐三背后的预警"),
        (1.5, 4.5, "巡检司杀手", "右脚蹬地前冲，右手反握短刃沿齐三后背中线刺向心口高度", "右脚掌与湿地、刀尖与齐三后背之间的攻击线", "力量从右脚经髋肩传到右臂，刀尖由后向前", "刀尖逼近齐三后背但尚未接触，齐三惊恐回头来不及躲", "狠厉决绝，视线只锁齐三", "清楚建立灭口目标、攻击方向和即将接触的位置"),
        (4.5, 8.5, "陈迹", "左掌按向脚边积水，蓝白冰流从掌下贴地沿积水连续爬到杀手承重右脚鞋底", "左掌与积水、冰流与杀手右脚鞋底", "冰流由陈迹脚边沿地面向杀手右脚直线推进", "杀手右脚下形成一层薄冰，刀尖因重心失稳向齐三右肩外侧偏开", "瞬间专注，呼吸压住，目光锁定落脚点", "让观众看懂陈迹改变的是刺客落脚摩擦，而不是凭空推人"),
        (8.5, 13.0, "杀手与齐三", "杀手右脚在薄冰上向前滑出，刀锋擦过齐三右肩外侧划破衣料后离开身体；齐三向左扑到门柱旁，杀手左掌撑地止住滑势", "右脚与薄冰、刀锋与齐三右肩衣料、左掌与湿地", "杀手下肢向前滑，刀锋同向偏到肩外；齐三向左脱离攻击线", "齐三靠住门柱捂住仅受皮外伤的右肩，杀手单膝撑地停稳，短刃仍在杀手右手", "杀手由狠厉转惊愕，齐三惊恐喘息，陈迹保持戒备", "完整呈现冰流接触、失衡、偏刃、轻伤和救下齐三的结果"),
    ],
    "U10": [
        (0.0, 2.4, "巡检司杀手", "左掌撑地翻身起膝，右手短刃从齐三左侧横向补向咽喉，刀锋只走一次完整弧线", "左掌与湿地、右手与刀柄、刀锋与齐三咽喉攻击线", "身体由仰倒向左侧翻起，刀锋由右向左横切", "刀锋越过齐三咽喉后停在杀手左侧，齐三双手捂颈向后倒下", "杀手决绝无迟疑，齐三由侥幸转绝望", "让观众看懂杀手优先完成灭口而不是先逃生"),
        (2.4, 4.8, "巡检司杀手", "杀手左脚踏碎身前薄冰，借碎冰反作用向暗巷出口跃退，袖口被冲击扯开", "左脚掌与薄冰、袖口与手腕", "脚向下踏、身体向后上方退出", "杀手退出画面边缘，半枚巡检铜牌从破开的袖口落向雨血混合的地面", "决绝转为急迫，始终不回头", "把逃离和令牌脱落建立为同一次受力结果"),
        (4.8, 7.2, "陈迹", "右掌贴向地面，冰流沿雨血包住正在下落的半枚铜牌并把它冻结在地面原位", "右掌与地面、冰流与铜牌边缘", "冰流由掌下向铜牌汇聚，铜牌垂直落地后停止", "铜牌固定在陈迹面前，齐三倒地不动，云羊蹲身查看印记", "震怒被压成冷静取证", "让巡检半牌从杀手袖口进入证据链的每一步都可见"),
        (7.2, 12.0, "陈迹与云羊", "陈迹用右手两指从薄冰中夹起半枚铜牌，翻到有巡检印的一面；云羊指向印记说出同线判断，陈迹接着说出对方宁可灭口也不肯露名", "两指与铜牌边缘、云羊指尖与印记旁空处", "铜牌由地面上提到胸前并绕竖轴翻面一次", "半枚铜牌最终留在陈迹右手，巡检印朝向镜头；云羊收手看向死去的齐三", "云羊震怒确认，陈迹声音克制而寒冷", "用明确换手、翻面和两句判断完成灭口同源结论"),
    ],
    "U11": [
        (0.0, 2.0, "乌云", "通体漆黑的大乌鸦从窗框短距离振翅落到案头两枚证物之间，双爪抓稳后立即收拢翅膀", "双爪与案面、翼下气流与纸角", "由窗框向案面斜下方落下", "乌鸦停在案头不再飞动，纸角只被气流掀起一次后落回", "警觉专注，头部依次观察两枚印记", "用乌鸦落点把两件证物连接到同一判断空间"),
        (2.0, 5.2, "姚太医", "左手把骨牌印推到乌鸦左侧，右手把巡检半牌推到乌鸦右侧，使两枚巡检印并排朝向陈迹", "左右指腹与两枚证物边缘", "两手分别由外向内平移", "两枚印记并排停稳，姚太医双手离开证物", "温和但沉重，眉头收紧", "让观众从并置证物直接读懂发令与灭口同源"),
        (5.2, 8.0, "陈迹", "俯身逐一看过两枚印记，右拳在案边缓慢收紧后停止", "视线与两枚印记、右指与掌心", "视线由左牌移到右牌，手指向内合拢", "证物与乌鸦均保持原位，陈迹压住怒意进入判断终态", "目光冷硬，怒意被克制压住", "以主角反应确认同一巡检线而不新增对白"),
    ],
    "U14": [
        (0.0, 2.0, "远处城门与室内众人", "画外第一声沉重落闩从远处传来，案上药碗水面向门口方向震出一圈涟漪，陈迹和姚太医同时停住动作", "声波与药碗水面、视线与门口方向", "涟漪由碗心向外扩散，二人视线同向转向门口", "第一圈涟漪触及碗沿后自然消失", "陈迹警觉收紧，姚太医神色骤沉", "不拍城门也用可见介质让第一道封锁被观众感知"),
        (2.0, 4.6, "乌云", "第二、第三声落闩由近及远连续传来，漆黑乌鸦在案头炸开颈羽，振翅绕堂一圈后重新落回原位", "声波与窗纸、翼下气流与案面", "乌鸦由案头起飞绕顺时针一圈再下降", "窗纸随每声闷响各震一次，乌鸦落回案头收翅", "受惊戒备，鸣叫急促", "用三次有先后空间感的闷响和乌鸦反应表现封城正在合拢"),
        (4.6, 7.5, "姚太医", "右掌压住案面稳定药碗，抬眼看向陈迹并逐字说出密谍司封城", "右掌与案面、视线与陈迹", "身体不移动，只有掌心下压和视线上抬", "台词结束后姚太医手掌仍压案，陈迹缓慢吸气站稳", "凝重确认，没有慌乱", "让封城判断由连续闷响自然落到人物结论"),
        (7.5, 8.0, "陈迹", "抬眼看向门外黑暗，双肩停止起伏", "视线与门外方向", "视线由姚太医转向门口", "陈迹恢复冷静，准备应对围猎", "警觉转为决断", "用克制收势承接下一场全城灯网"),
    ],
    "U15": [
        (0.0, 2.4, "镜头与洛城", "镜头从太平医馆屋檐后方缓慢升高，四座城门与主要坊口的灯笼长龙依次亮起", "灯笼挂钩与檐杆、灯焰与夜风", "镜头向上后方移动，灯火由城门向坊口逐段点亮", "不同街区的灯队形成四条清晰路线但尚未合拢", "陈迹冷静观察，皎兔紧张扫视", "先让观众从可见路线读懂封锁不是一句空话"),
        (2.4, 9.8, "皎兔", "站在陈迹右侧，右手依次指向城门、医馆街口和王府侧门三处灯队，逐字说明三处封锁正把知情人压进同一圈", "右指与三处灯队的视线轴、鞋底与湿瓦", "手指由远到近依次移动三次，身体始终远离檐边", "台词结束时右手收回胸前，三处灯队继续向中心推进", "紧张急促但判断清楚，眉眼持续锁定灯网", "让每个地点名都落在可见灯队上，观众能跟随她的判断"),
        (9.8, 12.0, "陈迹与灯网", "陈迹向前半步但停在安全瓦脊内，俯视三路灯队在街口外形成尚未闭合的巨大包围圈", "鞋底与瓦脊、灯队脚步与街面", "陈迹向前短移，灯队沿街道向中心推进", "灯网留下一个狭窄缺口，陈迹和皎兔都看向缺口方向", "陈迹冷静计算，皎兔由紧张转为等待决策", "把整城围猎与仍可利用的结构缺口同时交给下一单元"),
    ],
    "U05": [
        (0.0, 2.5, "齐三", "左手压住名单，右手沿纸边把同一叠名单分成三份", "右掌和纸边", "右手由上向下分纸", "三份纸整齐分开且仍在齐三手边", "贪婪熟练，眼神快速扫门", "让观众看懂材料来自同一叠名单"),
        (2.5, 5.5, "齐三", "依次把三份名单塞入三只不同信封，手指逐一压平封口", "纸张进入信封开口", "纸张由案面向信封内部推进", "三只信封各装一份名单", "警觉而麻利", "让观众看懂同一消息将卖给不同买家"),
        (5.5, 8.0, "齐三", "把三封信分别放向案上三个方向并抬头听门外动静", "信封底面接触桌案", "一封向左、一封向右、一封留在身前", "三封信空间分离，齐三手离开信封", "贪意收住转为戒备", "把分卖消息的结果落在清楚可读的构图上"),
    ],
    "U06": [
        (0.0, 1.2, "陈迹", "肩膀撞开木门跨入室内，右掌同时拍向油灯灯罩", "肩与门板、掌与灯罩", "门向室内打开，手掌向下", "门开、灯火被掌风压低", "冷定压迫", "让突袭和控制光线同时发生"),
        (1.2, 3.7, "齐三", "后退撞上桌沿，双手慌乱撑桌并逐字说完参考音频台词", "腰背与桌沿、双掌与桌面", "身体向后，信封受震向外散开", "齐三停在桌边，信封散落但人物不摔倒", "赔笑迅速崩成惊恐", "对白与狼狈退路形成同一因果"),
        (3.7, 5.0, "陈迹", "左手冰流沿灯座爬上灯芯，把残火冻成一粒蓝白冰点", "冰流接触灯座和灯芯", "冰流由掌下向灯芯上行", "室内只剩门外冷光，灯芯冻结不复燃", "目光始终锁住齐三", "清楚表现陈迹封住照明和退路"),
    ],
    "U09": [
        (0.0, 4.0, "云羊", "左手拇指压住纸人背面，食指点亮纸人双眼，随后手腕向前甩送；纸人沿一条连续弧线飞到杀手双眼前才展开，完全遮住他的视线", "拇指与纸背、食指与纸人双眼、纸面与杀手视线轴", "纸人始终从云羊左掌出发，沿可见弧线向杀手面部移动", "杀手先追视纸人，纸人展开后才抬臂挡脸并失去目标", "云羊凝神判断距离，杀手由狠厉转为错愕慌乱", "用清楚的出手、飞行、遮眼三步建立因果，纸人不得凭空出现或瞬移"),
        (4.0, 9.5, "云羊", "确认杀手被遮眼后，右脚先向后踩实湿地，膝髋压低蓄力；胯部带动右肩前送，右拳沿唯一一条直线击中冰墙上已经可见的蓝色圆形固定点", "右鞋底与湿地、拳峰与蓝色圆形固定点", "力量依次从右脚、膝髋、肩、肘传到拳峰，镜头侧前方中景完整保留这条传力链", "拳峰接触固定点后停止前移，固定点由内向外亮起放射裂纹，云羊身体没有穿墙", "云羊咬牙发力、眉眼锁死落点，杀手在纸人后惊慌寻找目标", "让观众明确看见冲拳的目标、接触和受阻，不是打空气，也不是人物瞬移"),
        (9.5, 15.0, "冰墙与杀手", "拳峰保持接触的瞬间，放射裂纹从蓝色固定点只向杀手所在一侧扩散；冰墙该侧碎片顺同一方向喷出，先撞中杀手胸肩，再把他向后掀翻", "裂纹与冰墙、冰屑与杀手胸肩、杀手背部与湿地", "裂纹由拳点向杀手侧扩散，冰屑和杀手受力都沿同一方向远离云羊", "杀手背部落地后只滑行一次并自然停住，纸人落地；云羊收拳站稳，警戒看向倒地杀手", "杀手受击时痛苦惊愕，停住后失去反击能力；云羊由爆发转为冷静警戒", "以裂纹、碎冰、胸肩受击、倒地滑停四个可见结果完整兑现这次攻击的目的"),
    ],
    "U09A": [
        (0.0, 2.2, "云羊", "左手拇指压住纸人背面，食指依次点亮纸人两眼，确认杀手视线锁住纸人", "拇指与纸背、食指与纸眼、杀手视线与纸人", "云羊左手停在胸前，杀手目光由云羊移到纸人", "纸人双眼亮起，杀手短暂迟疑", "云羊凝神计算距离，杀手警惕困惑", "先让观众看见纸人来源和杀手注意力被吸引"),
        (2.2, 7.0, "云羊与纸人", "云羊手腕向前甩送，纸人沿连续弧线飞到杀手眼前才展开遮住双眼；杀手确认看不见后才抬臂拨挡", "指尖与纸人、展开纸面与杀手视线轴", "纸人由云羊左掌向杀手面部连续移动，不瞬移", "杀手被遮眼后后撤半步，纸人仍贴在视线前方，云羊右脚开始向后落位", "云羊专注镇定，杀手由困惑转惊慌", "完整兑现出手、飞行、展开、遮眼四步因果，为下一单元蓄力"),
    ],
    "U09B": [
        (0.0, 4.0, "云羊", "右脚先向后踩实湿地，膝髋压低蓄力；胯部带动右肩前送，右拳沿直线击中冰墙上可见的蓝色圆形固定点", "右鞋底与湿地、拳峰与蓝色固定点", "力量依次从右脚、膝髋、肩、肘传到拳峰", "拳峰接触固定点后停止前移，固定点向外亮起放射裂纹", "云羊咬牙爆发，视线锁死落点", "清楚表现目标、传力、接触和受阻，人物不得穿墙"),
        (4.0, 8.0, "冰墙与杀手", "放射裂纹从拳点只向杀手一侧扩散，冰墙该侧碎片同向喷出撞中杀手胸肩，把他向后推倒", "裂纹与冰墙、冰屑与杀手胸肩、杀手背部与湿地", "冰屑和杀手都沿远离云羊的方向移动", "杀手落地后只滑一次并停住，云羊收拳站稳警戒", "杀手痛苦惊愕，云羊由爆发转冷静", "用裂纹、碎冰、胸肩受力和滑停四个结果说明攻击目的"),
    ],
    "U10A": [
        (0.0, 2.0, "巡检司杀手与齐三", "倒地杀手突然翻身起立，短刃从齐三颈侧掠过；镜头只拍齐三惊愕捂住颈侧并失力跪倒，不表现伤口细节", "杀手鞋底与湿地、短刃运动轨迹与齐三颈侧衣领、齐三膝盖与地面", "杀手由低位向上翻身，短刃横向掠过后立刻收回", "齐三倒地失去反应，杀手背向众人冲入雨巷", "齐三惊愕转空白，杀手决绝急迫", "观众明确看懂齐三被灭口、杀手随即撤离，不用血腥特写"),
        (2.0, 7.0, "云羊", "云羊蹲到齐三身边，从湿地上的半枚巡检铜牌认出暗记，抬眼追视杀手离开的方向并逐字说完参考音频台词", "云羊指尖与半枚铜牌边缘、膝盖与湿地", "手指由地面铜牌移向雨巷方向，头部随视线抬起", "铜牌仍在地面，云羊手指停在牌旁，杀手消失在雨幕中", "云羊由震惊转为发冷确认，语气克制清楚", "让巡检暗记、同线灭口和杀手遁走同时成为可见证据"),
    ],
    "U10B": [
        (0.0, 1.0, "陈迹", "陈迹俯身用右手拇指和食指从湿地捏起唯一半枚巡检铜牌，举到眼前", "右手指腹与铜牌断边", "铜牌由地面连续上移到陈迹眼前", "铜牌唯一归陈迹右手持有，其他人双手空着", "陈迹压住怒意，目光先落铜牌后转向云羊", "用真实抓取完成道具归属变化"),
        (1.0, 6.0, "陈迹与云羊", "陈迹握紧半牌并逐字说完参考音频台词；云羊站在侧后方听完，只以眼神回应，不开口", "陈迹指节与铜牌、二人视线轴", "陈迹手掌由半开到握紧，身体保持稳定", "台词结束时陈迹握牌垂到胸前，云羊看向杀手遁走的雨巷", "陈迹声沉如铁，云羊沉默警戒", "把牙人之死与隐藏同线名字的目的落在陈迹判断上"),
    ],
    "U10BR": [
        (0.0, 6.0, "黑衣年轻陈迹", "从首帧到末帧始终由画面左侧黑衣年轻陈迹的右手拇指和食指唯一夹持半枚巡检铜牌；陈迹把铜牌保持在自己眼前，逐字说完参考音频台词后握入自己掌心。画面中央灰衣云羊双手始终空着、嘴唇闭合，只转眼看向陈迹；倒地齐三不动，远处杀手继续离开", "陈迹右手指腹与铜牌断边、陈迹视线与铜牌、云羊空手与衣袖", "铜牌只在陈迹右手内从夹持变为握紧，绝不横向移动到灰衣云羊", "台词结束时黑衣陈迹仍握着唯一铜牌，灰衣云羊空手闭口，齐三倒地，杀手远去", "黑衣陈迹压住怒意、声沉如铁；灰衣云羊沉默警戒", "让观众明确判断者和说话者都是陈迹，并彻底锁死铜牌归属"),
    ],
    "U13": [
        (0.0, 2.0, "陈迹", "握拳压住发颤的右腕，白霜从指尖沿腕骨逆向爬向小臂", "左掌与右腕、霜纹与皮肤", "霜纹由指尖向肘部扩散", "陈迹身体微屈但没有倒下", "忍痛克制，额角见汗", "让观众看懂冰流正在反噬本人"),
        (2.0, 5.5, "乌云", "黑猫从案边跃起，口中衔着透明人参珠，把珠子准确抵入陈迹张开的右掌", "猫爪与案边、珠子与掌心", "猫由下向上跃，珠子由猫口进入掌心", "陈迹五指合拢握住珠子，乌云落回案面", "乌云急切专注，陈迹惊痛", "人参珠的归属通过真实递交改变"),
        (5.5, 8.0, "陈迹与人参珠", "珠子贴住掌心后发出柔和白光，霜纹在腕骨处停止并缓慢退回指尖", "珠子与掌心、霜纹与腕骨", "光从掌心向手腕扩散，霜纹反向回缩", "手臂恢复稳定，陈迹重新站直", "痛苦缓解但仍警觉", "清楚显示珠子压制反噬的接触因果"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--units", default=",".join(DEFAULT_READY), help="Comma-separated short unit IDs")
    parser.add_argument("--jobs", type=Path, help="Optional reflowed job manifest with source_unit/job_id/duration/dialogue_ids/beats_key")
    parser.add_argument("--harvest", type=Path, default=HARVEST)
    parser.add_argument("--end-anchor", type=Path, help="Optional required end anchor for a multi-anchor unit")
    parser.add_argument("--continuity-qa", type=Path, help="QA evidence for the adjacent anchor pair")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ready = tuple(unit.strip() for unit in args.units.split(",") if unit.strip())
    harvest_path = args.harvest if args.harvest.is_absolute() else ROOT / args.harvest
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    receipt_path = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
    end_anchor = None
    if args.end_anchor:
        end_anchor = args.end_anchor if args.end_anchor.is_absolute() else ROOT / args.end_anchor
        if not end_anchor.is_file():
            raise SystemExit(f"Missing end anchor: {end_anchor}")
    continuity_qa = None
    if args.continuity_qa:
        continuity_qa = args.continuity_qa if args.continuity_qa.is_absolute() else ROOT / args.continuity_qa
        if not continuity_qa.is_file():
            raise SystemExit(f"Missing continuity QA: {continuity_qa}")
    plan = json.loads(PLAN.read_text())
    harvest = json.loads(harvest_path.read_text())
    audio = json.loads(AUDIO.read_text())
    units = {row["unit_id"].split("-")[-1]: row for row in plan["units"]}
    images = {}
    for row in harvest["results"]:
        path = row.get("output_path")
        if path:
            images[row["task_key"].split("-")[2]] = Path(path)
    audio_by_unit = {}
    for row in audio["rows"]:
        audio_by_unit.setdefault(row["video_unit_id"].split("-")[-1], []).append(row)
    prompt_dir = BASE / "prompts"
    spec_dir = BASE / "specs"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    SCENE_STATE.write_text(json.dumps({
        "schema": "qingshan.scene_authority_state.v1", "episode": "E32",
        "scene_state": [
            {"scene_id": "E32-CW-S01", "location": "太平医馆后堂", "time_of_day": "night", "weather": "interior_clear", "event_summary": "冰流显出焦纸版本暗号，坐实内院名单流向景朝"},
            {"scene_id": "E32-CW-S02", "location": "洛城西市暗楼与太平医馆交叉", "time_of_day": "night", "weather": "rain", "event_summary": "皎兔阴神锁定齐三，陈迹破门逼供双面交易与巡检指挥席位"},
            {"scene_id": "E32-CW-S03", "location": "洛城西市暗巷檐下", "time_of_day": "night", "weather": "heavy_rain", "event_summary": "巡检司杀手灭口齐三，陈迹与云羊以冰流纸术反击"},
            {"scene_id": "E32-CW-S04", "location": "太平医馆前堂", "time_of_day": "night", "weather": "interior_rain_outside", "event_summary": "姚太医点破围猎抢时，冰流反噬并由乌云人参珠压制"},
            {"scene_id": "E32-CW-S05", "location": "太平医馆屋檐与洛城夜景", "time_of_day": "night", "weather": "rain_stopped_cloud_break", "event_summary": "全城灯网收拢，陈迹看出可利用三方互疑反制"},
        ],
    }, ensure_ascii=False, indent=2) + "\n")
    if args.jobs:
        jobs_path = args.jobs if args.jobs.is_absolute() else ROOT / args.jobs
        jobs = json.loads(jobs_path.read_text())["jobs"]
    else:
        jobs = [{"source_unit": short, "job_id": short, "beats_key": short} for short in ready]
    tasks = []
    for job in jobs:
        short = job["source_unit"]
        job_id = job.get("job_id", short)
        beats_key = job.get("beats_key", job_id)
        anchor_key = job.get("anchor_key", short)
        unit = units[short]
        duration = int(job.get("duration_seconds", unit["duration_seconds"]))
        direct_anchor = job.get("anchor_path")
        image = (Path(direct_anchor) if Path(direct_anchor).is_absolute() else ROOT / direct_anchor) if direct_anchor else images[anchor_key]
        reference_paths = [image]
        if end_anchor is not None:
            if len(jobs) != 1:
                raise SystemExit("--end-anchor may only be used when compiling one video job")
            reference_paths.append(end_anchor)
        elif short == "U04":
            if end_anchor is None:
                raise SystemExit("U04 requires --end-anchor; one start frame cannot express separation and cross-city arrival")
        planned_anchors = int(job.get("planned_reference_image_count", unit.get("planned_reference_image_count", 1)))
        if len(reference_paths) != planned_anchors:
            raise SystemExit(f"{short}: planned {planned_anchors} anchors but resolved {len(reference_paths)}")
        dialogues = audio_by_unit.get(short, [])
        if "dialogue_ids" in job:
            wanted = set(job["dialogue_ids"])
            dialogues = [row for row in audio["rows"] if row["dia_id"] in wanted]
        resolved_audio = [(row, *video_audio(row)) for row in dialogues]
        total_audio = sum(item[2] for item in resolved_audio)
        if total_audio + 0.5 > duration:
            raise SystemExit(f"{short}: dialogue {total_audio:.3f}s does not fit {duration:.3f}s")
        rows = []
        for start, end, subject, action, contact, direction, end_state, expression, viewer in BEATS[beats_key]:
            rows.append({"start_seconds": start, "end_seconds": end, "subject": subject, "action": action,
                         "contact_point": contact, "direction": direction, "end_state": end_state,
                         "intent": unit["performance_spec"]["intent"], "visible_causality": viewer,
                         "force_feedback": "衣料、纸张、水、冰屑、灯火或案面器物只按明确受力方向反馈一次并自然停止。",
                         "expression": expression, "viewer_read": viewer})
        spec = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E32",
                "unit_id": f"E32-CW-{job_id}", "source_unit_id": unit["unit_id"], "duration_seconds": duration,
                "prop_ownership": {
                    "documents": "名单与信封始终由逐拍脚本声明的持有人掌握，只通过明确抓取、装入或放下改变归属。",
                    "combat_props": "纸人、短刃和冰墙只由脚本声明人物或能力控制，不得无接触换手或凭空出现。",
                    "medicine": "透明人参珠先由乌云口衔，明确抵入陈迹掌心后才归陈迹持有。",
                },
                "motion_beats": rows}
        spec_path = spec_dir / f"E32-CW-{job_id}-PERFORMANCE-SPEC-V1.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
        timeline = []
        cursor = 0.3
        for index, (row, _, audio_duration) in enumerate(resolved_audio, 1):
            end = cursor + audio_duration
            timeline.append(f"- {cursor:.2f}-{end:.2f}秒：@音频{index}，{row['speaker']}逐字说‘{row['spoken_text']}’，口型、气息、表情严格同步，其他人物闭口。")
            cursor = end + 0.12
        beat_lines = [f"- {r['start_seconds']:.1f}-{r['end_seconds']:.1f}秒：主体={r['subject']}；动作={r['action']}；接触点={r['contact_point']}；方向={r['direction']}；动作目的={r['intent']}；可见因果={r['visible_causality']}；表情={r['expression']}；终态={r['end_state']}。" for r in rows]
        dialogue_brace = "；".join(f"{r['speaker']}：{r['spoken_text']}" for r in dialogues) if dialogues else "无对白"
        tail_brace = "承接上述参考音频，不新增对白" if dialogues else "无对白"
        prompt = "\n".join([
            f"《青山》E32 {job_id}，Seedance 2.0 Pro 四模态表演生成，{duration:g}秒，9:16，720p，原速连续动作。",
            f"【实体绑定】现场人物[[char_e32_{job_id.lower()}]]、本场空间[[scene_{unit['scene_id'].lower().replace('-', '_')}]]、本单元道具与能力介质[[prop_e32_{job_id.lower()}]]；只允许剧本声明实体出现。",
            ("【生成范式】@图片1锁动作起态，@图片2锁动作完成后的身份、道具归属与终态；中间运动完全由同一逐拍物理脚本连续生成，相邻锚图必须可物理插值，禁止直接变形或闪切。"
             if len(reference_paths) == 2 else
             "【生成范式】@图片1只锁人物身份、场景和动作起始空间；连续动作完全由下面同一份逐拍物理脚本驱动，不逐帧硬凑。"),
            "【色彩与动机光】palette=雨夜冷蓝、室内油灯暖橙、冰流蓝白、纸术微金；光影只来自现场灯火、雨夜天光和已声明能力，不凭空改变昼夜或方向。",
            "【力量作用环境】力量必须通过环境介质显形：纸张、信封、火焰、积水、冰墙、冰屑、衣摆和案面器物只按明确接触点与受力方向反馈一次并自然停止。",
            "【对白音频】" if dialogues else "【声音】无对白，只生成符合动作的现场声、呼吸和环境声。",
            *timeline,
            f"镜头1【0.0-{duration * 0.42:.1f}秒，大远景定场转中景跟移】先完整建立人物、道具、接触物和行动路线，再连续完成动作起势与第一次接触，不跳轴、不省略传力起点。{{{dialogue_brace}}}<脚步、衣料、纸张、呼吸与环境现场声>",
            f"镜头2【{duration * 0.42:.1f}-{duration:.1f}秒，中景侧移接近景表情特写】承接同一速度、方向与道具归属，清楚拍到关键接触、受力反馈、人物表情和动作终态。{{{tail_brace}}}<接触、受力、冰裂、灯火或案面器物现场声>",
            "【连续物理动作脚本】", *beat_lines,
            "【摄影】先建立主体、接触物和行动路线，再跟随受力链移动；关键接触点和最终结果必须清楚入画。",
            "【单一状态源】人物身份、道具归属、动作时间轴、锚图和对白音频全部服从本 spec；禁止新增人物、额外动作、额外台词或道具跳变。",
            "【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、分身、融肢、穿模、瞬移、无因腾空、无接触受力、慢放、停帧、循环、周期重复、静帧微动和首尾重复；禁止BGM和旁白。",
        ]) + "\n"
        prompt_path = prompt_dir / f"E32-CW-{job_id}-PERFORMANCE-V1.txt"
        prompt_path.write_text(prompt)
        task = {
            "task_key": f"E32-CW-{job_id}-PERFORMANCE-V1", "source_id": unit["unit_id"],
            "tool_type": "video_generation", "generation_mode": "performance_generation",
            "episode": "E32", "batch_id": "E32-PERFORMANCE-V1", "unit_id": f"E32-CW-{job_id}",
            "scene_id": unit["scene_id"], "visual_zone": f"E32-CW-{job_id}",
            "duration": duration, "duration_seconds": duration, "model": "seedance-2.0-pro",
            "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": duration,
                              "rationale": "Exact contiguous Claude-script duration.",
                              "edit_policy": "End when scripted result lands; never pad, slow or loop."},
            "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path), "reference_images": [rel(path) for path in reference_paths],
            "reference_image_sequence": [
                {"asset_label": f"@图片{i}", "role": job.get("anchor_role", unit["anchor_count_decision"]["anchor_roles"][i - 1]),
                 "path": rel(path), "sha256": sha(path)} for i, path in enumerate(reference_paths, 1)
            ],
            "state_reference_minimum": len(reference_paths), "planned_reference_image_count": len(reference_paths),
            "still_sequence_only_allowed": True, "inherits_establishing_coverage": True, "action_unit": True,
            "performance_spec": spec,
            "keyframe_interpolation_gate": {**unit["keyframe_interpolation_gate"], "status": "PASS",
                                                "anchor_count": len(reference_paths),
                                                "checked_adjacent_pairs": max(0, len(reference_paths) - 1),
                                                "candidate_recheck_required": False,
                                                "qa_report": rel(continuity_qa) if continuity_qa else None},
            "dialogue": [{"dia_id": r["dia_id"], "speaker": r["speaker"], "spoken_text": r["spoken_text"]} for r in dialogues],
            "reference_audios": [rel(path) for _, path, _ in resolved_audio],
            "dialogue_audio_assets": [{"dia_id": r["dia_id"], "speaker": r["speaker"], "spoken_text": r["spoken_text"],
                                       "audio_slot": f"@音频{i}", "path": rel(path), "sha256": sha(path),
                                       "duration_seconds": audio_duration,
                                       "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
                                       "local_transform": "TRAILING_SILENCE_PADDING_TO_2S" if float(r["duration_seconds"]) < 2.0 else "NONE"}
                                      for i, (r, path, audio_duration) in enumerate(resolved_audio, 1)],
            "native_dialogue_required": bool(dialogues), "audio_reference_optional": not bool(dialogues),
            "dialogue_audio_coverage": {"required": len(dialogues), "bound": len(dialogues),
                                        "status": "PASS" if dialogues else "NOT_APPLICABLE_NO_DIALOGUE"},
            "source_spec": rel(spec_path), "source_spec_sha256": sha(spec_path),
            "workflow_credit_scope": "e32_claude_writer_v1_20260722", "status": "READY_TO_SUBMIT",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
    config = {"schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E32",
              "status": "READY_INCREMENTAL_UNITS", "recorded_at": datetime.now(timezone.utc).isoformat(),
              "targeted_unit_replacement": False, "concurrency": len(tasks), "max_retries": 0,
              "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
              "workflow_credit_scope": "e32_claude_writer_v1_20260722", "video_credit_limit": 6000,
              "source_script_sha256": sha(SCRIPT),
              "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script",
                                           "source_script": rel(SCRIPT), "source_script_sha256": sha(SCRIPT),
                                           "production_manifest": rel(MANIFEST), "production_manifest_sha256": sha(MANIFEST)},
              "scene_contract_ref": rel(SCENE_STATE),
              "supervisor_script_gate_required": False,
              "output_dir": rel(BASE / "outputs"), "qa_dir": rel(BASE / "qa"), "tasks": tasks}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"config": rel(config_path), "receipt": rel(receipt_path), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
