# Multi-Camera Soccer Recording Rig

A three-node Raspberry Pi 5 system for synchronized 4K soccer capture. Each node uses an Arducam IMX686 camera and NVMe storage, providing reliable 90+ minute recordings with web-based controls and GitHub-driven updates.

See `PROCESSING_STATION.md` for the off-field processing station and cloud viewer design (GPU stitching + ML tagging with auth-protected search). A starter FastAPI implementation for ingest/search lives in `processing_station/`.

## Processing Station Docker container
- Build: `docker build -t processing-station .`
- Run: `docker run --rm -p 8001:8001 -v $(pwd)/data:/app/data processing-station`
- Health check: `curl http://localhost:8001/healthz`

The container starts the FastAPI ingest/search service on port 8001 and writes uploads/metadata under `/app/data` (mount a host volume to persist between restarts).

## System Overview
- Nodes: CAM_L, CAM_C, CAM_R along the sideline with overlapping coverage; CAM_C is the NTP master.
- Recording: 4K30 H.265 with continuous capture, local NVMe storage, and optional 720p “Grandma Mode” stream that never interrupts primary recording.
- Connectivity: Joins a shared WiFi mesh; falls back to AP mode (SSID `SOCCER_CAM_{L|C|R}`) when the mesh is unavailable.
- Control Surface: Mobile-friendly Web UI plus REST API for framing, start/stop, node status, and update operations.

## Core Requirements
- Time sync drift under 5 ms via NTP/Chrony with CAM_C as master.
- Automatic safety gates: block recording if camera or NVMe are missing, refuse new sessions under critical battery, and surface temperature or sync warnings in the UI and audio alerts.
- Production Mode minimizes disk logging; Development Mode keeps detailed logs under `/var/log/soccer_rig/`.
- Audio feedback for key events (recording start/stop, warnings) to support field use.

## Update Workflow
- Updates pulled from GitHub Releases; operators trigger “Check for Update” and “Apply Update”.
- Atomic install: download to a temp path, verify, apply, restart services (recorder, web UI, sync agent) without interrupting active recordings. If recording is active, the updater returns HTTP 409.
- Version surfaced in the UI (e.g., `version: soccer-rig-1.2.0`) alongside update history.

## Data Management
- Per-session manifests store file metadata (timing, codec, bitrate, dropped frames, checksum, offload status, optional snapshot).
- Web UI lists recordings and supports bulk download for laptop-based stitching and ML workflows.
- Retention policies remove only confirmed-offloaded files to protect field footage.

## Power & Shutdown
- Battery percentage displayed when supported, with warnings at 20% and 10%.
- “Shutdown All Nodes” plus per-node shutdown ensures: stop recording, flush buffers, unmount NVMe, then power down gracefully.

## Deployment Checklist
- Hardware per node: Raspberry Pi 5 (8 GB recommended), Arducam 64MP IMX686 with autofocus, NVMe SSD (≥512 GB) and carrier, tripod mount, speaker/buzzer, and optional UPS HAT and weatherproofing.
- Mount cameras 6–12 ft high with slight downward tilt for overlapping coverage.
- Verify mesh connectivity and time sync before matches; confirm AP fallback messaging when mesh is unavailable.
