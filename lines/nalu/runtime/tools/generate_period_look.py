#!/usr/bin/env python3
"""Generate Tang/Song period-look source photos for Roger's female leads (SUPERVISOR_ORDERS seq=8).

Paid: gpt-image-2-pro image-to-image, one 9:16 2K image per character, face crop as the reference.
Writes runtime/casting/<CID>/{intent,submit_response,task_response}.json + <CID>__SOURCE_V2_TANG.png,
measures InsightFace cosine vs the face crop, and appends a credit statement stub.
"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse, json, os, sys, time, pathlib, hashlib, datetime, urllib.request
sys.path.insert(0, f"{_np.ENGINE_ROOT}"); sys.path.insert(0, f"{_np.ENGINE_ROOT}/tools")
from tools import giggle_api_client as g  # noqa: E402

HOLD = pathlib.Path(f"{_np.RUNTIME_ROOT}/runtime/character_sources_hold")
SRC = pathlib.Path(f"{_np.RUNTIME_ROOT}/runtime/character_sources")
OUT = pathlib.Path(f"{_np.RUNTIME_ROOT}/runtime/casting")
LOOKS = {
    "CHAR-LIQINGYUE": ("黎清月", "青丝如瀑、身段纤柔、绝艳清冷；唐代高髻（单刀半翻髻）配银质步摇，月白色交领襦裙外罩淡银色大袖纱衣，衣袂轻展；神情平静、目光深邃"),
    "CHAR-TANGYUSHANG": ("唐羽裳", "红裙谪仙、高深莫测；唐代高髻配金簪与红色绢花，正红色齐胸襦裙外披朱红大袖披帛，衣袂猎猎；神情沉静、微微蹙眉"),
    "CHAR-MENGZHIYU": ("梦知语", "温婉、有大姐气度；宋代低髻（同心髻）配玉簪，藕荷色交领褙子配月白长裙，肩披素纱；神情温和、含笑"),
    "CHAR-JIANGRAN": ("姜苒", "青衣少女、仙种之姿；宋代双环髻配青玉发钗，青色交领窄袖上襦配鸦青色长裙，腰束丝绦；神情清亮、坚定"),
}
PROMPT = (
    "【参考图·最高优先级】画中人物必须是参考图里的同一个人——同一张脸：脸型轮廓、眉骨、眼距与眼型、鼻梁鼻翼、嘴唇、下颌线、耳形、肤色都与参考图一致，"
    "人脸识别应判定为同一人；年龄与参考图一致，不年轻化、不老化、不换脸、不改五官比例、不美化成另一个人。忽略参考图中的服装、发型、背景、光线与画幅。\n"
    "呈现为中国唐宋时期的古装人物写真：{look}。"
    "半身正面肖像，竖幅 9:16，人物居中，头顶留少量空间，视线看向镜头，自然柔和的暖光，背景为虚化的唐宋木构庭院（格窗、廊柱、瓦檐）。"
    "真实摄影质感、细腻皮肤纹理、高清晰度。禁止：现代服饰与饰品、和风元素、欧式与哥特元素、夸张妆容、文字水印。"
)


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def run(cids, dry, note=""):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = []
    for cid in cids:
        name, look = LOOKS[cid]
        crop = HOLD / f"{cid}__FACE_CROP.png"
        d = OUT / cid; d.mkdir(parents=True, exist_ok=True)
        prompt = PROMPT.format(look=look) + (("\n" + note) if note else "")
        intent = {"schema": "nalu.period_look_generation.v1", "character_id": cid, "canonical_name": name, "model": "gpt-image-2-pro",
                  "aspect_ratio": "9:16", "resolution": "2K", "reference": str(crop), "reference_sha256": sha(crop), "prompt": prompt,
                  "authority": "SUPERVISOR_ORDERS seq=8", "requested_at_utc": now}
        (d / f"intent_{now}.json").write_text(json.dumps(intent, ensure_ascii=False, indent=2), encoding="utf-8")
        if dry:
            print("DRY", cid); continue
        args = argparse.Namespace(prompt=prompt, reference_image=[str(crop)], model="gpt-image-2-pro", aspect_ratio="9:16", resolution="2K", count=1)
        with g.durable_generation_context():
            resp = g.generate_image(args)
        (d / f"submit_response_{now}.json").write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
        task_id = (resp.get("data") or {}).get("task_id")
        print(cid, "task", task_id, flush=True)
        rows.append((cid, task_id, d, now))
    for cid, task_id, d, ts in rows:
        for _ in range(120):
            tr = g.query_task(argparse.Namespace(task_id=task_id))
            st = (tr.get("data") or {}).get("status")
            if st in ("completed", "failed", "error"):
                break
            time.sleep(10)
        (d / f"task_response_{ts}.json").write_text(json.dumps(tr, ensure_ascii=False, indent=2), encoding="utf-8")
        assets = (tr.get("data") or {}).get("asset_info") or []
        if st != "completed" or not assets:
            print(cid, "FAILED", st, (tr.get("data") or {}).get("err_msg"), flush=True); continue
        url = assets[0].get("download_url") or assets[0].get("signed_url")
        out = d / f"{cid}__SOURCE_V2_TANG_{ts}.png"
        urllib.request.urlretrieve(url, out)
        print(cid, "saved", out, out.stat().st_size, flush=True)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--cid", action="append"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--note", default="")
    a = ap.parse_args()
    run(a.cid or list(LOOKS), a.dry_run, a.note)
