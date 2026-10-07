#!/bin/sh
# Host setup for kiosk Wi-Fi control (run once per kiosk box with sudo).
#
#   sudo ./deploy/install-wifi-control.sh
#
# What it does:
#   1. Allows the host kiosk user to scan and switch Wi-Fi via NetworkManager
#      without an interactive password prompt (the container drives
#      NetworkManager over D-Bus as this same user id).
#   2. Verifies nmcli can see the Wi-Fi radio.
#
# Afterwards rebuild and restart:  docker compose up -d --build
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "شغّل هذا الملف بواسطة sudo." >&2
    exit 1
fi

TARGET_USER="${SUDO_USER:-}"
if [ -z "${TARGET_USER}" ] || ! id "${TARGET_USER}" >/dev/null 2>&1; then
    echo "تعذر تحديد مستخدم الكشك (SUDO_USER=${SUDO_USER:-})." >&2
    exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
    echo "nmcli غير موجود على المضيف. ثبّت NetworkManager أولاً:" >&2
    echo "  sudo apt-get install -y network-manager" >&2
    exit 1
fi

RULE_FILE=/etc/polkit-1/rules.d/49-sunset-kiosk-wifi.rules
cat >"${RULE_FILE}" <<EOF
// Sunset kiosk: let the kiosk host user scan and switch Wi-Fi without an
// interactive password prompt. The kiosk container drives NetworkManager
// over D-Bus as this same user id. Installed by install-wifi-control.sh.
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.NetworkManager.wifi.scan" ||
         action.id == "org.freedesktop.NetworkManager.network-control" ||
         action.id == "org.freedesktop.NetworkManager.settings.modify.system" ||
         action.id == "org.freedesktop.NetworkManager.settings.modify.own") &&
        subject.user == "${TARGET_USER}") {
        return polkit.Result.YES;
    }
});
EOF
chmod 644 "${RULE_FILE}"
echo "Wrote ${RULE_FILE} for user ${TARGET_USER}."

systemctl try-reload-or-restart polkit.service >/dev/null 2>&1 || true

echo "--- Wi-Fi radio check (as ${TARGET_USER}) ---"
if sudo -u "${TARGET_USER}" nmcli -t -f DEVICE,TYPE,STATE device status 2>&1 | grep -q wifi; then
    sudo -u "${TARGET_USER}" nmcli -t -f DEVICE,TYPE,STATE device status | grep wifi || true
    echo "OK: Wi-Fi radio is visible to NetworkManager."
else
    echo "WARNING: no wifi device reported. Output was:" >&2
    sudo -u "${TARGET_USER}" nmcli -t -f DEVICE,TYPE,STATE device status 2>&1 || true
    echo "تحقق من تعريف الواي فاي على الجهاز." >&2
fi

echo "--- Next steps ---"
echo "  1. docker compose up -d --build"
echo "  2. Open the chat page, tap the connection pill, press «بحث مجدد»."
