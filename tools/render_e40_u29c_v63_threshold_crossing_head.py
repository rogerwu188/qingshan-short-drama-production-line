#!/usr/bin/env python3
"""V63 1.5x articulated-head source after the preserved V62 cadence failure."""
from __future__ import annotations
import json, math
from pathlib import Path
import render_e40_u29c_v58_articulated_head as base
import render_e40_u29c_v61_editorial_survival_head as v61

FAILURE_MEMORY_SHA256 = "65abd1441d92ed6cbece254174ea0a58733cdaf8b63d2fdb132d9cbccf0fe0d9"
SPEC_SHA256 = "eb7f0931c036a1f62080643c51a660707fee9b5037ebe2fa76fe13897f4870a7"
ORIGINAL_SPLIT = base.split_layer

def split_layer(layer, which: str):
    body, head, metadata = ORIGINAL_SPLIT(layer, which)
    degrees = 15.0 if which == "jiaotu" else 10.5
    metadata["nominal_shear"] = (-1.0 if which == "jiaotu" else 1.0) * math.tan(math.radians(degrees))
    metadata["equivalent_degrees"] = degrees
    return body, head, metadata

def main() -> int:
    args = base.parser().parse_args()
    base.EXPECTED["failure_memory"] = FAILURE_MEMORY_SHA256
    base.EXPECTED["spec"] = SPEC_SHA256
    base.split_layer = split_layer
    base.articulation_amplitudes = v61.articulation_amplitudes
    report = base.render(args)
    a = report["articulation"]
    passed = report["frame0_raw_rgb_exact"] and report["audio_stream_count"] == 0 and 14.7 <= a["jiaotu_peak_equivalent_degrees"] <= 15.1 and 10.2 <= a["yunyang_peak_equivalent_degrees"] <= 10.6 and a["opposite_signed_shears"] and a["body_layers_fixed"]
    report.update({
        "schema": "qingshan.e40.u29c.v63.threshold_crossing_head_render_report.v1",
        "status": "PASS_RENDER_PENDING_ORIGINAL_RESOLUTION_AND_AGENTCUT_PARITY_QA" if passed else "FAIL_CLOSED",
        "renderer_sha256": base.sha256(Path(__file__).resolve()),
        "predecessor_failure_memory_sha256": FAILURE_MEMORY_SHA256,
        "material_change": "1.5x V61 peak articulation: 15/10.5 degrees; unchanged distinct smooth nonperiodic timings",
    })
    base.atomic_json(args.report, report)
    print(json.dumps({"status": report["status"], "output": report["output"], "sha256": report["output_sha256"]}))
    return 0 if passed else 2

if __name__ == "__main__": raise SystemExit(main())
