# Multi-Camera Pi 5 Soccer Rig – Implementation Plan

This plan aligns SPEC.md v1.2 with a concrete, phased roadmap for the three Raspberry Pi 5 camera nodes (CAM_L, CAM_C, CAM_R). It merges the earlier pull requests (3, 4, 5, 7, and 8) into a single service-oriented roadmap that prioritizes boring, observable behavior and keeps Production Mode state in-memory whenever possible.

## Core Services and State Model
- **recorder:** owns camera pipeline, session IDs, file naming, 4K30 encode settings, dropped-frame/error signaling, and start/stop control gates.
- **sync-agent:** manages NTP/Chrony config; exposes offset/confidence and master/local timestamps; triggers the optional start beep after a cross-node readiness check so the tone is aligned.
- **api:** aiohttp/FastAPI-style REST layer with SSE/websocket hooks for live status; gates control routes when prerequisites (camera, NVMe, battery, sync) are unhealthy.
- **ui:** mobile-first dashboard served by the API process; reuses REST endpoints for controls and settings.
- **updater:** GitHub Release checker/applier that is update-safe during active recordings; optional retry queue when an update is deferred by a recording.
- **housekeeper:** tracks free space, offload confirmations, retention rules, metrics, and AP fallback transitions so the UI can reflect mesh/AP state.

Production Mode keeps state in-memory; only manifests and recordings are persisted. A small versioned config file (TOML/JSON/YAML) is editable via `/api/v1/config` and mirrored in UI settings. Guard rails refuse recording when camera/NVMe are missing, battery is critical, or sync offset exceeds threshold.

## Observability & Health Signals
- Production Mode: transient in-memory error fields only; `/logs` returns minimal info and avoids request/access logging.
- Development Mode: structured logs under `/var/log/soccer_rig/` with optional ruff/black/mypy hooks enabled for local debugging.
- Minimal metrics view (REST or UI) surfaces encode FPS, dropped frames, free space, CPU temperature, and sync offset per node; short tones flag degraded states (temperature, battery, camera presence, NVMe health, or sync drift).

## Phase 1: Foundations
1. **Repository bootstrap**
   - Layout: `services/recorder`, `services/sync`, `services/web`, `services/updater`, `services/models`, `scripts/`, and `configs/` for defaults.
   - Add `pyproject.toml` for shared Python tooling; ruff/black/mypy are optional and enabled only in Development Mode.
2. **Configuration schema**
   - Per-node `config.yaml` capturing camera ID, WiFi/AP credentials, bitrate/codec defaults, NVMe mount point, audio toggle, and cleanup thresholds.
   - Provide `/api/v1/config` GET/POST stubs to read/write the file and restart services on change (no-op until services exist).
3. **Health model**
   - Define a `NodeStatus` dataclass (in `services/models/status.py`) matching dashboard fields in SPEC 6.1.
   - Expose a placeholder `/api/v1/status` returning static data so the Web UI shell can integrate early, and add a minimal metrics endpoint showing encode FPS, dropped frames, free space, and CPU/temp per node.

## Phase 2: Time Sync & Signaling
1. **Chrony/NTP setup**
   - Systemd units: `sync-master.service` (CAM_C) and `sync-client.service` (CAM_L/R) with templated configs; helper scripts promote a node to master/client.
2. **Sync telemetry**
   - `services/sync/telemetry.py` polls `chronyc tracking`, publishes offset/confidence, and feeds the status endpoint.
3. **Start beep**
   - `scripts/beep_start.sh` plays a short tone via ALSA; the recorder triggers it at record start (guarded to run only once across nodes and only after readiness is confirmed).

## Phase 3: Recording Service
1. **Camera pipeline**
   - `services/recorder/controller.py` orchestrates libcamera + ffmpeg/GStreamer to produce 4K30 H.265 MP4 to NVMe; clamps bitrate to 25–35 Mbps, falls back to H.264 when HEVC fails, and surfaces encoder errors.
   - Enforce gating: block when camera missing, NVMe unwritable, high temperature, low battery, or sync drift exceeds threshold.
2. **File naming and manifest**
   - Naming: `{SESSION_ID}_{CAM_ID}_{YYYYMMDD}_{HHMMSS}.mp4` with optional audio channel.
   - `services/recorder/manifest.py` writes `{SESSION_ID}_{CAM_ID}.json` containing start times (master/local), offset ms, duration, resolution/FPS/codec/bitrate, dropped frames, checksum, snapshot (Lock View), camera position, software version, and `offloaded` flag.
3. **Test recording mode**
   - `POST /api/v1/selftest` triggers a 10-second clip, hashes it, deletes it, and returns pass/fail with encoder and disk-write errors surfaced.
4. **Grandma Mode (optional)**
   - Low-res 720p, 2–4 Mbps stream runs independently of 4K capture and auto-disables on high CPU load.

## Phase 4: Web UI & REST API
1. **REST surface**
   - Implement `/api/v1` routes: status, start/stop, recordings list, confirm (checksum), config get/set, shutdown, selftest, update check/apply, logs (disabled in Production Mode).
2. **Dashboard UI**
   - Mobile-first single-page app from `services/web/static/`; shows CAM_L/CAM_C/CAM_R cards with recording state, resolution/FPS/codec/bitrate, NVMe free space + estimated minutes, battery %, temperature, time offset, warnings, preview (MJPEG or still frame), and AP Mode banner when relevant.
   - Controls: start/stop all, Lock View (tone + snapshot), audio toggle, session metadata edit, test recording, shutdown node, Dev↔Prod switch.
   - Aggregated view polls `/status` from all nodes, highlights disagreements (e.g., one node unhappy with sync or disk), and keeps SSE/websocket hooks for live updates.
