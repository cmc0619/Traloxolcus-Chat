"""Minimal sync agent for managing chrony roles and reporting health."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .telemetry import ChronyTelemetry, chrony_telemetry


@dataclass(slots=True)
class SyncHealth:
    telemetry: ChronyTelemetry
    chrony_running: bool
    sources: list[str]
    last_error: Optional[str] = None


class SyncAgent:
    """Drive basic chrony role configuration and expose runtime telemetry."""

    def __init__(self, role: str, master_host: Optional[str] = None, status_path: Optional[Path] = None):
        self.role = role
        self.master_host = master_host
        self.status_path = status_path

    def status(self) -> SyncHealth:
        telemetry = chrony_telemetry(self.role)
        sources, last_error = self._chrony_sources()
        health = SyncHealth(
            telemetry=telemetry,
            chrony_running=self._chrony_active(),
            sources=sources,
            last_error=last_error,
        )
        if self.status_path:
            self._write_status(health)
        return health

    def configure(self) -> SyncHealth:
        """Ensure chrony is available and pointing at the intended master when a client."""

        errors: list[str] = []
        if not self._chrony_active():
            self._start_chrony(errors)

        if self.role == "client" and self.master_host:
            self._prefer_master(self.master_host, errors)

        health = self.status()
        if errors and health.last_error is None:
            health.last_error = "; ".join(errors)
            if self.status_path:
                self._write_status(health)
        return health

    def _start_chrony(self, errors: list[str]) -> None:
        try:
            subprocess.run(["systemctl", "start", "chronyd"], check=False, capture_output=True, text=True)
        except FileNotFoundError:
            errors.append("systemctl missing; cannot start chronyd")

    def _prefer_master(self, master_host: str, errors: list[str]) -> None:
        try:
            subprocess.run(["chronyc", "add", "server", master_host], check=False, capture_output=True, text=True, timeout=1)
        except FileNotFoundError:
            errors.append("chronyc missing; cannot set preferred server")
        except subprocess.TimeoutExpired:
            errors.append("chronyc add server timeout")

    def _chrony_active(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "chronyd"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
            return result.stdout.strip() == "active"
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            return False

    def _chrony_sources(self) -> tuple[list[str], Optional[str]]:
        try:
            result = subprocess.run(
                ["chronyc", "sources", "-n"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except FileNotFoundError:
            return [], "chronyc not installed"
        except subprocess.TimeoutExpired:
            return [], "chronyc sources timeout"

        if result.returncode != 0:
            return [], "chronyc sources error"

        sources: list[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "Name/IP" in line:
                continue
            parts = line.split()
            if not parts:
                continue
            marker = parts[0]
            if marker[0] in "^#=*?+" and len(parts) >= 2:
                sources.append(parts[1])
            elif len(parts) >= 1:
                sources.append(parts[0])
        return sources, None

    def _write_status(self, health: SyncHealth) -> None:
        payload = {
            "role": self.role,
            "offset_ms": health.telemetry.offset_ms,
            "confidence": health.telemetry.confidence,
            "chrony_running": health.chrony_running,
            "sources": health.sources,
            "master_timestamp": health.telemetry.master_timestamp.isoformat(),
            "local_timestamp": health.telemetry.local_timestamp.isoformat(),
            "last_error": health.last_error,
        }
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.write_text(json.dumps(payload, indent=2))
        except OSError:
            return
