from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class RigSettings(BaseSettings):
    """Runtime configuration for a single camera node."""

    model_config = SettingsConfigDict(env_prefix="SOCCER_RIG_", case_sensitive=False)

    camera_id: Literal["CAM_L", "CAM_C", "CAM_R"] = "CAM_L"
    base_dir: Path = Path("data")

    # Capture parameters
    codec: Literal["h265", "h264"] = "h265"
    bitrate_mbps: int = 30
    resolution: str = "3840x2160"
    fps: int = 30
    audio_enabled: bool = True
    duration_minutes_default: int = 110

    # Sync and coordination
    ntp_master_id: str = "CAM_C"
    sync_offset_warn_ms: int = 5

    # Storage and retention
    free_space_min_gb: int = 10
    delete_after_confirm: bool = False

    # Network + modes
    wifi_mesh_ssid: str = "SOCCER_MESH"
    ap_ssid_prefix: str = "SOCCER_CAM"
    wifi_password: str = "changeme123"
    ap_mode_timeout_sec: int = 15
    production_mode: bool = True

    # Update + versioning
    version: str = "soccer-rig-1.2.0"
    update_channel: str = "stable"
    update_repo: str = "traloxolcus/soccer-rig"

    @property
    def recordings_dir(self) -> Path:
        return self.base_dir / "recordings"

    @property
    def manifests_dir(self) -> Path:
        return self.base_dir / "manifests"

    @property
    def snapshots_dir(self) -> Path:
        return self.base_dir / "snapshots"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    def model_post_init(self, __context):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


settings = RigSettings()
