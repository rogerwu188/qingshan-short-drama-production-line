#!/usr/bin/env python3
"""V65 rigid head rotation with early counterturns; local-only and zero-cost."""
from __future__ import annotations
import json, math
from pathlib import Path
import cv2
import numpy as np
import render_e40_u29c_v58_articulated_head as base
import render_e40_u29c_v61_editorial_survival_head as v61

FAILURE_MEMORY_SHA256="6d1636e613e3f22d5f26efb6b8f52a7bed54bcb39e195d5c4649c4fa6f177db0"
SPEC_SHA256="ce9f26e6c28d3f52ba3e3774b9398b903d872c3940145e72f4a2f4f39f1a69c5"
ORIGINAL_SPLIT=base.split_layer

def split_layer(layer,which):
    body,head,meta=ORIGINAL_SPLIT(layer,which); degrees=15.0 if which=="jiaotu" else 10.5
    meta["nominal_shear"]=(-1.0 if which=="jiaotu" else 1.0)*math.tan(math.radians(degrees)); meta["equivalent_degrees"]=degrees
    return body,head,meta

def rotate_premultiplied_rgba(layer,signed_tangent,pivot_y):
    h,w=layer.shape[:2]; pivot_x=174.0 if w==316 else 126.0
    angle=math.degrees(math.atan(signed_tangent)); alpha=layer[:,:,3].astype(np.float32)/255.0; prem=layer[:,:,:3].astype(np.float32)*alpha[:,:,None]
    matrix=cv2.getRotationMatrix2D((pivot_x,pivot_y),angle,1.0)
    wa=cv2.warpAffine(alpha,matrix,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=0.0)
    wp=cv2.warpAffine(prem,matrix,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=(0.0,0.0,0.0)); wa=np.clip(wa,0.0,1.0)
    rgb=np.zeros_like(wp); valid=wa>1e-5; rgb[valid]=wp[valid]/wa[valid,None]
    return np.dstack([np.clip(np.rint(rgb),0,255).astype(np.uint8),np.clip(np.rint(wa*255),0,255).astype(np.uint8)])

def articulation_amplitudes(seconds):
    j=v61.smooth_track(seconds,((0,.0),(.14,.55),(.29,.15),(.44,.80),(.59,.28),(.74,1.0),(.89,.42),(1.04,.86),(1.18,.55),(1.34,.92),(1.54,.52),(1.78,.87),(2.06,.43),(2.29,.79),(2.57,.36),(2.83,.71),(3.11,.30),(3.34,.65),(3.62,.25),(3.81,.58),(4,.39)))
    y=v61.smooth_track(seconds,((0,.0),(.11,.36),(.26,.08),(.41,.63),(.56,.22),(.71,.88),(.83,1.0),(.97,.37),(1.12,.82),(1.29,.49),(1.48,.91),(1.71,.44),(1.98,.81),(2.24,.34),(2.52,.73),(2.77,.29),(3.04,.67),(3.31,.23),(3.55,.61),(3.76,.31),(4,.52)))
    return j,y

def main():
    args=base.parser().parse_args(); base.EXPECTED["failure_memory"]=FAILURE_MEMORY_SHA256; base.EXPECTED["spec"]=SPEC_SHA256
    base.split_layer=split_layer; base.warp_premultiplied_rgba=rotate_premultiplied_rgba; base.articulation_amplitudes=articulation_amplitudes
    report=base.render(args); a=report["articulation"]
    passed=report["frame0_raw_rgb_exact"] and report["audio_stream_count"]==0 and 14.7<=a["jiaotu_peak_equivalent_degrees"]<=15.1 and 10.2<=a["yunyang_peak_equivalent_degrees"]<=10.6 and a["opposite_signed_shears"] and a["body_layers_fixed"]
    report.update({"schema":"qingshan.e40.u29c.v65.rigid_head_rotation_render_report.v1","status":"PASS_RENDER_PENDING_ORIGINAL_RESOLUTION_AND_AGENTCUT_PARITY_QA" if passed else "FAIL_CLOSED","renderer_sha256":base.sha256(Path(__file__).resolve()),"predecessor_failure_memory_sha256":FAILURE_MEMORY_SHA256,"material_change":"rigid rotation replaces shear; different early counterturns break V64 0.375-1.083 low-motion window"})
    base.atomic_json(args.report,report); print(json.dumps({"status":report["status"],"output":report["output"],"sha256":report["output_sha256"]})); return 0 if passed else 2
if __name__=="__main__": raise SystemExit(main())
