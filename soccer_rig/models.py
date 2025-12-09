from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

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
    total_gb: float
    free_gb: float
    used_gb: float
    free_percent: float
    est_record_minutes_remaining: Optional[int] = None
    

class SyncStatus(BaseModel):
    role: Literal["master", "client"] = "client"
    offset_ms: float = 0.0
    confidence: str = "unknown"
    master_timestamp: Optional[datetime] = None


class RecordingDescriptor(BaseModel):
    session_id: str
    camera_id: str
    file_name: str
    path: Path
    manifest_path: Path
    start_time_local: datetime
    start_time_master: Optional[datetime]
    duration_seconds: Optional[int] = None
    target_duration_seconds: Optional[int] = None
    ended_at: Optional[datetime] = None
    codec: str
    resolution: str
    fps: int
    bitrate_mbps: int
    audio_enabled: bool
    dropped_frames: int = 0
    offloaded: bool = False
    checksum_sha256: Optional[str] = None
    snapshot_b64: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class RecordingState(BaseModel):
    active: bool = False
    file_name: Optional[str] = None
    session_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    eta_seconds: Optional[int] = None
    elapsed_seconds: Optional[int] = None


class StatusResponse(BaseModel):
    camera_id: str
    recording: RecordingState
    disk: DiskStatus
    settings: dict
    sync: SyncStatus
    temperature_c: Optional[float] = None
    battery_percent: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)


class StartRecordingRequest(BaseModel):
    session_id: Optional[str] = None
    duration_minutes: Optional[int] = None
    audio_enabled: Optional[bool] = None
    test_mode: bool = False


class StopRecordingResponse(BaseModel):
    stopped: bool
    manifest: Optional[str] = None


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

    checksum: dict


class ConfigUpdate(BaseModel):
    bitrate_mbps: Optional[int] = Field(None, ge=5, le=50)
    codec: Optional[str] = Field(None, pattern="^(h264|h265)$")
    audio_enabled: Optional[bool] = None
    production_mode: Optional[bool] = None
    delete_after_confirm: Optional[bool] = None
    wifi_mesh_ssid: Optional[str] = None
    wifi_password: Optional[str] = None
    duration_minutes_default: Optional[int] = Field(None, ge=1, le=240)
    free_space_min_gb: Optional[int] = Field(None, ge=1, le=500)


class UpdateCheckResponse(BaseModel):
    current_version: str
    available_version: Optional[str]
    can_update: bool
    message: Optional[str] = None


class UpdateApplyResponse(BaseModel):
    started: bool
    message: str
    applied_version: Optional[str] = None


class SelfTestResult(BaseModel):
    ok: bool
    details: List[str]
