from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, status

from . import status as status_service
from .models import (
    Config,
    ConfigUpdate,
    ConfirmRequest,
    LogsResponse,
    RecordStartRequest,
    RecordingInfo,
    RecordStopResponse,
    SelfTestResult,
    ShutdownResponse,
    StatusResponse,
    TestRecordingResult,
    UpdateStatus,
)
from .state import state

app = FastAPI(title="Soccer Rig", version="1.2.0")


@app.get("/api/v1/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    return status_service.current_status()


@app.post("/api/v1/record/start", response_model=RecordingInfo)
def start_recording(body: RecordStartRequest) -> RecordingInfo:
    if state.camera_status.recording:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recording already in progress")
    if body.camera_id != state.config.camera_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera ID mismatch: expected {state.config.camera_id}",
        )
    try:
        record = state.start_recording(
            session_id=body.session_id,
            camera_id=body.camera_id,
            audio_enabled=body.audio_enabled,
            bitrate_mbps=body.bitrate_mbps,
            codec=body.codec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # sync fields for reporting
    now = datetime.now(timezone.utc)
    state.camera_status.sync.master_timestamp = now
    state.camera_status.sync.local_timestamp = now
    return record


@app.post("/api/v1/record/stop", response_model=RecordStopResponse)
def stop_recording() -> RecordStopResponse:
    try:
        return state.stop_recording()
    except ValueError as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/v1/recordings", response_model=list[RecordingInfo])
def list_recordings() -> list[RecordingInfo]:
    return state.get_recordings()


@app.post("/api/v1/recordings/confirm", response_model=RecordingInfo)
def confirm_recording(body: ConfirmRequest) -> RecordingInfo:
    try:
        return state.confirm_offload(body)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/v1/config", response_model=Config)
def get_config() -> Config:
    return state.config


@app.post("/api/v1/config", response_model=Config)
def update_config(body: ConfigUpdate) -> Config:
    payload = body.model_dump()
    return state.update_config(payload)


@app.get("/api/v1/logs", response_model=LogsResponse)
def get_logs() -> LogsResponse:
    if state.config.production_mode:
        return LogsResponse(message="Logs are disabled in Production Mode")
    return LogsResponse(message="Development logs would appear here")


@app.post("/api/v1/shutdown", response_model=ShutdownResponse)
def shutdown() -> ShutdownResponse:
    return ShutdownResponse(shutting_down=True, reason="Graceful shutdown initiated")


@app.post("/api/v1/selftest", response_model=SelfTestResult)
def selftest() -> SelfTestResult:
    return state.run_self_test()


@app.post("/api/v1/record/test", response_model=TestRecordingResult)
def test_recording() -> TestRecordingResult:
    try:
        return state.run_test_recording()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/v1/update/check", response_model=UpdateStatus)
def update_check() -> UpdateStatus:
    return state.update_check()


@app.post("/api/v1/update/apply", response_model=UpdateStatus)
def update_apply() -> UpdateStatus:
    try:
        return state.apply_update()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/api/v1/manifest", response_model=dict)
def manifest() -> dict:
    """Return a simplified manifest for downstream tooling."""
    return state.manifest().model_dump()

