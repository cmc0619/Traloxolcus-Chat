from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DiskStatus(BaseModel):
    total_gb: float = Field(..., description="Total storage in gigabytes")
    free_gb: float = Field(..., description="Free storage in gigabytes")
    estimated_minutes_remaining: int = Field(..., description="Estimated minutes left for recording at current bitrate")


class SyncStatus(BaseModel):
    role: str = Field(..., description="ntp-master or ntp-client")
    offset_ms: float = Field(..., description="Current time offset in milliseconds relative to master")
    confidence: str = Field(..., description="qualitative confidence in sync")
    master_timestamp: datetime = Field(..., description="Timestamp on master when recording started")
    local_timestamp: datetime = Field(..., description="Local timestamp when recording started")


class RecordingInfo(BaseModel):
    session_id: str
    camera_id: str
    filename: str
    started_at: datetime
    master_start: datetime
    local_start: datetime
    duration_seconds: Optional[int] = None
    size_gb: Optional[float] = None
    resolution: str = "3840x2160"
    fps: int = 30
    codec: str = "h265"
    bitrate_mbps: float = 30.0
    audio_enabled: bool = True
    dropped_frames: int = 0
    offloaded: bool = False
    checksum_sha256: Optional[str] = None
    marked_for_deletion: bool = False


class CameraStatus(BaseModel):
    camera_id: str
    recording: bool
    active_session: Optional[str] = None
    health: str = "ok"
    temperature_c: float = 45.0
    battery_percent: Optional[int] = None
    disk: DiskStatus
    sync: SyncStatus
    resolution: str = "3840x2160"
    fps: int = 30
    codec: str = "h265"
    bitrate_mbps: float = 30.0
    audio_enabled: bool = True
    live_preview_url: Optional[str] = None


class Config(BaseModel):
    camera_id: str
    bitrate_mbps: float = 30.0
    codec: str = "h265"
    ssid: Optional[str] = None
    ap_fallback_seconds: int = 30
    ap_ssid: str = "SOCCER_CAM"
    ap_password: Optional[str] = None
    min_free_gb: float = 5.0
    production_mode: bool = True
    delete_after_confirm: bool = False
    version: str = "soccer-rig-1.2.0"


class Checksum(BaseModel):
    algo: str = Field(..., description="Checksum algorithm such as sha256")
    value: str = Field(..., description="Hex digest of the file")


class UpdateStatus(BaseModel):
    current_version: str
    latest_version: str
    update_available: bool


class SelfTestResult(BaseModel):
    passed: bool
    details: List[str] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    session_id: str
    camera_id: str
    file: str
    checksum: Checksum


class ConfigUpdate(BaseModel):
    camera_id: Optional[str] = None
    bitrate_mbps: Optional[float] = None
    codec: Optional[str] = None
    ssid: Optional[str] = None
    ap_fallback_seconds: Optional[int] = None
    ap_ssid: Optional[str] = None
    ap_password: Optional[str] = None
    production_mode: Optional[bool] = None
    delete_after_confirm: Optional[bool] = None


class RecordStartRequest(BaseModel):
    session_id: str
    camera_id: str
    audio_enabled: Optional[bool] = None
    bitrate_mbps: Optional[float] = None
    codec: Optional[str] = None


class RecordStopResponse(BaseModel):
    session_id: str
    camera_id: str
    duration_seconds: int


class Manifest(CameraStatus):
    recording_files: List[RecordingInfo] = Field(default_factory=list)


class LogsResponse(BaseModel):
    message: str


class ShutdownResponse(BaseModel):
    shutting_down: bool
    reason: str


class TestRecordingResult(BaseModel):
    passed: bool
    duration_seconds: int
    detail: str

