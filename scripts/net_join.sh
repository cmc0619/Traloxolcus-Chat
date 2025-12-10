#!/usr/bin/env bash
# Attempt to join the mesh network; fall back to reporting status for the UI.
set -euo pipefail

SSID=${1:-"SOCCER_MESH"}
LOG_FILE="${LOG_FILE:-/tmp/net_join.log}"

echo "[$(date -Is)] bringing up mesh interface for SSID ${SSID}" | tee -a "$LOG_FILE"
if nmcli -t -f NAME connection show --active | grep -q "$SSID"; then
  echo "[$(date -Is)] mesh already active" | tee -a "$LOG_FILE"
  exit 0
fi

if nmcli dev wifi connect "$SSID" >/dev/null 2>&1; then
  echo "[$(date -Is)] mesh connected" | tee -a "$LOG_FILE"
  exit 0
fi

echo "[$(date -Is)] mesh unavailable; will trigger AP fallback" | tee -a "$LOG_FILE"
exit 1
