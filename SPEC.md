SPEC.md – Multi-Camera Pi 5 Soccer Recording System
Version 1.2
TL;DR

Build a three-camera synchronized 4K recording system using three Raspberry Pi 5 nodes, each equipped with an Arducam IMX686 camera and NVMe storage.
Cameras are placed along the sideline (left, center, right).

Each Pi:

Records 4K30 H.265 continuously for 90+ minutes

Uses WiFi mesh for communication

Exposes a mobile-friendly Web UI + REST API

Provides audio feedback

Maintains tight time sync via NTP/Chrony

Stores metadata & manifests for stitching + ML

Auto-deletes recordings after confirmed offload

Runs in Production Mode with no disk logging

Performs automatic GitHub-based software updates

1. System Overview

The system consists of three independent Pi-Cam nodes ("CAM_L", "CAM_C", "CAM_R") that:

Capture synchronized 4K footage

Serve a phone-accessible UI via WiFi mesh

Store video to NVMe

Provide status, health, and framing assistance

Export recordings for downstream stitching + ML on a laptop

Automatically clean up files post-offload

Stay updated via GitHub Releases

CAM_C acts as time master for NTP synchronization.

2. Hardware Specification
2.1 Required Per Node

Raspberry Pi 5 (8GB recommended)

Arducam 64MP Autofocus (IMX686)

NVMe SSD (512GB minimum)

Pi 5 NVMe carrier

Tripod + adjustable camera mount

USB-C battery bank or field battery pack

Small speaker/buzzer

Optional:

UPS HAT for voltage reporting

Weatherproof housing

2.2 Field Deployment Layout

CAM_L → left sideline corner

CAM_C → midfield (also NTP master)

CAM_R → right sideline corner

Mounted 6–12 ft high

Slight downward tilt, overlapping coverage

3. Networking
3.1 WiFi Mesh

All Pis join the same WiFi mesh network.
Operator’s phone also joins this network.

3.2 Web Server on Each Pi

Automatically starts on boot

Mobile-friendly

Allows:

Framing

Starting/stopping recording

Checking status across all nodes

3.3 AP Fallback

If Pi cannot join WiFi mesh after N seconds:

Switch to Access Point mode:

SSID: SOCCER_CAM_{L|C|R}

WPA2 password configurable

UI must indicate AP Mode clearly.

4. Time Synchronization
4.1 Architecture

CAM_C = NTP master

CAM_L and CAM_R = NTP clients

Drift must remain < 5 ms

4.2 Sync Reporting

Each node exposes:

Current offset

Sync confidence

Master timestamp at recording start

Local timestamp at recording start

4.3 Sync Event (Optional)

At recording start:

All Pis emit a short beep simultaneously

Helps visual/audio alignment in downstream ML

5. Recording Specifications
5.1 Capture Format

Resolution: 3840×2160

FPS: 30

Codec: H.265 (preferred), fallback H.264

Bitrate: 25–35 Mbps

Container: MP4 or MKV

Audio: selectable (ON/OFF)

Duration: 110 minutes continuous

5.2 File Naming
{SESSION_ID}_{CAM_ID}_{YYYYMMDD}_{HHMMSS}.mp4

5.3 Recording Behavior

Must never drop frames if CPU available

Must surface encoder failures clearly

Must warn if disk free < threshold

Must include a test mode:

“10-second test recording” with pass/fail indicators

6. Web UI
6.1 Dashboard View (Aggregated)

Each camera shows:

CAM ID

Recording status

Resolution/FPS/codec/bitrate

NVMe free space + estimated recording time

Battery % (if supported)

Temperature

Time sync offset

Live preview (MJPEG or still-frame refresh)

6.2 Controls

Start Recording (all nodes)

Stop Recording

Lock View (with audio tone + stored snapshot)

Toggle audio channel

Edit session metadata

Run test recording

Shutdown node

Switch mode (Dev ↔ Prod)

6.3 Settings

Bitrate / Codec

Camera ID assignment

WiFi settings

AP fallback settings

Version info & update controls

7. REST API

Base path: /api/v1

Endpoints:

GET /status

POST /record/start

POST /record/stop

GET /recordings

POST /recordings/confirm (checksum verification)

GET /config

POST /config

GET /logs (disabled in Production Mode)

POST /shutdown

POST /selftest

POST /update/check

POST /update/apply

8. Session Manifest

Each Pi writes:

{SESSION_ID}_{CAM_ID}.json

Includes:

Recording file name

Start time local

Start time master

Offset ms

Duration

Resolution / FPS / codec / bitrate

Dropped frames

Camera position metadata

Base64 snapshot from framing

SHA-256 video checksum

offloaded: true|false

Software version

9. File Offload & Auto-Cleanup
9.1 Offload Protocol

External device downloads recordings and manifests.
Checksum verification is REQUIRED.

9.2 Confirmation Endpoint

Client posts:

POST /recordings/confirm
{
  "session_id": "...",
  "camera_id": "...",
  "file": "...",
  "checksum": {
    "algo": "sha256",
    "value": "<hex>"
  }
}


Pi verifies and marks file as offloaded=true.

9.3 Auto-Cleanup Rules

If offloaded=true and:

“Delete after confirm” enabled → delete immediately

OR disk free < threshold → delete oldest offloaded files

9.4 Manual Cleanup

UI exposes “Delete all offloaded files”.

10. Logging & Operating Modes
10.1 Production Mode (Default)

No persistent disk logging

Only in-memory status + transient error fields

/logs endpoint returns minimal info

No access/request logs saved

10.2 Development Mode

Full logs under /var/log/soccer_rig/

For debugging only

Switchable via Web UI

11. Power & Shutdown

Battery % displayed if hardware supports it

Threshold warnings at 20% and 10%

Must refuse new recordings under critical battery

UI “Shutdown All Nodes” and per-node shutdown

Graceful shutdown:

Stop recording

Flush buffers

Unmount NVMe

Power down

12. Live Streaming (Optional)

Called “Grandma Mode”.

Low-res (720p, 2–4 Mbps)

Must not affect main 4K recording

If CPU load high → auto-disable stream

13. Software Updates (GitHub-Based Updater)
13.1 Update Source

Updates pulled from GitHub Releases of a specified repo.

13.2 Update Workflow

Operator presses “Check for Updates”.

Pi queries GitHub Releases API.

If a newer version exists:

Download .tar.gz or .deb from GitHub

Verify checksum (if provided)

Install update

Restart services (camera-recorder, web-ui, sync-agent)

Display version in UI:
"version": "soccer-rig-1.2.0"

13.3 Requirements

Must not interrupt active recordings

If recording active, updater returns:

409: Recording in progress


Updates should be atomic:

Download to temp dir

Extract / apply

Switch symlink or install package

13.4 UI Integration

“Check for Update”

“Apply Update”

Version display

Update history

14. Data Offload Workflow

Web UI lists files + manifests

Bulk download available

Retention policies configurable

Only offloaded (confirmed) files eligible for auto-delete

15. Safety & Failure Modes

If camera not detected → block recording

If NVMe missing/not writable → block recording

If temperature high → warn + tone

If sync offset > threshold → warn

If WiFi connection lost → still record locally

16. Non-Goals

On-device ML

Real-time stitching

GPS-based positioning

Cloud upload

Cellular backhaul

17. End of SPEC.md v1.2
