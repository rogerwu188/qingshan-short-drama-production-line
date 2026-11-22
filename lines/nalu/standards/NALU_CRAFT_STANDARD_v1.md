# NALU 成片质量标准 v1

> 状态：**已接入引擎（线主 2026-11-17 选方案 A：每集不加成本、镜头数不变）**。只评分，不新增门禁。v0 保留在线主的 nalu-fleet 仓库。
> 用途：每一集成片对照的「标准录音」，让写作、S7 剪辑、终审和知识库朝同一个方向学。
> 依据：引擎 origin/main（`dabfa1e`，已含 PR #248 的 `DIRECTING_GUIDANCE` 载体）。2026-11-17。
> 接入点（本仓库）：
> - 条目机读版 `lines/nalu/standards/NALU_CRAFT_STANDARD_v1.items.json`（id、层、core/nice、中英原则、终审检查；`codex_compressed_zh` 即 §2 压缩版）；
> - Codex 开集提示的「NALU 成片标准 v1」一节（`skills/nalu-claude-code/scripts/codex_production.py`，≤1500 字，独立于「本集导演经验」）；
> - S7 无台词镜 / 爽点后反应镜按运动峰值选窗（`tools/performance_cut.apply_peak_windows`，§4 冲突 1 的方案 A 做法：免费、不新增生成）；
> - 终审答卷可选块 `craft_standard`（`lines/nalu/runtime/tools/nalu_craft_standard.py` 宽松解析，不是门禁）；
> - top gap → 知识库事件 `CRAFT_STD_GAP|<条目 id>`，按 release_train **默认**阈值聚类（不按 §3 第 2 点的 3 集 / 2 台 / 14 天）。
> 本文件只在引擎仓库里，不进任何公开桶上传路径。

## 0. 定位

- **节奏和结构跟竖屏爽剧走**：开场即冲突，约 15–25 秒一个爽点，平均镜长 2–3 秒，进场晚、离场早，结尾停在揭示上。
- **好莱坞只管清晰和语法**：景别动机、视线、180°、正反打覆盖、有动机的切、表演和连续性（Mascelli、Bowen、Murch、McKee、场记连续性做法；只概括，不摘录）。
- 凡是暗示「留白、慢铺垫、建立镜、长镜头、情绪淡出、氛围空镜」的写法，v1 一律删掉或改写。
- **只评分，不新增硬伤。** 现有 `hard_fail` 不动：身份颜色、开场 10 s 钩子、结尾 5 s 钩子、烧录字幕。v1 的数字更严，但只进分数、gap 和知识库，不拦片。
- **数字按成片时长 D 缩放**，基准 D ≈ 110 s（`SCRIPT_DEFAULT_TARGET_SECONDS`）。中文、英文剧用同一套数字；台词条件按语言换算。
- **台词占比只作参考值，不打分。**
- **例子分中英两套，编号相同**：中文以打脸、反转为主，英文以悬疑、惊悚为主（Suspense & Horror）。
- 每条注明它细分的 `DIRECTOR_SCORE_V1` 维度：narrative_causality / pacing_information / performance_interaction / composition_camera_motivation / editing_action_continuity / sound_dialogue / emotion_continuation。本标准是这套评分的细目。

**条目**共 **26 条**：S 层（节奏与结构）10 条，core 8 / nice 2；C 层（清晰与语法）16 条，core 13 / nice 3。S 层排在前面。

**爽点的定义**（S-02、S-05、S-10 通用）：一个**观众看得见的力量或信息翻转**，并且翻转的方向是观众期待的（或者恐惧的）。算作爽点的有以下六类，其余都不算：
1. **打脸 / 反击**：被压的一方当场回击，压人的一方吃瘪。
2. **身份揭示**：被轻视的人亮出真实身份，或者揭出隐藏身份。
3. **局势反转**：权力、筹码、生死从一方转到另一方。
4. **羞辱回报**：之前受的羞辱，被对方当面还回来。
5. **秘密曝光**：证据、真相当众或当面揭开。
6. **威胁升级**（英文悬疑和惊悚的主要形式）：危险被确认、逼近或加码，比如那个东西就在屋里。

**不算爽点**的有：情绪抒发、单纯的争吵升级（没有出现翻转）、景色或氛围、对已知信息的复述。

---

## S 层：节奏与结构（10 条）

### S-01 1–2 秒钩子，从戏中间进 · core
- **原则**：第一帧就有冲突、羞辱、揭示或危险正在发生，从场景中途切入，没有任何铺垫镜。*Frame one: a conflict, insult, reveal or danger already under way; enter mid-scene, no setup shot.*
- **为什么**：竖屏观众在 1–2 秒内决定划不划走，铺垫镜等于把观众送走。
- **Codex**：第一镜的 `action` 从动作中途写起（`first_frame_motion_state` 写已经在动），台词第 0 s 开口，或者第 0 s 有身体冲击。第一镜不写 WIDE、空镜或片名；片名卡放在钩子之后。第一镜 `target_seconds` 写 2–3。
- **终审**：0–2.0 s 内的第一个冲突事件（事件时间戳）。第一个冲突事件晚于 2.0 s，或者第一镜是空镜、建立镜，记为 gap。
- **中**：好：0.0 s 一杯酒泼到她脸上，「穷鬼也配坐主桌？」。坏：先 4 s 酒店外景，再是她走进宴会厅。
- **EN**：好：0.0 s 手电扫过，床底下有一只眼睛睁着。坏：先 5 s 雨夜公路航拍，再切车内。
- **依据**：短视频留存惯例；McKee（激励事件前置）。**细分** pacing_information

### S-02 爽点节拍：每 15–25 秒一个，有铺垫才算 · core
- **原则**：大约每 15–25 秒一个爽点或转折，全集至少 ⌊D/25⌋ 个（110 s 约 4 个），相邻两个间隔不超过 25 s。每个爽点之前必须有一个**挑衅或铺垫镜**，即把观众情绪压下去的那一下。*A payoff or turn every 15–25 s (≥ ⌊D/25⌋, ~4 per 110 s); each must be set up by an earlier provocation.*
- **为什么**：爽剧靠「压、扬」循环留住人；没有压的扬落不下来，没有扬的空档就是流失点。
- **Codex**：大纲列一张爽点表：`{秒数, 类型(6 类之一), 铺垫镜号, 爽点镜号, 反应镜号}`，秒数按镜头时长累计。第一个爽点不晚于 25 s；铺垫和爽点之间不超过 3 场。
- **终审**：从事件账本里标出每个爽点的时间和类型，每个要有一句话说明「它兑现的是哪一次挑衅（时间戳）」。爽点数量不足、或者任意两个间隔超过 25 s，记 gap，写法如「S-02：38–71 s 无爽点（33 s）」。没有铺垫的爽点不计数。
- **中**：好：12 s 婆婆当众撕她简历（压），31 s 她接到电话「董事长请您上台」（揭示），48 s 婆婆被保安请出（打脸）……。坏：前 60 s 只有吵架，一直在升级，没有一次翻转。
- **EN**：好：9 s 他锁好所有门，24 s 楼上传来脚步声（威胁确认），45 s 监控显示那人一直站在他身后（威胁升级）。坏：从头到尾都是不安的氛围，没有一个确认的事件。
- **依据**：McKee（setup/payoff、转折递进）；短剧付费节奏惯例。**细分** pacing_information / emotion_continuation

