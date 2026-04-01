#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cpihed}"
ENV_FILE="${ENV_FILE:-/etc/cpihed/cpihed.env}"
SERVICE_NAME="${SERVICE_NAME:-cpihed}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.11}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python binary not found or not executable: $PYTHON_BIN" >&2
  echo "Install Python 3.11 first or set PYTHON_BIN to the correct interpreter." >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
  echo "requirements.txt was not found in $APP_DIR" >&2
  echo "Copy or clone the repository into APP_DIR before running this installer." >&2
  exit 1
fi

mkdir -p "$APP_DIR" "$(dirname "$ENV_FILE")"

"$PYTHON_BIN" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 640 "$APP_DIR/.env.example" "$ENV_FILE"
  echo "Created environment template at $ENV_FILE"
fi

install -m 644 "$APP_DIR/deploy/rocky-linux/cpihed.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload

echo
echo "Runtime installed."
echo "Next steps:"
echo "1. Edit $ENV_FILE"
echo "2. Run: cd $APP_DIR && .venv/bin/python main.py --check"
echo "3. Enable the service: systemctl enable --now $SERVICE_NAME"
