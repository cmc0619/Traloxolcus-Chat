# Recorder Rig Notes

This file is a scratchpad for ideas and code sketches about the three-node soccer camera rig. It mixes personal commentary with practical snippets that might evolve into production code.

## Thoughts

- Keeping the recording loop boring is a feature; anything surprising (CPU spikes, throttling, sync drift) needs immediate surfacing in the UI and audible alerts.
- I want each Pi to be able to "sulk" gracefully when something is wrong: refuse to start, tell the operator exactly why, and log it in Development Mode only.
- Cross-node empathy matters; if CAM_L is unhappy about sync, CAM_C and CAM_R should echo that sentiment in their dashboards so the operator can tell at a glance.
- Updates should feel like pit stops: quick, safe, and never while a lap (recording) is underway.

## Implementation Sketches

### Status Model
```python
from dataclasses import dataclass, asdict
from typing import Literal, Optional

CameraID = Literal["CAM_L", "CAM_C", "CAM_R"]

@dataclass
class NodeStatus:
    camera_id: CameraID
    recording: bool
    resolution: str
    fps: int
    codec: str
    bitrate_mbps: float
    nvme_free_gb: float
    estimated_minutes_remaining: int
    battery_percent: Optional[int]
    temperature_c: float
    time_offset_ms: float
    warning: Optional[str] = None

    def to_json(self) -> dict:
        # Future hook to trim internal details in Production Mode.
        return asdict(self)
```

### Simple In-Memory Manifest
```python
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

class SessionManifest:
    def __init__(self, session_id: str, camera_id: CameraID, root: Path):
        self.session_id = session_id
        self.camera_id = camera_id
        self.root = root
        self.records: list[dict] = []

    def add_recording(
        self,
        file_name: str,
        start_time_local: datetime,
        start_time_master: datetime,
        offset_ms: float,
        duration_s: int,
        resolution: str,
        fps: int,
        codec: str,
        bitrate_mbps: float,
        dropped_frames: int,
        checksum: str,
        offloaded: bool,
        snapshot_b64: Optional[str] = None,
    ) -> None:
        self.records.append(
            {
                "file": file_name,
                "start_time_local": start_time_local.isoformat(),
                "start_time_master": start_time_master.isoformat(),
                "offset_ms": offset_ms,
                "duration_s": duration_s,
                "resolution": resolution,
                "fps": fps,
                "codec": codec,
                "bitrate_mbps": bitrate_mbps,
                "dropped_frames": dropped_frames,
                "snapshot_b64": snapshot_b64,
                "checksum_sha256": checksum,
                "offloaded": offloaded,
            }
        )

    def save(self) -> Path:
        out = self.root / f"{self.session_id}_{self.camera_id}.json"
        out.write_text(json.dumps({"session_id": self.session_id, "camera_id": self.camera_id, "recordings": self.records}, indent=2))
        return out
```

### REST Handlers (sketch)
```python
from aiohttp import web

routes = web.RouteTableDef()

@routes.get("/api/v1/status")
async def get_status(request: web.Request) -> web.Response:
    status: NodeStatus = request.app["status"]
    return web.json_response(status.to_json())

@routes.post("/api/v1/record/start")
async def record_start(request: web.Request) -> web.Response:
    controller = request.app["recorder"]
    if controller.recording:
        raise web.HTTPConflict(reason="Recording already active")
    await controller.start()
    return web.json_response({"ok": True})

@routes.post("/api/v1/record/stop")
async def record_stop(request: web.Request) -> web.Response:
    controller = request.app["recorder"]
    await controller.stop()
    return web.json_response({"ok": True})
```

These snippets are intentionally lightweight so they can be adapted into the eventual camera service without locking in implementation details.
