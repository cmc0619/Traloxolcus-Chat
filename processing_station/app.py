"""FastAPI application for processing-station ingest and search."""

from __future__ import annotations

import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from .database import Database
from .schemas import (
    EventRecord,
    EventsRequest,
    ImportAck,
    SearchResponse,
    SessionDetail,
    SessionSummary,
    StitchRequest,
    StitchResponse,
    UploadResponse,
)
from .storage import Storage

app = FastAPI(title="Processing Station", version="0.1.0")
_db = Database()
_storage = Storage()
security = HTTPBasic()
allowed_origins = os.getenv("VIEWER_ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.mount("/media", StaticFiles(directory=_storage.root), name="media")


def get_db() -> Database:
    return _db


def get_storage() -> Storage:
    return _storage


def require_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Simple HTTP Basic authentication for viewer-facing endpoints."""

    expected_user = os.getenv("VIEWER_USERNAME", "viewer")
    expected_password = os.getenv("VIEWER_PASSWORD", "viewerpass")
    username_match = secrets.compare_digest(credentials.username, expected_user)
    password_match = secrets.compare_digest(credentials.password, expected_password)
    if not (username_match and password_match):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _media_url(path: str | None) -> str | None:
    """Convert a stitched asset path into a web-facing URL if possible."""

    if not path:
        return None
    path_obj = Path(path)
    try:
        relative = path_obj.resolve().relative_to(_storage.root.resolve())
    except ValueError:
        return None
    return f"/media/{relative.as_posix()}"


def _system_metrics() -> dict:
    disk = psutil.disk_usage("/")
    memory = psutil.virtual_memory()
    return {
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "percent": disk.percent,
        },
        "memory": {
            "total_gb": round(memory.total / (1024**3), 2),
            "used_gb": round(memory.used / (1024**3), 2),
            "percent": memory.percent,
        },
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }


def _gpu_metrics() -> list[dict]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        return []
    except subprocess.CalledProcessError:
        return []

    gpus: list[dict] = []
    for line in completed.stdout.strip().splitlines():
        name, mem_total, mem_used, util = [token.strip() for token in line.split(",")]
        gpus.append(
            {
                "name": name,
                "memory_total_mb": float(mem_total),
                "memory_used_mb": float(mem_used),
                "utilization_percent": float(util),
            }
        )
    return gpus


def _session_status(db: Database) -> list[dict]:
    sessions = db.sessions()
    status_payload: list[dict] = []
    for row in sessions:
        stitched = db.latest_stitched_for_session(row["id"])
        viewer_ready = stitched is not None
        waiting_for_cameras = row["camera_assets"] < 3
        status_payload.append(
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "camera_assets": row["camera_assets"],
                "stitched_assets": row["stitched_assets"],
                "events": row["events"],
                "viewer_ready": viewer_ready,
                "waiting_for_cameras": waiting_for_cameras,
            }
        )
    return status_payload


def _status_payload(db: Database) -> dict:
    return {
        "system": _system_metrics(),
        "gpu": _gpu_metrics(),
        "sessions": _session_status(db),
    }


@app.post("/api/v1/upload", response_model=UploadResponse)
async def upload_camera_asset(
    session_id: str,
    camera_id: str,
    file: UploadFile = File(...),
    codec: str | None = None,
    fps: float | None = None,
    bitrate_mbps: float | None = None,
    offset_ms: int | None = None,
    db: Database = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> UploadResponse:
    """Persist an uploaded file and record it as a camera asset."""

    if not session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required")
    if not camera_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="camera_id is required")

    destination = storage.save_upload(session_id, camera_id, file.filename, file.file)
    started_at = datetime.now(timezone.utc).isoformat()
    db.upsert_session(session_id=session_id, started_at=started_at)
    db.add_camera_asset(
        session_id=session_id,
        camera_id=camera_id,
        path=str(destination),
        codec=codec,
        fps=fps,
        bitrate_mbps=bitrate_mbps,
        offset_ms=offset_ms,
    )
    return UploadResponse(
        session_id=session_id,
        camera_id=camera_id,
        path=str(destination),
        manifest_recorded=True,
    )


@app.post("/api/v1/stitch", response_model=StitchResponse)
async def record_stitched_asset(
    request: StitchRequest,
    db: Database = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> StitchResponse:
    if not request.session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required")

    db.upsert_session(request.session_id, datetime.now(timezone.utc).isoformat())
    path_fullres = request.path_fullres
    path_proxy = request.path_proxy
    if path_fullres is None:
        reserved = storage.reserve_stitched_path(request.session_id, request.layout)
        reserved.touch()
        path_fullres = str(reserved)
    if path_proxy is None:
        proxy_path = storage.reserve_stitched_path(request.session_id, request.layout, proxy=True)
        proxy_path.touch()
        path_proxy = str(proxy_path)
    db.add_stitched_asset(
        session_id=request.session_id,
        layout=request.layout,
        path_fullres=path_fullres,
        path_proxy=path_proxy,
        checksum_sha256=request.checksum_sha256,
    )
    return StitchResponse(
        session_id=request.session_id,
        layout=request.layout,
        path_fullres=path_fullres,
        path_proxy=path_proxy,
        checksum_sha256=request.checksum_sha256,
    )


@app.post("/api/v1/events", response_model=ImportAck)
async def ingest_events(request: EventsRequest, db: Database = Depends(get_db)) -> ImportAck:
    if not request.events:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No events provided")

    db.upsert_session(request.session_id, datetime.now(timezone.utc).isoformat())
    event_records = [
        (
            request.session_id,
            event.type,
            event.t_start_ms,
            event.t_end_ms,
            event.confidence,
            event.source,
            event.payload_json and str(event.payload_json),
        )
        for event in request.events
    ]
    db.add_events(request.session_id, event_records)
    stitched = db.latest_stitched_for_session(request.session_id)
    stitched_count = 1 if stitched else 0
    return ImportAck(imported=True, stitched_assets=stitched_count, events_ingested=len(event_records))


@app.get("/api/v1/search", response_model=SearchResponse)
async def search_events(
    q: str,
    session_id: str | None = None,
    db: Database = Depends(get_db),
    _: str = Depends(require_auth),
) -> SearchResponse:
    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query string 'q' is required")
    results = [
        EventRecord(
            id=row["id"],
            session_id=row["session_id"],
            type=row["type"],
            t_start_ms=row["t_start_ms"],
            t_end_ms=row["t_end_ms"],
            confidence=row["confidence"],
            source=row["source"],
            payload_json=row["payload_json"],
        )
        for row in db.search_events(q, session_id)
    ]
    proxy = db.latest_stitched_for_session(session_id) if session_id else None
    stitched_proxy = _media_url(proxy["path_proxy"]) if proxy else None
    return SearchResponse(results=results, stitched_proxy=stitched_proxy)


@app.get("/api/v1/sessions", response_model=list[SessionSummary])
async def list_sessions(
    db: Database = Depends(get_db),
    _: str = Depends(require_auth),
) -> list[SessionSummary]:
    summaries: list[SessionSummary] = []
    for row in db.sessions():
        stitched = db.latest_stitched_for_session(row["id"])
        summaries.append(
            SessionSummary(
                id=row["id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                notes=row["notes"],
                camera_assets=row["camera_assets"],
                stitched_assets=row["stitched_assets"],
                events=row["events"],
                latest_proxy=_media_url(stitched["path_proxy"]) if stitched else None,
            )
        )
    return summaries


@app.get("/api/v1/sessions/{session_id}", response_model=SessionDetail)
async def session_detail(
    session_id: str,
    db: Database = Depends(get_db),
    _: str = Depends(require_auth),
) -> SessionDetail:
    session_row = db.session(session_id)
    if not session_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    stitched = db.latest_stitched_for_session(session_id)
    events = [
        EventRecord(
            id=row["id"],
            session_id=row["session_id"],
            type=row["type"],
            t_start_ms=row["t_start_ms"],
            t_end_ms=row["t_end_ms"],
            confidence=row["confidence"],
            source=row["source"],
            payload_json=row["payload_json"],
        )
        for row in db.session_events(session_id)
    ]
    return SessionDetail(
        id=session_row["id"],
        started_at=datetime.fromisoformat(session_row["started_at"]),
        notes=session_row["notes"],
        camera_assets=session_row["camera_assets"],
        stitched_assets=session_row["stitched_assets"],
        events=session_row["events"],
        latest_proxy=_media_url(stitched["path_proxy"]) if stitched else None,
        stitched_fullres=_media_url(stitched["path_fullres"]) if stitched else None,
        events_list=events,
    )


@app.get("/api/v1/sessions/{session_id}/events", response_model=list[EventRecord])
async def events_for_session(
    session_id: str,
    db: Database = Depends(get_db),
    _: str = Depends(require_auth),
) -> list[EventRecord]:
    events = db.session_events(session_id)
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or no events")
    return [
        EventRecord(
            id=row["id"],
            session_id=row["session_id"],
            type=row["type"],
            t_start_ms=row["t_start_ms"],
            t_end_ms=row["t_end_ms"],
            confidence=row["confidence"],
            source=row["source"],
            payload_json=row["payload_json"],
        )
        for row in events
    ]


@app.get("/api/v1/status")
async def status_report(db: Database = Depends(get_db), _: str = Depends(require_auth)) -> dict:
    return _status_payload(db)


@app.get("/", response_class=HTMLResponse)
async def landing(_: str = Depends(require_auth)) -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <title>Processing Station API</title>
        <style>
            :root { color-scheme: dark; }
            body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: #0b1025; color: #e8ecff; display: grid; place-items: center; min-height: 100vh; margin: 0; }
            .panel { max-width: 640px; padding: 28px; border-radius: 16px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); box-shadow: 0 24px 80px rgba(0,0,0,0.35); }
            h1 { margin-top: 0; font-size: 26px; }
            .muted { color: #9fb4d8; }
            a { color: #73f0c6; font-weight: 600; }
        </style>
    </head>
    <body>
        <div class="panel">
            <h1>Processing Station API</h1>
            <p class="muted">This container now exposes ingest + data endpoints only. Deploy the separate viewer container to browse stitched sessions, play proxies, and run natural-language search.</p>
            <p>Default API port: <strong>8001</strong>. Configure CORS via <code>VIEWER_ALLOWED_ORIGINS</code>. Media is still served under <code>/media</code>.</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/healthz")
async def health() -> dict:
    db_path = Path(_db.path).resolve()
    return {"ok": True, "database": str(db_path)}