### S-03 剪辑节奏：平均镜长 2–3 秒，没台词不超过约 4 秒 · core
- **原则**：成片里的平均镜长约 2–3 秒；**没有正在说的台词，任何镜头都不停留超过约 4 秒**。动作镜剪在峰值。*Average on-screen shot ~2–3 s; nothing holds past ~4 s unless a line is still being spoken; action shots are cut at the peak.*
- **为什么**：在竖屏上，节奏本身就是信息密度，一个 6 秒的无声镜头就是一次划走机会。
- **Codex**（结合引擎现有剪法，见 §4 冲突 1）：
  - 无台词镜 `target_seconds` 写 **1.5–3**。H3 按 4 s 生成（`PROVIDER_MINIMUM_PADDED`），S7 从尾部剪掉多出的部分，**保留的是开头的这几秒**。所以动作必须**从第 0 帧开始**，峰值落在所写的时长之内：写「已经扬起的手落下」，不写「抬手、停顿、落下」。
  - 对白镜由 S7 剪到表演（首字前 0.15 s 到末字后 0.4 s）。不加停顿，不加说完之后的动作。
  - 同一说话人连续几句仍然放在一个镜头里，但同机位连续台词超过约 8 s 就插一个 1.5–2 s 的反应镜（比引擎 R12 的 12 s 更紧，只是写法建议）。
- **终审**：用逐镜时间窗算出平均镜长和最长镜头（客观数据）。平均镜长超过 3.2 s，或者有无台词镜超过 4.0 s，记 gap，写法如「S-03：shot 14 无台词停 6.1 s @52.0 s」「平均 3.8 s」。
- **中**：好：「你敢？」（1.8 s），她抬手（1.2 s），耳光落下（0.9 s），他捂脸愣住（1.5 s）。坏：她缓缓起身、走到窗边、回头，一个 7 s 的无声镜头。
- **EN**：好：门把转动（1.5 s），他屏息（1.8 s），门缝下有影子停住（2 s）。坏：一个 8 s 的慢推，推向一扇关着的门。
- **依据**：Murch（节奏、剪在念头结束处）；短剧剪辑惯例。**细分** pacing_information / editing_action_continuity

### S-04 进场晚、离场早 · core
- **原则**：每场从铺垫之后开始，在转折处结束；不拍进门、寒暄、告别、赶路。*Enter late, leave early: start after the setup, end on the turn; no walk-ins, greetings, goodbyes or travel.*
- **为什么**：过场和寒暄不改变任何东西，在 110 秒里每一秒都要有事发生。
- **Codex**：每场第一镜是冲突已经开始的状态，最后一镜是转折镜（或者转折后的反应镜），然后直接切下一场；换地点靠硬切，不写走过去的镜头；时间跳跃靠台词或一张字幕交代。
- **终审**：数一数「进门 / 落座 / 问候 / 道别 / 走路去某地」的镜头和它们的时长（记时间）；场景在转折之后还继续了几秒（超过 2 s 记 gap）。
- **中**：好：上一场她被赶出门（转折），硬切她已经坐在对手的办公桌上。坏：她拎包走出别墅、打车、下车、走进公司大堂，一共 12 s。
- **EN**：好：硬切，她已经在地下室，手电只照亮半张脸。坏：她下楼梯，一级一级下了 9 s。
- **依据**：通行的编剧准则 enter late / leave early（McKee 的场景经济）。**细分** pacing_information / narrative_causality

### S-05 爽点后接反应特写 · core
- **原则**：每个爽点后紧接输家或旁观者的震惊反应，用 CU，1.5–2.5 s。*After every payoff, cut to the loser's or onlookers' shocked reaction in close-up.*
- **为什么**：观众的满足感是从对方脸上「读」出来的；没有反应镜，爽点就只是一句台词。
- **Codex**：在爽点镜后面写一个无对白镜，`shot_scale: CLOSE_UP`，`REACTION_CUT`，`target_seconds` 1.5–2.5；`listener_reaction_en` 写具体的身体动作（笑容僵住、杯子停在嘴边）。旁观者最多 2 人，或者只给 1 人的 CU，不拍人群（C-04）。可以用 `sound_bridge_from_previous_seconds` 让爽点那句台词盖在反应上。
- **终审**：每个爽点后 3 s 内有没有反应特写（是/否，记爽点时间）？反应是不是只是在「听」，没有可读的情绪？
- **中**：好：她亮出工牌，切经理的 CU，笑容一点点僵掉。坏：她亮出工牌，直接切到下一场。
- **EN**：好：他念出死者的名字，切她的 CU，瞳孔一缩，手里的杯子停在半空。坏：揭示之后切一个两人的远景。
- **依据**：Murch（情感优先）；Mascelli（Cutting：reaction shot）；爽剧惯例。**细分** performance_interaction / emotion_continuation

### S-06 结尾悬念：最后 2–3 秒，切在揭示上 · core
- **原则**：最后 2–3 秒是揭示或威胁本身，必要时在台词中途切黑；不解决，不抒情，不淡出。*The last 2–3 s are the reveal or threat itself; cut on it, mid-line if needed. No resolution, no mood fade.*
- **为什么**：悬念决定下一集的点击；解决之后再结束，观众就没有理由继续看。
- **Codex**：最后一镜写揭示或威胁的那一下，`target_seconds` 2–3，台词可以写成被打断的半句（「你根本不是我——」），引擎按最后一个台词字后 0.4 s 剪；接着直接进片尾卡，不写情绪空镜。
- **终审**：沿用 `tail_5s_hook_intact`，另外看揭示或威胁是否落在最后 3 s 内（时间戳）。揭示之后还有超过 1.5 s 的余韵或解决，记 gap。
- **中**：好：门开，床上坐着的竟是「已死」的新娘，她抬眼：「老公，我回来了——」切黑。坏：两人相拥，夕阳空镜，淡出。
- **EN**：好：手机亮起，来电显示是她自己的号码，切黑。坏：凶手被抓，她长出一口气，镜头拉远。
- **依据**：连续剧 cliffhanger 惯例。**细分** emotion_continuation

