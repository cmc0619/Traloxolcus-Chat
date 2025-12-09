#!/usr/bin/env bash
# Enable AP mode with a predictable SSID if mesh join fails.
set -euo pipefail

CAM_ID=${CAM_ID:-CAM_X}
SSID=${SSID:-"SOCCER_CAM_${CAM_ID}"}
PASSWORD=${PASSWORD:-"changeme123"}
LOG_FILE="${LOG_FILE:-/tmp/ap_fallback.log}"

cat <<CONF >/tmp/hostapd.conf
interface=wlan0
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=1
wmm_enabled=0
auth_algs=1
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
CONF

echo "[$(date -Is)] enabling AP mode (${SSID})" | tee -a "$LOG_FILE"
if command -v hostapd >/dev/null 2>&1; then
  hostapd -B /tmp/hostapd.conf
else
  echo "hostapd not installed; cannot enable AP" | tee -a "$LOG_FILE"
  exit 1
fi
