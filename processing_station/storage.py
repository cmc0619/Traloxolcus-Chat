"""Filesystem helpers for ingest and stitched outputs."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import IO


class Storage:
    """Organizes staging and stitched outputs on disk."""

    def __init__(self, root: Path | str = Path("data")):
        self.root = Path(root)
        self.staging = self.root / "staging"
        self.stitched = self.root / "stitched"
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.stitched.mkdir(parents=True, exist_ok=True)

    def save_upload(self, session_id: str, camera_id: str, filename: str, file_obj: IO[bytes]) -> Path:
        session_dir = self.staging / session_id / camera_id
        session_dir.mkdir(parents=True, exist_ok=True)
        destination = session_dir / filename
        with destination.open("wb") as out_file:
            shutil.copyfileobj(file_obj, out_file)
        return destination

    def reserve_stitched_path(self, session_id: str, layout: str, proxy: bool = False) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        stem = f"{session_id}_{layout}_{timestamp}"
        folder = self.stitched / session_id
        folder.mkdir(parents=True, exist_ok=True)
        suffix = "_proxy.mp4" if proxy else "_full.mp4"
        return folder / f"{stem}{suffix}"

    def latest_proxy(self, session_id: str) -> Path | None:
        folder = self.stitched / session_id
        if not folder.exists():
            return None
        proxies = sorted(folder.glob("*_proxy.mp4"), reverse=True)
        return proxies[0] if proxies else None
