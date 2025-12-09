from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DiskStatus(BaseModel):
    total_gb: float = Field(..., description="Total storage in gigabytes")
    free_gb: float = Field(..., description="Free storage in gigabytes")
    used_gb: float | None = Field(
        default=None, description="Used storage in gigabytes; optional for simulated environments"
    )
    free_percent: float | None = Field(
        default=None, description="Free space percentage when available from the filesystem"
    )
    estimated_minutes_remaining: int | None = Field(
        default=None,
        description="Estimated minutes left for recording at current bitrate. Optional when bitrate is unknown.",
    )


class SyncStatus(BaseModel):
    role: Literal["master", "client"] = "client"
    offset_ms: float = 0.0
    confidence: str = "unknown"
    master_timestamp: Optional[datetime] = None
    local_timestamp: Optional[datetime] = None


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
    bitrate_mbps: int = 30
    codec: str = "h265"
    resolution: str = "3840x2160"
    fps: int = 30
    audio_enabled: bool = True
    duration_minutes_default: int = 110
    wifi_mesh_ssid: str = "SOCCER_MESH"
    ap_ssid_prefix: str = "SOCCER_CAM"
    wifi_password: str = "changeme123"
    ap_mode_timeout_sec: int = 15
    production_mode: bool = True
    delete_after_confirm: bool = False
    free_space_min_gb: int = 10
    ntp_master_id: str = "CAM_C"
    sync_offset_warn_ms: int = 5
    update_repo: str = "traloxolcus/soccer-rig"
    update_channel: str = "stable"
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
    total_gb: Optional[float] = None
    free_gb: Optional[float] = None
    used_gb: Optional[float] = None
    free_percent: Optional[float] = None
    est_record_minutes_remaining: Optional[int] = None


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
    model_config = ConfigDict(extra="forbid")

    camera_id: Optional[str] = None
    bitrate_mbps: Optional[int] = Field(None, ge=5, le=50)
    codec: Optional[str] = Field(None, pattern="^(h264|h265)$")
    resolution: Optional[str] = None
    fps: Optional[int] = None
    audio_enabled: Optional[bool] = None
    duration_minutes_default: Optional[int] = Field(None, ge=1, le=240)
    wifi_mesh_ssid: Optional[str] = None
    ap_ssid_prefix: Optional[str] = None
    wifi_password: Optional[str] = None
    ap_mode_timeout_sec: Optional[int] = None
    production_mode: Optional[bool] = None
    delete_after_confirm: Optional[bool] = None
    free_space_min_gb: Optional[int] = Field(None, ge=1, le=500)
    ntp_master_id: Optional[str] = None
    sync_offset_warn_ms: Optional[int] = None
    update_repo: Optional[str] = None
    update_channel: Optional[str] = None


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


class UpdateCheckResponse(BaseModel):
    current_version: str
    available_version: Optional[str]
    can_update: bool
    message: Optional[str] = None


class UpdateApplyResponse(BaseModel):
    started: bool
    message: str
    applied_version: Optional[str] = None
