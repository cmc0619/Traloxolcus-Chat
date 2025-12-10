#!/usr/bin/env bash
# Enable AP mode with a predictable SSID if mesh join fails.
set -euo pipefail

CAM_ID=${CAM_ID:-CAM_X}
SSID_PREFIX=${SSID_PREFIX:-"SOCCER_CAM"}
SSID=${SSID:-"${SSID_PREFIX}_${CAM_ID}"}
PASSWORD=${PASSWORD:-"changeme123"}
CHANNEL=${CHANNEL:-1}
IFACE=${IFACE:-wlan0}
LOG_FILE="${LOG_FILE:-/tmp/ap_fallback.log}"

cat <<CONF >/tmp/hostapd.conf
interface=${IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=${CHANNEL}
wmm_enabled=0
auth_algs=1
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
CONF

echo "[$(date -Is)] enabling AP mode (${SSID}) on ${IFACE}" | tee -a "$LOG_FILE"
if command -v nmcli >/dev/null 2>&1; then
  nmcli radio wifi off >/dev/null 2>&1 || true
fi

if ! command -v hostapd >/dev/null 2>&1; then
  echo "hostapd not installed; cannot enable AP" | tee -a "$LOG_FILE"
  exit 1
fi

if command -v ip >/dev/null 2>&1; then
  ip link set "${IFACE}" down || true
  ip link set "${IFACE}" up || true
fi

hostapd -B /tmp/hostapd.conf
