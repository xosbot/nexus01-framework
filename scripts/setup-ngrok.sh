#!/bin/bash
# Expose NEXUS-01 webhooks via ngrok (WhatsApp, Slack, Teams)
set -euo pipefail

PORT="${API_PORT:-8765}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"

if ! command -v ngrok &>/dev/null; then
  echo "Install ngrok: https://ngrok.com/download"
  exit 1
fi

echo "=== NEXUS-01 ngrok tunnel ==="
echo "Port: $PORT"
echo ""
echo "Webhook URLs (configure in provider dashboards):"
echo "  WhatsApp: https://<your-ngrok>/webhooks/whatsapp"
echo "  Slack:    https://<your-ngrok>/webhooks/slack"
echo "  Teams:    https://<your-ngrok>/webhooks/teams"
echo ""

if [ -n "$NGROK_DOMAIN" ]; then
  ngrok http "$PORT" --domain="$NGROK_DOMAIN"
else
  ngrok http "$PORT"
fi
