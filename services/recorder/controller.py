"""Recorder controller implementing the libcamera→ffmpeg pipeline."""

from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..sync.telemetry import chrony_telemetry
from . import gates
from .manifest import RecordingManifest, write_manifest


@dataclass(slots=True)
class ActiveRecording:
    session_id: str
    camera_id: str
    file_path: Path
    manifest_path: Path
    started_at: datetime
    target_duration: Optional[int]
    process: Optional[subprocess.Popen]
    audio_enabled: bool
    bitrate_mbps: float
    codec: str
    resolution: str
    fps: int
    offset_ms: float
    start_time_master: datetime
    start_time_local: datetime
    snapshot_b64: Optional[str] = None


class RecorderController:
    """Manage a single camera recording session.

    The controller can operate in `simulate` mode where the pipeline command is
    not executed. In that mode we still honor readiness gates, emit manifests,
    and write placeholder files so downstream code can exercise the full flow
    without camera hardware.
    """

    def __init__(
        self,
        base_dir: Path,
        camera_id: str,
        version: str,
        bitrate_mbps: float = 30.0,
        codec: str = "h265",
        resolution: str = "3840x2160",
        fps: int = 30,
        audio_enabled: bool = True,
        simulate: bool = False,
    ) -> None:
        self.base_dir = base_dir
        self.camera_id = camera_id
        self.version = version
        self.bitrate_mbps = bitrate_mbps
        self.codec = codec
        self.resolution = resolution
        self.fps = fps
        self.audio_enabled_default = audio_enabled
        self.simulate = simulate
        self.recordings_dir = base_dir / "recordings"
        self.manifests_dir = base_dir / "manifests"
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self._active: Optional[ActiveRecording] = None
        self._lock = threading.Lock()

    def gates(self, minimum_free_gb: float) -> list[gates.GateReport]:
        return gates.all_gates(self.base_dir, minimum_free_gb)

    def start(
        self,
        session_id: str,
        minimum_free_gb: float,
        audio_enabled: Optional[bool] = None,
        bitrate_mbps: Optional[float] = None,
        codec: Optional[str] = None,
        resolution: Optional[str] = None,
        fps: Optional[int] = None,
        test_mode: bool = False,
    ) -> ActiveRecording:
        with self._lock:
            if self._active:
                raise RuntimeError("recording already active")

            reports = self.gates(minimum_free_gb)
            failures = [r.reason for r in reports if not r.ok]
            if failures:
                raise RuntimeError("; ".join(reason for reason in failures if reason))

            now = datetime.now(timezone.utc)
            filename = f"{session_id}_{self.camera_id}_{now:%Y%m%d}_{now:%H%M%S}.mp4"
            file_path = self.recordings_dir / filename
            manifest_path = self.manifests_dir / f"{session_id}_{self.camera_id}.json"
            selected_bitrate = bitrate_mbps or self.bitrate_mbps
            selected_codec = codec or self.codec
            audio_flag = self.audio_enabled_default if audio_enabled is None else audio_enabled
            selected_resolution = resolution or self.resolution
            selected_fps = fps or self.fps
            target_duration = 10 if test_mode else None

            if selected_codec not in {"h265", "h264"}:
                raise RuntimeError(f"unsupported codec: {selected_codec}")

            try:
                width_str, height_str = selected_resolution.lower().split("x")
                width = int(width_str)
                height = int(height_str)
            except (ValueError, AttributeError):
                raise RuntimeError(f"invalid resolution: {selected_resolution}") from None

            telemetry = chrony_telemetry(role="recorder")

            process: Optional[subprocess.Popen] = None
            if self.simulate:
                file_path.write_bytes(b"simulated clip\n")
            else:
                cmd = self._build_pipeline(
                    destination=file_path,
                    bitrate_mbps=selected_bitrate,
                    codec=selected_codec,
                    audio_enabled=audio_flag,
                    width=width,
                    height=height,
                    fps=selected_fps,
                )
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if process.stderr:
                    threading.Thread(
                        target=self._log_pipeline_output,
                        args=(process.stderr,),
                        daemon=True,
                    ).start()
                if target_duration:
                    threading.Thread(target=self._stop_after, args=(target_duration,), daemon=True).start()

            self._active = ActiveRecording(
                session_id=session_id,
                camera_id=self.camera_id,
                file_path=file_path,
                manifest_path=manifest_path,
                started_at=now,
                target_duration=target_duration,
                process=process,
                audio_enabled=audio_flag,
                bitrate_mbps=selected_bitrate,
                codec=selected_codec,
                resolution=selected_resolution,
                fps=selected_fps,
                offset_ms=telemetry.offset_ms,
                start_time_master=telemetry.master_timestamp,
                start_time_local=telemetry.local_timestamp,
                snapshot_b64=None,
            )
            return self._active

    def _stop_after(self, seconds: int) -> None:
        time.sleep(seconds)
        self.stop()

    def stop(self) -> Path:
        with self._lock:
            if not self._active:
                raise RuntimeError("no active recording")
            record = self._active
            self._active = None

        if record.process:
            record.process.terminate()
            try:
                record.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                record.process.kill()

        duration = int((datetime.now(timezone.utc) - record.started_at).total_seconds())
        checksum = self._checksum(record.file_path)
        manifest = RecordingManifest(
            session_id=record.session_id,
            camera_id=record.camera_id,
            file_name=record.file_path.name,
            start_time_master=record.start_time_master,
            start_time_local=record.start_time_local,
            offset_ms=record.offset_ms,
            duration=duration,
            resolution=record.resolution,
            fps=record.fps,
            codec=record.codec,
            bitrate_mbps=record.bitrate_mbps,
            dropped_frames=0,
            audio_enabled=record.audio_enabled,
            camera_position=record.camera_id,
            checksum_sha256=checksum,
            snapshot_b64=None,
            offloaded=False,
            software_version=self.version,
        )
        write_manifest(manifest, record.manifest_path)
        return record.manifest_path

    def run_self_test(self, minimum_free_gb: float) -> dict:
        reports = self.gates(minimum_free_gb)
        return {
            "passed": all(r.ok for r in reports),
            "details": [r.reason or "ok" for r in reports],
        }

    def _build_pipeline(
        self,
        *,
        destination: Path,
        bitrate_mbps: float,
        codec: str,
        audio_enabled: bool,
        width: int,
        height: int,
        fps: int,
    ) -> list[str]:
        audio_stage = "-an"
        if audio_enabled:
            audio_stage = "-f alsa -thread_queue_size 1024 -i plughw:1,0 -map 0:v:0 -map 1:a:0 -c:a aac -b:a 128k"

        video_stage = (
            "libcamera-vid --nopreview "
            f"--width {width} --height {height} --framerate {fps} "
            f"--codec {codec} --bitrate {int(bitrate_mbps * 1_000_000)} --profile high --level 5.1 "
            "--inline -t 0 -o -"
        )
        ffmpeg_stage = (
            "ffmpeg -y -loglevel info -stats -i pipe:0 "
            f"{audio_stage if audio_enabled else '-an'} -c:v copy -movflags +faststart {destination}"
        )
        pipeline = f"{video_stage} | {ffmpeg_stage}"
        return ["bash", "-lc", pipeline]

    def _checksum(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _log_pipeline_output(self, stream) -> None:  # pragma: no cover - threaded logging helper
        for line in stream:
            line = line.strip()
            if line:
                print(f"[recorder] {line}")

