#!/usr/bin/env python3
"""Build U08 V5 with captive-excluding blade geometry and cleaner fragments."""

from __future__ import annotations

import cv2
import numpy as np

import build_e36_u08_zero_credit_vfx_bridge_v3 as v3
import build_e36_u08_zero_credit_vfx_bridge_v4 as v4


def captive_excluding_mask() -> np.ndarray:
    mask = np.zeros((v3.HEIGHT, v3.WIDTH), np.uint8)
    cv2.fillPoly(mask, [np.array([
        (0, 0), (445, 0), (470, 170), (455, 360), (390, 565), (225, 550), (0, 495),
    ], np.int32)], 255)
    cv2.fillPoly(mask, [np.array([
        (285, 0), (395, 0), (420, 155), (460, 355), (565, 650),
        (500, 705), (430, 520), (375, 305),
    ], np.int32)], 255)
    return cv2.GaussianBlur(mask, (0, 0), sigmaX=9, sigmaY=9)


def clean_fragment_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    raw = ((hsv[:, :, 1] < 88) & (hsv[:, :, 2] > 158)).astype(np.uint8) * 255
    raw[:70, :] = 0
    raw[760:, :] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
    kept = np.zeros_like(raw)
    for label in range(1, count):
        _, _, width, height, area = stats[label]
        if 7 <= area <= 1300 and width <= 105 and height <= 125:
            kept[labels == label] = 255
    kept = cv2.dilate(kept, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.GaussianBlur(kept, (0, 0), sigmaX=1.0, sigmaY=1.0)


def main() -> None:
    v3.overlay_mask = captive_excluding_mask
    v4.fragment_mask = clean_fragment_mask
    v4.OUT_DIR = v4.ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v5"
    v4.OUT = v4.OUT_DIR / "E36_U08_ZERO_CREDIT_CAPTIVE_EXCLUDING_PAPER_IMPACT_BRIDGE_V5.mp4"
    v4.CONTACT = v4.QA_DIR / "E36_U08_V5_8FPS_DIRECT_TEMPORAL_CONTACT.jpg"
    v4.MANIFEST = v4.QA_DIR / "E36_U08_V5_CAPTIVE_EXCLUDING_PAPER_IMPACT_MANIFEST.json"
    v4.SCHEMA = "qingshan.e36.u08_source_native_captive_excluding_paper_impact_bridge.v5"
    v4.SOURCE_CL2X = "CL2X-923"
    v4.METHOD = "SOURCE_NATIVE_MOVING_ROTOSCOPE_WITH_CAPTIVE_EXCLUDING_BLADE_MASK_PLUS_MOVING_PAPER_FRAGMENTS; NO_STILL_TO_MOTION; NO_GENERATIVE_PIXELS"
    v4.main()


if __name__ == "__main__":
    main()
