const els = {
  cameraId: document.getElementById("camera-id"),
  codec: document.getElementById("codec"),
  resolution: document.getElementById("resolution"),
  fps: document.getElementById("fps"),
  bitrate: document.getElementById("bitrate"),
  audio: document.getElementById("audio"),
  diskFree: document.getElementById("disk-free"),
  diskUsed: document.getElementById("disk-used"),
  diskTotal: document.getElementById("disk-total"),
  diskEst: document.getElementById("disk-est"),
  syncRole: document.getElementById("sync-role"),
  syncOffset: document.getElementById("sync-offset"),
  syncConfidence: document.getElementById("sync-confidence"),
  temperature: document.getElementById("temperature"),
  battery: document.getElementById("battery"),
  warnings: document.getElementById("warnings"),
  recordingPill: document.getElementById("recording-pill"),
  version: document.getElementById("version"),
  recordingsBody: document.getElementById("recordings-body"),
  actionResult: document.getElementById("action-result"),
  configBitrate: document.getElementById("config-bitrate"),
  configCodec: document.getElementById("config-codec"),
  configResolution: document.getElementById("config-resolution"),
  configFps: document.getElementById("config-fps"),
  configAudio: document.getElementById("config-audio"),
  configProduction: document.getElementById("config-production"),
  startBitrate: document.getElementById("start-bitrate"),
  startCodec: document.getElementById("start-codec"),
  startAudio: document.getElementById("start-audio"),
  sessionId: document.getElementById("session-id"),
};

let cachedConfig = null;
let eventSource = null;

function updatePill(active, sessionId) {
  els.recordingPill.classList.remove("active", "idle");
  if (active) {
    els.recordingPill.classList.add("active");
    els.recordingPill.textContent = sessionId ? `Recording ${sessionId}` : "Recording";
  } else {
    els.recordingPill.classList.add("idle");
    els.recordingPill.textContent = "Idle";
  }
}

function updateWarnings(list) {
  els.warnings.innerHTML = "";
  if (!list || list.length === 0) {
    const li = document.createElement("li");
    li.textContent = "None";
    els.warnings.appendChild(li);
    return;
  }
  list.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    els.warnings.appendChild(li);
  });
}

function updateStatus(data) {
  els.cameraId.textContent = data.camera_id;
  els.codec.textContent = data.settings?.codec ?? "-";
  els.resolution.textContent = data.settings?.resolution ?? "-";
  els.fps.textContent = data.settings?.fps ?? "-";
  els.bitrate.textContent = data.settings?.bitrate_mbps ?? "-";
  els.audio.textContent = data.settings?.audio_enabled ? "Enabled" : "Muted";

  els.diskFree.textContent = data.disk?.free_gb ?? "-";
  els.diskUsed.textContent = data.disk?.used_gb ?? "-";
  els.diskTotal.textContent = data.disk?.total_gb ?? "-";
  els.diskEst.textContent = data.disk?.estimated_minutes_remaining ?? "-";

  els.syncRole.textContent = data.sync?.role ?? "-";
  els.syncOffset.textContent = data.sync?.offset_ms ?? "-";
  els.syncConfidence.textContent = data.sync?.confidence ?? "-";

  els.temperature.textContent = data.temperature_c ?? "-";
  els.battery.textContent = data.battery_percent ?? "-";
  updateWarnings(data.warnings || []);

  updatePill(data.recording?.active, data.recording?.session_id);
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/v1/status");
    if (!res.ok) throw new Error("Status failed");
    const data = await res.json();
    updateStatus(data);
  } catch (err) {
    console.error(err);
  }
}

async function fetchConfig() {
  const res = await fetch("/api/v1/config");
  const cfg = await res.json();
  cachedConfig = cfg;
  els.configBitrate.value = cfg.bitrate_mbps;
  els.configCodec.value = cfg.codec;
  els.configResolution.value = cfg.resolution;
  els.configFps.value = cfg.fps;
  els.configAudio.checked = cfg.audio_enabled;
  els.configProduction.checked = cfg.production_mode;
  els.startAudio.checked = cfg.audio_enabled;
  els.startBitrate.placeholder = cfg.bitrate_mbps;
  els.sessionId.placeholder = `SESSION_${new Date().toISOString().slice(0, 19)}`;
  els.version.textContent = `Version ${cfg.version}`;
}

