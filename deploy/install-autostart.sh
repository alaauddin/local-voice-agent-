#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "شغّل هذا الملف بواسطة sudo." >&2
    exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "${1:-${SCRIPT_DIR}/..}" && pwd)
DOCKER_BIN=$(command -v docker)
SERVICE_FILE=/etc/systemd/system/sunset-kiosk.service

if [ ! -f "${PROJECT_DIR}/docker-compose.yml" ] || [ ! -f "${PROJECT_DIR}/.env" ]; then
    echo "تعذر العثور على docker-compose.yml أو .env في ${PROJECT_DIR}." >&2
    exit 1
fi

cat >"${SERVICE_FILE}" <<EOF
[Unit]
Description=Sunset Resort Ghoroub Voice Kiosk
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${DOCKER_BIN} compose up -d --remove-orphans
ExecStop=${DOCKER_BIN} compose stop
TimeoutStartSec=0
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now docker.service
systemctl enable --now sunset-kiosk.service
systemctl --no-pager --full status sunset-kiosk.service
