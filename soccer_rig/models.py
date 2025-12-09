from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DiskStatus(BaseModel):
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
