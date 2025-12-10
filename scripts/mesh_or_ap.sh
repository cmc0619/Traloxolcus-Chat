#!/usr/bin/env bash
# Try to join the mesh network and write a status file for the UI; fall back to AP.
set -euo pipefail

BASE_DIR="$(cd -- "$(dirname "$0")" && pwd)"
STATUS_FILE=${STATUS_FILE:-/tmp/network_status.json}
LOG_FILE=${LOG_FILE:-/tmp/net_join.log}
SSID=${SSID:-"SOCCER_MESH"}
PASSWORD=${PASSWORD:-"changeme123"}
CAM_ID=${CAM_ID:-CAM_X}
IFACE=${IFACE:-wlan0}
AP_SSID_PREFIX=${AP_SSID_PREFIX:-"SOCCER_CAM"}

write_status() {
  local mode=$1
  local message=$2
  mkdir -p "$(dirname "$STATUS_FILE")"
  cat >"$STATUS_FILE" <<JSON
{
  "mode": "$mode",
  "iface": "$IFACE",
  "mesh_ssid": "$SSID",
  "ap_ssid": "${AP_SSID_PREFIX}_${CAM_ID}",
  "timestamp": "$(date -Is)",
  "message": "$message"
}
JSON
}

if "$BASE_DIR/net_join.sh" "$SSID" >/dev/null 2>&1; then
  write_status "mesh" "Connected to mesh ${SSID}"
  exit 0
fi

write_status "mesh" "Mesh unavailable; enabling AP"
CAM_ID="$CAM_ID" SSID_PREFIX="$AP_SSID_PREFIX" PASSWORD="$PASSWORD" IFACE="$IFACE" LOG_FILE="$LOG_FILE" "$BASE_DIR/ap_fallback.sh"
write_status "ap" "AP mode active"
exit 1
