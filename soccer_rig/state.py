from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from services.sync.agent import SyncAgent, SyncHealth
from services.sync.telemetry import ChronyTelemetry

from .config import settings
from .models import (
    CameraStatus,
    Config,
    ConfirmRequest,
    DiskStatus,
    Manifest,
    RecordingInfo,
    RecordingState,
    RecordStopResponse,
    SelfTestResult,
    SyncStatus,
    TestRecordingResult,
    UpdateStatus,
)


class RigState:
    def __init__(self) -> None:
        self.config = Config(
            camera_id=settings.camera_id,
            bitrate_mbps=settings.bitrate_mbps,
            codec=settings.codec,
            resolution=settings.resolution,
            fps=settings.fps,
            audio_enabled=settings.audio_enabled,
            duration_minutes_default=settings.duration_minutes_default,
            ssid=None,
            ap_fallback_seconds=settings.ap_mode_timeout_sec,
            ap_ssid=settings.ap_ssid_prefix,
            ap_password=settings.wifi_password,
            wifi_mesh_ssid=settings.wifi_mesh_ssid,
            ap_ssid_prefix=settings.ap_ssid_prefix,
            wifi_password=settings.wifi_password,
            ap_mode_timeout_sec=settings.ap_mode_timeout_sec,
            production_mode=settings.production_mode,
            delete_after_confirm=settings.delete_after_confirm,
            free_space_min_gb=settings.free_space_min_gb,
            ntp_master_id=settings.ntp_master_id,
            sync_offset_warn_ms=settings.sync_offset_warn_ms,
            update_repo=settings.update_repo,
            update_channel=settings.update_channel,
            version=settings.version,
        )
        role = self._role()
        master_host = self._master_host(role)
        self.sync_agent = SyncAgent(
            role=role,
            master_host=master_host,
            status_path=settings.logs_dir / "sync_status.json",
        )
        sync_health = self.sync_agent.configure()
        disk = self._disk_status(settings.base_dir, settings.bitrate_mbps)
        sync = self._sync_status_from_health(sync_health)
        self.camera_status = CameraStatus(
            camera_id=self.config.camera_id,
            recording=False,
            active_session=None,
            disk=disk,
            sync=sync,
            live_preview_url="/preview.jpg",
        )
        self.camera_status.resolution = self.config.resolution
        self.camera_status.fps = self.config.fps
        self.camera_status.codec = self.config.codec
        self.camera_status.bitrate_mbps = self.config.bitrate_mbps
        self.camera_status.audio_enabled = self.config.audio_enabled
        self.recordings: Dict[str, RecordingInfo] = {}
        self.active_recording_id: Optional[str] = None

    def current_status(self) -> StatusResponse:
        disk = self._disk_status(settings.base_dir, self.camera_status.bitrate_mbps)
        self.camera_status.disk = disk
        sync_health = self.sync_agent.status()
        self.camera_status.sync = self._sync_status_from_health(sync_health)
        temperature_c = self._read_temperature()
        battery_percent = self._read_battery_percent()
        warnings = self._warnings(disk, self.camera_status.sync, temperature_c, battery_percent)
        return StatusResponse(
            camera_id=self.camera_status.camera_id,
            recording=self._recording_state(),
            disk=disk,
            settings={
                "codec": self.camera_status.codec,
                "bitrate_mbps": self.camera_status.bitrate_mbps,
                "resolution": self.camera_status.resolution,
                "fps": self.camera_status.fps,
                "audio_enabled": self.camera_status.audio_enabled,
                "production_mode": self.config.production_mode,
                "version": self.config.version,
                "duration_minutes_default": self.config.duration_minutes_default,
                "free_space_min_gb": self.config.free_space_min_gb,
                "update_channel": self.config.update_channel,
            },
            sync=self.camera_status.sync,
            temperature_c=temperature_c,
            battery_percent=battery_percent,
            warnings=warnings,
        )

    def start_recording(self, session_id: str, camera_id: str, **overrides) -> RecordingInfo:
        self._ensure_storage_capacity()
        sync_health = self.sync_agent.status()
        now = datetime.now(timezone.utc)
        filename = f"{session_id}_{camera_id}_{now:%Y%m%d}_{now:%H%M%S}.mp4"
        record = RecordingInfo(
            session_id=session_id,
            camera_id=camera_id,
            filename=filename,
            started_at=now,
            master_start=sync_health.telemetry.master_timestamp,
            local_start=sync_health.telemetry.local_timestamp,
            audio_enabled=overrides.get("audio_enabled", True),
            bitrate_mbps=overrides.get("bitrate_mbps", self.config.bitrate_mbps),
            codec=overrides.get("codec", self.config.codec),
        )
        self.recordings[filename] = record
        self.camera_status.recording = True
        self.camera_status.active_session = session_id
        self.camera_status.audio_enabled = record.audio_enabled
        self.camera_status.bitrate_mbps = record.bitrate_mbps
        self.camera_status.codec = record.codec
        self.camera_status.sync = self._sync_status_from_health(sync_health)
        self.active_recording_id = filename
        self._refresh_disk_estimate(record.bitrate_mbps)
        return record

    def stop_recording(self) -> RecordStopResponse:
        if not self.active_recording_id:
            raise ValueError("No active recording")
        record = self.recordings[self.active_recording_id]
        session_id = record.session_id
        now = datetime.now(timezone.utc)
        duration = int((now - record.started_at).total_seconds())
        record.duration_seconds = duration
        record.size_gb = self._reduce_disk_by(record.bitrate_mbps, duration)
        self.camera_status.recording = False
        self.camera_status.active_session = None
        self.active_recording_id = None
        return RecordStopResponse(session_id=session_id, camera_id=record.camera_id, duration_seconds=duration)

    def confirm_offload(self, request: ConfirmRequest) -> RecordingInfo:
        record = self._find_recording(request.session_id, request.file)
        if request.checksum.algo.lower() != "sha256":
            raise ValueError("Unsupported checksum algorithm")
        record.offloaded = True
        record.checksum_sha256 = request.checksum.value
        record.marked_for_deletion = self.config.delete_after_confirm
        if record.marked_for_deletion:
            self._delete_recording(record.filename)
        else:
            self._maybe_cleanup_storage()
        return record

    def run_self_test(self) -> SelfTestResult:
        disk = self._disk_status(settings.base_dir, self.camera_status.bitrate_mbps)
        sync_health = self.sync_agent.status()
        details = [
            f"Disk free: {disk.free_gb} GB",
            f"Sync offset: {sync_health.telemetry.offset_ms} ms ({sync_health.telemetry.confidence})",
        ]
        return SelfTestResult(
            passed=sync_health.telemetry.confidence not in {"chrony-error", "chrony-missing", "chrony-timeout"},
            details=details,
            total_gb=disk.total_gb,
            free_gb=disk.free_gb,
            used_gb=disk.used_gb,
            free_percent=disk.free_percent,
            est_record_minutes_remaining=disk.estimated_minutes_remaining,
        )

    def run_test_recording(self) -> TestRecordingResult:
        """Simulate a 10-second test recording with disk accounting."""
        self._ensure_storage_capacity()
        record = self.start_recording(session_id="TEST", camera_id=self.config.camera_id, bitrate_mbps=10.0)
        record.duration_seconds = 10
        record.size_gb = self._reduce_disk_by(record.bitrate_mbps, record.duration_seconds)
        self.camera_status.recording = False
        self.camera_status.active_session = None
        self.active_recording_id = None
        self._delete_recording(record.filename)
        return TestRecordingResult(passed=True, duration_seconds=10, detail="Test clip captured")

    def manifest(self) -> Manifest:
        return Manifest(**self.camera_status.model_dump(), recording_files=list(self.recordings.values()))

    def update_check(self) -> UpdateStatus:
        latest = "soccer-rig-1.2.0"
        return UpdateStatus(
            current_version=self.config.version,
            latest_version=latest,
            update_available=self.config.version != latest,
        )

    def apply_update(self) -> UpdateStatus:
        status = self.update_check()
        if self.camera_status.recording:
            raise RuntimeError("Recording in progress")
        self.config.version = status.latest_version
        return self.update_check()

    def update_config(self, partial: dict) -> Config:
        allowed_fields = set(Config.model_fields.keys())
        unsupported = set(partial) - allowed_fields
        if unsupported:
            unsupported_list = ", ".join(sorted(unsupported))
            raise ValueError(f"Unsupported config fields: {unsupported_list}")

        for key, value in partial.items():
            if key == "min_free_gb":
                key = "free_space_min_gb"
            if value is not None and hasattr(self.config, key):
                setattr(self.config, key, value)
        # ensure status reflects updated config
        self.camera_status.camera_id = self.config.camera_id
        self.camera_status.codec = self.config.codec
        self.camera_status.bitrate_mbps = self.config.bitrate_mbps
        self.camera_status.audio_enabled = self.config.audio_enabled
        self.camera_status.resolution = self.config.resolution
        self.camera_status.fps = self.config.fps
        self._refresh_disk_estimate(self.camera_status.bitrate_mbps)
        return self.config

    def get_recordings(self) -> List[RecordingInfo]:
        return list(self.recordings.values())

    def _refresh_disk_estimate(self, bitrate_mbps: float) -> None:
        self.camera_status.disk = self._disk_status(settings.base_dir, bitrate_mbps)

    def _reduce_disk_by(self, bitrate_mbps: float, duration_seconds: int) -> float:
        consumed_mb = (bitrate_mbps / 8) * duration_seconds
        consumed_gb = consumed_mb / 1024
        # Reflect the write immediately without waiting for filesystem polling
        self.camera_status.disk.free_gb = max(self.camera_status.disk.free_gb - consumed_gb, 0)
        self.camera_status.disk.used_gb = max(self.camera_status.disk.total_gb - self.camera_status.disk.free_gb, 0)
        self._refresh_disk_estimate(bitrate_mbps)
        return consumed_gb

    def _recording_state(self) -> RecordingState:
        state = RecordingState(active=bool(self.active_recording_id))
        if self.active_recording_id:
            record = self.recordings[self.active_recording_id]
            now = datetime.now(timezone.utc)
            elapsed = int((now - record.started_at).total_seconds())
            state.file_name = record.filename
            state.session_id = record.session_id
            state.started_at = record.started_at
            state.elapsed_seconds = elapsed
            state.eta_seconds = max((record.duration_seconds or 0) - elapsed, 0)
        return state

    def _find_recording(self, session_id: str, filename: str) -> RecordingInfo:
        record = self.recordings.get(filename)
        if not record or record.session_id != session_id:
            raise KeyError("Recording not found")
        return record

    def _delete_recording(self, filename: str) -> None:
        record = self.recordings.pop(filename, None)
        if record and record.size_gb:
            self.camera_status.disk.free_gb += record.size_gb
            self._refresh_disk_estimate(self.camera_status.bitrate_mbps)

    def _ensure_storage_capacity(self) -> None:
        self.camera_status.disk = self._disk_status(settings.base_dir, self.camera_status.bitrate_mbps)
        if self.camera_status.disk.free_gb < self.config.free_space_min_gb:
            raise ValueError("Insufficient free space")

    def _disk_status(self, base_dir: Path, bitrate_mbps: float) -> DiskStatus:
        usage = shutil.disk_usage(base_dir)
        total_gb = round(usage.total / (1024**3), 2)
        free_gb = round(usage.free / (1024**3), 2)
        used_gb = round(usage.used / (1024**3), 2)
        free_percent = round((usage.free / usage.total) * 100, 2) if usage.total else None
        est_minutes = None
        if bitrate_mbps:
            mb_per_sec = bitrate_mbps / 8
            gb_per_minute = (mb_per_sec * 60) / 1024
            est_minutes = int(free_gb / gb_per_minute) if gb_per_minute else 0
        return DiskStatus(
            total_gb=total_gb,
            free_gb=free_gb,
            used_gb=used_gb,
            free_percent=free_percent,
            estimated_minutes_remaining=est_minutes,
        )

    def _sync_status_from_health(self, health: SyncHealth) -> SyncStatus:
        telemetry: ChronyTelemetry = health.telemetry
        return SyncStatus(
            role=telemetry.role,
            offset_ms=telemetry.offset_ms,
            confidence=telemetry.confidence,
            master_timestamp=telemetry.master_timestamp,
            local_timestamp=telemetry.local_timestamp,
        )

    def _read_temperature(self) -> Optional[float]:
        thermal = Path("/sys/class/thermal/thermal_zone0/temp")
        if thermal.exists():
            try:
                raw = float(thermal.read_text().strip())
                return round(raw / 1000, 2)
            except (OSError, ValueError):
                return None
        return None

    def _read_battery_percent(self) -> Optional[int]:
        power_path = Path("/sys/class/power_supply/BAT0/capacity")
        if power_path.exists():
            try:
                return int(power_path.read_text().strip())
            except (OSError, ValueError):
                return None
        return None

    def _warnings(
        self, disk: DiskStatus, sync: SyncStatus, temperature_c: Optional[float], battery_percent: Optional[int]
    ) -> List[str]:
        notices: List[str] = []
        if disk.free_gb < self.config.free_space_min_gb:
            notices.append("Low disk space: below configured threshold")
        if sync.offset_ms and abs(sync.offset_ms) > self.config.sync_offset_warn_ms:
            notices.append("Time sync offset exceeds tolerance")
        if temperature_c and temperature_c >= 80:
            notices.append("High temperature detected")
        if battery_percent is not None and battery_percent <= 10:
            notices.append("Battery critically low")
        if self.camera_status.recording and self.active_recording_id:
            record = self.recordings.get(self.active_recording_id)
            if record and record.duration_seconds:
                now = datetime.now(timezone.utc)
                elapsed = int((now - record.started_at).total_seconds())
                if elapsed >= record.duration_seconds:
                    notices.append("Recording duration reached; finalizing soon")
        return notices

    def _role(self) -> str:
        return "master" if self.config.camera_id == self.config.ntp_master_id else "client"

    def _master_host(self, role: str) -> Optional[str]:
        if role == "master":
            return None
        return os.environ.get("SYNC_MASTER_HOST") or f"{self.config.ntp_master_id.lower()}.local"

    def _maybe_cleanup_storage(self) -> None:
        if self.camera_status.disk.free_gb >= self.config.free_space_min_gb:
            return
        for filename, record in list(self.recordings.items()):
            if record.offloaded:
                self._delete_recording(filename)
                if self.camera_status.disk.free_gb >= self.config.free_space_min_gb:
                    break


state = RigState()
