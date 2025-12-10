import shutil
from pathlib import Path
from typing import List, Optional

from services.sync.telemetry import chrony_telemetry

from .config import settings
from .models import DiskStatus, StatusResponse, SyncStatus
from .recording import recorder


def _disk_status(base_dir: Path, bitrate_mbps: int) -> DiskStatus:
    usage = shutil.disk_usage(base_dir)
    total_gb = round(usage.total / (1024**3), 2)
    free_gb = round(usage.free / (1024**3), 2)
    used_gb = round(usage.used / (1024**3), 2)
    free_percent = round((usage.free / usage.total) * 100, 2)
    est_minutes = _estimate_record_time_minutes(free_gb, bitrate_mbps)
    return DiskStatus(
        total_gb=total_gb,
        free_gb=free_gb,
        used_gb=used_gb,
        free_percent=free_percent,
        estimated_minutes_remaining=est_minutes,
    )


def _estimate_record_time_minutes(free_gb: float, bitrate_mbps: int) -> int:
    mb_per_sec = bitrate_mbps / 8
    gb_per_minute = (mb_per_sec * 60) / 1024
    if gb_per_minute == 0:
        return 0
    return int(free_gb / gb_per_minute)


def _sync_status() -> SyncStatus:
    role = "master" if settings.camera_id == settings.ntp_master_id else "client"
    telemetry = chrony_telemetry(role)
    return SyncStatus(
        role=telemetry.role,
        offset_ms=telemetry.offset_ms,
        confidence=telemetry.confidence,
        master_timestamp=telemetry.master_timestamp,
        local_timestamp=telemetry.local_timestamp,
    )


def _read_temperature() -> Optional[float]:
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal.exists():
        try:
            raw = float(thermal.read_text().strip())
            return round(raw / 1000, 2)
        except (OSError, ValueError):
            return None
    return None


def _read_battery_percent() -> Optional[int]:
    power_path = Path("/sys/class/power_supply/BAT0/capacity")
    if power_path.exists():
        try:
            return int(power_path.read_text().strip())
        except (OSError, ValueError):
            return None
    return None


def _warnings(disk: DiskStatus, sync: SyncStatus, temperature_c: Optional[float], battery_percent: Optional[int]) -> List[str]:
    notices: List[str] = []
    if disk.free_gb < settings.free_space_min_gb:
        notices.append("Low disk space: below configured threshold")
    if recorder.state().active and recorder.state().eta_seconds == 0:
        notices.append("Recording duration reached; finalizing soon")
    if sync.offset_ms and abs(sync.offset_ms) > settings.sync_offset_warn_ms:
        notices.append("Time sync offset exceeds tolerance")
    if temperature_c and temperature_c >= 80:
        notices.append("High temperature detected")
    if battery_percent is not None and battery_percent <= 10:
        notices.append("Battery critically low")
    return notices


def current_status() -> StatusResponse:
    disk = _disk_status(settings.base_dir, settings.bitrate_mbps)
    sync = _sync_status()
    temperature_c = _read_temperature()
    battery_percent = _read_battery_percent()
    return StatusResponse(
        camera_id=settings.camera_id,
        recording=recorder.state(),
        disk=disk,
        settings={
            "codec": settings.codec,
            "bitrate_mbps": settings.bitrate_mbps,
            "resolution": settings.resolution,
            "fps": settings.fps,
            "audio_enabled": settings.audio_enabled,
            "production_mode": settings.production_mode,
            "version": settings.version,
            "duration_minutes_default": settings.duration_minutes_default,
            "free_space_min_gb": settings.free_space_min_gb,
            "update_channel": settings.update_channel,
        },
        sync=sync,
        temperature_c=temperature_c,
        battery_percent=battery_percent,
        warnings=_warnings(disk, sync, temperature_c, battery_percent),
    )
