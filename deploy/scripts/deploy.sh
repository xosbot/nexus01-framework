#!/usr/bin/env bash
# deploy.sh — Deploy NEXUS-01 to navos.online
# Run from the repo root on the target server
set -euo pipefail

DOMAIN="navos.online"
EMAIL="admin@navos.online"
COMPOSE_FILE="docker-compose.yml"
PROD_FILE="deploy/docker-compose.prod.yml"

echo "╔══════════════════════════════════════════╗"
echo "║  NEXUS-01 — Deploy to navos.online       ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. Pre-flight checks ──────────────────────────────────────────
echo ""
echo "▸ Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "✗ docker not found. Install Docker first."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "✗ docker compose not found."; exit 1; }
echo "  ✓ Docker and docker compose found"

# ── 2. Pull latest code ───────────────────────────────────────────
echo ""
echo "▸ Pulling latest code..."
if [ -d .git ]; then
    git pull origin main
    echo "  ✓ Code updated"
else
    echo "  ⚠ Not a git repo, skipping pull"
fi

# ── 3. Build images ───────────────────────────────────────────────
echo ""
echo "▸ Building Docker images..."
docker compose build nexus
echo "  ✓ Nexus image built"

# ── 4. Start services (without nginx first for cert generation) ───
echo ""
echo "▸ Starting core services..."
docker compose up -d redis nexus
echo "  ✓ Core services started"

# Wait for nexus to be healthy
echo "▸ Waiting for nexus to be healthy..."
for i in $(seq 1 30); do
    if docker exec nexus-01 curl -sf http://localhost:8765/health >/dev/null 2>&1; then
        echo "  ✓ Nexus is healthy"
        break
    fi
    sleep 2
done

# ── 5. Generate SSL certificate (first time only) ────────────────
echo ""
if [ ! -d "/etc/letsencrypt/live/${DOMAIN}" ] && ! docker volume ls | grep -q nexus_certbot_certs; then
    echo "▸ Generating SSL certificate for ${DOMAIN}..."
    
    # Start nginx on port 80 only for cert validation
    docker run --rm \
        -v "$(pwd)/deploy/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
        -v certbot_www:/var/www/certbot \
        -p 80:80 \
        nginx:alpine &
    NGINX_PID=$!
    sleep 3
    
    # Get certificate
    docker run --rm \
        -v certbot_www:/var/www/certbot \
        -v certbot_certs:/etc/letsencrypt \
        certbot/certbot certonly \
        --webroot -w /var/www/certbot \
        -d "${DOMAIN}" \
        --non-interactive --agree-tos \
        --email "${EMAIL}" || {
            echo "  ⚠ Certificate generation failed. Ensure DNS points to this server."
            echo "    You can retry with: certbot certonly --webroot -w /var/www/certbot -d ${DOMAIN}"
        }
    
    kill $NGINX_PID 2>/dev/null || true
    echo "  ✓ SSL certificate ready"
else
    echo "▸ SSL certificate already exists, skipping generation"
fi

# ── 6. Start all services including nginx ─────────────────────────
echo ""
echo "▸ Starting all services with SSL..."
docker compose -f "${COMPOSE_FILE}" -f "${PROD_FILE}" up -d
echo "  ✓ All services started"

# ── 7. Verify deployment ──────────────────────────────────────────
echo ""
echo "▸ Verifying deployment..."
sleep 5

# Check health
if curl -sf "http://localhost/health" >/dev/null 2>&1 || \
   curl -sf "https://${DOMAIN}/health" -k >/dev/null 2>&1; then
    echo "  ✓ Health check passed"
else
    echo "  ⚠ Health check failed — check logs with: docker compose logs"
fi

# ── 8. Summary ────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Deployment Complete!                    ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Dashboard: https://${DOMAIN}             ║"
echo "║  API:       https://${DOMAIN}/api/overview║"
echo "║  Health:    https://${DOMAIN}/health      ║"
echo "║  WS:        wss://${DOMAIN}/ws            ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Logs:  docker compose logs -f           ║"
echo "║  Stop:  docker compose down              ║"
echo "╚══════════════════════════════════════════╝"
