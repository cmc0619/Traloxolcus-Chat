"""Recording pipeline for the soccer rig.

This module wires libcamera and ffmpeg together to record
3840x2160@30fps H.265 video to NVMe while optionally muxing
microphone audio. It also tracks encoder anomalies for surfacing
through status endpoints and manifests.
"""

from __future__ import annotations

import json
import logging
import math
import re
import struct
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class RecordingMetrics:
    """Captures runtime errors and data quality counters."""

    dropped_frames: int = 0
    encode_errors: int = 0

    def bump_from_log_line(self, line: str) -> None:
        lowered = line.lower()
        drop_match = re.search(r"drop=\s*(\d+)", lowered)
        if drop_match:
            self.dropped_frames = max(self.dropped_frames, int(drop_match.group(1)))
        if "error" in lowered:
            self.encode_errors += 1


@dataclass
class RecordingEntry:
    file_path: str
    start_time_local: str
    start_time_master: str
    duration_s: Optional[float]
    audio_enabled: bool
    dropped_frames: int
    encode_errors: int


@dataclass
class RecordingManifest:
    path: Path
    entries: list[RecordingEntry] = field(default_factory=list)

    def add_entry(self, entry: RecordingEntry) -> None:
        self.entries.append(entry)
        self.save()

    def save(self) -> None:
        payload = [asdict(entry) for entry in self.entries]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: Path) -> "RecordingManifest":
        if not path.exists():
            return cls(path=path)
        data = json.loads(path.read_text())
        entries = [RecordingEntry(**item) for item in data]
        return cls(path=path, entries=entries)


