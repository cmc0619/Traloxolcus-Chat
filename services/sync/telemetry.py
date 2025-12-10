"""Chrony telemetry helpers feeding the status endpoint."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(slots=True)
class ChronyTelemetry:
    role: str
    offset_ms: float
    confidence: str
    master_timestamp: datetime
    local_timestamp: datetime
    raw: str


def _run_chronyc() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["chronyc", "tracking"], check=False, capture_output=True, text=True, timeout=1
    )


def _parse_offset(output: str) -> tuple[Optional[float], str]:
    offset_line = next((line for line in output.splitlines() if "Last offset" in line), None)
    if not offset_line:
        return None, "chrony-unknown"
    try:
        parts = offset_line.split(":")[-1].strip().split()
        offset_seconds = float(parts[0])
        return round(offset_seconds * 1000, 3), "good"
    except (ValueError, IndexError):
        return None, "chrony-parse"


def chrony_telemetry(role: str) -> ChronyTelemetry:
    now = datetime.now(timezone.utc)
    try:
        result = _run_chronyc()
    except FileNotFoundError:
        return ChronyTelemetry(
            role=role,
            offset_ms=0.0,
            confidence="chrony-missing",
            master_timestamp=now,
            local_timestamp=now,
            raw="chronyc not installed",
        )
    except subprocess.TimeoutExpired:
        return ChronyTelemetry(
            role=role,
            offset_ms=0.0,
            confidence="chrony-timeout",
            master_timestamp=now,
            local_timestamp=now,
            raw="timeout",
        )

    offset_ms, confidence = _parse_offset(result.stdout)
    if offset_ms is None:
        offset_ms = 0.0
    if result.returncode != 0:
        confidence = "chrony-error"

    return ChronyTelemetry(
        role=role,
        offset_ms=offset_ms,
        confidence=confidence,
        master_timestamp=now,
        local_timestamp=now,
        raw=result.stdout.strip(),
    )

