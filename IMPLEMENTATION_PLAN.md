# Multi-Camera Pi 5 Soccer Rig — Implementation Plan

This plan turns `SPEC.md` into a sequence of concrete deliverables for the three-node Raspberry Pi 5 camera system. Work is split into short, verifiable increments so each feature can be merged independently.

## Phase 1: Foundations
1. **Repository bootstrap**
   - Layout: `services/recorder`, `services/sync`, `services/web`, `scripts/` for ops tasks, `configs/` for defaults.
   - Add `pyproject.toml` for shared Python tooling (ruff/black/mypy optional in Dev Mode only).
2. **Configuration schema**
   - One `config.yaml` per node with camera ID, WiFi/AP credentials, bitrate/codec defaults, and NVMe mount point.
   - Provide `/api/v1/config` GET/POST stubs that read/write the file and restart services on change (no-op until services exist).
3. **Health model**
   - Define a `NodeStatus` dataclass (in `services/models/status.py`) matching the dashboard fields in SPEC section 6.1.
   - Expose a placeholder `/api/v1/status` returning static data so the Web UI shell can integrate early.

## Phase 2: Time Sync & Signaling
1. **Chrony/NTP setup**
   - Systemd units: `sync-master.service` (CAM_C) and `sync-client.service` (CAM_L/R) with templated configs.
   - CLI helpers under `scripts/` to promote a node to master or client.
2. **Sync telemetry**
   - `services/sync/telemetry.py` polls `chronyc tracking` and publishes offset/confidence to an in-memory store consumed by the status endpoint.
3. **Start beep**
   - `scripts/beep_start.sh` triggers a short tone via ALSA; recorder service calls it when recording begins (guarded so it runs only once across all nodes).

## Phase 3: Recording Service
1. **Camera pipeline**
   - `services/recorder/controller.py` orchestrates libcamera + ffmpeg to produce 4K30 H.265 MP4 to NVMe.
   - Fallback to H.264 based on config; include bitrate clamp (25–35 Mbps) and audio toggle.
2. **File naming and manifest**
   - Naming: `{SESSION_ID}_{CAM_ID}_{YYYYMMDD}_{HHMMSS}.mp4`.
   - `services/recorder/manifest.py` writes `{SESSION_ID}_{CAM_ID}.json` with checksum, offsets, dropped frames, and snapshot (per SPEC section 8).
3. **Test recording mode**
   - `POST /api/v1/selftest` triggers a 10-second clip and returns pass/fail with encoder errors surfaced.
4. **Disk and thermal guards**
   - Preflight checks block recording if NVMe missing/not writable, if camera not detected, or if temperature/battery are critical (SPEC section 15).

## Phase 4: Web UI & REST API
1. **REST surface**
   - Implement endpoints in `services/web/api.py` using `aiohttp`:
     - `/api/v1/record/start`, `/api/v1/record/stop`, `/api/v1/recordings`, `/api/v1/recordings/confirm`, `/api/v1/logs`, `/api/v1/shutdown`, `/api/v1/update/check|apply`.
2. **Dashboard UI**
   - Mobile-first single-page app served from `services/web/static/`.
   - Displays status cards for CAM_L/CAM_C/CAM_R, live preview (MJPEG or still-frame refresh), and big Start/Stop/Test buttons.
   - Clear AP Mode banner when mesh join fails.
3. **Lock View & snapshot**
   - Add “Lock View” action that plays a tone and persists a frame to the manifest for later alignment.

## Phase 5: Offload & Cleanup
1. **Checksum confirmation**
   - `/api/v1/recordings/confirm` verifies SHA-256, sets `offloaded=true`, and writes back to the manifest.
2. **Auto-delete policy**
   - Background task removes oldest `offloaded=true` files when free space is below threshold or “delete after confirm” is enabled.
3. **Bulk download**
   - Simple HTTP file server under `/recordings/` with index JSON for session manifests.

## Phase 6: Updates & Operations
1. **GitHub updater**
   - `services/updater/` polls Releases, downloads `.tar.gz`, verifies checksum, stages to temp dir, and swaps symlink; responds 409 if recording is active.
2. **Modes**
   - Development Mode: enable verbose logging to `/var/log/soccer_rig/` and expose `/api/v1/logs`.
   - Production Mode: in-memory errors only; `/api/v1/logs` returns minimal info.
3. **Shutdown path**
   - `/api/v1/shutdown` stops recording, syncs storage, unmounts NVMe, and powers down.

## Phase 7: Mesh Networking & AP Fallback
1. **Mesh join**
   - `scripts/net_join.sh` attempts mesh connection on boot and signals the web UI via status field.
2. **AP fallback**
   - After timeout, enable hostapd with SSID `SOCCER_CAM_{ID}` and WPA2 password from config; update status so UI shows AP Mode clearly.

## Acceptance Checklist (per SPEC v1.2)
- 4K30 H.265 recording for 110 minutes to NVMe with test mode.
- Drift < 5 ms with telemetry exposed in `/api/v1/status` and manifest offsets.
- Web UI with aggregated dashboard, start/stop/test, lock view tone + snapshot, AP Mode banner, and settings.
- Offload flow with checksum confirmation, auto-delete rules, and manual cleanup.
- GitHub-based updater that refuses to run while recording.
- Production vs. Development logging modes with `/logs` minimized in Production.

## Next Steps
- Scaffold repository structure (Phase 1) and add minimal `status` and `config` endpoints so UI work can begin in parallel.
- Create systemd service definitions for sync master/client and recorder placeholders to exercise the control API end-to-end.