### S-07 开场 3–5 秒兑现上集悬念，然后立刻加码 · core（第 2 集起）
- **原则**：开头 3–5 秒回应上集的结尾悬念，紧接着抛出一个更大的问题或威胁。*The first 3–5 s pay off the previous cliffhanger, then escalate at once.*
- **为什么**：追更的观众带着问题进来，先给答案留住人，再加码让人继续看。
- **Codex**：大纲写 `prev_cliffhanger → payoff_shot (≤5 s) → escalation_shot (≤10 s)`；兑现镜可以和 S-01 的钩子合成一镜；不复述上集，不放「前情提要」。
- **终审**：上集结尾的问题（读上集事件账本）在第几秒得到回应（超过 5 s 记 gap）；10 s 内有没有新的加码（是/否）？
- **中**：好：0 s 新娘摘下盖头，是双胞胎妹妹；4 s 她对新郎冷笑：「我姐姐是你推下去的吧？」。坏：从第二天早饭开场，40 s 后才提到新娘。
- **EN**：好：0 s 来电接通，是她自己的声音：「别回头。」6 s 卧室门在身后自己合上。坏：开场是警察做笔录，复述昨晚的事。
- **依据**：连续剧 setup/payoff 惯例。**细分** emotion_continuation / pacing_information

### S-08 台词：短、冲，信息只能以指控或揭示出现 · core
- **原则**：一句台词中文约 12–15 字以内、英文约 8–10 词以内、日文约 18–22 字以内、韩文约 14–18 个音节以内；每一句都在对抗；交代信息只能以指控或揭示的方式出现，人物不自报情绪。*Short, punchy, conflict-driven lines (≤ ~12–15 zh chars / ~8–10 en words / ~18–22 ja characters / ~14–18 ko syllables); exposition only as an accusation or reveal; no one names their own feelings.*
- **为什么**：竖屏字幕一长就挡脸、拖慢；说明性对白是最常见的弃剧点。爽剧台词可以直接，但要像子弹，不能像说明书。
- **Codex**：超长的台词在自然停顿处拆成两句；「你也知道，三年前……」改成「三年前是你推她下楼的！」；禁止「我好伤心 / I'm so scared」这类台词；情绪写进 `delivery_en` 和身体动作。参考值（不打分）：画内台词约占成片时长的 45–65%。
- **终审**：数一数超长句（超过 15 字 / 10 词 / 日文 22 字 / 韩文 18 音节）、说明性台词、自报情绪的台词（记时间）；字幕有没有超过 2 行。三类合计超过 3 句，记 gap。
- **中**：好：「钱呢？」「花了。」「给谁？」「你妹妹。」坏：「你知道吗，自从三年前爸爸生病以后，我们家就一直很困难……」
- **EN**：好："You locked it?" "Twice." "Then who opened it?" 坏："As you know, ever since the accident last winter, this house has felt different…"
- **依据**：McKee（对白是动作、潜台词，按爽剧改写成直接对抗）；竖屏字幕可读性惯例。**细分** sound_dialogue / narrative_causality

### S-09 5 秒内主角入局，15 秒内立起目标与对手 · nice
- **原则**：主角在 5 秒内正脸出场、处于困境；15 秒内观众知道这一集他要什么、谁在挡。*Protagonist on screen in a predicament by 5 s; the episode's goal and antagonist clear by 15 s.*
- **为什么**：观众需要一个可以代入的人和一个要等的结果，后面的爽点才有方向。
- **Codex**：第一或第二镜的 `cast` 包含主角，用 MCU 或 CU；大纲首行写 `本集目标: <主角> 要 <X>，<对手> 挡`。
- **终审**：主角正脸首次出现的时间；15 s 时能否用一句话说出本集的目标和对手（是/否）？
- **中**：好：3 s 她被按在地上抬起头；11 s「明天的股东会，我一定到场。」坏：前 20 s 都是反派密谋。
- **EN**：好：2 s 他从浴缸里惊醒；12 s "Whoever's in this house, I'm finding you tonight." 坏：前 18 s 是房产中介带客人看房。
- **依据**：McKee（protagonist & desire）。**细分** narrative_causality

### S-10 爽点逐级加码 · nice
- **原则**：每个爽点的力度要高过上一个（筹码更大、当众范围更广、威胁更近），最大的一个放在最后三分之一，然后接悬念。*Each payoff outbids the last; the biggest lands in the final third, right before the cliffhanger.*
- **为什么**：同等力度的爽点重复出现会让观众麻木，加码才会让人上头。
- **Codex**：爽点表里给每个爽点标 `强度 1–5`，要求单调不减；最大的一个放在 0.65D 之后。
- **终审**：按时间顺序给爽点排强度；有没有回落（记时间），最大的爽点在第几秒？
- **中**：好：私下顶嘴，当众打脸，揭示身份，全家跪求。坏：第一个爽点就是最大的身份揭示，后面都是小口角。
- **EN**：好：一个异响，一个人影，那东西进了屋，它在床底下。坏：第一分钟就把怪物完整亮相，后面只剩追逐。
- **依据**：McKee（progressive complications）。**细分** emotion_continuation

---

## C 层：清晰与语法（16 条）

### C-01 景别为冲突服务，不建立镜 · core
- **原则**：以 MCU 和 CU 为主；不写建立镜，空间关系靠冲突中的第一个双人镜交代；WIDE 只在空间本身就是戏的时候用；爽点和揭示给本场最紧的景别。*MCU/CU dominate; no establishing shots, geography comes from the first two-shot inside the conflict; WIDE only when space is the story; the payoff gets the tightest shot.*
- **为什么**：竖屏上远景看不清脸；景别是对观众说「看这里」，最紧的景别应该留给最重的那一下。
- **Codex**：`shot_scale` 分布：CU 和 MCU 占约 70% 以上；`WIDE`/`MEDIUM_WIDE` 全集不超过 3 镜，且必须有戏（追逐、对峙距离、怪物出现）；交代空间用 `MEDIUM` 的过肩双人镜，人物已经在冲突里。同一景别连续不超过 3 镜。
- **终审**：统计各景别的镜数；爽点、揭示是否是本场最紧的景别（是/否）；有没有无戏的远景或建立镜（记镜号）。
- **中**：好：MEDIUM 过肩镜里她把文件拍在桌上，切经理的 CU。坏：先给一个 3 s 的会议室全景，人物很小。
- **EN**：好：MEDIUM 过肩镜，他举着手电，前景是她的后脑。坏：3 s 的房子外景远景，什么都没发生。
- **依据**：Mascelli（Camera Angles、Close-ups）；Bowen（景别语法），按竖屏和爽剧改写。**细分** composition_camera_motivation

