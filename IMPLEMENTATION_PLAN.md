# Multi-Camera Pi 5 Soccer Rig — Implementation Plan

A single, de-duplicated roadmap that turns `SPEC.md` v1.2 into concrete work. Phases are intentionally small and observable so we can ship incrementally while keeping Production Mode minimal and in-memory.

## Core Services per Node
- **recorder**: camera pipeline, session IDs, file naming, encode settings, dropped-frame/error signaling, and lock-view snapshot.
- **sync-agent**: NTP/Chrony role management; exposes offset/confidence plus master/local timestamps; optional coordinated start beep.
- **api**: REST layer (aiohttp/FastAPI) with websocket/SSE hooks for live status; rejects control actions when camera/NVMe/battery/sync prerequisites fail.
- **ui**: mobile-first dashboard served by the API process; reuses REST endpoints for controls and settings.
- **updater**: GitHub Release checker/applier that refuses to run while recording; stages downloads atomically.
- **housekeeper**: free-space/offload tracking, retention rules, and mesh→AP fallback signaling for the UI.

## State & Configuration
- Production Mode keeps state in-memory; only manifests and recordings persist.
- Configuration lives in a small TOML/JSON/YAML file with a version stamp; editable via `/api/v1/config` and mirrored in UI settings.

## Phases
### Phase 1: Foundations
1. **Repository bootstrap**
   - Layout: `services/recorder`, `services/sync`, `services/web`, `scripts/` for ops tasks, `configs/` for defaults.
   - Add `pyproject.toml` for shared Python tooling (ruff/black/mypy optional in Development Mode only).
2. **Configuration schema**
   - Per-node `config.yaml` with camera ID, WiFi/AP credentials, bitrate/codec defaults, NVMe mount point, audio toggle, and cleanup thresholds.
   - `/api/v1/config` GET/POST stubs read/write the file and restart services on change (no-op until services exist).
3. **Health model**
   - Define a `NodeStatus` dataclass (in `services/models/status.py`) matching SPEC 6.1.
   - Expose a placeholder `/api/v1/status` returning static data so the Web UI shell can integrate early; add minimal metrics for encode FPS, dropped frames, free space, and CPU/temp per node.

### Phase 2: Time Sync & Signaling
1. **Chrony/NTP setup**
   - Systemd units: `sync-master.service` (CAM_C) and `sync-client.service` (CAM_L/R) with templated configs; helper scripts promote a node to master/client.
2. **Sync telemetry**
   - `services/sync/telemetry.py` polls `chronyc tracking`, publishes offset/confidence, and feeds the status endpoint.
3. **Start beep**
   - `scripts/beep_start.sh` plays a short tone via ALSA; recorder triggers it at record start after readiness is confirmed.

### Phase 3: Recording Service
1. **Camera pipeline**
   - `services/recorder/controller.py` orchestrates libcamera + ffmpeg/GStreamer to produce 4K30 H.265 MP4 to NVMe; clamps bitrate to 25–35 Mbps; falls back to H.264 on HEVC failure; surfaces encoder errors.
   - Gate start when camera missing, NVMe unwritable, temperature high, battery low, or sync drift exceeds threshold.
2. **File naming and manifest**
   - Naming: `{SESSION_ID}_{CAM_ID}_{YYYYMMDD}_{HHMMSS}.mp4` with optional audio channel.
   - `services/recorder/manifest.py` writes `{SESSION_ID}_{CAM_ID}.json` containing start times (master/local), offset ms, duration, resolution/FPS/codec/bitrate, dropped frames, checksum, snapshot (Lock View), camera position, software version, and `offloaded` flag.
3. **Test recording mode**
   - `POST /api/v1/selftest` triggers a 10-second clip, hashes it, deletes it, and returns pass/fail with encoder and disk-write errors surfaced.
4. **Grandma Mode (optional)**
   - Low-res 720p, 2–4 Mbps stream runs independently of 4K capture and auto-disables on high CPU load.

### Phase 4: Web UI & REST API
1. **REST surface**
   - `/api/v1/status`, `/api/v1/record/start`, `/api/v1/record/stop`, `/api/v1/recordings`, `/api/v1/recordings/confirm`, `/api/v1/config`, `/api/v1/logs`, `/api/v1/shutdown`, `/api/v1/selftest`, `/api/v1/update/check|apply`.
