#!/usr/bin/env python3
"""Compile the complete E32 v2 Seedance prompt set without submitting tasks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
PLAN_PATH = PRODUCTION / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"
SCENE_AUTHORITY_PATH = PRODUCTION / "E32_SCENE_AUTHORITY_STATE_V2.json"
DIALOGUE_PATH = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
VOICE_REGISTRY_PATH = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
PROMPT_DIR = PRODUCTION / "video_performance_v2/prompts"
MANIFEST_PATH = PRODUCTION / "video_performance_v2/E32_ALL_17_VIDEO_PROMPT_MANIFEST_V2.json"


SCENE_RULES = {
    "E32-CW-S01": {
        "weather": "INTERIOR_CLEAR_NO_RAIN",
        "palette": "太平医馆后堂暖黄孤灯、炭火暗红、焦纸幽墨、冰霜幽蓝",
        "contract": "室内无雨；画内、窗面和地面都不得出现雨幕、积水、湿反光或雨声。",
        "ambient": "更漏、炭火低噼、纸张摩擦与克制呼吸",
    },
    "E32-CW-S02": {
        "weather": "RAIN_NIGHT",
        "palette": "洛城雨夜冷蓝、西市暗楼油灯昏黄、湿木深褐、冰流幽蓝",
        "contract": "室外持续下雨；暗楼室内只能从窗外看见雨幕或听见雨声，不得让雨落进封闭室内。",
        "ambient": "檐雨、湿鞋、木门、油灯与近距离呼吸",
    },
    "E32-CW-S03": {
        "weather": "HEAVY_RAIN_EXTERIOR",
        "palette": "暗巷靛青、暴雨冷银、冰流幽蓝、血色暗红、冰屑碎银",
        "contract": "暗巷外景为密集暴雨；雨水、积水和冰层必须承担受力反馈，禁止无介质特效。",
        "ambient": "密雨、踏水、刀锋、冰裂、纸帛与急促呼吸",
    },
    "E32-CW-S04": {
        "weather": "INTERIOR_RAIN_OUTSIDE_ONLY",
        "palette": "太平医馆前堂药香暖黄、窗外雨夜冷青、白霜冷白、人参珠莹透、乌鸦漆黑",
        "contract": "人物全部在室内；雨只存在于檐外声音和窗外背景，室内地面、案桌与人物不得被雨淋湿。",
        "ambient": "檐外雨声、药柜木响、鸦翅、案面轻响与克制呼吸",
    },
    "E32-CW-S05": {
        "weather": "RAIN_STOPPED_CLOUD_BREAK",
        "palette": "雨后洛城夜靛蓝、残月冷白、密谍司灯笼橙红、湿屋瓦弱反光",
        "contract": "雨已经停止、云层裂开露出残月；可保留湿屋瓦和残留水滴，但严禁继续落雨或出现连续雨幕。",
        "ambient": "雨后风声、远更、万人调动的低沉脚步与灯笼轻响",
    },
}

SCENE_BINDINGS = {
    "E32-CW-S01": "[[scene_e32_cw_s01_clinic_back_room]]",
    "E32-CW-S02": "[[scene_e32_cw_s02_dark_tower]]",
    "E32-CW-S03": "[[scene_e32_cw_s03_rain_alley]]",
    "E32-CW-S04": "[[scene_e32_cw_s04_clinic_front_hall]]",
    "E32-CW-S05": "[[scene_e32_cw_s05_post_rain_rooftop]]",
}


# Durations are recomputed from the complete spoken lines plus the authored physical action.
# They are not inherited blindly from the first editorial estimate.
UNIT_SPECS = {
    "E32-CW-U01": {
        "duration": 12,
        "entities": "陈迹、皎兔、乌云、案角骨牌印、案心焦黑覆冰残纸",
        "camera": "后堂中景固定起步，切手部近景，再回双人中近景；不离开同一室内轴线",
        "force": "陈迹指腹只与焦纸接触；骨牌印始终留在案角无人触碰；焦纸受压后只产生轻微纸响",
        "beats": [
            (0.0, 3.0, "皎兔倚门压低声音追问，视线先落在案角骨牌印，再转向陈迹；陈迹不抬头，右手停在焦纸上方", "皎兔疑惑而警惕；陈迹冷静笃定", "观众先看懂骨牌印被主动搁置", ["E32-DIA-001"]),
            (3.0, 7.0, "陈迹只用食指轻点焦纸边缘，明确拒绝去碰骨牌印，随后把焦纸推到案心并用掌缘压平", "陈迹语气平直，目光只看焦纸", "观众看懂他主动改换验伪对象", ["E32-DIA-002", "E32-DIA-003"]),
            (7.0, 12.0, "皎兔离开门框走近半步，双手仍不碰证物；陈迹右手食指落在焦纸背面待查位置，两人同时收声观察", "皎兔由疑惑转专注；陈迹下颌稳定", "终态是焦纸成为唯一检查对象，骨牌印仍原位", []),
        ],
    },
    "E32-CW-U02": {
        "duration": 13,
        "entities": "陈迹、皎兔、焦黑覆冰残纸、版本暗号、案上孤灯",
        "camera": "手指与焦纸微距起步，沿冷雾横移到暗号，再抬至陈迹和皎兔面部特写",
        "force": "冷雾只能从陈迹指腹接触焦纸的位置产生；薄冰沿纸背连续扩展，暗号从冰下逐步显形，不得凭空跳出",
        "beats": [
            (0.0, 4.0, "陈迹右手食指贴住焦纸背面，冷雾从接触点向外爬行，薄冰按纸纹连续铺开", "陈迹专注克制，眼睛跟随冰纹", "观众看懂显痕由真实接触触发", []),
            (4.0, 8.2, "冰层中央逐笔显出一记极淡版本暗号；陈迹指腹停住暗号下方，眼神认出后骤然下沉", "被背叛的隐痛压在眼底，下颌轻绷", "观众看清这是陈迹认识的版本暗号", ["E32-DIA-004"]),
            (8.2, 13.0, "皎兔从焦纸抬眼看向陈迹，身体直起但不碰纸；她指出焦纸来自景朝火盆，陈迹保持手指压住暗号", "皎兔脸色骤变；陈迹寒意加深", "观众把内院版本与景朝焦纸连成同一条交易线", ["E32-DIA-005"]),
        ],
    },
    "E32-CW-U03": {
        "duration": 8,
        "entities": "陈迹、皎兔、显出版本暗号的焦纸、案角骨牌印",
        "camera": "陈迹面部近景缓推，短切焦纸暗号与案角骨牌印，回到双人静止终态",
        "force": "陈迹指腹从暗号上移开后薄冰保持稳定；两人不再触碰任何证物",
        "beats": [
            (0.0, 5.4, "陈迹看着版本暗号逐字说出双面交易结论，右手从焦纸上缓慢撤回并握成松拳", "眸色沉冷、下颌绷紧，情绪不外露", "观众明确内院用名单换信任后又转卖景朝", ["E32-DIA-006"]),
            (5.4, 8.0, "皎兔与陈迹同时停止动作，视线越过焦纸短暂落向案角骨牌印，再彼此确认戒备", "确认后的寒意与警觉", "终态是结论成立且证物保持原位", []),
        ],
    },
    "E32-CW-U04": {
        "duration": 14,
        "entities": "皎兔肉身、皎兔黑甲阴神、医馆窗口、雨夜屋脊、西市暗楼湿木窗框",
        "camera": "医馆中近景跟随离体，连续穿窗越过雨城，抵达暗楼窗外；空间变化连续可追踪",
        "force": "眉心受指腹压力渗血；离体气流只推动衣摆和灯焰一次；飞行压开雨线；右掌抓窗框吸收前冲惯性",
        "beats": [
            (0.0, 3.0, "皎兔肉身右手食指按住眉心旧血痕，向内压出一线新血，肩背绷紧但双脚不移动", "肉身克制忍痛", "观众看懂阴神分离由她主动开启", []),
            (3.0, 6.2, "黑甲阴神沿眉心血光依次脱出头肩、躯干和双腿，与留在原地的肉身完全分开", "肉身痛楚压抑；阴神冷峻苏醒", "观众看懂同一皎兔的肉身与阴神完成分离", []),
            (6.2, 10.5, "阴神俯身穿出打开的窗，沿雨幕上方朝西市暗楼直线飞掠，医馆在身后缩小、暗楼持续放大", "阴神目光锁定目标，警觉果断", "连续地标证明真实跨空间位移", []),
            (10.5, 14.0, "阴神侧身减速，右手抓住湿木窗框吸收惯性，雨水前甩、窗框只颤动一次后停止", "屏息冷峻，快速观察室内", "终态是阴神单独稳在暗楼二层窗外", []),
        ],
    },
    "E32-CW-U05": {
        "duration": 8,
        "entities": "齐三、西市暗楼案桌、同一叠名单、三只不同封色信封、油灯",
        "camera": "俯侧中景推近，横移跟手，最后抬升到齐三表情近景",
        "force": "纸张由齐三双手从同一原叠连续分出；纸边进入信封时弯曲一次回弹；不得复制或瞬移",
        "beats": [
            (0.0, 3.0, "齐三左掌压住同一叠名单，右拇指数页后把名单从案心推成左中右三叠", "贪婪中保持警觉，先看门再低头", "观众看懂三叠来自同一批消息", []),
            (3.0, 6.3, "齐三左手依次撑开三个信封，右手把三叠名单逐份装入对应信封，装入后信封逐个变厚", "动作熟练，眼底贪意加深", "观众看懂他把同一消息卖给多家", []),
            (6.3, 8.0, "齐三把三封信横向排开并逐封压平，门外雨声加密时他立刻收住笑意侧耳", "短暂贪笑转为警觉", "终态是三封信分列且纸张不再散落", []),
        ],
    },
    "E32-CW-U06": {
        "duration": 15,
        "entities": "陈迹、齐三、西市暗楼木门、油灯、三封信、门槛积水、冰流",
        "camera": "门内低机位后移接破门，横移跟手压灭油灯，贴地跟冰流再抬到对峙双人近景",
        "force": "门板受陈迹肩臂向内推开；灯罩受掌心向下压住灯芯；冰流从门槛积水接触点贴地封路；齐三后腰碰案使信封只滑散一次",
        "beats": [
            (0.0, 3.0, "陈迹左肩与前臂抵住半闭木门向内推开，跨过门槛落稳并封住出口；齐三受惊停手", "陈迹冷定压迫；齐三惊恐失措", "观众看懂陈迹主动突袭并占住退路", []),
            (3.0, 5.4, "陈迹右掌向下压住油灯金属灯罩使灯芯熄灭；暖光消失，门外冷蓝雨光接管轮廓", "陈迹动作短促果断；齐三瞳孔收紧", "观众看懂陈迹夺走齐三对光线的控制", ["E32-DIA-007"]),
            (5.4, 9.6, "陈迹左掌按住门槛积水，冰流贴地绕开自己双脚，在齐三身后合拢成半圆冰脊；齐三后退撞案，三封信滑散一次", "陈迹目光冷利；齐三赔笑迅速崩掉", "观众看懂陈迹封死退路并逼出三封证据", ["E32-DIA-008"]),
            (9.6, 15.0, "陈迹俯身拾起三封信，冷雾依次扫过封口使内院与景朝暗号显形，再抬眼逼住齐三；齐三背抵案沿膝盖发软", "陈迹眼神不移；齐三脸色煞白", "观众看懂一版名单被卖给两家主子", ["E32-DIA-009"]),
        ],
    },
    "E32-CW-U07": {
        "duration": 12,
        "entities": "陈迹、齐三、三封显出暗号的信、案角骨牌印、半圆冰脊",
        "camera": "双人对峙中近景，切齐三膝头与指向骨牌的手，再缓推齐三惊惧面部",
        "force": "齐三膝头因失力连续下沉，不得瞬间跪地；手指从自己胸前移动到骨牌方向并停稳；陈迹保持距离不施加无接触冲击",
        "beats": [
            (0.0, 3.3, "齐三背抵案沿，双手摊开急切撇清，膝头因恐惧开始发软；陈迹站定不逼近", "齐三赔笑转慌乱；陈迹目光不移", "观众看懂齐三开始供述而非继续逃跑", ["E32-DIA-010"]),
            (3.3, 7.2, "齐三右手颤抖抬起，越过三封信明确指向案角骨牌印，身体重心继续下沉", "齐三脸色煞白、孤注一掷", "观众听懂骨牌印属于巡检指挥席位", ["E32-DIA-011"]),
            (7.2, 12.0, "齐三膝头落地但双手仍可见，指尖从骨牌转向门外，强调围令另有线路；陈迹只用眼神确认", "齐三声音发颤；陈迹冷静记下结论", "观众听懂围令不走云羊线，内鬼席位被钉死", ["E32-DIA-012"]),
        ],
    },
    "E32-CW-U08": {
        "duration": 13,
        "entities": "陈迹、齐三、巡检司杀手、乌云、暗巷积水、短刃、冰流",
        "camera": "檐头乌云示警一闪，手持跟随杀手下落，贴地展示落脚摩擦改变，再回齐三肩部受伤终态",
        "force": "杀手短刃由檐上朝齐三后心前进；陈迹指尖冰流与积水接触后铺开；鞋底摩擦骤降使落脚横滑，刀锋因此只偏开寸许",
        "beats": [
            (0.0, 2.0, "乌云在墙头弓身尖啸；杀手从檐上踏雨滑落，右手短刃直取齐三后心", "乌云警觉爆发；杀手狠厉专注", "观众提前读懂灭口袭击方向", []),
            (2.0, 6.5, "陈迹侧身探出右臂，指尖冰流落入巷中积水并沿杀手预计落脚点铺成薄冰", "陈迹瞬间专注，目光锁定鞋底", "观众看懂救人手段是改变落脚摩擦", []),
            (6.5, 10.5, "杀手右脚落在薄冰上向外横滑，髋部失衡使刀尖从齐三后心向右偏出，只擦过肩头", "杀手由狠厉转惊愕；齐三痛惧缩肩", "鞋底滑动与刀锋偏移形成清楚因果", []),
            (10.5, 13.0, "齐三捂住流血肩头跌向墙边但未倒地；杀手左手撑地止滑，陈迹挡在两人之间", "齐三恐惧；陈迹戒备；杀手快速恢复", "终态是齐三肩伤未死、杀手仍可继续战斗", []),
        ],
    },
    "E32-CW-U09": {
        "duration": 15,
        "entities": "云羊、巡检司杀手、数张皮影纸人、结冰巷壁、冰屑、空账筐",
        "camera": "侧向中景保持完整身体动力链，近景确认纸人遮眼，低机位拍拳击固定点，广角收杀手撞筐",
        "force": "云羊咬指点睛激活纸人；纸人贴近杀手面门遮挡视线；云羊蹬地转胯传力到拳面；拳只命中冰墙预裂点，裂纹定向扩散后冰屑撞向杀手",
        "beats": [
            (0.0, 3.5, "云羊从巷口箭步进入，咬破食指点在三张纸人眼位，纸人依次展开", "云羊狠决专注；杀手转头寻找新威胁", "观众看懂纸人由点睛动作启动", []),
            (3.5, 7.0, "三张纸人沿不同低弧线扑到杀手面前，贴住视野但不穿入身体；杀手挥刀只切开最外一张", "杀手因遮眼慌乱，动作开始失序", "观众看懂遮眼制造了固定攻击窗口", []),
            (7.0, 11.5, "云羊左脚蹬住湿地、转胯送肩，右拳沿直线命中结冰巷壁的白色预裂点，拳面接触后才出现裂纹", "云羊咬牙爆发，面部受力真实", "观众看见蹬地到拳面的连续传力链", []),
            (11.5, 15.0, "裂纹从拳点朝杀手方向扩散，冰壁碎块和冰屑定向喷出撞中杀手胸肩，把他掀翻进空账筐；云羊收拳站稳", "杀手受击痛苦；云羊保持警戒", "终态是杀手撞筐、冰屑落地，不循环爆裂", []),
        ],
    },
    "E32-CW-U10": {
        "duration": 15,
        "entities": "陈迹、云羊、齐三、巡检司杀手、短刃、齐三咽喉、杀手袖口半枚铜牌、雨血、冰流",
        "camera": "杀手翻身近景接齐三侧面，跟随遁走一拍，低机位拍半牌落入雨血，抬到陈迹与云羊表情",
        "force": "杀手翻身后手臂回收再横向补刀；刀锋接触齐三咽喉后齐三才倒下；杀手蹬碎薄冰离开时半牌从袖口甩落；陈迹冷雾与雨血接触冻住半牌后用手拾起",
        "beats": [
            (0.0, 3.4, "杀手从账筐中翻身，放弃先逃，右臂回收后短刃横向补到齐三咽喉；齐三抓住伤口圆睁双眼", "杀手决绝；齐三由侥幸转绝望", "观众看懂灭口优先于逃生", []),
            (3.4, 6.0, "齐三失力仰倒进雨水；杀手左脚蹬碎薄冰跃向巷口，袖口受惯性翻开并甩落半枚铜牌", "齐三错愕凝固；杀手不回头", "观众看见半牌确实来自杀手袖口", []),
            (6.0, 9.5, "陈迹俯身让冷雾触到雨血中的半牌，血水从边缘向内结冰，随后右手拾起冻牌；云羊靠近辨认暗记", "陈迹震怒压在眼底；云羊热血褪成寒意", "证物从杀手转入陈迹手中的链条完整可见", ["E32-DIA-013"]),
            (9.5, 12.2, "云羊盯着牌面暗记说出发令与灭口同源，左拳慢慢握紧但不遮挡牌面", "云羊声音发冷、眼底寒", "观众确认两件事属于同一巡检线", ["E32-DIA-014"]),
            (12.2, 15.0, "陈迹把冻牌举到眼前，雨顺指缝滴落，他望向杀手消失方向说出判断", "陈迹声沉如铁，怒意克制", "终态是巡检线灭口事实被坐实", ["E32-DIA-015"]),
        ],
    },
    "E32-CW-U11": {
        "duration": 8,
        "entities": "陈迹、姚太医、乌云、通灵大乌鸦、骨牌印、巡检司半枚铜牌、医馆案桌",
        "camera": "案面俯拍两件证物并置，跟姚太医枯手和乌鸦落点，最后双人中近景",
        "force": "陈迹将半牌和骨牌印依次放到案面并排；姚太医拂袖产生气流，大乌鸦落在两物之间但不触碰证物",
        "beats": [
            (0.0, 3.0, "陈迹先把骨牌印放在案左，再把冻住的巡检司半牌放在案右，两者边缘平行可比较", "陈迹压住怒意，动作克制", "观众从并置关系开始比对两条证据", []),
            (3.0, 5.5, "姚太医枯手从两物上方缓慢拂过，大乌鸦从画外扑棱落到案后中央，歪头先看骨牌再看半牌", "姚太医温和而沉重；乌鸦警觉", "乌鸦视线把两件证物连成同源线索", []),
            (5.5, 8.0, "姚太医食指在两物之间点一下案面；陈迹不碰证物，只抬眼与他确认", "二人神色凝重", "终态是发令与灭口同源的判断成立", []),
        ],
    },
    "E32-CW-U12": {
        "duration": 12,
        "entities": "陈迹、姚太医、大乌鸦、并置的骨牌印与巡检半牌",
        "camera": "姚太医近景固定说话，短切证物与陈迹眼神，再缓推到两人同框",
        "force": "姚太医只以指节轻点案面一次；证物不移动；陈迹的反应只由眼神和呼吸表现",
        "beats": [
            (0.0, 4.0, "姚太医看着并置证物，右手指节轻点案面一次，说出印出现便有人被杀的事实", "声温和但每字沉重", "观众把骨牌印与齐三死亡直接连上", ["E32-DIA-016"]),
            (4.0, 9.5, "姚太医抬眼直视陈迹，手掌停在证物之外，说明敌人真正害怕的是陈迹仍有时间追查", "姚太医沉静警示；陈迹警觉逐渐加深", "观众读懂围猎目的在抢时间", ["E32-DIA-017"]),
            (9.5, 12.0, "陈迹眼神从证物移向窗外沉夜，呼吸放慢，右手悬在案边没有触碰任何物件", "陈迹把怒意转成戒备", "终态是他意识到对手即将提前收网", []),
        ],
    },
    "E32-CW-U13": {
        "duration": 12,
        "entities": "陈迹、乌云、透明人参珠、掌心白霜、医馆案桌",
        "camera": "手掌与铜牌碰案特写，沿白霜逆窜跟到手腕，再跟乌云跃案和珠子接触，最后抬到陈迹隐忍面部",
        "force": "陈迹右手失控颤动使铜牌碰案；白霜沿掌心向腕骨逆窜；乌云用前爪把人参珠抵入掌心；霜纹只在接触珠子后停止扩散并缓退",
        "beats": [
            (0.0, 3.0, "陈迹右手忽然颤动，半牌从指间落到案面碰响；白霜从掌心沿腕骨向上连续爬升", "额角沁汗、下颌死死绷住但不失态", "观众看懂冰流反噬由体内失控发作", []),
            (3.0, 6.0, "乌云从案边跃起，前爪推着透明人参珠准确抵入陈迹摊开的掌心，珠子与霜纹形成真实接触", "乌云急切专注；陈迹忍痛稳住手腕", "观众看懂救援接触点", ["E32-DIA-018"]),
            (6.0, 9.5, "人参珠亮起柔和内光，白霜先停止越过腕骨，再从边缘向掌心缓退；陈迹手指逐渐恢复控制", "陈迹压住痛楚、呼吸仍重", "观众看见珠子压制反噬的先后因果", ["E32-DIA-019"]),
            (9.5, 12.0, "陈迹合拢手掌护住人参珠，左手扶案重新站直；乌云守在手边仰头观察", "陈迹恢复冷静但疲惫明显", "终态是反噬暂缓而危机未解除", []),
        ],
    },
    "E32-CW-U14": {
        "duration": 8,
        "entities": "陈迹、姚太医、乌云、大乌鸦、医馆前堂窗、远处城门落锁声源",
        "camera": "室内固定中景，以人物和乌鸦对画外声音的连续反应表达封城，不切到不存在的城门画面",
        "force": "每一声远处闷响先到达室内，人物再依方向转头；乌鸦受连续声响惊动振翅绕堂，空气推动药签轻摆",
        "beats": [
            (0.0, 2.8, "第一声城门闷响从远处传来，陈迹稳住呼吸后转头看向窗；第二声从另一方向传来，姚太医抬眼", "陈迹克制警觉；姚太医神色凝重", "观众通过声源次第变化读懂多处落锁", []),
            (2.8, 5.2, "第三声闷响靠近，大乌鸦骤然振翅绕堂长鸣，气流带动窗边药签轻摆；乌云背毛竖起", "乌云炸毛，大乌鸦躁动示警", "群体反应证明封锁正在合围", []),
            (5.2, 8.0, "姚太医面向窗外沉夜确认封城；陈迹手握人参珠站稳，所有人停下等待下一步", "姚太医沉重确认；陈迹眼神转冷", "终态是全城围猎正式开始", ["E32-DIA-020"]),
        ],
    },
    "E32-CW-U15": {
        "duration": 13,
        "entities": "陈迹、皎兔、云羊、乌云、太平医馆飞檐、洛城四门与坊口、密谍司灯笼长龙、残月",
        "camera": "从医馆飞檐人物中远景持续升高成洛城大远景，再回皎兔侧面近景；保持雨后同一夜空",
        "force": "灯笼只能由远处人群沿街道路线依次点亮；三条长龙保持空间来源，不得瞬间全城同时亮起；雨后风只使灯笼轻摆",
        "beats": [
            (0.0, 4.2, "陈迹踏上湿润飞檐站稳，皎兔随后从后方掠上；镜头升高，云层裂口露出残月，天空不再落雨", "陈迹冷静观察；皎兔紧张确认", "观众明确环境已经雨停云开", []),
            (4.2, 8.5, "四面城门、医馆坊口和王府侧门的灯笼沿街道一处接一处点亮，三条长龙向城中收拢但保持不同队列", "陈迹目光跟随灯网；皎兔呼吸收紧", "观众一眼看懂整座城被同一张围猎网包住", ["E32-DIA-021"]),
            (8.5, 13.0, "皎兔抬手依次指向城门、医馆和王府侧门，说明知情人被压进同一圈；陈迹没有移动，只观察三路队列间的空隙", "皎兔焦虑；陈迹冷静计算", "终态是封锁范围和围猎目标都清楚", ["E32-DIA-022"]),
        ],
    },
    "E32-CW-U16": {
        "duration": 15,
        "entities": "陈迹、皎兔、云羊、乌云、医馆飞檐、三路不同编队的灯笼长龙、残月",
        "camera": "飞檐三人中景保持方位，切云羊握拳近景与灯网队列，最后缓推陈迹半边月光面部",
        "force": "云羊落在另一侧檐脊时屈膝吸收惯性；握拳只表现焦灼；陈迹转身和抬眼连续完成，不新增法术冲击",
        "beats": [
            (0.0, 4.8, "云羊从侧后方落到另一侧檐脊，屈膝站稳后指向三路灯笼队列，列举巡检线、景朝暗桩与内院私兵", "云羊焦灼而愤怒", "观众看懂围猎圈内有三拨不同势力", ["E32-DIA-023"]),
            (4.8, 8.0, "云羊握拳看着三路队列交错又彼此避让，指出所有人挤在一处却互不信任", "云羊眼底不安，呼吸急促", "不同编队的间距把互疑可视化", ["E32-DIA-024"]),
            (8.0, 12.0, "陈迹从灯网缓慢转身看向云羊和皎兔，残月照亮半边脸；他重述三拨人互不信任的关键", "从受压转为洞悉，眸底寒光开始亮起", "观众看懂他正在把猎物位置转成可利用条件", ["E32-DIA-025"]),
            (12.0, 15.0, "陈迹重新看向灯网，掌心冷雾凝聚一瞬后主动散去，不发动攻击；皎兔和云羊同时顺着他的视线看向三路交界", "陈迹冷极生锐；两人由焦虑转专注", "终态是反制思路形成但尚未执行", []),
        ],
    },
    "E32-CW-U17": {
        "duration": 15,
        "entities": "陈迹、皎兔、云羊、乌云、医馆飞檐、三路灯笼长龙、残月、洛城大远景",
        "camera": "陈迹近景说出反收网逻辑，镜头持续后拉越过三人和飞檐，最终成为灯网缠城大远景并自然切黑",
        "force": "镜头后拉必须连续；三路灯笼随真实人群缓慢移动、互相交错但保持不同队列；风起只使灯火明灭，不让队列瞬移",
        "beats": [
            (0.0, 4.2, "陈迹站在檐脊看着灯网，先说出收网者把网内众人都当猎物；皎兔与云羊保持安静倾听", "陈迹眸底冷亮，语气压低而笃定", "观众理解敌方当前判断", ["E32-DIA-026"]),
            (4.2, 8.8, "镜头开始缓慢后拉，陈迹视线依次落到三路灯笼交界，提出让三拨人先相信别人是内奸", "陈迹唇角几不可察一动，眼神锐利", "观众理解反制的动作目的", ["E32-DIA-027"]),
            (8.8, 12.5, "镜头继续后拉越过医馆飞檐，三路灯笼长龙彼此交错却保留不同队列；陈迹说出网会勒住收网者的手", "人物逐渐成为剪影，压迫感交给灯网", "观众读懂网内分裂可被反用", ["E32-DIA-028"]),
            (12.5, 15.0, "镜头升至洛城大远景，雨后风掠过使三路灯火按各自节奏明灭，残月冷照，画面在真实运动中自然切黑", "以宏大灯网压迫代替人物表情", "终态是围猎已成、反收网计划启动，禁止静帧和循环填时长", []),
        ],
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_dialogue_audio_rows(rows: list[dict], voice_registry: dict[str, dict]) -> tuple[list[str], list[str]]:
    """Accept exact line audio or a locked native voice reference for exempt roles.

    Chenji and Baili are native multimodal voices. Their registered reference audio
    is a voice-performance input, while the exact line remains authoritative text.
    Other roles must continue to provide one exact audio file per line.
    """
    blocked: list[str] = []
    native_style: list[str] = []
    for row in rows:
        mode = row.get("audio_mode")
        if mode == "EXACT_DIALOGUE_AUDIO_REFERENCE":
            continue
        if mode != "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT":
            blocked.append(row["dia_id"])
            continue
        voice = voice_registry.get(str(row.get("speaker_id") or ""))
        path = ROOT / str(row.get("path") or "")
        if not voice or voice.get("status") != "LOCKED_PRODUCTION_READY":
            blocked.append(row["dia_id"])
            continue
        if row.get("remote_asset_id") != voice.get("remote_asset_id"):
            blocked.append(row["dia_id"])
            continue
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            blocked.append(row["dia_id"])
            continue
        native_style.append(row["dia_id"])
    return blocked, native_style


def render_prompt(
    unit: dict,
    spec: dict,
    scene: dict,
    rows: list[dict],
    voice_registry: dict[str, dict],
) -> tuple[str, list[str], list[str]]:
    unit_id = unit["unit_id"]
    short_id = unit_id.rsplit("-", 1)[-1]
    duration = spec["duration"]
    image_count = unit["planned_reference_image_count"]
    blocked, native_style = validate_dialogue_audio_rows(rows, voice_registry)
    lines = [
        f"《青山》E32 {short_id}，Seedance 2.0 Pro 四模态表演生成，{duration}秒，9:16，720p，原速连续动作。",
        f"【剧本与分组】Claude Writer v2；{unit['scene_id']}；按本场连续分镜的实际动作与对白时长自然分组，当前编译时长={duration}秒。",
        f"【实体绑定】{SCENE_BINDINGS[unit['scene_id']]}；{spec['entities']}；只允许剧本声明实体出现，人物身份必须服从备案角色参考。",
        f"【参考图职责】本单元使用{image_count}个时间锚；锚图只锁身份、场景与必要的不可插值状态。动作过程必须由同一逐拍 spec 连续生成，不把锚图当作断裂姿势硬插值。",
        f"【天气硬合同】weather={scene['weather']}；{scene['contract']}",
        f"【色彩与动机光】palette={scene['palette']}；光影只来自本场真实灯火、夜空和剧本声明能力。",
        f"【摄影】{spec['camera']}；镜头运动必须连续，不靠闪切、停帧、慢放或循环填时长。",
        f"【力量作用环境】{spec['force']}。",
        f"【环境声音】{scene['ambient']}；禁止旁白与BGM。",
    ]
    if rows:
        lines.append("【原生对白与音频模态】以下台词必须由视频模型随画面原生生成自然中文普通话，并逐字同步口型、气息、表情和起止时间；字幕只在后期烧录：")
        for idx, row in enumerate(rows, 1):
            mode = row["audio_mode"]
            if mode == "EXACT_DIALOGUE_AUDIO_REFERENCE":
                audio_note = f"精确台词音频=@音频{idx}，path={row['path']}"
            elif row["dia_id"] in native_style:
                audio_note = (
                    f"备案原生声线参考=@音频{idx}，path={row['path']}，asset_id={row['remote_asset_id']}；"
                    "该音频只锁角色音色、年龄、气息与说话质感，台词内容以本行精确文本为唯一权威；"
                    "由视频模型原生说出并同步口型，禁止后配音、改词或借用其他声线"
                )
            else:
                audio_note = (
                    f"BLOCKED：audio_mode={mode} 未通过精确音频或备案原生声线注册校验"
                )
            lines.append(f"- {row['dia_id']}｜{row['speaker']}逐字说：\"{row['spoken_text']}\"｜{audio_note}")
    else:
        lines.append("【原生对白与音频模态】本单元无台词；仅生成动作同期声，禁止擅自新增对白、旁白或人声。")
    lines.append("【连续物理动作脚本】")
    row_map = {row["dia_id"]: row for row in rows}
    for shot_index, (start, end, action, expression, purpose, dia_ids) in enumerate(spec["beats"], 1):
        dialogue = "无对白"
        if dia_ids:
            dialogue = "；".join(
                f"{row_map[dia_id]['speaker']}逐字说\"{row_map[dia_id]['spoken_text']}\"" for dia_id in dia_ids
            )
        lines.append(
            f"镜头{shot_index}【{start:.1f}-{end:.1f}秒，{spec['camera']}】主体动作={action}；"
            f"接触/方向/终态必须按本段真实演出；动作目的={purpose}；表情={expression}；"
            f"{{{dialogue}}}<现场动作声、呼吸与{scene['ambient']}>"
        )
    lines.extend(
        [
            f"【观众读取】{unit['performance_spec']['viewer_read']}。所有动作都必须同时呈现动作目的与可见因果，不只做抽象肢体移动。",
            "【单一状态源】提示词、锚图、人物/道具归属、动作时间轴、对白文本和音频引用全部从本任务 spec 派生；禁止彼此矛盾或擅自补动作。",
            "【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、人物增殖、身份漂移、现代服装、道具换手跳变、融肢、穿模、无接触受力、无因腾空、瞬移、慢放、停帧、循环、周期重复、静帧微动和首尾重复。",
        ]
    )
    if blocked:
        lines.append(f"【提交状态】BLOCKED_DIALOGUE_AUDIO_BINDING：{','.join(blocked)} 未通过对白音频绑定；只允许继续准备，不得提交付费视频任务。")
    else:
        lines.append(
            "【提交状态】PROMPT_COMPILED；仍须通过锚图、人物身份、去重、积分和批次完整性门后方可提交；"
            "生成后逐句执行 ASR、说话人归属、口型和备案声线一致性复核。"
        )
    return "\n".join(lines) + "\n", blocked, native_style


def main() -> int:
    plan = load_json(PLAN_PATH)
    scene_authority = load_json(SCENE_AUTHORITY_PATH)
    dialogue = load_json(DIALOGUE_PATH)
    voice_registry_payload = load_json(VOICE_REGISTRY_PATH)
    voice_registry = {row["entity_id"]: row for row in voice_registry_payload["major_roles"]}
    if len(plan["units"]) != 17:
        raise RuntimeError(f"Expected 17 units, got {len(plan['units'])}")
    if set(UNIT_SPECS) != {unit["unit_id"] for unit in plan["units"]}:
        raise RuntimeError("UNIT_SPECS must cover exactly U01-U17")

    # The file is loaded intentionally: compilation must fail if the scene authority
    # source disappears, even though normalized weather contracts live above.
    if scene_authority.get("episode") != "E32":
        raise RuntimeError("Unexpected scene authority episode")

    rows_by_unit: dict[str, list[dict]] = {}
    for row in dialogue["rows"]:
        rows_by_unit.setdefault(row["video_unit_id"], []).append(row)

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for unit in plan["units"]:
        unit_id = unit["unit_id"]
        scene_id = unit["scene_id"]
        spec = UNIT_SPECS[unit_id]
        prompt, blocked, native_style = render_prompt(
            unit,
            spec,
            SCENE_RULES[scene_id],
            rows_by_unit.get(unit_id, []),
            voice_registry,
        )
        prompt_path = PROMPT_DIR / f"{unit_id}-PERFORMANCE-V2-COMPILED.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        manifest_rows.append(
            {
                "unit_id": unit_id,
                "scene_id": scene_id,
                "weather": SCENE_RULES[scene_id]["weather"],
                "editorial_estimate_seconds": unit["duration_seconds"],
                "compiled_duration_seconds": spec["duration"],
                "planned_reference_image_count": unit["planned_reference_image_count"],
                "dialogue_ids": [row["dia_id"] for row in rows_by_unit.get(unit_id, [])],
                "blocked_exact_dialogue_audio_ids": blocked,
                "native_voice_style_dialogue_ids": native_style,
                "status": "BLOCKED_DIALOGUE_AUDIO_BINDING" if blocked else "PROMPT_COMPILED",
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": sha256_text(prompt),
            }
        )

    manifest = {
        "schema": "qingshan.complete_video_prompt_manifest.v2",
        "episode": "E32",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_plan": str(PLAN_PATH.relative_to(ROOT)),
        "source_plan_sha256": sha256_file(PLAN_PATH),
        "source_scene_authority": str(SCENE_AUTHORITY_PATH.relative_to(ROOT)),
        "source_scene_authority_sha256": sha256_file(SCENE_AUTHORITY_PATH),
        "source_dialogue_manifest": str(DIALOGUE_PATH.relative_to(ROOT)),
        "source_dialogue_manifest_sha256": sha256_file(DIALOGUE_PATH),
        "source_voice_registry": str(VOICE_REGISTRY_PATH.relative_to(ROOT)),
        "source_voice_registry_sha256": sha256_file(VOICE_REGISTRY_PATH),
        "unit_count": len(manifest_rows),
        "all_units_have_prompt": len(manifest_rows) == 17,
        "paid_video_submission_performed": False,
        "weather_template_policy": "PER_SCENE_AUTHORITY_ONLY_NO_GLOBAL_RAIN_TEMPLATE",
        "duration_policy": "RECOMPUTE_FROM_ACTUAL_DIALOGUE_AND_CONTINUOUS_ACTION",
        "dialogue_audio_policy": "EXACT_LINE_AUDIO_OR_LOCKED_NATIVE_MULTIMODAL_VOICE_REFERENCE_WITH_EXACT_TEXT",
        "rows": manifest_rows,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(MANIFEST_PATH), "unit_count": len(manifest_rows), "blocked_units": [row["unit_id"] for row in manifest_rows if row["blocked_exact_dialogue_audio_ids"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
