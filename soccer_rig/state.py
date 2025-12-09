from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import (
    CameraStatus,
    Config,
    ConfirmRequest,
    DiskStatus,
    Manifest,
    RecordingInfo,
    RecordStopResponse,
    SelfTestResult,
    SyncStatus,
    TestRecordingResult,
    UpdateStatus,
)


class RigState:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        disk = DiskStatus(total_gb=512.0, free_gb=480.0, estimated_minutes_remaining=120)
        sync = SyncStatus(
            role="ntp-master",
            offset_ms=0.0,
            confidence="locked",
            master_timestamp=now,
            local_timestamp=now,
        )
        self.config = Config(camera_id="CAM_C")
        self.camera_status = CameraStatus(
            camera_id=self.config.camera_id,
            recording=False,
            active_session=None,
            disk=disk,
            sync=sync,
            live_preview_url="/preview.jpg",
        )
        self.recordings: Dict[str, RecordingInfo] = {}
        self.active_recording_id: Optional[str] = None

    def start_recording(self, session_id: str, camera_id: str, **overrides) -> RecordingInfo:
        self._ensure_storage_capacity()
        now = datetime.now(timezone.utc)
        filename = f"{session_id}_{camera_id}_{now:%Y%m%d}_{now:%H%M%S}.mp4"
        record = RecordingInfo(
            session_id=session_id,
            camera_id=camera_id,
            filename=filename,
            started_at=now,
            master_start=self.camera_status.sync.master_timestamp,
            local_start=self.camera_status.sync.local_timestamp,
            audio_enabled=overrides.get("audio_enabled", True),
            bitrate_mbps=overrides.get("bitrate_mbps", self.config.bitrate_mbps),
            codec=overrides.get("codec", self.config.codec),
        )
        self.recordings[filename] = record
        self.camera_status.recording = True
        self.camera_status.active_session = session_id
        self.camera_status.audio_enabled = record.audio_enabled
        self.camera_status.bitrate_mbps = record.bitrate_mbps
        self.camera_status.codec = record.codec
        self.active_recording_id = filename
        self._refresh_disk_estimate(record.bitrate_mbps)
        return record

    def stop_recording(self) -> RecordStopResponse:
        if not self.active_recording_id:
            raise ValueError("No active recording")
        record = self.recordings[self.active_recording_id]
        session_id = record.session_id
        now = datetime.now(timezone.utc)
        duration = int((now - record.started_at).total_seconds())
        record.duration_seconds = duration
        record.size_gb = self._reduce_disk_by(record.bitrate_mbps, duration)
        self.camera_status.recording = False
        self.camera_status.active_session = None
        self.active_recording_id = None
        return RecordStopResponse(session_id=session_id, camera_id=record.camera_id, duration_seconds=duration)

    def confirm_offload(self, request: ConfirmRequest) -> RecordingInfo:
        record = self._find_recording(request.session_id, request.file)
        if request.checksum.algo.lower() != "sha256":
            raise ValueError("Unsupported checksum algorithm")
        record.offloaded = True
        record.checksum_sha256 = request.checksum.value
        record.marked_for_deletion = self.config.delete_after_confirm
        if record.marked_for_deletion:
            self._delete_recording(record.filename)
        else:
            self._maybe_cleanup_storage()
        return record

    def run_self_test(self) -> SelfTestResult:
        details = [
            "Camera detected",
            "NVMe writable",
            "NTP synchronized",
            "Preview available",
        ]
        return SelfTestResult(passed=True, details=details)

    def run_test_recording(self) -> TestRecordingResult:
        """Simulate a 10-second test recording with disk accounting."""
        self._ensure_storage_capacity()
        record = self.start_recording(session_id="TEST", camera_id=self.config.camera_id, bitrate_mbps=10.0)
        record.duration_seconds = 10
        record.size_gb = self._reduce_disk_by(record.bitrate_mbps, record.duration_seconds)
        self.camera_status.recording = False
        self.camera_status.active_session = None
        self.active_recording_id = None
        self._delete_recording(record.filename)
        return TestRecordingResult(passed=True, duration_seconds=10, detail="Test clip captured")

    def manifest(self) -> Manifest:
        return Manifest(**self.camera_status.model_dump(), recording_files=list(self.recordings.values()))

    def update_check(self) -> UpdateStatus:
        latest = "soccer-rig-1.2.0"
        return UpdateStatus(
            current_version=self.config.version,
            latest_version=latest,
            update_available=self.config.version != latest,
        )

    def apply_update(self) -> UpdateStatus:
        status = self.update_check()
        if self.camera_status.recording:
            raise RuntimeError("Recording in progress")
        self.config.version = status.latest_version
        return self.update_check()

    def update_config(self, partial: dict) -> Config:
        for key, value in partial.items():
            if key == "min_free_gb":
                key = "free_space_min_gb"
            if value is not None and hasattr(self.config, key):
                setattr(self.config, key, value)
        # ensure status reflects updated config
        self.camera_status.camera_id = self.config.camera_id
        self.camera_status.codec = self.config.codec
        self.camera_status.bitrate_mbps = self.config.bitrate_mbps
        self.camera_status.audio_enabled = self.config.audio_enabled
        self.camera_status.resolution = self.config.resolution
        self.camera_status.fps = self.config.fps
        self._refresh_disk_estimate(self.camera_status.bitrate_mbps)
        return self.config

    def get_recordings(self) -> List[RecordingInfo]:
        return list(self.recordings.values())

    def _refresh_disk_estimate(self, bitrate_mbps: float) -> None:
        minutes = int((self.camera_status.disk.free_gb * 1024 * 8) / bitrate_mbps / 60)
        self.camera_status.disk.estimated_minutes_remaining = max(minutes, 0)

    def _reduce_disk_by(self, bitrate_mbps: float, duration_seconds: int) -> float:
        consumed_mb = (bitrate_mbps / 8) * duration_seconds
        consumed_gb = consumed_mb / 1024
        self.camera_status.disk.free_gb = max(self.camera_status.disk.free_gb - consumed_gb, 0)
        self._refresh_disk_estimate(bitrate_mbps)
        return consumed_gb

    def _find_recording(self, session_id: str, filename: str) -> RecordingInfo:
        record = self.recordings.get(filename)
        if not record or record.session_id != session_id:
            raise KeyError("Recording not found")
        return record

    def _delete_recording(self, filename: str) -> None:
        record = self.recordings.pop(filename, None)
        if record and record.size_gb:
            self.camera_status.disk.free_gb += record.size_gb
            self._refresh_disk_estimate(self.camera_status.bitrate_mbps)

    def _ensure_storage_capacity(self) -> None:
        if self.camera_status.disk.free_gb < self.config.free_space_min_gb:
            raise ValueError("Insufficient free space")

    def _maybe_cleanup_storage(self) -> None:
        if self.camera_status.disk.free_gb >= self.config.free_space_min_gb:
            return
        for filename, record in list(self.recordings.items()):
            if record.offloaded:
                self._delete_recording(filename)
                if self.camera_status.disk.free_gb >= self.config.free_space_min_gb:
                    break


state = RigState()