async function saveConfig(evt) {
  evt.preventDefault();
  const payload = {};
  const bitrateVal = els.configBitrate.valueAsNumber;
  if (!Number.isNaN(bitrateVal)) payload.bitrate_mbps = bitrateVal;
  if (els.configCodec.value) payload.codec = els.configCodec.value;
  if (els.configResolution.value) payload.resolution = els.configResolution.value;
  const fpsVal = els.configFps.valueAsNumber;
  if (!Number.isNaN(fpsVal)) payload.fps = fpsVal;
  payload.audio_enabled = els.configAudio.checked;
  payload.production_mode = els.configProduction.checked;
  const res = await fetch("/api/v1/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.text();
    els.actionResult.textContent = `Config update failed: ${detail}`;
    return;
  }
  await fetchConfig();
  els.actionResult.textContent = "Config saved";
}

async function startRecording(evt) {
  evt.preventDefault();
  if (!cachedConfig) await fetchConfig();
  const session = els.sessionId.value || `SESSION_${Date.now()}`;
  const payload = {
    session_id: session,
    camera_id: cachedConfig.camera_id,
    audio_enabled: els.startAudio.checked,
  };
  const bitrateVal = els.startBitrate.valueAsNumber;
  if (!Number.isNaN(bitrateVal)) payload.bitrate_mbps = bitrateVal;
  if (els.startCodec.value) payload.codec = els.startCodec.value;

  const res = await fetch("/api/v1/record/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    els.actionResult.textContent = `Start failed: ${await res.text()}`;
    return;
  }
  els.actionResult.textContent = `Recording started: ${session}`;
  els.sessionId.value = "";
  fetchStatus();
  fetchRecordings();
}

async function stopRecording() {
  const res = await fetch("/api/v1/record/stop", { method: "POST" });
  if (!res.ok) {
    els.actionResult.textContent = `Stop failed: ${await res.text()}`;
    return;
  }
  const data = await res.json();
  els.actionResult.textContent = `Stopped session ${data.session_id}`;
  fetchStatus();
  fetchRecordings();
}

async function testRecording() {
  const res = await fetch("/api/v1/record/test", { method: "POST" });
  const data = await res.json();
  els.actionResult.textContent = data.detail || `Test ${data.passed ? "passed" : "failed"}`;
  fetchStatus();
}

async function shutdownNode() {
  const res = await fetch("/api/v1/shutdown", { method: "POST" });
  const data = await res.json();
  els.actionResult.textContent = data.reason || "Shutdown initiated";
}

async function checkUpdate() {
  const res = await fetch("/api/v1/update/check", { method: "POST" });
  const data = await res.json();
  if (data.update_available) {
    els.actionResult.textContent = `Update available: ${data.latest_version}`;
  } else {
    els.actionResult.textContent = "Up to date";
  }
}

async function fetchRecordings() {
  const res = await fetch("/api/v1/recordings");
  const data = await res.json();
  const rows = Array.isArray(data) ? data : data.recordings;
  els.recordingsBody.innerHTML = "";
  (rows || []).forEach((rec) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${rec.session_id ?? ""}</td>
      <td>${rec.filename || rec.file}</td>
      <td>${rec.duration_seconds ?? rec.duration ?? ""}</td>
      <td>${rec.codec ?? ""}</td>
      <td>${rec.bitrate_mbps ?? ""}</td>
      <td>${rec.offloaded ? "Yes" : "No"}</td>
    `;
    els.recordingsBody.appendChild(tr);
  });
}

function initEvents() {
  document.getElementById("record-form").addEventListener("submit", startRecording);
  document.getElementById("stop-btn").addEventListener("click", stopRecording);
  document.getElementById("test-btn").addEventListener("click", testRecording);
  document.getElementById("refresh-btn").addEventListener("click", fetchStatus);
  document.getElementById("shutdown-btn").addEventListener("click", shutdownNode);
  document.getElementById("update-btn").addEventListener("click", checkUpdate);
  document.getElementById("config-form").addEventListener("submit", saveConfig);
  document.getElementById("refresh-recordings").addEventListener("click", fetchRecordings);
}

function beginStream() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/api/v1/events");
  eventSource.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      updateStatus(data);
    } catch (err) {
      console.error("Bad event payload", err);
    }
  };
  eventSource.onerror = () => {
    console.warn("SSE disconnected; falling back to polling");
    eventSource.close();
    setInterval(fetchStatus, 3000);
  };
}

async function bootstrap() {
  initEvents();
  await fetchConfig();
  await fetchStatus();
  await fetchRecordings();
  beginStream();
}

document.addEventListener("DOMContentLoaded", bootstrap);