2. **Dashboard UI**
   - Mobile-first single-page app from `services/web/static/`; shows CAM_L/CAM_C/CAM_R cards with recording state, resolution/FPS/codec/bitrate, NVMe free space + estimated minutes, battery %, temperature, time offset, warnings, preview (MJPEG or still frame), and AP Mode banner.
   - Controls: start/stop all, Lock View (tone + snapshot), audio toggle, session metadata edit, test recording, shutdown node, Dev↔Prod switch.
   - Aggregated view polls `/status` from all nodes and highlights disagreements (e.g., sync or disk issues).
3. **Lock View & snapshot**
   - Persist a frame and tone; include snapshot in manifest for downstream alignment.

### Phase 5: Offload & Cleanup
1. **Checksum confirmation**
   - `/api/v1/recordings/confirm` verifies SHA-256, sets `offloaded=true`, and updates the manifest.
2. **Auto-delete policy**
   - Background task removes oldest confirmed files when free space is below threshold or “delete after confirm” is enabled; retains manual “delete all offloaded” control.
3. **Bulk download**
   - Simple HTTP file server under `/recordings/` with index JSON for session manifests and recordings; streams to avoid blocking ongoing writes.

### Phase 6: Updates & Operations
1. **GitHub updater**
   - `services/updater/` polls Releases, downloads `.tar.gz`, verifies checksum (if provided), stages to temp, swaps symlink or installs package, and restarts services; returns HTTP 409 if recording is active and may queue retries until idle.
2. **Modes & logging**
   - Production Mode: in-memory status only, minimal `/logs`, no request/access logs; transient errors surfaced via status and tones.
   - Development Mode: verbose logs under `/var/log/soccer_rig/`; toggle via UI and config endpoint.
3. **Shutdown path**
   - `/api/v1/shutdown` stops recording, syncs storage, unmounts NVMe, and powers down gracefully.

### Phase 7: Mesh Networking & AP Fallback
1. **Mesh join**
   - `scripts/net_join.sh` attempts mesh connection on boot and reports status to the UI.
2. **AP fallback**
   - After timeout, enable hostapd with SSID `SOCCER_CAM_{ID}` and configurable WPA2 key; the housekeeper marks AP Mode for the UI and syncs retention rules.

## Acceptance Checklist (per SPEC v1.2)
- 4K30 H.265 (H.264 fallback) recording to NVMe for 110 minutes with test mode and encoder health surfaced.
- Drift < 5 ms with offsets reported in `/api/v1/status` and stored in manifests; optional synchronized start beep.
- Web UI with aggregated dashboard, start/stop/test, Lock View tone + snapshot, AP Mode banner, and settings for bitrate/codec/audio/IDs/network/update/version.
- Offload flow with SHA-256 confirm, cleanup tied to `offloaded=true` plus free-space thresholds, and manual “Delete all offloaded files”.
- GitHub-based updater that refuses to run while recording; version display and update history retained.
- Production vs. Development logging modes with `/logs` minimized in Production; safety gates for temperature, battery, and disk.

## Open Questions
- Preferred REST framework (aiohttp vs FastAPI) and UI stack (HTMX vs lightweight React); leaning toward aiohttp + HTMX for low overhead on Pi.
- Exact NVMe free-space threshold and battery critical level; propose 15% warn, 10% block pending field validation.
- Any storage encryption needs for field devices.

## Outstanding Work vs. Current Code
- Recording API is still in-memory and bypasses the libcamera/ffmpeg controller; start/stop only adjust local counters, never launch the pipeline or write manifests, and temperature/battery/sync readings are warnings rather than gates.
- Offload and retention are stubbed: confirmations only flip flags in memory, there is no checksum/file verification, and no background cleanup or download endpoints for recorded files and manifests.
- Update endpoints simply bump an in-memory version string; there is no release download/apply flow or enforcement of “recording in progress” blocks beyond a single guard.
- The UI/status layer is single-node with placeholder preview data; there is no mesh aggregation, lock-view snapshot, start-beep hook, or live preview endpoint for framing.
