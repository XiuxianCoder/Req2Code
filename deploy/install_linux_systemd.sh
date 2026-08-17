#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="req2code-approval"
HOST="127.0.0.1"
PORT="8088"
PYTHON_EXE="python3"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cat <<EOF | sudo tee /etc/systemd/system/${SERVICE_NAME}.service >/dev/null
[Unit]
Description=Req2Code Approval Callback Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${ROOT_DIR}
ExecStart=${PYTHON_EXE} -m req2code.main serve-approval --host ${HOST} --port ${PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}
sudo systemctl status ${SERVICE_NAME} --no-pager
