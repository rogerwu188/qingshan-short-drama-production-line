# H3 剧本改编指南（写手用）

适用：MiniMax-H3 出视频的集，写手（Codex）写四层文件时读。不加任何门禁，只是导演写法；
写错了引擎不会拦，只会花钱拍出错的画面。配套：`WRITER_CONTRACT.md` 的 Camera grammar 一节（CAMERA_GRAMMAR_V1）。

## 1. H3 能拍什么、不能拍什么

能拍：真人实景的一个连续镜头——1～2 个人在一个空间里做一件事、说一两句话；一个物件的特写插入镜；
一个有形体的非人存在（怪物、雕像、无脸人形）在画面里站着、转头、走几步。

拍不好：
- 抽象图形、文字、数字、发光点阵、界面——H3 一律当成「真人短剧」去拍，会自己加人、加手。
- 复杂特效：时代流转的延时、走廊不断复制、形体变形、分屏。
- 三人以上同框、人群、群众背景——人数和身份会漂。
- 只用文字点名、没写长相的角色——H3 会照着画面里别人的衣服去编（E01 仲裁者穿上了神父的长袍）。
- 「镜头一转，对面那个人」——一个单元里写两个机位，H3 只会用一次运镜把两拍糊在一起。

## 2. 每一拍先分桶

| 桶 | 判断 | 怎么写 |
|---|---|---|
| ① H3 拍 | 真人、真物、真空间，一个机位说得清 | 正常写镜头 |
| ② 纯 2-D 图形/文字 | 点阵、数字、地图、标题、界面、信件内容 | 不做 H3 单元：并进已有的片头标题卡/片尾卡，或写成字幕；画面上只拍能拍的实物（拿信的手不算，见 §6） |
| ③ 复杂特效 | 延时跨时代、空间复制、变形 | 改写成能拍的镜头：几条不同走廊的快切、同一扇门前三个时段各一镜、变形前后各一镜硬切 |

不新增渲染路径或后期图形流程；②只能落到现有的片头/片尾卡和字幕。

## 3. 人数与登记

- 一个单元最多 2 个可见人物（生物卡也算一个）。第三个人要么出画、要么另起单元。
- 没有人脸的可见存在（怪物、雕像、机器、无五官人形）登记成 `non_character_entities`：
  `kind: "CREATURE"`（动物 `ANIMAL`），带 `creature_card{locomotion, eye_color, silhouette_ref}`，
  `note` 用一句话写清长相（身高、形体、材质、颜色、脸是什么样），英文剧写英文。
  这样渲染器把它当「主体」而不是「道具」，并把 `note` 原文交给 H3。不要列进 `character_entities`（S3 测不到脸）。
- 真道具（本子、铅笔、灯）照常写 props。

## 4. 服装与长相写成文字

- 每个可见人物的服装要在作者层服装描述（asset_requirements 的 WARD-* 行）或
  `character_entities[].appearance_ch1` / `wardrobe_garments` 里写成一句完整的话：颜色、款式、材质、领口、鞋。
  英文剧写英文——渲染器只转交英文，中文描述不会进 H3 提示词。
- 两个主体的服装材质、颜色要能一眼分开（神父黑袍白领 vs 仲裁者哑光黑曜石躯体、无衣物）。
  渲染器会加一句「各穿各的，不互相转移衣服、领子、手、材质」。
- **人物特征只写在人物自己的字段里**：场景级字段（`scenes[].lighting`、`weather`、`palette`、环境声）只写光和环境，
  不写任何人的伤疤、残肢、发型、年龄、服装（K056）。场景字段会进入这一场的每一个单元：反例「阴天自然光，肤色与右脸旧伤可辨」
  让一场戏里所有人、连船上的另一场人物都带上「右脸旧伤」。要强调某人的特征，写进他的 `appearance_ch1` 或那一镜的 action。
- **每个人物只有一个英文名，全集一致**：H3 英文翻译里的称呼必须和人物登记的英文名一致（cast_roster 用的那个），不要一处
  「Liwei Adult」一处「Adult Li Wei」。身份/职务要意译成英文（特工 → the agent，老师 → Teacher Wu），不要拼音（Te Gong、Wu Laoshi）。
- **台词的情绪写成一句英文**：对白镜加 `action.performance.delivery_en`（可选），一句话写情绪 + 怎么说，如
  `"cold and contemptuous, low and clipped, a beat of silence before the second sentence"`。H3 不收中文，中文的 `delivery`
  到不了模型；不写时只有常见 `emotion` 单字（厌/怒/冷/疑/急/惊…）会被译成形容词，否则只剩通用的「清晰、偏快」一句，听着像念稿。
  要写出声音的走向：重读哪个词、哪里扬起、哪里压低到近乎耳语、哪里突然大声、哪里停顿；只写「冷淡」「生气」起伏不够。