### C-02 竖屏构图与视线落点 · core
- **原则**：脸在上三分之一，留出视线空间；双人只用前后叠放的过肩镜，不左右贴边；切点前后观众的注视位置尽量不跳。*Face in the upper third with look-room; two-shots stack front/back; keep the viewer's eye in place across a cut.*
- **为什么**：竖屏宽度有限，左右分站会让两张脸都小；快剪时，眼睛找不到脸，这一刀就显得卡。
- **Codex**：`start_framing` 写成画面范围（"mid-chest up, face in upper third, looking frame-left"）；正反打两镜的人脸都放在中上区域。
- **终审**：在接触表上找人脸被切、人物过小、左右贴边的镜头（记镜号）；抽查对白切点，看人脸的位置有没有大幅跳动。
- **中**：好：过肩镜，前景婆婆的肩，她的脸在右上三分之一。坏：两人分站画面左右边缘，中间是空墙。
- **EN**：好：他的脸在上三分之一，身后虚化的走廊尽头站着一个人影。坏：他的脸被画框底边切掉一半。
- **依据**：Mascelli（Composition）；Bowen（headroom/look room）；Murch（eye-trace）。**细分** composition_camera_motivation

### C-03 一镜一拍 · core
- **原则**：一个单元只做一件看得清的事；换机位、换视角就切。*One unit, one clear action beat; a new angle is a cut.*
- **为什么**：H3 会把两拍糊成一次运镜；而且只有一拍的镜头，S7 才能剪到 2 s 左右还保持完整。
- **Codex**：一镜一个动词主干；打斗只拍对峙、出手前一瞬和结果（K172）；对白镜只拍说话，不夹带动作。
- **终审**：逐镜看有没有两拍以上、动作没收住、或者中途换了主体（记镜号）。
- **中**：好：她扬手（1.2 s），耳光落下（0.9 s），他偏过头（1.5 s）。坏：一个镜头里扬手、扭打、夺包，手部畸形。
- **EN**：好：刀尖从门缝伸进来（1.5 s），她后退（1.2 s）。坏：一个镜头里破门、扑倒、搏斗。
- **依据**：Mascelli（Cutting）；H3 实测。**细分** editing_action_continuity

### C-04 只拍 AI 拍得好的东西 · core
- **原则**：每镜最多 2 个可见人物；不拍人群、无主的手、画面文字、复杂特效；拍结果和反应。*≤ 2 visible people; no crowds, ownerless hands, on-screen text or complex VFX; shoot outcome and reaction.*
- **为什么**：人一多，身份就会漂；手和文字是 AI 痕迹最重的地方。爽剧「当众」的场面，尤其容易写成人群。
- **Codex**：「当众」的效果用 1–2 个旁观者的 CU 加上群声来实现，不拍满屋的人；按桶分配（图形和文字进字幕卡）；登记人物的手出镜时写清袖口；遵守 §1b 的内容安全规定。
- **终审**：有没有超过 2 个人、多出来的人或手、乱码文字、变形（逐镜记录，计入 anti_ai）。
- **中**：好：「全场哗然」拍成一个宾客 CU 加上画外的议论声。坏：拍满屋子的宾客，背景里的人脸融化。
- **EN**：好：「怪物」登记成 CREATURE 并写清长相，只露一次轮廓。坏：一群邪教徒围成一圈。
- **依据**：H3 实测（`H3_SCRIPT_ADAPTATION_GUIDE` §1–§3、§6）。**细分** composition_camera_motivation

### C-05 视线 · core
- **原则**：说话时眼睛看着听者，略偏离镜头、朝向听者那一侧，不直视镜头；正反打的两镜视线方向相反。*Eyes on the listener, just off-lens toward their side; shot/reverse singles look to opposite sides.*
- **为什么**：快剪时，视线是观众判断「谁对谁说」的唯一线索。
- **Codex**：写 `dialogue_listener_screen_side`；说话镜里不写转头看窗或门；「看某样东西」另起一个镜头。
- **终审**：每组正反打的视线是否相对（是/否）；有没有直视镜头、或者说话时镜头摇走（记镜号）。
- **中**：好：她看画左骂，婆婆的反打看画右。坏：她对着镜头说「你给我滚」。
- **EN**：好：他看画右低语，她的反打看画左。坏：他说话时转头看窗，H3 跟着摇向窗户，把他丢出画面。
- **依据**：Bowen（eyeline match）。**细分** performance_interaction

### C-06 180° 轴线与屏幕方向 · core
- **原则**：一场之内人物的左右位置不换；运动方向在镜头之间保持一致；要越轴，先给一个中性镜或插入镜。*Hold the line and screen direction; cross only via a neutral or insert shot.*
- **为什么**：快剪之下，越轴的混乱会被放大，观众会以为人物换了位置。
- **Codex**：同一对人在一场里 `camera_side` 固定，`dialogue_listener_screen_side` 全场一致；追逐的 `motion_direction` 不能反过来。
- **终审**：一场内 A 是否始终在同一侧（记越轴的镜号）；运动方向有没有反转（记切点）。
- **中**：好：她始终在画左，婆婆始终在画右。坏：第三镜两人突然换边。
- **EN**：好：他从左往右跑，下一镜继续从左入画。坏：追逐中下一镜他朝相反方向跑。
- **依据**：Bowen（180° rule、screen direction）；Mascelli（Continuity）。**细分** editing_action_continuity

### C-07 对白覆盖：一镜一个说话人，正反打 · core
- **原则**：说话镜只拍说话人（单人镜，或者带一点对方肩膀的过肩镜）；正反打一来一回；双人同框只用在无对白的时刻；用 L-cut 让台词盖到反应上。*One speaker per shot in singles or OTS; alternate shot/reverse; two-shots only when silent; L-cuts carry lines onto reactions.*
- **为什么**：正反打既有说话人，又有挨骂的人；H3 在双人同框说话时会丢掉听者、出现重影。L-cut 还能压缩时长。
- **Codex**：说话镜 `cast` 里只有说话人一张正脸；同一人的连续几句放进同一个锁定的 `camera_plan` 加 `CONTINUOUS_ACTION`；反应镜写 `sound_bridge_from_previous_seconds` 0.3–1.0。不要求先给一个无声双人镜，第一镜就是冲突（S-01）。
- **终审**：有没有双人同框、一人说话的镜头（记镜号）；对白场是不是全程一个双人中景（是/否）。
- **中**：好：MCU 婆婆骂，切她的 CU 冷笑（话尾盖过去），再切她回击。坏：两人站在同一个中景里吵了 30 s。
- **EN**：好：他在 CU 里说 "She never left this room."，L-cut 到她在 CU 里僵住。坏：两人坐沙发，同一个双人镜里你一句我一句。
- **依据**：通行的覆盖做法；Bowen（shot/reverse shot）；CAMERA_GRAMMAR_V1。**细分** performance_interaction / editing_action_continuity

