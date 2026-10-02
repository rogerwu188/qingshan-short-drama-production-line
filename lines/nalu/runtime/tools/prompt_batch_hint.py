#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_batch_hint.py — bounded, order-preserving per-unit parallelism for nalu batch tools.

The batch tools that walk every video unit (S6 prompt finalisation, post-generation QA, Q2) all
share one shape: a pure per-unit function whose results are collected and then emitted in the
caller's own order so a JSON digest stays byte-identical to the serial run.  This mirrors the
``parallel_map`` + ``ThreadPoolExecutor`` pattern already used in
``lines/nalu/runtime/tools/post_generation_qa_runner.py`` and ``video_q2_builder.py`` so the three
tools have one implementation instead of three copies.

Exceptions: the default ``parallel_map`` propagates the first unit's exception exactly as a serial
loop would; ``never_raise`` wraps a per-unit function so one unit's failure becomes a recorded row
instead of aborting the whole batch (a review digest must still name every other unit's result).
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

#: bounded per-unit parallelism.  Every unit's work is independent (it reads its own prompt files
#: and writes nothing shared); results are keyed so the caller emits them in its own order.
DEFAULT_UNIT_WORKERS = 4


def unit_workers(default: int = DEFAULT_UNIT_WORKERS) -> int:
    """NALU_QA_WORKERS=1 restores strictly sequential execution."""
    try:
        return max(1, int(os.environ.get("NALU_QA_WORKERS") or default))
    except ValueError:
        return default


def parallel_map(fn: Callable[[Any], Any], keys: Iterable[Any],
                 workers: int | None = None) -> dict[Any, Any]:
    """fn(key) for every key on a bounded thread pool; results keyed so the caller emits them in
    its own order.  An exception in any unit propagates exactly as it would have sequentially."""
    keys = list(keys)
    workers = unit_workers() if workers is None else workers
    if workers <= 1 or len(keys) <= 1:
        return {key: fn(key) for key in keys}
    with ThreadPoolExecutor(max_workers=min(workers, len(keys))) as pool:
        futures = {key: pool.submit(fn, key) for key in keys}
        return {key: future.result() for key, future in futures.items()}


def never_raise(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Wrap fn so a raised exception becomes ``{"__error__": "<Type>: <msg>"}`` instead of aborting
    the pool.  The caller decides how to report a unit that raised; the other units still run."""
    def guarded(key: Any) -> Any:
        try:
            return fn(key)
        except Exception as exc:  # noqa: BLE001 — recorded per unit, not swallowed silently
            return {"__error__": f"{type(exc).__name__}: {exc}"}
    return guarded
