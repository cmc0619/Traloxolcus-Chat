# Edge Processing + Viewer Nodes for Soccer Rig Footage

Design for a GPU-equipped processing station that ingests recordings from the sideline cameras, stitches views, runs action-recognition ML, and pushes tagged media to a cloud viewer node with authentication and natural-language search.

## Goals
- Accept uploads from field cameras with minimal operator work.
- Align and stitch synchronized camera feeds into a single view (e.g., center + splits).
- Run ML to detect player actions: passes, dribbles, turnovers, goalkeeper saves, goals, shots, fouls, out-of-bounds, set pieces.
- Emit timestamped metadata that can be searched later and paired with video snippets.
- Mirror results to a cloud viewer node with auth, role-based access, and fast querying.

## Edge Processing Station (EPS)
- **Hardware**: Small-form-factor PC with NVMe scratch (≥2 TB), archival HDD (≥4 TB), RTX 4060/4070-class GPU, 32–64 GB RAM, 10 GbE optional; UPS for clean shutdowns.
- **OS**: Ubuntu Server LTS with NVIDIA drivers + CUDA/cuDNN, Docker/Podman for service isolation.

### Services (docker-compose friendly)
- `ingest-api` (FastAPI):
  - Receives uploads over HTTPS + token auth from camera nodes (pre-shared tokens issued per camera).
  - Accepts per-session manifests (start times, offsets, codecs) and MP4 chunks.
  - Writes to `staging/SESSION_ID/CAM_ID/` and records manifest rows in Postgres.
- `orchestrator` (Celery/RQ + Redis):
  - Enqueues stitching + ML jobs when all camera uploads for a session arrive or a timeout expires.
- `stitcher` worker:
  - Uses ffmpeg/pyav to time-align via manifest offsets; produces:
    - **Multiview MP4**: e.g., center view full frame with L/R inset, or 3840x2160 3-up grid.
    - **Single-stream proxies**: downscaled 1080p for quick review.
  - Emits frame-accurate time index mapping back to the original camera times.
- `ml-infer` worker (GPU):
  - Pipeline: per-frame/player tracking → event classifier → temporal smoothing.
  - Outputs structured events `{type, confidence, t_start, t_end, camera_source}`.
  - Optional: run lightweight ball detection to improve pass/turnover precision.
- `metadata-writer`:
  - Saves stitched file paths, proxies, and event timelines into Postgres.
  - Produces NDJSON/JSONL sidecar with events and frame timestamps for portability.
- `uploader`:
  - Pushes stitched media + proxies to object storage in the cloud (S3/GCS) and posts metadata to the viewer node API.
  - Retries with exponential backoff; marks sessions as `offloaded=true` when viewer confirms receipt.

### Data Model (Postgres on EPS)
- `sessions(id, started_at, duration_s, status, notes)`.
- `camera_assets(id, session_id, camera_id, path, codec, fps, bitrate_mbps, offset_ms)`.
- `stitched_assets(id, session_id, layout, path_fullres, path_proxy, checksum_sha256)`.
- `events(id, session_id, type, t_start_ms, t_end_ms, confidence, source, payload_jsonb)`.

### Operational Notes
- **Upload path**: cameras POST to `/api/v1/upload` with `session_id`, `camera_id`, and multipart files; small client script on each Pi can trigger upload after recording.
- **Failure handling**: orchestrator auto-retries failed stitch/ML jobs; alerts if a camera asset is missing after timeout.
- **Storage hygiene**: nightly job to purge local assets already confirmed in viewer + cloud storage; keep manifests and NDJSON for audit.
- **Metrics**: export Prometheus endpoints (GPU utilization, queue depth, job latency, upload success rate).

## Cloud Viewer Node
- **Purpose**: Authenticated portal for staff/players to browse stitched matches, search for events, and request clips.
- **Hosting**: Cloud VM or container service; object storage for media (S3/GCS/Azure), Postgres for metadata, Redis for caching.

### Services
- `viewer-api` (FastAPI):
  - JWT/OIDC auth (Auth0/Okta/Cognito or self-hosted Keycloak); roles: `admin`, `coach`, `player`.
  - Endpoints: list sessions, fetch events, request clip renders, accept metadata uploads from EPS (`/api/v1/import`).
- `viewer-web` (Next.js/HTMX):
  - Login/SSO + session picker.
  - Timeline view showing events with colored tags (passes, turnovers, saves, goals, fouls).
  - Clip player with multiview toggle (full stitched vs. single camera).
- `clip-service` worker:
  - On-demand slice rendering using stored proxies; returns signed URLs.
- `search-service`:
  - Builds text spans per event ("Player 8 passes to Player 10 at 12:03") and per timeline chunk.
  - Uses hybrid search: Postgres `tsvector` for keyword/filters + pgvector (or OpenSearch/Weaviate) for semantic search embeddings.
  - Natural-language queries are embedded via a small text-embedding model; results return ranked events and suggested clips.

### Metadata & Search
- Events from EPS land in Postgres `events` table; triggers populate `event_search` table with `{session_id, t_start_ms, text, embedding}`.
- Filters: event type, confidence threshold, half/period, team, player (when tracking IDs are available).
- Time slices: `/api/v1/clips?session_id=...&t_start_ms=...&duration_s=...` issues signed URL pointing to proxy or full-res asset.
- A starter FastAPI implementation for ingest/search lives in `processing_station/app.py` with endpoints for camera uploads, stitched asset registration, and text-based event search over SQLite.

### Security & Access
- All EPS→viewer uploads use a dedicated service account + mTLS or signed tokens.
- Media in object storage uses per-user signed URLs; metadata endpoints require JWT with appropriate role.
- Audit log records who viewed/downloaded clips.

## Minimal Delivery Sequence
1. Stand up EPS ingest + orchestrator with dummy jobs; prove uploads and time alignment work.
2. Add stitching worker producing 1080p proxies; publish NDJSON events stub.
3. Integrate GPU ML model for core events (passes/turnovers/goals/saves) with confidence thresholds.
4. Ship uploader to push stitched files + metadata to viewer.
5. Bring up viewer API/web with auth, session browser, and basic event timeline.
6. Add hybrid natural-language search with embeddings; tune prompts/text spans for soccer terminology.
7. Harden cleanup, retries, and observability before field trials.
