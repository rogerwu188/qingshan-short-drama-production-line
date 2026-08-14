#!/usr/bin/env python3
import argparse, copy, hashlib, json
from pathlib import Path

EXPECTED_SHOTS = ["U29A", "U29B", "U29C", "U29D"]
EXPECTED_COUNTS = [43, 43, 43, 63]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def validate(spec, root):
    errors = []
    sources = spec.get("sources", [])
    if [x.get("shot") for x in sources] != EXPECTED_SHOTS:
        errors.append("SOURCE_ORDER")
    counts = [x.get("end_frame_exclusive", 0) - x.get("start_frame", 0) for x in sources]
    if counts != EXPECTED_COUNTS:
        errors.append("FRAME_COUNTS")
    for source in sources:
        path = root / source.get("path", "")
        if not path.is_file() or sha256(path) != source.get("sha256"):
            errors.append("SOURCE_SHA:" + source.get("shot", "UNKNOWN"))
    out = spec.get("output", {})
    expected_out = {"container":"mp4","codec":"h264","profile":"High","level":41,"dimensions":[720,1280],"pixel_format":"yuv420p","fps":24,"sample_aspect_ratio":"1:1","time_base":"1/12288","frame_count":192,"duration_seconds":8.0,"audio_stream_count":0}
    for key, value in expected_out.items():
        if out.get(key) != value:
            errors.append("OUTPUT:" + key)
    policy = spec.get("policy", {})
    expected_policy = {"single_pass":True,"trim_before_normalize":True,"concat_order":EXPECTED_SHOTS,"cut_frames":[43,86,129],"pad_crop":False,"upscale":False,"frame_rate_conversion":False,"transition_frames":0,"audio_synthesis":False,"compile_allowed":False,"render_allowed":False,"assembly_allowed":False}
    for key, value in expected_policy.items():
        if policy.get(key) != value:
            errors.append("POLICY:" + key)
    return sorted(set(errors))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    spec = json.load(open(args.spec))
    root = Path(args.root).resolve()
    cases = [("CANONICAL", spec, True)]
    if args.self_test:
        mutations = []
        m=copy.deepcopy(spec); m["sources"][0]["sha256"]="0"*64; mutations.append(("WRONG_SOURCE_SHA",m))
        m=copy.deepcopy(spec); m["sources"][1]["end_frame_exclusive"]=44; mutations.append(("WRONG_FRAME_COUNT",m))
        m=copy.deepcopy(spec); m["output"]["dimensions"]=[1008,1792]; mutations.append(("UPSCALE_TARGET",m))
        m=copy.deepcopy(spec); m["output"]["pixel_format"]="yuv444p"; mutations.append(("YUV444P_OUTPUT",m))
        m=copy.deepcopy(spec); m["output"]["audio_stream_count"]=1; mutations.append(("ADDED_AUDIO",m))
        m=copy.deepcopy(spec); m["policy"]["transition_frames"]=1; mutations.append(("TRANSITION_FRAME",m))
        cases += [(name, value, False) for name, value in mutations]
    rows=[]
    for name, value, should_pass in cases:
        errors=validate(value,root); passed=not errors
        rows.append({"case":name,"expected":"PASS" if should_pass else "REJECT","actual":"PASS" if passed else "REJECT","errors":errors,"matched":passed==should_pass})
    result={"status":"PASS" if all(x["matched"] for x in rows) else "FAIL","cases":rows}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["status"]=="PASS" else 1)

if __name__ == "__main__": main()
