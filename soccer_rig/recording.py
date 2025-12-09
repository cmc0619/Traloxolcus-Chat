import base64
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

from .config import RigSettings, settings
from .models import RecordingDescriptor, RecordingState


class RecordingManager:
    def __init__(self, rig_settings: RigSettings):
        self.settings = rig_settings
        self._ensure_directories()
        self.current: Optional[RecordingDescriptor] = None
        self.recording_started_at: Optional[datetime] = None
        self._stop_event: Optional[threading.Event] = None
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._logs: List[str] = []
        self._last_manifest: Optional[Path] = None
        self._video_chunk: bytes = b""
        self._prepare_video_chunk()

    def _ensure_directories(self) -> None:
        self.settings.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.settings.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)

    def start_recording(
        self,
        session_id: Optional[str],
        duration_minutes: Optional[int],
        audio_enabled: Optional[bool] = None,
        test_mode: bool = False,
    ) -> RecordingDescriptor:
        with self._lock:
            if self.current:
                raise RuntimeError("recording already active")

            self._assert_disk_space()
            self._assert_camera_available()

            now = datetime.now(timezone.utc)
            session = session_id or now.strftime("%Y%m%dT%H%M%SZ")
            filename = self._build_filename(session, now)
            recording_path = self.settings.recordings_dir / filename
            audio_flag = self.settings.audio_enabled if audio_enabled is None else audio_enabled
            duration_seconds = 10 if test_mode else (duration_minutes or self.settings.duration_minutes_default) * 60

            descriptor = RecordingDescriptor(
                session_id=session,
                camera_id=self.settings.camera_id,
                file_name=filename,
                path=recording_path,
                manifest_path=self._manifest_path(session),
                start_time_local=now,
                start_time_master=now,
                duration_seconds=None,
                target_duration_seconds=duration_seconds,
                ended_at=None,
                codec=self.settings.codec,
                resolution=self.settings.resolution,
                fps=self.settings.fps,
                bitrate_mbps=self.settings.bitrate_mbps,
                audio_enabled=audio_flag,
                dropped_frames=0,
                offloaded=False,
                checksum_sha256=None,
                snapshot_b64=self._capture_snapshot(session, now),
            )

            self.current = descriptor
            self.recording_started_at = now
            self._stop_event = threading.Event()
            self._worker = threading.Thread(target=self._run_recording, daemon=True)
            self._worker.start()
            self._log(f"Recording started: {descriptor.file_name}")
            return descriptor

    def _run_recording(self) -> None:
        assert self.current is not None
        assert self._stop_event is not None
        path = self.current.path
        started = self.recording_started_at or datetime.now(timezone.utc)
        path.touch()
        target = self.current.target_duration_seconds or 0
        bytes_per_sec = max(len(self._video_chunk), int(self.settings.bitrate_mbps * 125_000))
        chunk = self._video_chunk if self._video_chunk else b"0" * bytes_per_sec
        next_tick = time.monotonic()
        try:
            with path.open("ab") as handle:
                while not self._stop_event.is_set():
                    now = datetime.now(timezone.utc)
                    elapsed = int((now - started).total_seconds())
                    handle.write(chunk)
                    handle.flush()
                    if target and elapsed >= target:
                        break
                    next_tick += 1
                    sleep_for = max(0, next_tick - time.monotonic())
                    if sleep_for:
                        time.sleep(sleep_for)
        finally:
            auto_finalized = not self._stop_event.is_set()
            self._finalize_recording(auto=auto_finalized)

    def stop_recording(self) -> Optional[Path]:
        with self._lock:
            if not self.current:
                return None
            if self._stop_event:
                self._stop_event.set()
            worker = self._worker
        if worker:
            worker.join()
        return self._last_manifest

    def list_recordings(self) -> List[RecordingDescriptor]:
        descriptors: List[RecordingDescriptor] = []
        for manifest in sorted(self.settings.manifests_dir.glob("*.json")):
            payload = json.loads(manifest.read_text())
            descriptors.append(self._descriptor_from_manifest(manifest, payload))
        with self._lock:
            if self.current:
                active = self.current.model_copy()
                if self.recording_started_at:
                    active.duration_seconds = int(
                        (datetime.now(timezone.utc) - self.recording_started_at).total_seconds()
                    )
                descriptors.append(active)
        return descriptors

    def mark_offloaded(self, session_id: str, camera_id: str, file_name: str, checksum: str) -> Optional[RecordingDescriptor]:
        manifests = sorted(self.settings.manifests_dir.glob("*.json"))
        for manifest in manifests:
            payload = json.loads(manifest.read_text())
            if (
                payload.get("session_id") == session_id
                and payload.get("camera_id") == camera_id
                and payload.get("file_name") == file_name
            ):
                recorded_checksum = payload.get("checksum", {}).get("value")
                if recorded_checksum and recorded_checksum != checksum:
                    raise ValueError("checksum mismatch")
                payload["offloaded"] = True
                manifest.write_text(json.dumps(payload, indent=2, default=str))
                descriptor = self._descriptor_from_manifest(manifest, payload)
                self._log(f"Offload confirmed for {file_name}")
                return descriptor
        return None

    def state(self) -> RecordingState:
        with self._lock:
            if not self.current:
                return RecordingState(active=False, ended_at=None)
            eta_seconds: Optional[int] = None
            elapsed_seconds: Optional[int] = None
            if self.recording_started_at:
                elapsed_seconds = int((datetime.now(timezone.utc) - self.recording_started_at).total_seconds())
                if self.current.target_duration_seconds:
                    remaining = self.current.target_duration_seconds - elapsed_seconds
                    eta_seconds = max(0, remaining)
            return RecordingState(
                active=True,
                file_name=self.current.file_name,
                session_id=self.current.session_id,
                started_at=self.recording_started_at,
                ended_at=None,
                eta_seconds=eta_seconds,
                elapsed_seconds=elapsed_seconds,
            )

    def cleanup_offloaded(self) -> List[Path]:
        removed: List[Path] = []
        free_gb = self._disk_free_gb()
        for manifest in sorted(self.settings.manifests_dir.glob("*.json")):
            payload = json.loads(manifest.read_text())
            offloaded = payload.get("offloaded", False)
            file_path = self.settings.recordings_dir / payload.get("file_name")
            should_delete = self.settings.delete_after_confirm and offloaded
            if not should_delete and free_gb < self.settings.free_space_min_gb:
                should_delete = offloaded
            if should_delete:
                if file_path.exists():
                    file_path.unlink()
                manifest.unlink()
                removed.append(file_path)
                free_gb = self._disk_free_gb()
        if removed:
            self._log(f"Removed {len(removed)} offloaded files")
        return removed

    def logs(self) -> List[str]:
        return list(self._logs)

    def _finalize_recording(self, auto: bool) -> None:
        with self._lock:
            if not self.current:
                return
            now = datetime.now(timezone.utc)
            elapsed = int((now - (self.recording_started_at or now)).total_seconds())
            self.current.duration_seconds = elapsed
            self.current.ended_at = now
            self.current.checksum_sha256 = self._compute_checksum(self.current.path)
            self._write_manifest(self.current)
            self._last_manifest = self.current.manifest_path
            finished_file = self.current.file_name
            self.current = None
            self.recording_started_at = None
            self._stop_event = None
            self._worker = None
        self._log(f"Recording completed: {finished_file} ({'auto' if auto else 'manual'})")

    def _build_filename(self, session_id: str, now: datetime) -> str:
        stamp = now.astimezone().strftime("%Y%m%d_%H%M%S")
        return f"{session_id}_{self.settings.camera_id}_{stamp}.mp4"

    def _manifest_path(self, session_id: str) -> Path:
        return self.settings.manifests_dir / f"{session_id}_{self.settings.camera_id}.json"

    def _write_manifest(self, descriptor: RecordingDescriptor) -> None:
        manifest = {
            "session_id": descriptor.session_id,
            "camera_id": descriptor.camera_id,
            "file_name": descriptor.file_name,
            "start_time_local": descriptor.start_time_local.isoformat(),
            "start_time_master": descriptor.start_time_master.isoformat() if descriptor.start_time_master else None,
            "offset_ms": 0,
            "duration": descriptor.duration_seconds,
            "ended_at": descriptor.ended_at.isoformat() if descriptor.ended_at else None,
            "resolution": descriptor.resolution,
            "fps": descriptor.fps,
            "codec": descriptor.codec,
            "bitrate_mbps": descriptor.bitrate_mbps,
            "dropped_frames": descriptor.dropped_frames,
            "audio_enabled": descriptor.audio_enabled,
            "camera_position": descriptor.camera_id,
            "snapshot_b64": descriptor.snapshot_b64,
            "checksum": {
                "algo": "sha256",
                "value": descriptor.checksum_sha256,
            },
            "offloaded": descriptor.offloaded,
            "software_version": self.settings.version,
        }
        descriptor.manifest_path.write_text(json.dumps(manifest, indent=2))

    def _descriptor_from_manifest(self, manifest: Path, payload: dict) -> RecordingDescriptor:
        return RecordingDescriptor(
            session_id=payload.get("session_id"),
            camera_id=payload.get("camera_id"),
            file_name=payload.get("file_name"),
            path=self.settings.recordings_dir / payload.get("file_name"),
            manifest_path=manifest,
            start_time_local=datetime.fromisoformat(payload.get("start_time_local")),
            start_time_master=datetime.fromisoformat(payload.get("start_time_master"))
            if payload.get("start_time_master")
            else None,
            duration_seconds=payload.get("duration"),
            target_duration_seconds=None,
            ended_at=datetime.fromisoformat(payload.get("ended_at")) if payload.get("ended_at") else None,
            codec=payload.get("codec"),
            resolution=payload.get("resolution"),
            fps=payload.get("fps"),
            bitrate_mbps=payload.get("bitrate_mbps"),
            audio_enabled=payload.get("audio_enabled", True),
            dropped_frames=payload.get("dropped_frames", 0),
            offloaded=payload.get("offloaded", False),
            checksum_sha256=payload.get("checksum", {}).get("value"),
            snapshot_b64=payload.get("snapshot_b64"),
        )

    def _compute_checksum(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _disk_free_gb(self) -> float:
        usage = shutil.disk_usage(self.settings.base_dir)
        return round(usage.free / (1024**3), 2)

    def _assert_disk_space(self) -> None:
        free_gb = self._disk_free_gb()
        if free_gb < self.settings.free_space_min_gb:
            raise RuntimeError("insufficient free space for recording")

    def _assert_camera_available(self) -> None:
        if not os.access(self.settings.base_dir, os.W_OK):
            raise RuntimeError("camera or storage unavailable: cannot write to base dir")

    def _capture_snapshot(self, session_id: str, started: datetime) -> Optional[str]:
        width, height = 640, 360
        image = Image.new("RGB", (width, height), color=(30, 60, 90))
        draw = ImageDraw.Draw(image)
        text = f"{session_id}\n{self.settings.camera_id}\n{started.isoformat()}"
        try:
            font = ImageFont.load_default()
        except OSError:
            font = None
        draw.multiline_text((20, 20), text, fill=(255, 255, 255), font=font, spacing=6)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        snapshot_path = self.settings.snapshots_dir / f"{session_id}_{self.settings.camera_id}.png"
        snapshot_path.write_bytes(buffer.getvalue())
        return data

    def _prepare_video_chunk(self) -> None:
        bytes_per_sec = max(1024, int(self.settings.bitrate_mbps * 125_000))
        marker = f"{datetime.now(timezone.utc).isoformat()}|{self.settings.camera_id}|".encode("utf-8")
        padding = b"#" * max(0, bytes_per_sec - len(marker))
        self._video_chunk = marker + padding

    def _log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = f"{timestamp} {message}"
        self._logs.append(entry)
        if len(self._logs) > 200:
            self._logs = self._logs[-200:]
        if not self.settings.production_mode:
            log_file = self.settings.logs_dir / "recorder.log"
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(entry + "\n")


recorder = RecordingManager(settings)
