#!/usr/bin/env python3
"""Compatibility adapter for the shared SD2/H3 execution-plan compiler."""

try:
    from tools.video_execution_plan_compiler import (
        SCHEMA,
        classify_unit,
        compile_video_execution_plan,
    )
except ModuleNotFoundError:
    from video_execution_plan_compiler import (
        SCHEMA,
        classify_unit,
        compile_video_execution_plan,
    )


def compile_sd2_execution_plan(unit):
    plan = compile_video_execution_plan(unit)
    if plan["model_family"] != "SEEDANCE_2":
        raise ValueError("SD2 execution adapter received a non-SD2 unit")
    return plan


__all__ = ["SCHEMA", "classify_unit", "compile_sd2_execution_plan"]
