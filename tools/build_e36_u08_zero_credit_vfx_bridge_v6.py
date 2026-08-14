#!/usr/bin/env python3
"""Build U08 V6 with paper-chaos terminal footage and no visible true captive."""

from __future__ import annotations

import cv2

import build_e36_u08_zero_credit_vfx_bridge_v3 as v3
import build_e36_u08_zero_credit_vfx_bridge_v4 as v4
import build_e36_u08_zero_credit_vfx_bridge_v5 as v5

BASE_RENDER = v4.render_frames


def paper_chaos_terminal_frames():
    initial = BASE_RENDER()
    paper = v3.read_all(v4.U05)
    output = initial[:30]
    for index in range(30, v3.FRAME_COUNT):
        if index < 39:
            left = output[-1]
            target_index = min(4 + (index - 30) * 2, len(paper) - 1)
            right = paper[target_index]
            mix = (index - 29) / 10.0
            frame = cv2.addWeighted(left, 1.0 - mix, right, mix, 0)
            frame = cv2.GaussianBlur(frame, (0, 0), sigmaX=max(0.0, 2.4 * (1.0 - abs(mix - 0.5) * 2.0)))
        else:
            source_index = min(22 + (index - 39), len(paper) - 1)
            frame = paper[source_index].copy()
        output.append(frame)
    return output


def main() -> None:
    v3.overlay_mask = v5.captive_excluding_mask
    v4.fragment_mask = v5.clean_fragment_mask
    v4.render_frames = paper_chaos_terminal_frames
    v4.SECOND_AUDIO = v4.U05
    v4.OUT_DIR = v4.ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v6"
    v4.OUT = v4.OUT_DIR / "E36_U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_BRIDGE_V6.mp4"
    v4.CONTACT = v4.QA_DIR / "E36_U08_V6_8FPS_DIRECT_TEMPORAL_CONTACT.jpg"
    v4.MANIFEST = v4.QA_DIR / "E36_U08_V6_PAPER_CHAOS_TERMINAL_MANIFEST.json"
    v4.SCHEMA = "qingshan.e36.u08_source_native_paper_chaos_terminal_bridge.v6"
    v4.SOURCE_CL2X = "CL2X-923"
    v4.U05_ROLE = "moving_white_paper_fragment_layer_from_first_frame_and_full_post_impact_paper_chaos_terminal"
    v4.METHOD = "SOURCE_NATIVE_MOVING_EXECUTIONER_AND_PAPER_DUMMY_IMPACT_PLUS_SOURCE_NATIVE_FULL_PAPER_CHAOS_TERMINAL; CAPTIVE_EXCLUDING_MASK; NO_STILL_TO_MOTION; NO_GENERATIVE_PIXELS"
    v4.main()


if __name__ == "__main__":
    main()