3. **Lock View & snapshot**
   - Persist a frame and tone; include snapshot in manifest for downstream alignment.

## Phase 5: Offload & Cleanup
1. **Checksum confirmation**
   - `/api/v1/recordings/confirm` verifies SHA-256, sets `offloaded=true`, and updates the manifest.
2. **Auto-delete policy**
   - Background task removes oldest confirmed files when free space is below threshold or “delete after confirm” is enabled; retains manual “delete all offloaded” control.
3. **Bulk download**
   - Simple HTTP file server under `/recordings/` with index JSON for session manifests and recordings; streams to avoid blocking ongoing writes.

## Phase 6: Updates & Operations
1. **GitHub updater**
   - `services/updater/` polls Releases, downloads `.tar.gz`, verifies checksum (if provided), stages to temp, swaps symlink or installs package, and restarts services; returns HTTP 409 if recording is active and may queue retries until idle.
2. **Modes & logging**
   - Production Mode: in-memory status only, minimal `/logs`, no request/access logs, no persistent disk logging, yet still surface transient errors and tones for degraded states (temperature, battery, camera presence, NVMe health, sync offset).
   - Development Mode: verbose logs under `/var/log/soccer_rig/`; toggle via UI and config endpoint.
3. **Shutdown path**
   - `/api/v1/shutdown` stops recording, syncs storage, unmounts NVMe, and powers down gracefully.

## Phase 7: Mesh Networking & AP Fallback
1. **Mesh join**
   - `scripts/net_join.sh` attempts mesh connection on boot and reports status to the UI.
2. **AP fallback**
   - After timeout, enable hostapd with SSID `SOCCER_CAM_{ID}` and configurable WPA2 key; the housekeeper marks AP Mode for the UI and syncs retention rules.

## Cross-Node Coordination & Safety Signals
- UI aggregations collect `/status` from all three nodes, with per-node warnings for temperature, battery, camera presence, NVMe health, and sync offset; short tones signal degraded states.
- “Start Recording” issues concurrent kicks with a per-node timeout; failures are reported individually while healthy nodes continue.

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

## Next Steps
- Scaffold repository structure (Phase 1) and ship minimal `status` and `config` endpoints so UI work can start.
- Create systemd service definitions for sync master/client and recorder placeholders to exercise control API end-to-end.
- Wire the housekeeper to track mesh/AP transitions and surface them through `/status` for early UI integration.
# Implementation Plan: Multi-Camera Pi 5 Soccer Rig

A concise, service-oriented roadmap to turn the SPEC into a working three-node rig. Prioritize boring, observable behavior and favor in-memory state in Production Mode.

## Core Services per Node
- **recorder**: owns camera pipeline, session IDs, file naming, 4K30 encode settings, and dropped-frame/error signaling.
- **sync-agent**: manages NTP/Chrony config; exposes offset/confidence and master/local timestamps; triggers optional start beep.
- **api**: aiohttp/fastapi-style REST layer and websocket/SSE hooks for live status; gates routes when prerequisites (camera, NVMe, battery, sync) are unhealthy.
- **ui**: mobile-first dashboard served by the API process; reuses REST endpoints for controls and settings.
- **updater**: GitHub Release checker/applier that is update-safe during active recordings.
- **housekeeper**: tracks free space, offload confirmations, retention rules, and AP fallback transitions.

## State & Configuration
- Keep Production Mode state in-memory; persist only manifests and recordings.
- Configuration lives in a small TOML/JSON file with a version stamp; mutable via `/api/v1/config` and mirrored in UI settings.
- Guard rails: refuse recording if camera/NVMe missing, battery critical, or sync offset exceeds threshold.

## Recording Pipeline
- Pipeline template: IMX686 → ISP → H.265 (fallback H.264) → MP4/MKV muxer → NVMe path `{SESSION_ID}_{CAM_ID}_{YYYYMMDD}_{HHMMSS}.mp4`.
- Provide a 10-second self-test that records, hashes, and deletes the clip while surfacing pass/fail in the UI.
- Emit manifest entries immediately after each recording with SHA-256 checksum, offsets, duration, framing snapshot, and software version.

## Networking & Sync
- Boot flow: attempt mesh join → if timeout, flip to AP mode (`SOCCER_CAM_{L|C|R}`) and mark state for the UI.
- CAM_C runs NTP server; CAM_L/R run clients. Expose offset/confidence and last sync time via `/status`.
- Optional sync beep is triggered after a cross-node readiness check to minimize drift.

## Offload & Cleanup
- `/recordings` lists files + manifest flags; `/recordings/confirm` validates the provided SHA-256 before marking `offloaded=true`.
- Housekeeper deletes only offloaded files based on “delete after confirm” and free-space thresholds; manual “delete offloaded” remains available.
- Bulk download endpoint should stream without blocking ongoing writes.

## Updates & Safety
- `/update/check` compares local version to GitHub Releases; `/update/apply` downloads to a temp dir, verifies, switches atomically, and restarts services.
- Return `409` for update attempts during recordings; retry queue optional for convenience.
- Temperature, battery, camera presence, NVMe health, and sync offset surface warnings in `/status` and trigger short tones when degraded.

## Observability
- Development Mode writes structured logs under `/var/log/soccer_rig/`; Production Mode keeps transient in-memory error fields only.
- Minimal metrics endpoint or status page showing encode fps, dropped frames, free space, and CPU/temp per node.

## Cross-Node Coordination
- UI aggregates `/status` from all three nodes, highlighting disagreements (e.g., one node unhappy with sync or disk).
- “Start Recording” attempts concurrent kicks with a per-node timeout; failures are reported individually while healthy nodes continue.
