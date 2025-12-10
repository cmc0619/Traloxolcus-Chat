"""Manifest helpers for recorded sessions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class RecordingManifest:
    session_id: str
    camera_id: str
    file_name: str
    start_time_master: datetime
    start_time_local: datetime
    offset_ms: float
    duration: Optional[int]
    resolution: str
    fps: int
    codec: str
    bitrate_mbps: float
    dropped_frames: int
    audio_enabled: bool
    camera_position: str
    checksum_sha256: Optional[str]
    snapshot_b64: Optional[str]
    offloaded: bool
    software_version: str

    def to_json(self) -> str:
        payload = asdict(self)
        payload["start_time_master"] = self.start_time_master.isoformat()
        payload["start_time_local"] = self.start_time_local.isoformat()
        return json.dumps(payload, indent=2)


def write_manifest(manifest: RecordingManifest, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.to_json(), encoding="utf-8")
    return target