### C-08 每一刀都有理由，剪在峰值 · core
- **原则**：每个切点都在回应一个看、一个反应、一个新信息或动作的延续；动作镜剪在峰值，跨镜动作从中途接上。*Every cut is motivated (Rule of Six: emotion first); action shots cut at the peak, matched mid-motion.*
- **为什么**：快节奏不等于乱剪；有理由的快切让观众察觉不到剪辑，没有理由的快切只会让人头晕。
- **Codex**：每个切写 `transition_mode`（MOTIVATED / REACTION / MATCH / HARD）；动作写成从第 0 帧开始、到峰值为止（配合 S-03）；跨镜动作，后一镜从同一个动作的中途开始。
- **终审**：逐个切点说出理由，说不出的记为 jump（记时间）；动作有没有在峰值前被剪断，或者峰值之后还拖着（记镜号）。
- **中**：好：她扬手，切到他脸上，耳光正好落下（动作匹配）。坏：两个景别相同的镜头之间无理由跳切。
- **EN**：好：她听见咔嗒一声，切到门锁正在转（反应加信息）。坏：快切了 6 个走廊空镜，什么也没交代。
- **依据**：Murch（Rule of Six）；Mascelli（Cutting）。**细分** editing_action_continuity

### C-09 每场一个价值翻转，并且在翻转处结束 · core
- **原则**：每一场至少翻转一个价值（正转负或负转正），并且就在翻转处结束；一场约 15–30 s。*Every scene flips a value and ends on the flip; scenes run ~15–30 s.*
- **为什么**：没有翻转的场就是冷场；翻转之后还停留，就是在拖。
- **Codex**：每场写 `价值: 起 → 终` 和翻转镜号；翻转镜就是本场最后一镜，或者倒数第二镜（最后一镜是反应镜）。
- **终审**：逐场写出翻转和它发生的秒数；没有翻转的场、或者翻转之后还拖了超过 2 s，记 gap。
- **中**：好：她以为来提亲（+），最后一句才知道新郎要娶妹妹（−），切。坏：吃饭聊天 30 s，什么也没变。
- **EN**：好：他以为屋里安全了（+），关灯的那一刻看见镜子里多出一个人（−），切。坏：两人回忆往事，场景无变化地结束。
- **依据**：McKee（scene turn / value change）。**细分** narrative_causality

### C-10 每个镜头都有可读的目的 · core
- **原则**：把叙述、概括、心理活动改写成有冲突、有反应的戏；每一镜都要能说出它是为什么存在的。*Dramatize, don't illustrate: every shot has a purpose a first-time viewer can name.*
- **为什么**：观众只看得到画面；没有目的的镜头既拖慢节奏，又让人迷路。
- **Codex**：每镜写一句目的（挑衅 / 爽点 / 反应 / 信息 / 威胁），写不出来就删；原著的时间跨度用一句台词或一张字幕带过。
- **终审**：静音那一遍里，逐镜说出它的作用；说不出的镜头数和合计时长。
- **中**：好：师弟抱着第四个蒲团吐槽「库房真没了」，用一句话交代四百年苦修。坏：8 个镜头分别拍按蒲团、举剑、翻书、白鹤。
- **EN**：好：一张冰箱贴纸条写着 "Don't open the basement"，字迹是她自己的（用插入镜）。坏：一串 montage 拍她搬家、拆箱、刷墙。
- **依据**：McKee；本线 §0。**细分** narrative_causality

### C-11 表演：眼睛先行，反应要大但不做鬼脸 · core
- **原则**：情绪先到眼睛，再到嘴上；主角收着演，爽点之后的反应可以大（震惊、僵住），但不做鬼脸；每一句台词有自己的音调走向。*Eyes lead; the protagonist plays it cool, reactions after a payoff may be big (shock, freeze) but never mugging; each line has its own pitch arc.*
- **为什么**：竖屏上脸占满整个画面，夸张会显得假；而爽点的快感来自「赢家冷、输家崩」的反差。
- **Codex**：每句写自己的 `delivery_en`（情绪、音调走向、重音、力度），不按说话人套模板；赢家写 "cold, low, unhurried"，输家写具体的崩溃动作；动作先写眼神。每句再写 `performance.business_en`：一个由这一拍意图推动的具体小动作（整理袖口、移开视线再看回、上前半步、抱臂、轻呼一口气），4 句内不重复同类、每场同类≤2 次，不写双手摊开（除非就是无奈/求饶）。
- **终审**：声音那一遍：是不是整集一个调、同一说话人一个模板（是/否）；画面那一遍：有没有鬼脸、表情和台词情绪对不上（记镜号）。表演单调（CRAFT-ACTING-MONOTONY）：说话时干站着、或反复同一个手势（如双手摊开）、听的人僵住（记时间点）。
- **中**：好：她不抬眼：「签字吧。」对方的笑一点点僵掉。坏：每句台词都用同一种急促上扬的腔调，挨打时张大嘴、双手抱头。
- **EN**：好："Then who's breathing?" 他的声音压到近乎耳语，最后一个词停住。坏：每句都在喊，脸部表情过度扭曲。
- **依据**：Mascelli（Close-ups）；通行的表演指导；本线 E04 的教训。**细分** performance_interaction / sound_dialogue

### C-12 人物身份与服装连续 · core
- **原则**：同一个人的脸、发型、服装、伤疤、配饰在每一镜里都一致；两个主体一眼就能分开。*Same face, hair, wardrobe, scars and props in every shot; subjects read apart at a glance.*
- **为什么**：快剪时镜头越多，漂移的机会越多；身份一漂，故事就断了（这是现有的硬伤项）。
- **Codex**：长相和服装写在人物字段里（英文剧写英文）；场景字段不写人物特征（K056）；残缺特征每一镜都要写。
- **终审**：沿用 `identity_color_consistent`，另外记录漂移的镜号。
- **中**：好：反派全集都是同一件酒红西装。坏：第 7 镜反派穿上了主角的灰布衫。
- **EN**：好：她左手的绷带每一镜都在。坏：神父的白领在第 4 镜消失了。
- **依据**：场记连续性做法；Mascelli（Continuity）。**细分** editing_action_continuity

### C-13 空间、道具与光线连续 · core
- **原则**：同一场的背景、道具形状、光源方向和色温一致；暗场也看得清人。*Within a scene, background, prop shapes, light direction and colour hold; dark scenes still read.*
- **为什么**：快剪会放大光线跳变，观众会以为时间或地点变了；英文惊悚剧的暗场尤其容易变成纯黑。
- **Codex**：`scenes[].lighting` 写一个具体的动机光源；近景写背景锁；暗场写清楚照亮轮廓的余光（NO_BLACK）；道具形状在第一次出现时就写死。
- **终审**：相邻镜头之间的背景、光、道具有没有跳变（记切点）；有没有接近全黑的帧（记时间）。
- **中**：好：宴会厅每一镜都是左上方的暖色吊灯。坏：近景背景从室内漂到了室外。
- **EN**：好：手电光始终从画右打来，墙上的影子方向一致。坏：地下室某一镜突然是白天的光。
- **依据**：Mascelli（Continuity）。**细分** editing_action_continuity

