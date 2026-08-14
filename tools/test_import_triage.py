#!/usr/bin/env python3
"""Separate "this sandbox lacks a package" from "production code will not import".

Authorization: `CL2X-1039`.

Why this exists, precisely. `python3 -m unittest discover -s tools/tests` on
2026-08-07 reported 18 errors. Seventeen were `ModuleNotFoundError: pytest` or
`boto3` — this sandbox, not the code. The eighteenth was
`tools/episode_stage_gate_runner.py` failing its own module-level

    assert RUNTIME_GATE_IDS == frozenset(EXECUTORS)

because `RELEASE-BRANDING-CONTRACT` had been added to `EXECUTORS` and to
`GATE_REGISTRY_v3` on 2026-08-03 but not to `RUNTIME_GATE_IDS`. The entire stage
gate runner — all 50 coded gates — had been unimportable for four days.

Both arrive in the summary as the same sentence:

    ERROR: tools.tests.test_x (unittest.loader._FailedTest)

The assert was correct and fired every single time. The test that would have
caught it existed and ran every single time. Nothing distinguished its failure
from seventeen pieces of sandbox noise, so it was read as noise. This is the
same shape as B9-ADV-03 (silence looks like PASS) and B9-ADV-06 (a blind
instrument looks like a defect), and it is the first one that cost production
time rather than a number.

The rule this encodes: an environment gap and a code defect must never be
allowed to render identically. Classification, not counting.

Exit code is 1 only for `PRODUCTION_IMPORT_BROKEN`. Missing optional packages
are reported and ignored, because failing on them would train everyone to
ignore the whole report — which is how this defect survived.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any

# Packages this sandbox is allowed not to have. Provisioned best-effort by
# workflow/tools/setup_supervisor_env.sh; their absence says nothing about the
# code. Anything NOT on this list that fails to import is a code defect.
OPTIONAL_PACKAGES = frozenset(
    {
        "pytest",
        "boto3",
        "botocore",
        "insightface",
        "faster_whisper",
        "cv2",
        "imagehash",
        "rapidocr_onnxruntime",
        "onnxruntime",
        "PIL",
        "numpy",
        "moviepy",
        "librosa",
        "soundfile",
        "torch",
    }
)

# Packages this project builds itself (see tools/build_portable_agentcut_wheel.py
# and workflow/agentcut/). Their absence is neither sandbox noise nor a code
# defect — it means this environment has no built runtime installed, which is a
# third thing and deserves to be called a third thing. Lumping it in with
# "missing dep" would let a genuinely broken agentcut hide; lumping it in with
# "broken code" would cry wolf on every text-only patrol round.
PROJECT_BUILT_PACKAGES = frozenset({"agentcut"})

CLASS_OK = "IMPORTS"
CLASS_OPTIONAL = "MISSING_OPTIONAL_DEP"
CLASS_PROJECT_RUNTIME_ABSENT = "PROJECT_RUNTIME_NOT_INSTALLED"
CLASS_BROKEN = "PRODUCTION_IMPORT_BROKEN"


def _missing_module_name(exc: BaseException) -> str | None:
    """The package name from a ModuleNotFoundError anywhere in the chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModuleNotFoundError) and current.name:
            return current.name.split(".")[0]
        current = current.__cause__ or current.__context__
    return None


def classify(
    module_name: str,
    *,
    optional: frozenset[str] = OPTIONAL_PACKAGES,
    project_built: frozenset[str] = PROJECT_BUILT_PACKAGES,
) -> dict[str, Any]:
    """Import one module and say which of the four states it is in.

    The two package sets are parameters rather than globals so a test can
    supply a name guaranteed absent. Hard-coding `boto3` as "the missing one"
    made this file's own test pass or fail depending on whether the sandbox
    had been provisioned that round — a test whose verdict tracks the
    environment is the thing this tool exists to stop.
    """
    try:
        importlib.import_module(module_name)
        return {"module": module_name, "classification": CLASS_OK}
    except BaseException as exc:  # noqa: BLE001 - an assert here is the point
        missing = _missing_module_name(exc)
        if missing in optional:
            return {
                "module": module_name,
                "classification": CLASS_OPTIONAL,
                "missing_package": missing,
                "detail": f"sandbox lacks {missing}; says nothing about the code",
            }
        if missing in project_built:
            return {
                "module": module_name,
                "classification": CLASS_PROJECT_RUNTIME_ABSENT,
                "missing_package": missing,
                "detail": (
                    f"{missing} is built by this project and is not installed here; "
                    f"this test is unrun, not passing"
                ),
            }
        return {
            "module": module_name,
            "classification": CLASS_BROKEN,
            "error_type": type(exc).__name__,
            "detail": (str(exc) or repr(exc))[:400],
            "missing_package": missing,
            "traceback_tail": traceback.format_exc().strip().splitlines()[-3:],
        }


def discover(test_dir: Path, package: str) -> list[str]:
    return [
        f"{package}.{path.stem}"
        for path in sorted(test_dir.glob("test_*.py"))
        if path.is_file()
    ]


def run(
    test_dir: Path,
    package: str,
    *,
    optional: frozenset[str] = OPTIONAL_PACKAGES,
    project_built: frozenset[str] = PROJECT_BUILT_PACKAGES,
) -> dict[str, Any]:
    results = [
        classify(name, optional=optional, project_built=project_built)
        for name in discover(test_dir, package)
    ]
    broken = [r for r in results if r["classification"] == CLASS_BROKEN]
    optional_results = [r for r in results if r["classification"] == CLASS_OPTIONAL]
    unrun = [r for r in results if r["classification"] == CLASS_PROJECT_RUNTIME_ABSENT]
    return {
        "schema": "qingshan.test_import_triage.v2",
        "authorization_ref": "CL2X-1039",
        "status": "FAIL" if broken else "PASS",
        "counts": {
            CLASS_OK: sum(1 for r in results if r["classification"] == CLASS_OK),
            CLASS_OPTIONAL: len(optional_results),
            CLASS_PROJECT_RUNTIME_ABSENT: len(unrun),
            CLASS_BROKEN: len(broken),
        },
        # Listed separately and first. The whole defect was that these
        # appeared in one undifferentiated pile.
        "production_import_broken": broken,
        "project_runtime_not_installed": [r["module"] for r in unrun],
        "missing_optional_deps": sorted({r["missing_package"] for r in optional_results if r.get("missing_package")}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-dir", type=Path, default=Path(__file__).resolve().parent / "tests")
    parser.add_argument("--package", default="tools.tests")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    report = run(args.test_dir, args.package)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
