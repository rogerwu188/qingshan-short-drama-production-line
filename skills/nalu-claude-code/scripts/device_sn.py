#!/usr/bin/env python3
"""This machine's hardware serial number, the device SN X2C's 设备矩阵映射 is keyed on.

Order: $NALU_DEVICE_SN, the cached $NALU_RUNTIME_ROOT/credentials/device_sn, then the hardware itself:
/sys/class/dmi/id/product_serial (Linux, readable when the kernel allows), ``dmidecode -s
system-serial-number``, the same through ``sudo -n`` (never prompts), and on macOS the IOPlatformSerialNumber.
Vendor placeholders ("To be filled by O.E.M.", "Default string", ...) are not serials.  A hardware read is
cached so later calls need no privileges.  The SN is not a secret.

  device_sn.py            print {"device_sn": ..., "source": ...} (exit 1 when none is found)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

VALID = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
PLACEHOLDERS = {"to be filled by o.e.m.", "default string", "system serial number", "not specified",
                "not applicable", "none", "0", "00000000", "0123456789", "123456789", "serial", "n/a", ""}


def cache_path() -> Path:
    root = Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()
    return root / "credentials" / "device_sn"


def clean(value: str | None) -> str:
    value = (value or "").strip().splitlines()[0].strip() if (value or "").strip() else ""
    return "" if value.lower() in PLACEHOLDERS or not VALID.fullmatch(value) else value


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def hardware_serial() -> tuple[str, str]:
    """(serial, source) read from the machine, or ("", "")."""
    try:
        sn = clean(Path("/sys/class/dmi/id/product_serial").read_text(encoding="utf-8", errors="ignore"))
        if sn:
            return sn, "sysfs:product_serial"
    except OSError:
        pass
    for argv, source in ((["dmidecode", "-s", "system-serial-number"], "dmidecode"),
                         (["sudo", "-n", "dmidecode", "-s", "system-serial-number"], "sudo-n-dmidecode")):
        sn = clean(_run(argv))
        if sn:
            return sn, source
    if sys.platform == "darwin":
        match = re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]+)"', _run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]))
        sn = clean(match.group(1) if match else "")
        if sn:
            return sn, "ioreg"
    return "", ""


def resolve(write_cache: bool = True) -> tuple[str, str]:
    """(device_sn, source); ("", "") when nothing usable is found."""
    sn = os.environ.get("NALU_DEVICE_SN", "").strip()
    if sn:
        return sn, "env:NALU_DEVICE_SN"
    try:
        sn = clean(cache_path().read_text(encoding="utf-8"))
        if sn:
            return sn, f"cache:{cache_path()}"
    except OSError:
        pass
    sn, source = hardware_serial()
    if sn and write_cache:
        try:
            cache_path().parent.mkdir(parents=True, exist_ok=True)
            cache_path().write_text(sn + "\n", encoding="utf-8")
        except OSError:
            pass
    return sn, source


def main() -> int:
    sn, source = resolve()
    print(json.dumps({"device_sn": sn or None, "source": source or None}, ensure_ascii=False))
    return 0 if sn else 1


if __name__ == "__main__":
    raise SystemExit(main())
