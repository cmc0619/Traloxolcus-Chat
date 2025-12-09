"""Status helpers for surfacing recorder health and manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from recording import Recorder, RecordingEntry


@dataclass
class RecorderStatus:
    camera_id: str
    recording: bool
    audio_enabled: bool
    dropped_frames: int
    encode_errors: int
    last_pipeline_error: str | None
    start_time_master: str | None
    start_time_local: str | None

    @property
    def has_encoder_failure(self) -> bool:
        return self.encode_errors > 0

    @property
    def has_drop_frame_issue(self) -> bool:
        return self.dropped_frames > 0


def build_status_payload(recorder: Recorder) -> dict:
    metrics = recorder.last_metrics()
    status = RecorderStatus(
        camera_id=recorder.camera_id,
        recording=recorder.recording,
        audio_enabled=recorder.audio_enabled,
        dropped_frames=metrics.dropped_frames,
        encode_errors=metrics.encode_errors,
        last_pipeline_error=recorder.last_pipeline_error,
        start_time_master=recorder.last_master_timestamp,
        start_time_local=recorder.last_local_timestamp,
    )
    payload = asdict(status)
    payload["has_encoder_failure"] = status.has_encoder_failure
    payload["has_drop_frame_issue"] = status.has_drop_frame_issue
    return payload


def recordings_payload(entries: Iterable[RecordingEntry]) -> list[dict]:
    return [asdict(entry) for entry in entries]