### C-14 运镜要有动机：推近只给爽点和揭示 · nice
- **原则**：默认锁定机位；运镜只用于跟拍、揭示、强调；一集最多 1–2 次推近，只给最大的爽点或揭示。*Lock off by default; move only to follow, reveal or emphasise; one or two push-ins per episode, on the biggest payoff or reveal.*
- **为什么**：无缘无故的运镜是 AI 合成感最明显的来源，也会拖慢节奏。
- **Codex**：`motion_family: LOCKED` 是默认值；推近写 `DOLLY PUSH_IN`，并在镜注里写明理由；不扫空景。
- **终审**：数运镜次数，标出每次的动机；无动机的漂移和推近记镜号。
- **中**：好：只在她亮出身份的那一刻缓推。坏：每个镜头都在慢慢环绕。
- **EN**：好：那东西从床底露出眼睛时缓推。坏：整集都在漂移的手持晃动。
- **依据**：Bowen（camera movement motivation）。**细分** composition_camera_motivation

### C-15 插入镜只用作证据 · nice
- **原则**：插入镜只拍推动剧情的物件（证据、信物、威胁），并且之前有人看过去；不拍氛围空镜。*Inserts show evidence, tokens or threats a character has just looked at; never atmosphere.*
- **为什么**：爽剧没有给氛围留的时间；证据插入镜是最快的信息传递方式。
- **Codex**：插入镜前一镜写人物看向那一侧；`target_seconds` 1.5–2；无人、无手；道具之前已经交代过。
- **终审**：每个插入镜，前面有没有人看、它交代了什么；纯氛围的空镜数量和合计时长（记 gap）。
- **中**：好：她瞥向桌角，切桌角压着的亲子鉴定书。坏：两句台词之间插一个窗外竹叶的空镜。
- **EN**：好：他低头，切地毯上一串湿脚印，脚印通向衣柜。坏：插一个月亮的空镜。
- **依据**：Mascelli（cut-in 的动机）。**细分** narrative_causality

### C-16 声音：台词清楚，用声音桥接 · nice
- **原则**：台词清楚可懂，一个人一种声线；L-cut 让台词盖到反应上；配乐铺在台词下面，不抢台词。*Intelligible dialogue, one voice per character; L-cuts carry lines; score stays under dialogue.*
- **为什么**：竖屏观众很多时候半听半看，声音一断就出戏。
- **Codex**：用 `sound_bridge_from_previous_seconds`；`audio_contract.bgm` 不写，或者写成整集一条 cue（沿用本线默认）。不写逐个爽点的音效 cue，原因见 §4 冲突 4。
- **终审**：声音那一遍：有没有听不清的句子、声线变化、配乐盖住台词（记时间）。
- **中**：好：「你被开除了。」的尾音盖在经理僵住的脸上。坏：同一个人前后两句声音不像同一个人。
- **EN**：好：她的低语延续到下一镜那扇空门上。坏：配乐突然响起，盖住了关键台词。
- **依据**：Murch（声画分离剪辑）。**细分** sound_dialogue

---

## 1. 最重要的 8 条

1. **S-01** 1–2 s 钩子：从戏中间进，没有铺垫镜。
2. **S-02** 每 15–25 s 一个爽点，全集不少于 ⌊D/25⌋ 个（110 s 约 4 个），每个都有更早的挑衅作铺垫。
3. **S-03** 平均镜长 2–3 s，没有台词不超过约 4 s；动作从第 0 帧开始，在峰值剪。
4. **S-06** 最后 2–3 s 切在揭示或威胁上，必要时切在台词中途，不解决、不淡出。
5. **S-04** 进场晚、离场早：不拍进门、寒暄、道别、赶路，每场在翻转处结束。
6. **S-05** 每个爽点之后接输家或旁观者的反应特写。
7. **S-08** 台词短而冲（中文不超过约 12–15 字，英文不超过约 8–10 词，日文约 18–22 字，韩文约 14–18 个音节）；交代信息只用指控或揭示。
8. **C-07 + C-04** 一镜一个说话人，用正反打；每镜最多 2 人，不拍人群、手、字、特效。

---

## 2. 压缩版：注入 Codex 写作提示（中文，≤1500 字）

```text
【NALU 成片标准 v1｜竖屏爽剧节奏优先｜写四层时逐条自查】
节奏（核心）
S-01 第一帧就是冲突、羞辱、揭示或危险正在发生，从戏中间进；第一镜不写空镜、建立镜或片名，台词第0秒开口。
S-02 每15–25秒一个爽点（打脸/反击、身份揭示、局势反转、羞辱回报、秘密曝光、威胁升级），全集≥⌊时长/25⌋个（110秒约4个），第一个≤25秒。每个爽点之前必须有一个挑衅或铺垫镜。大纲列爽点表：秒数、类型、铺垫镜、爽点镜、反应镜。
S-03 成片平均镜长2–3秒，无台词镜不超过约4秒。无台词镜target_seconds写1.5–3：H3按4秒生成，S7从尾部剪掉多余部分，所以动作从第0帧开始，峰值落在所写时长内（写「已扬起的手落下」，不写「抬手、停顿、落下」）。同机位连续台词约8秒就插一个1.5–2秒的反应镜。
S-04 进场晚、离场早：不拍进门、寒暄、道别、赶路；换地点直接硬切；每场在翻转处结束。
S-05 每个爽点后紧接输家或旁观者的CU反应，1.5–2.5秒，REACTION_CUT；listener_reaction_en写具体动作。
S-06 最后2–3秒就是揭示或威胁本身，可以写被打断的半句，然后切黑；不解决、不抒情、不淡出。
S-07 第2集起：5秒内兑现上集悬念，10秒内加码；不写前情提要。
S-08 一句台词中文≤约12–15字、英文≤约8–10词、日文≤约18–22字、韩文≤约14–18音节，句句对抗；交代信息只用指控或揭示；不自报情绪。
S-09 主角5秒内入局，15秒内立起本集目标和对手。S-10 爽点力度逐个加码，最大的放在最后三分之一。
清晰（核心）
C-01 以MCU/CU为主（约70%以上）；不写建立镜，WIDE全集≤3镜且必须有戏；爽点给本场最紧的景别。
C-02 脸在上1/3；双人用过肩前后叠放；start_framing写清画面范围。
C-03 一镜一个动词；打斗只拍对峙、出手前一瞬、结果。
C-04 每镜≤2人；「当众」用1–2个旁观者CU加群声；不拍人群、无主的手、文字、特效。
C-05 说话时看着听者、略偏离镜头；写dialogue_listener_screen_side；说话镜里不转头看窗或门。
C-06 一场内左右位置不换，运动方向不反转。
C-07 说话镜只拍说话人；正反打；双人同框只在无对白时；反应镜写sound_bridge做L-cut。
C-08 每个切都写transition_mode并有理由；跨镜动作从中途接上。
C-09 每场写「价值 起→终」，翻转镜就是本场最后一镜。
C-10 每镜写一句目的，写不出就删。
C-11 每句单独写delivery_en；赢家冷，输家写具体的崩溃动作；动作先写眼神。
C-12/13 长相和服装只写在人物字段；每场一个动机光源；暗场写照亮轮廓的余光。
C-14 默认LOCKED，推近只给最大的爽点。C-15 插入镜只拍证据，前一镜有人看。
```

