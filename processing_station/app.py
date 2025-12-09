"""FastAPI application for processing-station ingest and search."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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


@app.get("/healthz")
async def health() -> dict:
    db_path = Path(_db.path).resolve()
    return {"ok": True, "database": str(db_path)}