- **残缺与显眼的身体特征要写硬**（实验集：设定缺右臂的老师，大部分镜头被画回了两只手）：在人物外观、服装和每一镜动作里
  都写同一句——缺什么、空袖/伤疤怎么呈现（"right arm missing from the shoulder, empty right sleeve folded flat and tucked
  into the belt"）；该人物的动作只用剩下的那只手，避免「双手」「拍手」「抱臂」这类会让模型补出肢体的词；
  能用构图避开的就避开（侧向健全一侧、中近景）。

## 5. 景别、机位与切

- 景别跟内容走：两个人隔着一条石拱廊远远对望 = `WIDE` / `MEDIUM_WIDE`，不是 `EXTREME_CLOSE_UP`；
  特写只给一张脸、一只手、一个物件。
- 「忽然就在那里」、视角换到另一个人、换景别 = 一次切 = 另起一个单元，
  `internal_transition_authoring` 写 `REACTION_CUT` / `MOTIVATED_CUT` / `HARD_CUT`。
- **对白戏不要每句一切**（线主 2026-10-23：人拍的电影不会逐句切）。一个 H3 单元仍只有一个说话人（引擎硬规则），但：
  ① **同机位接力**：两人一来一回的连续几句，用**同一个双人镜**（两人都在画面里，`camera_side` / `shot_scale` /
  `camera_height` 不变），每句一个单元，彼此写 `CONTINUOUS_ACTION`——下一单元从上一单元真实尾帧接着拍，
  看起来是一条长镜头，只是说话的人在换。
  ② **景别节奏**：一场对白从双人镜/中景开场；只在情绪转折处切近到单人镜/近景（`REACTION_CUT` / `MOTIVATED_CUT`）；
  最狠的那句给最紧的镜头；同一个人连着说的几句留在同一个镜头里；听者的无声反应只在「反应本身就是戏」时才切过去。
  ③ **声音桥（L-cut）**：说话镜后面紧跟一个无对白反应镜时，可在反应镜写
  `prompt_spec.transition.sound_bridge_from_previous_seconds`（0.3–2.0 s）：S7 把说话人的画面提前这么多秒切走，
  他这句话的声音（和字幕）继续盖在反应镜开头，反应镜自己的现场声压成环境声。只对 CAMERA_GRAMMAR_V1 的集、
  且两镜分属相邻两个单元时生效；不写 = 照旧硬切。
- 机位要变的地方，一个单元只放一拍。一个单元两拍只适合同一机位里的连续动作。

**对白戏示例**（两人，5 镜，转折在第 4 句）：
1. `MEDIUM_WIDE` 双人镜，A 说第 1 句（开场，`MOTIVATED_CUT` 或场景切入）。
2. 同一双人镜，B 回第 2 句（`CONTINUOUS_ACTION`，同机位接力）。
3. 同一双人镜，A 说第 3 句（`CONTINUOUS_ACTION`）。
4. `CLOSE_UP` B 单人，最狠的第 4 句（`MOTIVATED_CUT`，转折才切近）。
5. `MEDIUM_CLOSE_UP` A 无对白反应（`REACTION_CUT`，`prompt_spec.transition.sound_bridge_from_previous_seconds: 0.8`，
   B 的话尾盖在 A 的脸上）。
- 运镜要有动机（#121）：跟人、揭示、强调、主观视角；否则 `LOCKED` 或慢推。
  不要写「Framing changes with the camera motion.」这类空话当 `end_framing`——写清落幅是谁、多大、在画面哪里。
- **关键帧的取景要写成画面范围**（实验集 2026-10-22：中近景被生图画成站立全身「定妆照」）：`start_framing` 写清从哪里截
  （"framed from mid-chest up"、"head and shoulders"、"seated behind the desk, waist up"）和人在做什么、看向谁；
  不写成正面站立直视镜头。同一场连续几镜的构图要有变化（角度、高低、前景）。
- **对白镜不留空**（线主 2026-10-23：H3 会用乱码般的「像英文但不是英文」的话填满台词说完后的时间）：对白镜 `target_seconds` = 台词说话时长 + 0.5–1.0 s（中文约 4 字/秒，英文约 2.5 词/秒）；不要给对白镜加长，需要停顿、反应就另写一个无对白的反应镜。S7 也会把每个对白单元剪在最后一句说完后约 0.5 s，多给的时长只会被剪掉。

## 6. 避开人群和手

- 不写背景路人、围观、人群；空间里的生命感用风、光、灰尘、火苗表达。
- 「手」最容易被 H3 凭空加出来：插入镜不写「手拿着」「手指划过」，除非这只手属于本单元登记的人物且该人物在 cast 里。
- 渲染器会对有人的单元加名单句：「只有 A 和 B；画面任何位置（含背景与画边）不出现其他人、人影、手或身体部位」；
  对无人无生物的插入镜改写为「一个实拍物件插入镜，无人、无手、无身体部位」。剧本要和这两句一致，别写矛盾的东西。

## 7. 反面 → 正面（Twelve Gazes E01）