---

## 3. 终审输出提案（同一位终审填写，作为 DIRECTOR_SCORE_V1 的细目）

由现有的 `final_audience_review` 终审在同一遍里填写，不另起评审。在答卷里加一个可选块 `craft_standard`，现有字段和 `hard_fail` 逻辑都不变。

```json
"craft_standard": {
  "standard_version": "NALU_CRAFT_STANDARD_v1",
  "duration_seconds": 108.4,
  "pacing_metrics": {
    "first_conflict_at": 0.6,
    "payoffs": [{"t": 14.2, "type": "打脸", "setup_t": 6.0, "reaction_shot": 7},
                {"t": 71.0, "type": "身份揭示", "setup_t": 52.3, "reaction_shot": 21}],
    "payoff_count": 2, "payoff_required": 4, "max_payoff_gap": [14.2, 71.0],
    "mean_shot_seconds": 3.6, "longest_silent_shot": {"shot_index": 14, "seconds": 6.1, "at": 52.0},
    "cliffhanger_at": 106.9, "prev_payoff_at": 2.1,
    "dialogue_share_ref": 0.58
  },
  "layer_scores": {
    "pacing_structure": {"score": "1..5", "core_pass": "5/8", "reason": "≥12 字证据"},
    "clarity_grammar":  {"score": "1..5", "core_pass": "12/13", "reason": "≥12 字证据"}
  },
  "director_score_breakdown": {
    "pacing_information": ["S-01:PASS", "S-02:GAP", "S-03:GAP", "S-04:PASS"],
    "editing_action_continuity": ["C-03:PASS", "C-06:PASS", "C-08:PASS"]
  },
  "items": {"S-02": {"verdict": "GAP", "evidence": "14.2–71.0 s 无爽点（56.8 s）"}},
  "top_gaps": [
    {"rank": 1, "item_id": "S-02", "window": [14.2, 71.0], "metric": "56.8 s 无爽点（上限 25 s）",
     "fix": "把 71 s 的身份揭示前移到约 35 s，并在 45–60 s 加一次反击", "fix_owner": "writer"},
    {"rank": 2, "item_id": "S-03", "shot_index": 14, "at_seconds": 52.0, "metric": "无台词停 6.1 s",
     "fix": "改写成 2 s、动作从第 0 帧开始", "fix_owner": "writer"},
    {"rank": 3, "item_id": "S-05", "at_seconds": 71.0, "metric": "爽点后 3 s 内无反应特写",
     "fix": "71 s 后加一个经理 CU 反应镜", "fix_owner": "writer"}
  ]
}
```

- **节奏指标**：大部分可以从现有的逐镜时间窗和事件账本里直接算出来（平均镜长、最长无台词镜、首个冲突时间、结尾揭示时间）。爽点的判定和类型由终审给出，按 §0 的 6 类定义。
- **Gap 必须引用数字**，例如「S-02：15–40 s 无爽点」「S-03：shot 9 停 6 s」「S-06：揭示后又拖 4 s」「S-01：首个冲突在 3.4 s」。这样同一个 id 在不同集之间可以直接比较。
- **分层打分**：节奏结构层和清晰语法层各给一个 1–5 的整体分，不由逐条平均；core 条目的通过数作为客观参照。`director_score_breakdown` 把每一条归到它所细分的 `DIRECTOR_SCORE_V1` 维度下，维度分要和这些条目的判定一致。
- **Top 3 gaps**：在 core 的 GAP 里按对留存伤害的大小排序。节奏类（S-01、S-02、S-03、S-06）的 gap 默认排在清晰类前面，除非清晰类 gap 让剧情看不懂。

### 差距 → 知识库（沿用现有 `DIRECTING_GUIDANCE` 载体）

1. **记录**：每个 top gap 写成一条 `FAILURE_OBSERVATION`，`evidence.cluster_key = "CRAFT_STD_GAP|<item_id>"`（release_train 按 `<failure_type>|<detail_category>` 聚类），证据带集号、设备、时间窗、指标值。
2. **升级**：同一个 cluster 满足**≥3 集、≥2 台设备、14 天内**，就进入 release_train 的 review。批准后得到 `application.carrier: DIRECTING_GUIDANCE`、`category: DIRECTING_HEURISTIC`、`scope.stages: [SCRIPT_AUTHORING]`，可选 `scope.languages`；`prompt_clause {zh, en}` 从该条的「Codex」行改写，附带 1–2 个真实 gap 的反例，经 `authoring.prepare` 注入 Codex 开集提示的「本集导演经验」一节。
3. **Canary 指标**：该 item 的 GAP 率（以及节奏类的指标值，例如平均镜长、最大爽点间隔），比较 canary 设备上 APPLIED 的集和对照集。**≥5 集**，GAP 率**下降 ≥50%** 即通过；同时其他 core 条目的 GAP 率没有上升超过 20 个百分点，每集积分也没有上升。
4. **退役**：连续 10 集不再出现，就按 release_train 的 retire 流程退役，内容并入写作指南的正文。

---

## 3b. 剧本阶段免费测量与改稿（SHORT_DRAMA_PACING_V1，线主 2026-11-22）

线主：「剧情推进太慢……一集基本就是人物在念台词，一点都不刺激。」S 层的节奏问题大多在剧本里就定了（一章拍成一集、几乎全是对白），
成片终审才发现已经花了钱。所以 S-01/S-02/S-04/S-06/S-08 在 S1 先对剧本合同做一次**免费、确定性**的测量
（`lines/nalu/runtime/tools/script_pacing_check.py`，镜头时间线 = 累计 `target_seconds`）：

| 指标 | 来源 | 目标 | 对应条目 |
|---|---|---|---|
| 第一冲突秒数 | `pacing.hook.at_seconds` 与第一个转折 | ≤ 3 s | S-01 |
| 转折数 / 每分钟转折 | `pacing.beat_sheet` + `beat_role: PAYOFF` | ≥ max(4, ⌊D/25⌋) | S-02 |
| 转折最大间隔 | 0、各转折、结尾悬念之间 | ≤ 30 s | S-02 |
| 纯对白占比 | 说话镜无 MOMENTUM/CONTACT/POSSESSION/INTEGRITY 动作的秒数 / D | ≤ 60 % | S-04 / S-08 |
| 最长台词 | 句数、语言单位（zh 28 字 / en 20 词 / ja 44 字 / ko 36 音节） | ≤ 2 句 | S-08 |
| 同一人连说 | 无打断、无动作的连续台词 | ≤ 12 s | S-03 |
| 无动作场 | 整场没有任何状态改变的身体动作 | 0 | S-04 / C-09 |
| 场次计划 | `pacing.scene_plan` 每场 objective / conflict / physical_action | 齐全 | C-09 / C-10 |
| 结尾悬念 | `pacing.cliffhanger`（最后一镜或最后 8 s，open_question） | 有 | S-06 |
| 改编事件数 | `adaptation_plan.plot_events`（按事件取材，不按章节） | ≥ 所需转折数 | S-02 / S-04 |

