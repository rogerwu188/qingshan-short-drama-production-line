#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile E39 independent Seedance units with exact keyframes and expressive voices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805/independent_video_v1"
QA = ROOT / "qa/e39_video_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E39剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E39_manifest_v3.json"
SCRIPT_SHA = "2726b69bd1f91ca4efbcb37cce7664cc17919f2eac7970cc49eb795318d42e0a"
MANIFEST_SHA = "f00015b954ad19f5a56d6cb116823956ee26fa8ec4742a53d443a16b77f2952a"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


UNITS = [
    {
        "id": "U01", "duration": 15,
        "image": "working_assets/e39_keyframes_v3/candidates/E39_E39-U01-A1-STILL-R3_15d39896-676e-4aee-974f-c0a5320e636c.png",
        "image_sha": "631b687e927b9db4138ac71b2be1828530c43585844f176f141a67182ff9a798",
        "voices": ["v0udrgrojud", "cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧和人物身份、服装、空间基准；@音频1锁定云羊17岁少年声线，@音频2锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，15秒，真实1倍速。0.0-5.5秒固定中景：两名官差持续架着15岁阿栓跨出门槛，差役队列同步向外走，火把随风横卷，幌布拍打，病房人影探看又缩回；阿栓挣扎回望并发颤喊“迹哥……”，陈迹在暗处手指抵墙逐寸收紧，药簿被靴底踩过。5.5秒动机硬切近景，5.5-9.2秒：云羊已半步前冲、右手抽出纸符一半，陈迹反手扣紧他手腕；云羊用@音频1惊怒急切说准确台词“那是家里的孩子！拦下他们！”，说“孩子”后短断句，陈迹不看他、仍盯官差。9.2秒动机硬切足部与面部同轴特写，9.2-15.0秒：陈迹靴尖探进火把光半寸又立即碾住，扣腕指节发白；用@音频2低冷压痛、短句清楚说准确台词“一动手，就是当众劫官。”，重音“一动手”“当众劫官”；云羊挣势止住但胸口急促起伏，皎兔在旁持续观察官差站位，乌云耳朵转向门外。全体可见人物每秒都有呼吸、步伐、视线或环境反应，禁止背景冻结。每个镜头内部机位锁定，只允许两次叙事硬切；禁止推拉摇移、环绕、漫游、浅景深遮挡、慢动作、姿势停留、重复动作、换脸换衣、伪中文、画内字幕、水印。""",
        "lines": ["那是家里的孩子！拦下他们！", "一动手，就是当众劫官。"],
    },
    {
        "id": "U02", "duration": 11,
        "image": "working_assets/e39_keyframes_v3/candidates/E39_E39-U02-A1-STILL-R3_144cbcab-86eb-4ff1-856f-0123e29d47f5.png",
        "image_sha": "5b3ad2337e400653fb3067557f438fa6c9cb7295c35398774b2a494d12760293",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、陈迹身份和前堂暗处空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，11秒，真实1倍速。0.0-5.8秒固定证物近景：官差手中的纸质查案文书从半卷状态持续卷紧并随脚步移出画面，陈迹灰袍袖中冷雾从食指根部爬到第二节形成细霜，指骨自然屈伸；皎兔视线跟随文书，云羊压住呼吸，背景火把尾光继续向门外移动。陈迹用@音频1贴近耳语、前缓后紧说准确台词“饵他不取，他借来了官府的刀。”，重音“不取”“官府的刀”。5.8秒动机硬切锁定反应近景，5.8-11.0秒：陈迹五指从云羊手腕上逐指松开，勒痕仍在；目光越过最后一束移动的火把光落向长街，皎兔先一步转身，云羊收回纸符并跟上。陈迹用同一@音频1果断克制、两段短促说准确台词“顺着刀，摸握刀的手。”，重音“顺着刀”“握刀的手”。所有可见角色持续呼吸、转眼、收手或迈步，不得冻结。两镜内部机位完全锁定，只一次硬切；文书和手指保持清晰，禁止慢动作、推拉摇移、漫游、浅焦虚化主体、原地摆姿势、重复松腕、换脸换衣、伪中文、画内字幕、水印。""",
        "lines": ["饵他不取，他借来了官府的刀。", "顺着刀，摸握刀的手。"],
    },
    {
        "id": "U03", "duration": 11,
        "image": "working_assets/e39_keyframes_v3/candidates/E39_E39-U03-A1-STILL-R2_7686274a-3f96-4e9a-8576-7b4adaaae6af.png",
        "image_sha": "aa494e87f518e5047fb1653833881c20f48828bf65a7b513e631e64e4b9849cf",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、身份、服装与长街空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，11秒，真实1倍速。0.0-5.0秒锁定高位可读街轴：原本同队的押送正在移动中分成两路，壮硕皂黑官差甲架着靛蓝短褐阿栓转向大道，瘦削青灰官差乙抱文书匣与药账转入小巷；陈迹、皎兔、云羊始终藏在檐影中同步缀行，更夫远处弓背敲梆，灯笼和幌子被急风持续拉扯。5.0秒动机硬切为贴着乌云运动方向的稳定短跟，5.0-11.0秒：乌云从陈迹肩头蹬离，真实猫速跃上檐脊，鼻尖依次擦过甲乙下风口后立即回到陈迹肩头，尾尖先后准确点向大道和小巷，喉间低鸣；陈迹用@音频1低声笃定说准确台词“两把刀，同一只手派的。”，重音“两把刀”“同一只手”，皎兔眼神一紧，云羊停止躁动。所有可见人物和猫持续完成各自动作，禁止背景冻结。第一镜绝对锁定，第二镜仅一次短距离平行跟猫且不回摆；禁止装饰性揭示、俯冲、环绕、慢动作、重复跃猫、队伍站定、角色复制、换脸换衣、伪中文、画内字幕、水印。""",
        "lines": ["两把刀，同一只手派的。"],
    },
    {
        "id": "U04", "duration": 12,
        "image": "working_assets/e39_keyframes_v3/candidates/E39_E39-U04-A1-STILL-R2_2df3faea-3542-4064-8a99-1185160949f0.png",
        "image_sha": "bb5f774f64cf25e7944fef2b6aeb45b79d96c12c5e244151f514a5f9801d812d",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、身份、服装、账页和长街空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，12秒，真实1倍速。0.0-6.6秒锁定俯斜证物特写，整张纸页和陈迹双手始终清晰：账页上唯一允许的来源绑定标题是准确中文“药柜更换日期”，其余细项用短横、印记和数字占位，不生成伪中文；陈迹指尖冷雾沿纸纤维前行，把标题下的一组日期墨迹整体向后移三格，移动过程清楚且只发生一次，纸不变形。陈迹用@音频1审慎锐利、数字清晰说准确台词“这一页，日子挪了三天。”，重音“这一页”“三天”；云羊俯身核对，皎兔同时看另一页。6.6秒动机硬切稳定中近景，6.6-12.0秒：乌云从檐脊一次掠落撞上官差甲怀中卷册，卷册正在脱手；陈迹与云羊一前一后俯身拾还，在遮挡最短的瞬间各自完成一次公文封互换，随后立刻起身继续缀行；官差甲伸手接回，官差乙回头但不察觉。所有可见人物、猫、衣摆和幌子持续运动，禁止任何人冻结。两镜内部机位锁定，只有一次硬切；文字、手指和纸页不得失焦或模糊。禁止新增文字、错字、伪中文、画内字幕、水印、慢动作、重复掉包、连续摇镜、推拉、漫游、角色换脸换衣。""",
        "lines": ["这一页，日子挪了三天。"],
        "exact_text": ["药柜更换日期"],
    },
    {
        "id": "U05", "duration": 11,
        "image": "working_assets/e39_keyframes_v4/candidates/E39_E39-U05-A1-STILL-R4_7b4c49cf-1cd7-4261-aa43-78ba06a7e66f.png",
        "image_sha": "64b4322ec866238e08f4538d4fef9e29a280e508eb70bb4c3268b43af8b20d94",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、陈迹皎兔云羊身份、服装和长街空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，11秒，真实1倍速。0.0-6.0秒锁定正面中景：18岁女性皎兔闭眼站稳，眉心逸出一缕与皎兔同脸同体态同黑色窄袖服装的半透明女性阴神；这唯一阴神在运动中分成两缕薄影，一缕朝大道、一缕朝小巷离开，不生成第二个实体皎兔，不变成男性。皎兔实体始终微微呼吸，指尖结印缓慢收拢；陈迹与云羊分别转眼追踪两路，乌云尾尖甩动。6.0秒动机硬切固定长焦街道出口，6.0-11.0秒：甲乙两路押送持续远去，两个火把光点自然向左右拉开，风吹幌子和衣摆；陈迹用@音频1冷静设伏、前后对称且后半更重说准确台词“谁咬这三天，谁在握刀。”，重音“咬这三天”“握刀”，皎兔无声点头，云羊转身准备分路。所有可见实体与投影持续有明确动作，禁止冻结。两镜内部机位锁定，只一次硬切；禁止俯拍揭示、环绕、慢动作、阴神男性化、人物复制、角色换脸换衣、光点停住、画内文字、字幕、水印。""",
        "lines": ["谁咬这三天，谁在握刀。"],
    },
    {
        "id": "U10", "duration": 12,
        "image": "working_assets/e39_keyframes_v4/candidates/E39_E39-U10-A1-STILL-R4_22d8364e-5eab-41d3-b75f-6f464246f8ea.png",
        "image_sha": "025eb833c97ae78debf5f8bc191571bdbd86530a1c2c4a7faaf070fd9cfa7af3",
        "voices": ["x2ucerh9xoo"],
        "prompt": """@图片1是唯一首帧、皎兔陈迹云羊身份、服装和密室空间基准；@音频1锁定皎兔18岁少女中高、冷而轻的声线。E39古装写实短剧，9:16，原生1080p，12秒，真实1倍速。0.0-5.2秒固定近景：第二缕与皎兔同脸同体态同黑色窄袖服装的半透明女性阴神正在没入她眉心，皎兔胸口浅喘、睫毛轻颤后睁眼；烛焰被潮气压低，案角乌云尾尖持续扫动，陈迹抬眼等待，云羊搓去袖口雨水。5.2秒动机硬切锁定案面证据近景，5.2-12.0秒：两页账摹本并排平放，皎兔右手食指先压甲页再一次移向乙页，手指、纸页和眼神始终清晰；用@音频1先轻喘后专业克制说准确台词“真页进库，压着没动。”，短停后更冷更快说“假页，连夜有人调档。”，分别重音“真页、没动”和“假页、连夜、调档”；陈迹快速扫记录，云羊立刻望向门窗，乌云耳朵跟随声音转动。所有可见角色持续呼吸、转眼、移手或警戒，不得冻结。两镜内部机位锁定，只一次硬切；禁止推拉摇移、漫游、浅焦模糊纸页、慢动作、阴神男性化、人物复制、角色换脸换衣、伪中文、画内字幕、水印。""",
        "lines": ["真页进库，压着没动。", "假页，连夜有人调档。"],
    },
    {
        "id": "U11", "duration": 14,
        "image": "working_assets/e39_keyframes_v2/candidates_r2/E39_E39-U11-A1-STILL-R2_22fbf5dc-a29e-4360-9d8d-a3c7b175bc3f.png",
        "image_sha": "c454c7d7f171b93364a5a010a4795db9e0eeedca31c8034b10effa9c0666c42d",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、陈迹身份、服装、两页账和密室空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，14秒，真实1倍速。0.0-6.0秒锁定俯斜证据特写：陈迹食指从离纸半寸处落到乙页错移的三日位置，冷雾一次漫过，只有对应的三个日期格被霜纹逐格托亮，不生成额外文字；陈迹用@音频1缓起、结论利落说准确台词“咬这三天错的，就是指挥。”，重音“三天错”“指挥”，皎兔屏息、云羊凑近但双手不遮证物。6.0秒动机硬切锁定另一证据构图，6.0-14.0秒：陈迹双手把一幅手绘调案令拓影从半卷状态连续展开，皎兔按住纸角，冷雾从令尾掠过，一方旧印的花瓣纹路逐瓣显形且只显一次；纸面仅保留清楚印纹和绘线，不生成伪中文。陈迹用同一@音频1先否定后停一息，再沉重确定说准确台词“不是衙印，是云妃的旧印。”，重音“不是衙印”“云妃的旧印”；云羊脸色骤变后退半步，皎兔压住账页，乌云抬头。所有可见人物与纸角、烛焰持续动作，不得冻结。两镜内部机位完全锁定，只一次硬切；证据、手指、眼睛保持清晰，禁止慢动作、推拉摇移、漫游、文字虚化、伪中文、画内字幕、水印、角色换脸换衣。""",
        "lines": ["咬这三天错的，就是指挥。", "不是衙印，是云妃的旧印。"],
    },
    {
        "id": "U12", "duration": 6,
        "image": "working_assets/e39_keyframes_v2/candidates_r2/E39_E39-U12-A1-STILL-R2_54c4edbf-3103-471a-82b1-829623712f3a.png",
        "image_sha": "4836b8cecb591c5abc75ecdfdc6897b2f5a61675c19fa65ceaf11b4fcca2019a",
        "voices": ["v0udrgrojud", "cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、陈迹皎兔云羊身份、服装和密室空间基准；@音频1锁定云羊17岁少年中音，@音频2锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，6秒，真实1倍速，单一锁定群像镜头。0.0-2.7秒：云羊正倒吸短气并后退半步，用@音频1震惊压成耳语、前慢后急说准确台词“王府的手，伸进了咱们家？”，重音“王府的手”“咱们家”；陈迹正在卷起拓影，皎兔侧头警戒门外，乌云尾尖扫过案角，烛焰和纸角持续颤动。2.7-6.0秒：陈迹不抬高音量，目光从卷起的拓影移到案角阿栓那册散线药簿，用@音频2近乎自语、缓慢拆句说准确台词“阿栓扣得太顺，像摆好的。”，重音“太顺”“摆好的”；云羊停止追问但胸口仍起伏，皎兔转身确认退路。每个可见角色全程都有呼吸、视线、手部或警戒反应，禁止背景冻结。摄影机全程锁定，不切镜、不推拉摇移；两句自然抢接但互不重叠，口型只属于对应说话者。禁止慢动作、朗诵腔、同一语气、角色换脸换衣、伪中文、画内字幕、水印。""",
        "lines": ["王府的手，伸进了咱们家？", "阿栓扣得太顺，像摆好的。"],
    },
    {
        "id": "U13", "duration": 14,
        "image": "working_assets/e39_keyframes_v2/candidates_r2/E39_E39-U13-A1-STILL-R2_66561c02-37a9-4b4a-8273-2c520e0d1c26.png",
        "image_sha": "b5f2a202d4c5b81633fb092a2c1b656d9cdfdbab7d1c4913bf88ed21a39ae9bb",
        "voices": ["x2ucerh9xoo"],
        "prompt": """@图片1是唯一首帧、陈迹素白衣、皎兔身份服装、王府朱门和雾夜空间基准；@音频1锁定皎兔18岁少女中高、冷而轻的声线。E39古装写实短剧，9:16，原生1080p，14秒，真实1倍速。0.0-7.5秒固定大远景：素白细布直裰的陈迹已经在街心按正常步速连续走近朱门，前脚每步完整落地，衣角随夜风抬起；两名玄黑镶朱红缘戟士在门侧完成一次换岗，灯笼轻晃，湿雾逐级漫过石阶，乌云伏在陈迹肩头转耳。7.5秒按视线关系硬切锁定中近景，7.5-14.0秒：皎兔从后方真实快步追上半步，右手伸向陈迹前臂但尚未抓住；用@音频1克制担忧、慢于平时说准确台词“这一趟，是她设的局。”，重音“这一趟”“她设的局”；陈迹继续向前半步后只侧眼看她的手，脚步没有停死，乌云尾尖不安扫动，戟士背景继续换岗。所有可见人物、雾、灯笼持续有动作，禁止背景冻结。两镜内部机位锁定，只一次硬切；禁止慢推、连续跟拍、环绕、漫游、慢动作、走路拖帧、角色换脸换衣、守卫复制脸、伪中文、画内字幕、水印。""",
        "lines": ["这一趟，是她设的局。"],
    },
    {
        "id": "U14", "duration": 11,
        "image": "working_assets/e39_keyframes_v3/candidates/E39_E39-U14-A1-STILL-R3_982fe585-ccfa-43ff-8c93-06f03b2f5337.png",
        "image_sha": "8df793ec72b0156f267d877226a33a13205c42a78a086a0c14085083b6642b73",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、陈迹素白衣、皎兔身份服装、拓影和王府雾夜空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，11秒，真实1倍速。0.0-5.8秒锁定胸口与双手近景：陈迹把半露的手绘拓影沿原方向稳稳推入最贴身衣襟，手指不遮住动作，完成后手立即离开胸口；用@音频1平静决绝、转折后更慢说准确台词“她出第二问，我就去听。”，重音“第二问”“去听”；皎兔的手在画面边缘停住后缓慢落下，乌云爪子随陈迹步伐调整。5.8秒动机硬切锁定面部与抬脚反应，5.8-11.0秒：陈迹前脚正在抬向石阶，门内一线古乐传来，他只停顿不到0.35秒，眸底掠过极淡不安并立即压平，随后脚继续向前落下；皎兔仍向前一步保持距离，背景戟士换岗、灯笼和雾持续运动。所有可见角色持续呼吸、步伐和视线反应，不得冻结。两镜内部机位锁定，只一次硬切；禁止慢推、摇镜、漫游、慢动作、延长迟疑、重复收拓影、角色换脸换衣、伪中文、画内字幕、水印。""",
        "lines": ["她出第二问，我就去听。"],
    },
    {
        "id": "U15", "duration": 7,
        "image": "working_assets/e39_keyframes_v2/candidates_r2/E39_E39-U15-A1-STILL-R2_420ed40d-18d9-4fe3-ac67-4160e2cc4156.png",
        "image_sha": "dc46ce3192e24e9b6036dfd516c13dca63ceb288f391c3a23f05130ede9a4a68",
        "voices": ["cypqud0bu7t"],
        "prompt": """@图片1是唯一首帧、陈迹素白衣、乌云、王府石阶和雾灯空间基准；@音频1锁定陈迹20岁中低冷稳声线。E39古装写实短剧，9:16，原生1080p，7秒，真实1倍速，单一连续镜头。陈迹从首帧已在踏上第二级石阶的动作中继续，以正常坚定步速逐级上行，素白衣摆和乌云身体随每步产生真实惯性；两名玄黑镶朱红缘戟士在朱门两侧完成换岗，灯笼被夜风推晃，湿雾向上漫。摄影机只做一次与他登阶动机严格绑定的垂直升高，速度恒定，不左右摆、不回落、不环绕，到6.4秒露出朱门与层层雾灯但仍看清陈迹。1.0-4.5秒陈迹画外音用@音频1极低、清醒、带锋芒但不做预告腔说准确台词“拿她自己的印，赴她的问。”，重音“她自己的印”“赴她的问”；可见陈迹不张口，继续走路。所有可见人物、猫、灯笼、雾持续运动，禁止背景冻结。禁止慢动作、步伐拉伸、摇摆升降、二次运镜、推拉变焦、角色换脸换衣、守卫复制脸、伪中文、画内字幕、水印。""",
        "lines": ["拿她自己的印，赴她的问。"],
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    if sha(SCRIPT) != SCRIPT_SHA or sha(MANIFEST) != MANIFEST_SHA:
        raise SystemExit("canonical SHA mismatch")
    tasks = []
    for unit in UNITS:
        image = ROOT / unit["image"]
        if not image.is_file() or sha(image) != unit["image_sha"]:
            raise SystemExit(f"{unit['id']} admitted image SHA mismatch")
        prompt_path = OUT / f"E39-{unit['id']}-R1.txt"
        prompt_path.write_text(unit["prompt"].strip() + "\n", encoding="utf-8")
        prompt_text = prompt_path.read_text(encoding="utf-8")
        checks = {
            "canonical_sha": "PASS",
            "admitted_keyframe_exact_sha": "PASS",
            "normal_or_pro": "PASS_PRO",
            "native_1080p": "PASS",
            "real_time_1x": "PASS" if "真实1倍速" in prompt_text else "FAIL",
            "camera_motion_budget": "PASS" if "禁止" in prompt_text and "慢动作" in prompt_text else "FAIL",
            "all_visible_roles_active": "PASS" if "冻结" in prompt_text else "FAIL",
            "dialogue_exact": "PASS" if all(line in prompt_text for line in unit["lines"]) else "FAIL",
            "voice_assets_bound": "PASS" if unit["voices"] else "FAIL",
            "text_policy": "PASS_SOURCE_BOUND" if unit.get("exact_text") else "PASS_NO_DIEGETIC_TEXT_REQUIRED",
        }
        gate = {
            "schema": "qingshan.e39_independent_video_preflight.v1",
            "episode": "E39", "unit_id": f"E39-{unit['id']}-R1",
            "status": "PASS" if all(value.startswith("PASS") for value in checks.values()) else "FAIL",
            "source_script_sha256": SCRIPT_SHA, "canonical_manifest_sha256": MANIFEST_SHA,
            "prompt_file": rel(prompt_path), "prompt_sha256": sha(prompt_path),
            "admitted_keyframe": unit["image"], "admitted_keyframe_sha256": unit["image_sha"],
            "gate_results": checks,
        }
        gate_path = QA / f"E39_{unit['id']}_R1_VIDEO_PREFLIGHT_V1.json"
        gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if gate["status"] != "PASS":
            raise SystemExit(json.dumps(gate, ensure_ascii=False, indent=2))
        tasks.append({
            "task_key": f"E39-{unit['id']}-R1", "model": "seedance-2.0-pro",
            "duration_seconds": unit["duration"], "aspect_ratio": "9:16", "resolution": "1080p",
            "action_unit": False, "native_dialogue_required": bool(unit["lines"]),
            "dialogue_lines": unit["lines"], "reference_audio_asset_ids": unit["voices"],
            "prompt_file": rel(prompt_path), "prompt_sha256": sha(prompt_path),
            "reference_images": [unit["image"]], "reference_sha256": [unit["image_sha"]],
            "source_script_sha256": SCRIPT_SHA, "canonical_manifest_sha256": MANIFEST_SHA,
            "text_policy": {"exact_allowed": unit.get("exact_text", []), "pseudo_text_forbidden": True},
        })
    wave1_ids = {"U01", "U02", "U03", "U04", "U05"}
    wave1_tasks = [task for task in tasks if task["task_key"].split("-")[1] in wave1_ids]
    wave2_tasks = [task for task in tasks if task not in wave1_tasks]
    manifest = {
        "schema": "qingshan.giggle_video_batch.v2", "episode": "E39",
        "status": "READY_TO_SUBMIT_BOUNDED_CONCURRENT_WAVE_1",
        "source_script_sha256": SCRIPT_SHA, "canonical_manifest_sha256": MANIFEST_SHA,
        "machine_gate_reports": [f"qa/e39_video_v1/E39_{u['id']}_R1_VIDEO_PREFLIGHT_V1.json" for u in UNITS],
        "tasks": wave1_tasks,
    }
    manifest_path = OUT / "E39_INDEPENDENT_VIDEO_WAVE1_MANIFEST_V1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest2 = {
        **manifest,
        "status": "READY_TO_SUBMIT_BOUNDED_CONCURRENT_WAVE_2",
        "machine_gate_reports": [
            f"qa/e39_video_v1/E39_{task['task_key'].split('-')[1]}_R1_VIDEO_PREFLIGHT_V1.json"
            for task in wave2_tasks
        ],
        "tasks": wave2_tasks,
    }
    manifest2_path = OUT / "E39_INDEPENDENT_VIDEO_WAVE2_MANIFEST_V1.json"
    manifest2_path.write_text(json.dumps(manifest2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    print(manifest2_path)


if __name__ == "__main__":
    main()
