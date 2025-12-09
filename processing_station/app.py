"""FastAPI application for processing-station ingest and search."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status

from .database import Database
from .schemas import (
    EventRecord,
    EventsRequest,
    ImportAck,
    SearchResponse,
    SessionSummary,
    StitchRequest,
    StitchResponse,
    UploadResponse,
)
from .storage import Storage

app = FastAPI(title="Processing Station", version="0.1.0")
_db = Database()
_storage = Storage()


def get_db() -> Database:
    return _db


def get_storage() -> Storage:
    return _storage


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
async def search_events(q: str, session_id: str | None = None, db: Database = Depends(get_db)) -> SearchResponse:
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
    stitched_proxy = proxy["path_proxy"] if proxy else None
    return SearchResponse(results=results, stitched_proxy=stitched_proxy)


@app.get("/api/v1/sessions", response_model=list[SessionSummary])
async def list_sessions(db: Database = Depends(get_db)) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            notes=row["notes"],
            camera_assets=row["camera_assets"],
            stitched_assets=row["stitched_assets"],
            events=row["events"],
        )
        for row in db.sessions()
    ]


@app.get("/api/v1/sessions/{session_id}/events", response_model=list[EventRecord])
async def events_for_session(session_id: str, db: Database = Depends(get_db)) -> list[EventRecord]:
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
async def status_report(db: Database = Depends(get_db)) -> dict:
    return _status_payload(db)


@app.get("/", response_class=HTMLResponse)
async def status_page(db: Database = Depends(get_db)) -> HTMLResponse:
    payload = _status_payload(db)
    gpu_section = """<p>No GPU detected.</p>""" if not payload["gpu"] else "".join(
        f"<div class='card'><h3>{gpu['name']}</h3><p>Memory: {gpu['memory_used_mb']:.0f} / {gpu['memory_total_mb']:.0f} MB</p><p>Utilization: {gpu['utilization_percent']}%</p></div>"
        for gpu in payload["gpu"]
    )
    sessions_section = """<p>No sessions ingested.</p>""" if not payload["sessions"] else "".join(
        """
        <div class='card'>
            <h3>Session {id}</h3>
            <p>Started: {started_at}</p>
            <p>Cameras: {camera_assets} / 3</p>
            <p>Stitched assets: {stitched_assets}</p>
            <p>Events: {events}</p>
            <p class='{viewer_class}'>Viewer upload ready: {viewer_ready}</p>
            <p class='{waiting_class}'>Waiting for cameras: {waiting}</p>
        </div>
        """.format(
            id=session["id"],
            started_at=session["started_at"],
            camera_assets=session["camera_assets"],
            stitched_assets=session["stitched_assets"],
            events=session["events"],
            viewer_ready="Yes" if session["viewer_ready"] else "No",
            waiting="Yes" if session["waiting_for_cameras"] else "No",
            viewer_class="ok" if session["viewer_ready"] else "warn",
            waiting_class="warn" if session["waiting_for_cameras"] else "ok",
        )
        for session in payload["sessions"]
    )

    html = f"""
    <html>
    <head>
        <title>Processing Station Status</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #0b1021; color: #e5e7ef; margin: 0; padding: 0; }}
            header {{ background: #131938; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }}
            h1 {{ margin: 0; font-size: 20px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; padding: 24px; }}
            .card {{ background: #192344; padding: 16px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
            .metric {{ font-size: 24px; margin: 4px 0; }}
            .muted {{ color: #9aa3c2; }}
            .warn {{ color: #f6a609; font-weight: bold; }}
            .ok {{ color: #45d483; font-weight: bold; }}
            a {{ color: #8ac7ff; }}
        </style>
    </head>
    <body>
        <header>
            <div>
                <h1>Processing Station Status</h1>
                <div class='muted'>System health, ingest, and viewer readiness</div>
            </div>
            <div class='muted'>Updated {datetime.now(timezone.utc).isoformat()}</div>
        </header>
        <div class='grid'>
            <div class='card'>
                <h3>Disk</h3>
                <div class='metric'>{payload['system']['disk']['used_gb']} / {payload['system']['disk']['total_gb']} GB</div>
                <div class='muted'>{payload['system']['disk']['percent']}% used</div>
            </div>
            <div class='card'>
                <h3>Memory</h3>
                <div class='metric'>{payload['system']['memory']['used_gb']} / {payload['system']['memory']['total_gb']} GB</div>
                <div class='muted'>{payload['system']['memory']['percent']}% used</div>
            </div>
            <div class='card'>
                <h3>CPU</h3>
                <div class='metric'>{payload['system']['cpu_percent']}%</div>
                <div class='muted'>Recent utilization</div>
            </div>
        </div>
        <div class='grid'>
            <div class='card'>
                <h2>GPU</h2>
                {gpu_section}
            </div>
            <div class='card'>
                <h2>Sessions</h2>
                {sessions_section}
            </div>
        </div>
        <div style='padding: 0 24px 24px;'>
            <p class='muted'>API endpoints: <a href='/docs'>/docs</a> | <a href='/api/v1/status'>/api/v1/status</a></p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/healthz")
async def health() -> dict:
    db_path = Path(_db.path).resolve()
    return {"ok": True, "database": str(db_path)}
