"""Pydantic models for processing-station API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


class UploadResponse(BaseModel):
    session_id: str
    camera_id: str
    path: str
    manifest_recorded: bool = Field(
        description="True when the upload has been persisted to the metadata store."
    )


class CameraAsset(BaseModel):
    id: int
    session_id: str
    camera_id: str
    path: str
    codec: Optional[str]
    fps: Optional[float]
    bitrate_mbps: Optional[float]
    offset_ms: Optional[int]


class StitchRequest(BaseModel):
    session_id: str
    layout: str = Field(examples=["three_up", "center_with_insets"])
    path_fullres: Optional[str] = Field(
        None, description="Optional path if an external stitcher already produced an asset."
    )
    path_proxy: Optional[str] = Field(None, description="Proxy clip path for quick viewing.")
    checksum_sha256: Optional[str]


class StitchResponse(BaseModel):
    session_id: str
    layout: str
    path_fullres: str
    path_proxy: Optional[str]
    checksum_sha256: Optional[str]


class EventPayload(BaseModel):
    type: str = Field(examples=["pass", "turnover", "gk_save"])
    t_start_ms: int
    t_end_ms: int
    confidence: Optional[float] = Field(None, ge=0, le=1)
    source: Optional[str] = Field(None, description="Which pipeline produced this event")
    payload_json: Optional[Any] = Field(None, description="Additional classifier metadata")


class EventsRequest(BaseModel):
    session_id: str
    events: list[EventPayload]


class EventRecord(EventPayload):
    id: int
    session_id: str


class SearchResponse(BaseModel):
    results: list[EventRecord]
    stitched_proxy: Optional[HttpUrl | str] = Field(
        None,
        description="If available, a proxy clip URI for quick preview of the session.",
    )


class SessionSummary(BaseModel):
    id: str
    started_at: datetime
    notes: Optional[str]
    camera_assets: int
    stitched_assets: int
    events: int
    latest_proxy: Optional[str]


class SessionDetail(SessionSummary):
    stitched_fullres: Optional[str]
    events_list: list[EventRecord]


class ImportAck(BaseModel):
    imported: bool
    stitched_assets: int
    events_ingested: int
