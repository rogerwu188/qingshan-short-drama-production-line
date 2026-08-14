#!/usr/bin/env python3
"""Pad a PCM WAV with silence to satisfy a platform minimum duration."""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--minimum-seconds", type=float, default=2.1)
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(params.nframes)
    target_frames = max(params.nframes, int(round(args.minimum_seconds * params.framerate)))
    silence_frames = target_frames - params.nframes
    silence = b"\0" * silence_frames * params.nchannels * params.sampwidth
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames + silence)
    print(json.dumps({
        "input": str(source),
        "output": str(output),
        "source_seconds": params.nframes / params.framerate,
        "output_seconds": target_frames / params.framerate,
        "silence_padding_seconds": silence_frames / params.framerate,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
