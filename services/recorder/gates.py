"""Readiness and safety gates for the recorder pipeline.

The functions here keep the controller decoupled from hardware-specific
checks so we can reuse the same logic in test mode. None of the helpers
raise exceptions; instead they return booleans and human-readable reasons
so the caller can decide how to surface the failure to the UI.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TEMP_LIMIT_C = 85.0
BATTERY_CRITICAL = 10


@dataclass(slots=True)
class GateReport:
    ok: bool
    reason: Optional[str] = None


def camera_present(device: Path = Path("/dev/video0")) -> GateReport:
    if device.exists():
        return GateReport(ok=True)
    return GateReport(ok=False, reason=f"Camera device missing at {device}")


def nvme_writable(path: Path) -> GateReport:
    path.mkdir(parents=True, exist_ok=True)
    try:
        test_file = path / ".recording-write-test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return GateReport(ok=True)
    except OSError as exc:  # noqa: PERF203
        return GateReport(ok=False, reason=f"NVMe not writable: {exc}")


def free_space_ok(path: Path, minimum_gb: float) -> GateReport:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    if free_gb >= minimum_gb:
        return GateReport(ok=True)
    return GateReport(ok=False, reason=f"Low disk: {free_gb:.1f}GB < {minimum_gb}GB threshold")


def temperature_safe(thermal_path: Path = Path("/sys/class/thermal/thermal_zone0/temp")) -> GateReport:
    if not thermal_path.exists():
        return GateReport(ok=True, reason="Temperature sensor unavailable")
    try:
        raw = float(thermal_path.read_text().strip())
    except (OSError, ValueError):
        return GateReport(ok=False, reason="Temperature read failed")
    temp_c = raw / 1000
    if temp_c < TEMP_LIMIT_C:
        return GateReport(ok=True)
    return GateReport(ok=False, reason=f"Overheating: {temp_c:.1f}C >= {TEMP_LIMIT_C}C")


def battery_safe(capacity_path: Path = Path("/sys/class/power_supply/BAT0/capacity")) -> GateReport:
    if not capacity_path.exists():
        return GateReport(ok=True, reason="Battery sensor unavailable")
    try:
        percent = int(capacity_path.read_text().strip())
    except (OSError, ValueError):
        return GateReport(ok=False, reason="Battery read failed")
    if percent > BATTERY_CRITICAL:
        return GateReport(ok=True)
    return GateReport(ok=False, reason=f"Battery critically low: {percent}%")


def all_gates(base_dir: Path, minimum_gb: float) -> list[GateReport]:
    checks = [
        camera_present(),
        nvme_writable(base_dir),
        free_space_ok(base_dir, minimum_gb),
        temperature_safe(),
        battery_safe(),
    ]
    return checks