**VU-011（坏）**：一个单元两拍——Elias 抬头；反打：仲裁者转头。仲裁者登记成道具，长相没写；
没写任何人的服装；机位 `EXTREME_CLOSE_UP + TRACK LEFT_TO_RIGHT`，两人隔着石拱廊远远相对；
`end_framing` = "Framing changes with the camera motion."
结果：H3 给仲裁者穿上了 Elias 的长袍，长出银色的手。

**VU-011（好）**：
- 拆成两个单元。单元 A：`MEDIUM_WIDE`，`LOCKED`，Elias 在拱廊近端抬头望向远端；
  单元 B（`REACTION_CUT`）：`WIDE` 或 `MEDIUM`，慢推，仲裁者在拱廊尽头转头。
- 仲裁者：`kind: CREATURE`，`creature_card.locomotion: biped`，
  `note: "faceless 2.4 m two-armed matte-obsidian humanoid with a mirror-black oval face, no clothing"`。
- Elias 服装：`"a worn black cassock with a white clerical collar, black leather shoes"`。
- `end_framing` 写实：`"Elias small at the near end of the arch, the Arbiter's silhouette at the far end"`。

**VU-012（坏）**：「近黑底上一排十二个暗点，第一个亮起暗金色」做成 H3 单元，机位 CLOSE_UP + TRACK。
H3 当真人短剧拍，凭空加了好几双真人的手。

**VU-012（好）**：属于桶②。把十二个点做进片头标题卡（或字幕/片尾卡），不进 H3。
若剧情一定要实物，就拍一个能拍的物件——例如石墙上十二个烛台、第一支被点亮——
单元里没有人物，渲染器会按「实拍物件插入镜、无人无手」出提示词。

## 7b. 导演式提示词 DIRECTOR_PROMPT_V2（可选，线主 2026-10-23）

- **开关**：生成合同顶层写 `"h3_prompt_style": "DIRECTOR_PROMPT_V2"`。只有声明了的合同的 H3 单元换成 V2；
  没写（或写别的值）的集一字不变，仍是 `subject_definitions:` 那版 V1 提示词。分组编译把字段盖到 H3 单元上，
  交易任务带着它，付费边界按同一字段重渲染并逐字比对（「提示词必须是当前编译器的原样输出」不变）。
- **形状**：像导演给摄影和演员讲戏，依次是 References（每张参考图/每条参考音一句：开场画面 / X 的脸和身体 / X 的声音只取音色）、
  Who is in frame（"exactly these two people, each exactly once, both visible from the first frame to the last"
  这一句就是人数约束，逐人写画左画右、长相、服装；有人入画出画或只露手，就逐人写时段）、Setting、Camera、Action（每拍说话的人
  和听的人各做什么）、Dialogue（`<d>[Chinese] …</d>` 只出现一次 + delivery_en；说完后 "After the line nobody speaks"）、
  Sound（一行，"No background music"）、Never。不再出现内部 id、retention_analysis、Force origin/Interaction mode 模板、
  NO_BGM、"render at most one visible instance…" 之类机器句。一般 2–4k 字符（构图文字长的单元会更长）。
- **英文长相、服装、场景**：V2 单元的英文合同请求（`<EP>_H3_ENGLISH_CONTRACTS.REQUEST.json`）多一个 `director_v2` 块：
  只有中文的人物长相（appearance：脸、年龄、发型、体型）、服装（wardrobe）、生物外观（look）和一两句场景（setting：地点与布局，
  时间、天气、光另有字段）。英文剧已有英文字段的不会再要。
- **听者在做什么**（可选）：对白镜可写 `prompt_spec.action.listener_reaction_en`——一句英文，或按人物 id/英文名分别写
  （`{"CHAR-LINQIAO": "holds his gaze, jaw tight, lifts her chin on the second question"}`）。不写时默认
  「X listens without speaking, holding Y's gaze.」；无对白镜默认「X stays silent, watching Y.」。V1 提示词不读这个字段。
- 覆盖面不变：每条执行事实仍要在 V2 文本里找到对应句子（semantic coverage receipt）；只有微表情/身体同步模板和
  非打斗、无接触时刻的拍里的接触点/反馈模板改由「每个人在做什么」表达，回执里逐条列为 `style_omitted_fact_ids`。

## 8. 写完自查（不是门禁）

- [ ] 每一拍都分了桶；②③没有直接塞给 H3。
- [ ] 每个单元 ≤ 2 个可见主体；无脸存在登记为 CREATURE，`note` 写了长相。
- [ ] 每个可见人物服装写成英文（英文剧）一句话。
- [ ] 景别和人物距离对得上；突然出现、换景别都切开了；对白来回用同一双人镜 `CONTINUOUS_ACTION` 接力，只在转折处切近。
- [ ] 机位要变的单元只有一拍；运镜都有理由；`end_framing` 不是空话。
- [ ] 没有人群、路人；插入镜里没有无主的手。
