#!/usr/bin/env bash
# Attempt to join the mesh network; fall back to AP mode when unreachable.
set -euo pipefail

SSID=${SSID:-${1:-"SOCCER_MESH"}}
PASSWORD=${PASSWORD:-"changeme123"}
IFACE=${IFACE:-wlan0}
TRIES=${TRIES:-5}
SLEEP_SECONDS=${SLEEP_SECONDS:-3}
LOG_FILE="${LOG_FILE:-/tmp/net_join.log}"
AP_FALLBACK=${AP_FALLBACK:-"$(dirname "$0")/ap_fallback.sh"}

echo "[$(date -Is)] bringing up mesh interface ${IFACE} for SSID ${SSID}" | tee -a "$LOG_FILE"
if nmcli -t -f NAME connection show --active | grep -q "$SSID"; then
  echo "[$(date -Is)] mesh already active" | tee -a "$LOG_FILE"
  exit 0
fi

for attempt in $(seq 1 "$TRIES"); do
  echo "[$(date -Is)] attempt ${attempt}/${TRIES} to join ${SSID}" | tee -a "$LOG_FILE"
  if nmcli dev wifi connect "$SSID" password "$PASSWORD" ifname "$IFACE" >/dev/null 2>&1; then
    echo "[$(date -Is)] mesh connected" | tee -a "$LOG_FILE"
    exit 0
  fi
  sleep "$SLEEP_SECONDS"
done

echo "[$(date -Is)] mesh unavailable after ${TRIES} attempts; triggering AP fallback" | tee -a "$LOG_FILE"
if [ -x "$AP_FALLBACK" ]; then
  CAM_ID="${CAM_ID:-CAM_X}" SSID_PREFIX="${SSID_PREFIX:-SOCCER_CAM}" PASSWORD="$PASSWORD" "$AP_FALLBACK" | tee -a "$LOG_FILE"
fi
exit 1
