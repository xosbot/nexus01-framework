#!/bin/bash
# NEXUS-01 VPS deployment script
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/nexus}"
REPO_URL="${REPO_URL:-}"
USER_NAME="${USER_NAME:-nexus}"

echo "=== NEXUS-01 Deploy ==="

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root or with sudo"
  exit 1
fi

apt-get update && apt-get install -y python3 python3-pip python3-venv git curl ufw fail2ban

if ! id "$USER_NAME" &>/dev/null; then
  useradd -m -s /bin/bash "$USER_NAME"
fi

mkdir -p "$INSTALL_DIR"
if [ -n "$REPO_URL" ]; then
  git clone "$REPO_URL" "$INSTALL_DIR" || (cd "$INSTALL_DIR" && git pull)
else
  echo "Copying local files to $INSTALL_DIR"
  rsync -a --exclude .git --exclude data --exclude .pytest_cache ./ "$INSTALL_DIR/" 2>/dev/null || cp -r . "$INSTALL_DIR/"
fi

cd "$INSTALL_DIR/nexus01-framework" 2>/dev/null || cd "$INSTALL_DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
  echo "Edit $INSTALL_DIR/config.yaml with your tokens"
fi

mkdir -p data
chown -R "$USER_NAME:$USER_NAME" "$INSTALL_DIR"

# Firewall
ufw allow 22/tcp
ufw allow 8765/tcp comment "NEXUS-01 API"
ufw --force enable

# systemd
cp scripts/nexus.service /etc/systemd/system/nexus.service
sed -i "s|/opt/nexus|$INSTALL_DIR|g" /etc/systemd/system/nexus.service
sed -i "s|User=nexus|User=$USER_NAME|g" /etc/systemd/system/nexus.service

systemctl daemon-reload
systemctl enable nexus
systemctl restart nexus

echo "=== Deployed ==="
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8765"
echo "Logs: journalctl -u nexus -f"
echo "Config: $INSTALL_DIR/config.yaml"
