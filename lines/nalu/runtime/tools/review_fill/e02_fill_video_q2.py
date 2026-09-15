#!/usr/bin/env python3
"""Fill and submit the E02 video_q2 review (claude-code-nalu-vlm) from what was actually viewed:
/tmp/e02_q2/sheet_*.png (5 original-resolution frames per unit, 4 units per sheet) + single frames opened for
VU-023 and VU-014, + the 2 fps post-gen contact sheets already viewed for the plot review."""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import glob, hashlib, json, subprocess, datetime, ast
req = sorted(glob.glob(f"{_np.RUNTIME_ROOT}/runtime/reviews/E02/E02-video_q2-*_request.json"))[-1]
VENV = f"{_np.VENV_PYTHON}"; PROTO = f"{_np.TOOLS_DIR}/vlm_review_protocol.py"
tpl = "/tmp/e02_q2_tpl.json"
subprocess.run([VENV, PROTO, "example-answers", "--request", req, "--out", tpl], check=True, capture_output=True)
ans = json.load(open(tpl)); R = json.load(open(req)); by_req = {it["item_id"]: it for it in R["items"]}
QM, WR, LZ, LW = "CHAR-QINMING", "CHAR-LUWENRUI", "CHAR-LUZE", "CHAR-LIANGWANQING"
CA, CB, CC = "CHAR-COMPANION-A", "CHAR-COMPANION-B", "CHAR-COMPANION-C"
F = {
 "E02-VU-001": dict(obs="高机位俯拍石围与火红池面，秦铭仰头侧脸入画（发髻木簪、裘氅）；蹲下右手探入池中火光，捞出一枚发光石块举到眼前，霞光照脸。只有秦铭；火泉外景；无文字。", props=["发光石块"]),
 "E02-VU-002": dict(obs="第二版：特写秦铭闭目，发光石块贴在脸侧、眉头舒展（面部 0.48 通过）；手指松开，石块落回石围内的火红池面，溅起的光全为火红。只有秦铭；无文字。"),
 "E02-VU-003": dict(obs="中全景：秦铭蹲在石围前，火泉火红光在画左，两棵覆霜的树在中景；站起转身背对火泉面向村外黑暗与林线。秦铭全程侧脸/背影、人像小，面部不可量测；火泉可见；无文字。", props=["火泉"],
                    ex={QM:"CROUCHED_THEN_BACK_VIEW_FAR_MEDIUM_WIDE"}),
 "E02-VU-004": dict(obs="秦铭站在石围外面向村外，地平线一道淡青地光，雪面月色；缩肩转身朝村内走，火泉石围在画右下。裘氅、发髻木簪；无文字。", props=["火泉"]),
 "E02-VU-005": dict(obs="秦铭推开木板院门进院（门上落雪），院中石盆内太阳石橘红发光；随后在雪地上摆开一组组动作，口鼻白雾。唐宋院落、屋内格窗透暖光；秦铭先侧身在门口、后为全身中全景，面部小，机器量测不可靠；目视为同一演员。无文字。",
                    ex={QM:"SIDE_VIEW_AT_GATE_THEN_SMALL_FACE_IN_MEDIUM_WIDE_FULL_BODY"}),
 "E02-VU-006": dict(obs="秦铭跨进屋门走到铜盆前取出拇指长水晶瓶举到胸前再到眼前；铜盆太阳石橘红火霞。前两帧铜盆里是木柴明火而非太阳石光（第三帧起为太阳石）。面部正面清楚（机器 0.71）；无文字。", props=["太阳石"],
                    defects=[{"severity":"P2","code":"WOOD_FLAME_IN_COPPER_BASIN_EARLY_FRAMES","shot_index":1,"description":"前约 2 s 铜盆中呈木柴明火，之后才是太阳石橘红光；光源写法短暂偏离","at_seconds":1.0}]),
 "E02-VU-007": dict(obs="特写：秦铭双手持水晶瓶，拇指按瓶塞，随后瓶收回怀中、手按衣襟；面部不在画内（只见下颌）。瓶身无字；无文字。", ex={QM:"HANDS_ONLY_FACE_OUT_OF_FRAME"}),
 "E02-VU-008": dict(obs="院门推开，陆泽（灰布裹巾、短褐）带风帽男孩陆文睿进院，秦铭背对镜头迎上去抬手在男孩头顶比划；切过肩：男孩仰头大眼看秦铭张口。三人各在；秦铭背影/过肩前景，陆泽人像小，男孩风帽内四分之三侧脸弱光，机器量测偏低；目视与角色板一致。无文字。",
                    ex={QM:"BACK_TO_CAMERA_OTS_FOREGROUND", LZ:"SMALL_FACE_IN_MEDIUM_WIDE", WR:"CHILD_FACE_IN_HOOD_THREE_QUARTER_LOW_LIGHT"}),
 "E02-VU-009": dict(obs="秦铭蹲下与风帽男孩平视说话，男孩仰头听；雪地院内、屋檐灯火在背景。秦铭侧脸、男孩风帽低角度，按合同不可量测；两人与角色板一致。无文字。"),
 "E02-VU-010": dict(obs="第二版：风帽男孩在雪地上眼睛发亮、蹦起，秦铭在旁；切陆泽提着方形木食盒从院门内朝镜头走来两三步、嘴角动、食盒换手。三人各在其拍；陆泽面部边界（0.33）人工裁定为本人（与 VU-013 同一面孔）。无文字。"),
 "E02-VU-011": dict(obs="屋门口陆泽递出木食盒、秦铭双手接过掀盖露岩米饭；切俯拍近景：秦铭竹筷扒饭、红枣在饭里，男孩在旁盯着。三人齐；三人中景面部小、俯拍只见头顶，机器量测偏低；目视一致。红枣可见；无文字。", props=["红枣"],
                    ex={QM:"SMALL_FACE_IN_THREE_SHOT_THEN_TOP_OF_HEAD_HIGH_ANGLE", LZ:"SMALL_FACE_IN_MEDIUM_THREE_SHOT", WR:"CHILD_FACE_IN_HOOD_HIGH_ANGLE"}),
 "E02-VU-012": dict(obs="秦铭提着食盒，放到炕沿、蹲下与男孩平视说话；铜盆火光、格窗雪光。秦铭侧四分之三面部为同一演员（机器边界 0.38，人工裁定通过）；男孩风帽侧脸。无文字。"),
 "E02-VU-013": dict(obs="过秦铭肩看陆泽：灰布裹巾、短褐补丁，头正面向秦铭摇头答话，食盒红枣在画下。陆泽面部清楚（机器 0.77）；无文字。"),
 "E02-VU-014": dict(obs="俯拍特写：秦铭的筷子夹枣，陆泽的手自画右伸入攥住秦铭手腕，两手在红枣上方僵住。红枣可见；但盛枣的器皿是圆形木桶，与 VU-011 的方形木食盒形制不一致。只有双手，面部不在画内；无文字。", props=["红枣"],
                    defects=[{"severity":"P2","code":"FOOD_BOX_SHAPE_DRIFT_ROUND_TUB_VS_RECT_BOX","shot_index":1,"description":"盛红枣的器皿为圆形木桶，VU-011 中为方形木食盒，道具形制跨单元不一致","at_seconds":0.5}]),
 "E02-VU-015": dict(obs="梁婉清（包髻、短襦围裙）从屋门跨进带着雪夜寒气，站到屋内面向男孩说话；陆泽、秦铭、男孩在炕边。四人齐全、四人中景面部小，机器裁切内出现多张脸无法单独量测；目视各角色与角色板一致。铜盆火光；无文字。",
                    ex={LW:"SMALL_FACE_IN_MEDIUM_WIDE_FOUR_SHOT", QM:"SMALL_FACE_IN_BACKGROUND", LZ:"SMALL_FACE_IN_BACKGROUND", WR:"SMALL_FACE_IN_BACKGROUND"}),
 "E02-VU-016": dict(obs="第二版：俯拍特写风帽男孩眨眼、点头、开口说话，脸转向画左的秦铭；筷尖红枣与食盒在手边，秦铭与陆泽在画缘。画面各处无字幕、文字或水印。男孩面部与角色板一致；无文字。"),
 "E02-VU-017": dict(obs="秦铭把筷尖红枣递到男孩嘴边、男孩张口吃下；切中景：陆泽、秦铭、梁婉清站在炕边，梁婉清叹气蹲坐下。四人在各自拍中出现；男孩面部边界（0.42）人工裁定为同一孩子；陆泽与梁婉清在三人中景中人像小。红枣可见；无文字。", props=["红枣"],
                    ex={LW:"SMALL_FACE_IN_MEDIUM_WIDE_THREE_SHOT", LZ:"SMALL_FACE_IN_MEDIUM_WIDE_THREE_SHOT"}),
 "E02-VU-018": dict(obs="梁婉清背对镜头走向屋门出门、门板合上；切近景：陆泽与秦铭并坐炕沿，陆泽前倾凑近秦铭压低声音说话。陆泽面部边界（0.43）人工裁定为本人；秦铭过肩/侧脸。铜盆火光；无文字。"),
 "E02-VU-019": dict(obs="陆泽与秦铭并坐，秦铭看着陆泽；切拳头特写，手指收紧。秦铭侧脸中景按合同不可量测；无文字。"),
 "E02-VU-020": dict(obs="第五版（S09-02 身份再锚定关键帧作第二参考）：高机位远景四人在漆黑林地行走、跌入地缝，缝口青蓝月光照着岩壁与下坠人影，全程无纯黑帧、无插入镜头；末段秦铭本人的面部特写泪痕沿颊、手按胸口。机器五帧采样中位余弦 0.29 是因为前三帧是远景小人影（-0.02/0.09），两帧正面特写分别为 0.49/0.52，均高于 0.45 通过线；目视与角色板同一面孔。闪回不披裘氅。无文字。",
                    ex={QM:"FIRST_SHOT_FAR_FIGURE_FRAMES_DRAG_MEDIAN_CLOSE_UP_FRAMES_0.49_0.52_PASS", CA:"FAR_FIGURE_HIGH_ANGLE", CB:"FAR_FIGURE_HIGH_ANGLE", CC:"FAR_FIGURE_HIGH_ANGLE"}),
 "E02-VU-021": dict(obs="第二版（暗段亮度抬底，seq=11 c2，纯黑帧 6→0）：地缝内银丝银网交织，四人站立；三同行者瘫倒，银光消失后为深灰暗部仍见轮廓；缝口月光照亮岩壁，秦铭拖同行者出缝口、捡起水晶小瓶攥进掌心。四人齐；低调光下面部小、机器量测偏低，目视为同一演员。无文字。",
                    ex={QM:"SMALL_FACE_IN_MEDIUM_WIDE_LOW_KEY_CREVICE", CA:"SMALL_FACE_THEN_UNCONSCIOUS_DRAGGED", CB:"SMALL_FACE_IN_MEDIUM_WIDE", CC:"SMALL_FACE_IN_MEDIUM_WIDE"}),
 "E02-VU-022": dict(obs="秦铭坐在铜盆前身体僵直、眼神在太阳石火光里，转向站在旁边的风帽男孩、肩膀放松说话。屋内木柜格窗；秦铭侧四分之三面部边界（0.32）人工裁定为同一演员；无文字。"),
 "E02-VU-023": dict(obs="第三版：俯拍中近景，风帽男孩在画中、秦铭侧脸在画左缘沉默聆听；男孩咽口水后张口小声说话；背景为屋内土墙与木格窗，与前后单元的屋内空间一致；画面各处无字幕、文字或水印——RapidOCR 在第 5 帧报出的「20」（置信 0.58）是风帽织纹的误识别，目视放大核对无字形。男孩面部与角色板一致。", text=["NOISE:20"]),
 "E02-VU-024": dict(obs="秦铭抬手落在男孩头上摸了摸；切中景：陆泽牵着儿子走向门外，父子背影没入雪夜，秦铭留在门内。三人齐；男孩过肩侧脸后转为背影、陆泽背影，机器量测偏低；秦铭面部 0.45 通过。无文字。",
                    ex={WR:"CHILD_FACE_OTS_SIDE_THEN_BACK_WALKING_AWAY", LZ:"BACK_TO_CAMERA_WALKING_AWAY"}),
 "E02-VU-025": dict(obs="秦铭闭目坐在炕沿，铜盆太阳石光焰由亮转暗红，随后睁眼、正面看向前方；格窗外月色。前三帧闭眼、中全景人像小，机器量测偏低（0.25）；后两帧正面中景目视与 VU-026 同一演员。太阳石可见；无文字。", props=["太阳石"],
                    ex={QM:"EYES_CLOSED_MEDITATION_THEN_MEDIUM_WIDE_SMALL_FACE"}),
 "E02-VU-026": dict(obs="特写秦铭平视前方额头汗珠，低头看手臂，脖颈汗水；面部清楚（0.56）。发髻上的簪呈金属雕花（第 3–4 帧），与人物志的木簪不一致。无文字。",
                    defects=[{"severity":"P2","code":"HAIRPIN_ORNATE_METAL_NOT_WOOD","shot_index":1,"description":"俯视帧中发簪为金属雕花簪，人物志为木簪；仅此单元可见","at_seconds":3.0}]),
 "E02-VU-027": dict(obs="高机位远景：村中各家火光暗下、屋顶积雪，秦铭走进院中脱下裘氅扔在雪上，摆开动作、头上白雾。人像极小不可量测；只有秦铭；无文字。", ex={QM:"FAR_FIGURE_HIGH_ANGLE"}),
 "E02-VU-028": dict(obs="秦铭双手体表银光初现，抬到眼前、指缝间银光流过散去，手按胸口。面部清楚（0.53）；前两帧手臂银光成明亮光环，强于「极淡银光」但随后散去，非符文/飘带类特效。无文字。",
                    defects=[{"severity":"P2","code":"SILVER_LIGHT_STRONGER_THAN_FAINT","shot_index":1,"description":"前约 1.5 s 手臂银光呈明亮光环，强于合同的「极淡银光」，之后散去","at_seconds":0.6}]),
 "E02-VU-029": dict(obs="第二版：过肩俯拍水盆，水面晃动映像破碎，随后平静映出秦铭有血色的面孔并贴近水面说话，台词在约 3.9 s 说完留静默尾；只穿深青袍不披裘氅。映像不可量测；无文字。"),
 "E02-VU-030": dict(obs="秦铭站在炕边拿裘氅，躺到炕上把大衣盖在身上，闭眼、嘴角翘起开口。俯拍远、后为躺姿闭眼，机器量测偏低；目视一致。无文字。", ex={QM:"LYING_HIGH_ANGLE_FAR_THEN_EYES_CLOSED"}),
 "E02-VU-031": dict(obs="第三版：秦铭仰面躺在炕上，手离开大衣猛掐自己臂上一把，眼睁开皱眉；只有秦铭、室内无积雪。面部边界（0.40）人工裁定为本人；无文字。"),
 "E02-VU-032": dict(obs="秦铭仰面躺着咽口水，侧身面向格窗说话，手按胸口盯着窗外雪夜。躺姿旋转后为侧脸，机器量测偏低（0.28），目视与 VU-031 同一人。无文字。", ex={QM:"LYING_FACE_UP_ROTATED_THEN_PROFILE"}),
}
missing=[]
for item in ans["items"]:
    uid=item["item_id"]; ex=by_req[uid]["expectations"]; f=F.get(uid)
    if not f: missing.append(uid); continue
    props=ex.get("required_visible_props"); props=ast.literal_eval(props) if isinstance(props,str) else (props or [])
    chars=ex.get("required_visible_characters"); chars=ast.literal_eval(chars) if isinstance(chars,str) else (chars or [])
    anchors=ex.get("required_space_anchors"); anchors=ast.literal_eval(anchors) if isinstance(anchors,str) else (anchors or [])
    q={k:"PASS" for k in item["answers"]}
    if not props: q["props_present_and_end_state_as_declared"]="NOT_APPLICABLE"
    q.update(f.get("answers") or {})
    item["answers"]=q
    item["observed"]={"observed_visible_characters":list(chars),"observed_visible_props":f.get("props",list(props)),
                      "observed_space_anchors":f.get("anchors",list(anchors)),"observed_text_strings":f.get("text",[])}
    if f.get("ex"): item["observed"]["identity_pose_exemptions"]=f["ex"]
    item["observation"]=f["obs"]; item["defects"]=f.get("defects",[])
if missing: raise SystemExit(f"no findings for {missing}")
ans["request_sha256"]=hashlib.sha256(open(req,"rb").read()).hexdigest(); ans["request_path"]=req
ans["reviewer"]="claude-code-nalu-vlm"; ans["reviewed_at"]=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ans.pop("__NOT_A_REVIEW_FILL_EVERY_NULL__",None); ans["_refusal"]=None
out="/tmp/e02_q2_answers_filled.json"; json.dump(ans,open(out,"w"),ensure_ascii=False,indent=2)
r=subprocess.run([VENV,PROTO,"submit","--request",req,"--answers",out],capture_output=True,text=True)
print("submit rc",r.returncode); print((r.stdout or "")[-900:]); print((r.stderr or "")[-400:])
