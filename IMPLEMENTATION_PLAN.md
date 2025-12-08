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