class Recorder:
    """Coordinates the libcamera/ffmpeg pipeline and metadata bookkeeping."""

    def __init__(self, nvme_root: Path, camera_id: str, manifest_name: str = "manifest.json"):
        self.nvme_root = nvme_root
        self.camera_id = camera_id
        self.manifest = RecordingManifest.load(nvme_root / manifest_name)
        self._process: Optional[subprocess.Popen[str]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._metrics = RecordingMetrics()
        self._start_time: Optional[float] = None
        self._current_destination: Optional[Path] = None
        self._audio_enabled: bool = False
        self.last_master_timestamp: Optional[str] = None
        self.last_local_timestamp: Optional[str] = None
        self.last_pipeline_error: Optional[str] = None

    @property
    def recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def audio_enabled(self) -> bool:
        return self._audio_enabled

    def _emit_start_tone(self, frequency_hz: int = 880, duration_s: float = 0.2) -> None:
        sample_rate = 44100
        total_samples = int(sample_rate * duration_s)
        temp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                with wave.open(temp_wav, "w") as wav_out:
                    wav_out.setnchannels(1)
                    wav_out.setsampwidth(2)
                    wav_out.setframerate(sample_rate)
                    for i in range(total_samples):
                        value = int(32767.0 * math.sin(2 * math.pi * frequency_hz * (i / sample_rate)))
                        wav_out.writeframes(struct.pack("<h", value))
                temp_path = temp_wav.name
            subprocess.run(
                ["aplay", temp_path], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    logger.debug("Failed to clean up temp tone file at %s", temp_path)

    def _chrony_timestamps(self) -> tuple[str, str]:
        now_local = datetime.now(timezone.utc)
        master_ts = "unknown"
        try:
            output = subprocess.check_output(["chronyc", "tracking"], text=True, stderr=subprocess.STDOUT)
            for line in output.splitlines():
                if line.lower().startswith("reference time"):
                    master_ts = line.split(":", 1)[1].strip()
                    break
        except (subprocess.CalledProcessError, FileNotFoundError):
            master_ts = "chrony_unavailable"
        return master_ts, now_local.isoformat()

    def _build_pipeline_command(self, destination: Path, audio_enabled: bool) -> list[str]:
        bitrate = 32000000  # ~32 Mbps
        video_stage = (
            "libcamera-vid --nopreview --width 3840 --height 2160 --framerate 30 "
            f"--codec h265 --bitrate {bitrate} --profile high --level 5.1 --inline -t 0 -o -"
        )
        audio_stage = "-an"
        if audio_enabled:
            audio_stage = "-f alsa -thread_queue_size 512 -i plughw:1,0 -map 0:v:0 -map 1:a:0 -c:a aac -b:a 128k"
        ffmpeg_stage = (
            "ffmpeg -y -loglevel info -stats -i pipe:0 "
            f"{audio_stage if audio_enabled else '-an'} "
            "-c:v copy -movflags +faststart "
            f"{destination}"
        )
        pipeline = f"{video_stage} | {ffmpeg_stage}"
        return ["bash", "-lc", pipeline]

    def _monitor_stderr(self, stderr: Iterable[str]) -> None:
        for line in stderr:
            line = line.strip()
            if not line:
                continue
            self._metrics.bump_from_log_line(line)
            if "error" in line.lower():
                self.last_pipeline_error = line
            logger.debug("pipeline: %s", line)

    def start_recording(self, session_id: str, audio_enabled: bool) -> Path:
        if self.recording:
            raise RuntimeError("Recording already active")

        self._metrics = RecordingMetrics()
        self.last_pipeline_error = None
        destination = self._output_path(session_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._current_destination = destination
        self._audio_enabled = audio_enabled

        master_ts, local_ts = self._chrony_timestamps()
        self.last_master_timestamp = master_ts
        self.last_local_timestamp = local_ts

        self._emit_start_tone()

        command = self._build_pipeline_command(destination, audio_enabled)
        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
        )
        self._process = process
        self._start_time = time.time()
        if process.stderr is not None:
            self._monitor_thread = threading.Thread(
                target=self._monitor_stderr, args=(process.stderr,), daemon=True
            )
            self._monitor_thread.start()
        return destination

    def stop_recording(self, audio_enabled: Optional[bool] = None) -> Optional[RecordingEntry]:
        if not self.recording:
            return None
        assert self._process is not None
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)
        if self._process.returncode not in (0, None):
            self._metrics.encode_errors += 1
            if not self.last_pipeline_error:
                self.last_pipeline_error = f"pipeline exited with {self._process.returncode}"
        if audio_enabled is not None:
            self._audio_enabled = audio_enabled
        duration_s = None
        if self._start_time is not None:
            duration_s = time.time() - self._start_time
        entry = self._create_manifest_entry(
            self._audio_enabled, duration_s
        )
        self._process = None
        self._monitor_thread = None
        self._start_time = None
        self._current_destination = None
        return entry

    def _create_manifest_entry(self, audio_enabled: bool, duration_s: Optional[float]) -> RecordingEntry:
        file_path = str(self._current_destination) if self._current_destination else "unknown"
        entry = RecordingEntry(
            file_path=file_path,
            start_time_local=self.last_local_timestamp or "unknown",
            start_time_master=self.last_master_timestamp or "unknown",
            duration_s=duration_s,
            audio_enabled=audio_enabled,
            dropped_frames=self._metrics.dropped_frames,
            encode_errors=self._metrics.encode_errors,
        )
        self.manifest.add_entry(entry)
        return entry

    def _output_path(self, session_id: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{session_id}_{self.camera_id}_{timestamp}.mp4"
        return self.nvme_root / "recordings" / file_name

    def last_metrics(self) -> RecordingMetrics:
        return self._metrics

    def manifest_entries(self) -> list[RecordingEntry]:
        return self.manifest.entries

    def status_payload(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "recording": self.recording,
            "audio_enabled": self.audio_enabled,
            "dropped_frames": self._metrics.dropped_frames,
            "encode_errors": self._metrics.encode_errors,
            "last_pipeline_error": self.last_pipeline_error,
            "start_time_master": self.last_master_timestamp,
            "start_time_local": self.last_local_timestamp,
        }
