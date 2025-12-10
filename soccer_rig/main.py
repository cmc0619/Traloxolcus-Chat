from typing import Any, Dict

from fastapi import FastAPI, HTTPException

from .config import settings
from .models import (
    Config,
    ConfigUpdate,
    ConfirmRequest,
    SelfTestResult,
    StartRecordingRequest,
    StatusResponse,
    StopRecordingResponse,
)
from .recording import recorder
from .status import current_status
from .updater import apply_update, check_for_update


app = FastAPI(title="Soccer Rig", version=settings.version)


@app.get("/api/v1/status", response_model=StatusResponse)
def status() -> StatusResponse:
    return current_status()


@app.post("/api/v1/record/start")
def start_recording(request: StartRecordingRequest) -> Dict[str, Any]:
    try:
        descriptor = recorder.start_recording(
            session_id=request.session_id,
            duration_minutes=request.duration_minutes,
            audio_enabled=request.audio_enabled,
            test_mode=request.test_mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "file": str(descriptor.path),
        "session_id": descriptor.session_id,
        "camera_id": descriptor.camera_id,
        "codec": descriptor.codec,
        "bitrate_mbps": descriptor.bitrate_mbps,
        "resolution": descriptor.resolution,
        "fps": descriptor.fps,
        "test_mode": request.test_mode,
        "duration_seconds": descriptor.target_duration_seconds,
        "snapshot_b64": descriptor.snapshot_b64,
    }


@app.post("/api/v1/record/stop", response_model=StopRecordingResponse)
def stop_recording() -> StopRecordingResponse:
    manifest_path = recorder.stop_recording()
    if manifest_path is None:
        raise HTTPException(status_code=409, detail="No active recording")
    recorder.cleanup_offloaded()
    return StopRecordingResponse(stopped=True, manifest=str(manifest_path))


@app.get("/api/v1/recordings")
def list_recordings() -> Dict[str, Any]:
    entries = []
    for descriptor in recorder.list_recordings():
        entries.append(
            {
                "session_id": descriptor.session_id,
                "camera_id": descriptor.camera_id,
                "file": descriptor.file_name,
                "path": str(descriptor.path),
                "duration": descriptor.duration_seconds,
                "ended_at": descriptor.ended_at.isoformat() if descriptor.ended_at else None,
                "codec": descriptor.codec,
                "bitrate_mbps": descriptor.bitrate_mbps,
                "fps": descriptor.fps,
                "resolution": descriptor.resolution,
                "audio_enabled": descriptor.audio_enabled,
                "offloaded": descriptor.offloaded,
                "checksum_sha256": descriptor.checksum_sha256,
                "manifest": str(descriptor.manifest_path),
                "snapshot_b64": descriptor.snapshot_b64,
            }
        )
    return {"recordings": entries}


@app.post("/api/v1/recordings/confirm")
def confirm_recording(request: ConfirmRequest) -> Dict[str, Any]:
    try:
        descriptor = recorder.mark_offloaded(
            session_id=request.session_id,
            camera_id=request.camera_id,
            file_name=request.file,
            checksum=request.checksum.get("value"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not descriptor:
        raise HTTPException(status_code=404, detail="Recording not found")
    removed = recorder.cleanup_offloaded()
    return {"offloaded": True, "removed": [str(path) for path in removed]}


@app.get("/api/v1/config")
def get_config() -> Dict[str, Any]:
    return {
        "camera_id": settings.camera_id,
        "codec": settings.codec,
        "bitrate_mbps": settings.bitrate_mbps,
        "resolution": settings.resolution,
        "fps": settings.fps,
        "audio_enabled": settings.audio_enabled,
        "production_mode": settings.production_mode,
        "wifi_mesh_ssid": settings.wifi_mesh_ssid,
        "ap_ssid_prefix": settings.ap_ssid_prefix,
        "wifi_password": settings.wifi_password,
        "delete_after_confirm": settings.delete_after_confirm,
        "duration_minutes_default": settings.duration_minutes_default,
        "free_space_min_gb": settings.free_space_min_gb,
        "ntp_master_id": settings.ntp_master_id,
        "sync_offset_warn_ms": settings.sync_offset_warn_ms,
        "ap_mode_timeout_sec": settings.ap_mode_timeout_sec,
        "update_repo": settings.update_repo,
        "update_channel": settings.update_channel,
    }


@app.post("/api/v1/config")
def update_config(update: ConfigUpdate) -> Dict[str, Any]:
    updated_fields = {}
    for field, value in update.model_dump(exclude_none=True).items():
        if field == "min_free_gb":
            field = "free_space_min_gb"
        if hasattr(settings, field):
            setattr(settings, field, value)
            updated_fields[field] = value
    return {"updated": updated_fields}


@app.get("/api/v1/logs")
def logs() -> Dict[str, Any]:
    if settings.production_mode:
        return {"message": "Production mode enabled: verbose logs suppressed"}
    return {"logs": recorder.logs()}


@app.post("/api/v1/shutdown")
def shutdown_node() -> Dict[str, Any]:
    recorder.stop_recording()
    return {"shutting_down": True}


@app.post("/api/v1/selftest", response_model=SelfTestResult)
def self_test() -> SelfTestResult:
    details = [
        "Camera detected",
        "Storage writable",
        "Sync within threshold",
    ]
    try:
        recorder._assert_disk_space()
    except RuntimeError:
        return SelfTestResult(passed=False, details=details + ["Insufficient free space"])
    try:
        recorder._assert_camera_available()
    except RuntimeError as exc:
        return SelfTestResult(passed=False, details=details + [str(exc)])
    return SelfTestResult(passed=True, details=details)


@app.post("/api/v1/update/check")
def update_check() -> Dict[str, Any]:
    return check_for_update().model_dump()


@app.post("/api/v1/update/apply")
def update_apply() -> Dict[str, Any]:
    return apply_update(recording_active=recorder.state().active).model_dump()


@app.get("/")
def root() -> Dict[str, Any]:
    return {"message": "Soccer Rig API", "version": settings.version}