- 只对合同写了 `"pacing_policy": "SHORT_DRAMA_PACING_V1"` 的集生效（新派单起写；进行中的旧集只记录数字）。
- 不合格 → S1 报 `SCRIPT_PACING_REVISE:round=n/2`，由编剧（Codex）自己改稿重跑，**最多两轮**，之后自动放行并记录差距；
  不问线主、不付费、不新增硬伤（`NALU_SCRIPT_PACING=off` 关闭改稿要求）。
- 数字记在流水线状态 `stages.S1.details.script_pacing`，并作为 `script_pacing` 放进终审请求的 `craft_standard_request`
  和 Gemini 导演/剪辑专审（D）的上下文：终审对照「剧本计划的节奏」和「成片量出来的节奏」判断问题出在写作还是剪辑。
  终审确认的 CRAFT-PACING / CRAFT-*-HOOK / CRAFT-BEAT-MISSED 照旧进知识库 `DIRECTING_GUIDANCE`（不涉及台词语言的默认 global，走快速通道）。
- 改编进度记在 `$NALU_RUNTIME_ROOT/series/SOURCE_COVERAGE.json`（每集用到的章节、事件数、删减数），下一集从 `next_chapter` 接着取。

## 4. 与现有引擎的冲突和需要线主决定的点

已核对 `performance_cut.py`、`build_video_unit_grouping_spec.provider_min_seconds`、`build_nalu_preproduction.project_provider_slots`、`post_generation_qa_runner` 的 static-hold 检查、`nalu_pipeline.script_length_check`、`nalu_selective_bgm` / `nalu_bgm_default`、`collective_learning/release_train` / `authoring`。**没有哪条和门禁正面矛盾**（v1 只评分）。以下几处需要知道：

1. **剪到峰值不是自动的。** 无台词单元按 4 s 生成，S7 只从**尾部**剪掉 handle，留下的是开头的 authored 秒数；`performance_cut` 从不剪进 take 内部，没人说话的无台词单元也不做剪辑。所以 v1 要求 Codex 让动作从第 0 帧开始、峰值落在写的时长之内。如果 H3 起动慢，峰值会掉进被剪掉的尾巴里。要真正「剪到峰值」，需要 S7 对无台词单元按运动峰值选窗口，这是引擎改动，**待线主决定**。
2. **成本上升（和 NALU cost first 冲突）。** 平均 2–3 s 一镜，意味着 110 s 约 40–50 个镜头。每个单元按至少 4 s 计费，生成总时长约 170–200 s，现在约 115–120 s。按 480p 1.09 积分/s 估算，每集多出约 60–90 积分（按 1.56 积分/s 估算是 +90–130），关键帧也会相应增加。缓解办法：同一说话人的连续台词并成一个单元；回到同一机位时复用关键帧（`MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE`）。但反应镜和插入镜都是独立单元。**是否接受这部分成本，待线主决定**；另一种做法是只把核心爽点段落剪快。
3. **写作指南和 v1 相反（只是指导，不是门禁）。** WRITER_CONTRACT 的 CAMERA_GRAMMAR_V1 要求「每个新地点前两镜给 WIDE/MEDIUM_WIDE」，H3 指南 §5 写「每场有远、中、近，开场一个远景」，§8 写「≤12 s 的同机位独白组」。v1 取消建立镜，并建议约 8 s 就插一个反应镜。如果采纳 v1，需要同步修改这两份文档（本草案没有改）。`script_length_check` 按 authored 秒数的 1.3 倍检查，短镜头不受影响；`post_generation_qa` 的 static hold 上限是 2.0 s（E01 是 4.0 s），和 v1 方向一致。
4. **爽点音效 cue 已删。** 本线的 nalu runtime 没有便宜的逐点音效钩子：选择性配乐每个不同的 brief 都要付费生成（约 8 积分），并且要求 ≥8 s 的纯环境窗口；引擎的 `sound_cue_contract.py`（SFX 层）没有接进 nalu runtime。按指示，因为不便宜，所以删掉；配乐继续使用现有的整集默认铺底。
5. **知识库阈值和 release_train 默认值不同。** release_train 的默认值是：≥3 台设备**或** ≥5 个（设备，集）组合、30 天内；canary 是 ≥3 集，判定标准是「不更差」。线主给的是 3 集 / 2 台设备 / 14 天，以及 ≥5 集、下降 ≥50%。需要为 `CRAFT_STD_GAP|*` 这类 cluster 单独配置，或者接受默认值。另外，`authoring` 的「本集导演经验」一节上限是 1500 字（`MAX_SECTION_CHARS`），所以上面的压缩版要**单独**放进写作提示，不能挤占这一节的预算。

## 附：v0 → v1 编号对照

| v1 | 来自 v0 | 说明 |
|---|---|---|
| S-01 | S-01 | 3 s 收紧到 1–2 s，不写铺垫镜 |
| S-02 | S-04 + S-08 | 每 30–60 s 一次转折，改为每 15–25 s 一个爽点，并给出 6 类定义和铺垫要求 |
| S-03 | C-15 + C-18 部分 | 新增：平均镜长和剪到峰值 |
| S-04 | 新增 | 进场晚、离场早 |
| S-05 | C-17 | 反应镜由 nice 升为 core，绑定在爽点之后 |
| S-06 | S-05 | 最后 5 s 收紧到 2–3 s，可以切在台词中途 |
| S-07 | S-02 | 10 s 收紧到 3–5 s，并要求立刻加码 |
| S-08 | S-06 + C-11 | 句长收紧，潜台词改写成「指控或揭示」 |
| S-09 | S-03 + S-07 | 合并，时间提前到 5 s / 15 s |
| S-10 | 新增 | 爽点逐级加码 |
| C-01 | C-01 | 删除建立镜要求，以 MCU/CU 为主 |
| C-02 | C-02 + C-18 | 合并视线追踪 |
| C-07 | C-07 | 删除「先给无声双人镜」 |
| C-14 / C-15 / C-16 | C-16 / C-19 / C-20 | 插入镜限定为证据；删除氛围和情绪淡出 |
| 其余 C | 对应的 v0 条目 | 例子改成中英两套，并删掉慢节奏的写法 |
