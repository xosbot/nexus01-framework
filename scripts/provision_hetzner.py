"""Hetzner Cloud VPS provisioning and hardening script.

Usage:
    python scripts/provision_hetzner.py --name nexus-prod --type cx22 --location fsn1
    python scripts/provision_hetzner.py --name nexus-prod --dry-run

Requires:
    - HCLOUD_TOKEN env var (Hetzner Cloud API token)
    - SSH public key accessible at ~/.ssh/id_rsa.pub
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("provision")

HARDENING_SCRIPT = """#!/bin/bash
set -euo pipefail

# System update
apt-get update && apt-get upgrade -y

# Create non-root user
useradd -m -s /bin/bash -G sudo nexus
echo "nexus ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/nexus

# SSH hardening
mkdir -p /home/nexus/.ssh
cp /root/.ssh/authorized_keys /home/nexus/.ssh/
chown -R nexus:nexus /home/nexus/.ssh
chmod 700 /home/nexus/.ssh
chmod 600 /home/nexus/.ssh/authorized_keys

# Disable root SSH
sed -i 's/^PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker nexus

# Install fail2ban
apt-get install -y fail2ban
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
[sshd]
enabled = true
EOF
systemctl enable fail2ban && systemctl start fail2ban

# UFW firewall
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 8765/tcp
ufw --force enable

# Unattended upgrades
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

# Create workspace
mkdir -p /home/nexus/nexus01
chown -R nexus:nexus /home/nexus

echo "Hardening complete."
"""


def get_ssh_public_key() -> str:
    pub_key_path = Path.home() / ".ssh" / "id_rsa.pub"
    if not pub_key_path.exists():
        pub_key_path = Path.home() / ".ssh" / "id_ed25519.pub"
    if not pub_key_path.exists():
        raise FileNotFoundError("No SSH public key found. Generate one with: ssh-keygen -t ed25519")
    return pub_key_path.read_text().strip()


def create_server(name: str, server_type: str, location: str, image: str, token: str, dry_run: bool = False) -> dict:
    from hcloud import Client
    from hcloud.server_types import ServerType
    from hcloud.locations import Location
    from hcloud.images import Image

    client = Client(token=token, application_name="nexus01-provision")

    if dry_run:
        logger.info("[DRY RUN] Would create server: %s (%s in %s)", name, server_type, location)
        return {"name": name, "status": "dry_run"}

    ssh_key = get_ssh_public_key()

    resp = client.servers.create(
        name=name,
        server_type=ServerType(name=server_type),
        image=Image(name=image),
        location=Location(name=location),
        ssh_keys=[client.ssh_keys.create(name=f"{name}-key", public_key=ssh_key)],
    )
    server = resp.server
    logger.info("Server created: %s (IP: %s)", server.name, server.public_net.ipv4.ip)

    return {"name": server.name, "ip": server.public_net.ipv4.ip, "id": server.id}


def harden_server(ip: str, dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[DRY RUN] Would harden server at %s", ip)
        return

    script_path = Path("/tmp/harden.sh")
    script_path.write_text(HARDENING_SCRIPT)

    logger.info("Connecting to %s for hardening...", ip)
    subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no", str(script_path), f"root@{ip}:/tmp/harden.sh"],
        check=True,
    )
    subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}", "bash /tmp/harden.sh"],
        check=True,
    )
    logger.info("Server hardened successfully.")


def deploy_framework(ip: str, source_dir: str, dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[DRY RUN] Would deploy framework to %s", ip)
        return

    logger.info("Deploying NEXUS-01 to %s...", ip)
    subprocess.run(
        ["rsync", "-avz", "--exclude", "data/", "--exclude", "__pycache__/",
         "--exclude", ".git/", f"{source_dir}/", f"nexus@{ip}:/home/nexus/nexus01/"],
        check=True,
    )
    subprocess.run(
        ["ssh", f"nexus@{ip}", "cd /home/nexus/nexus01 && pip install -r requirements.txt"],
        check=True,
    )
    logger.info("Framework deployed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS-01 Hetzner Provisioner")
    parser.add_argument("--name", default="nexus-prod", help="Server name")
    parser.add_argument("--type", default="cx22", help="Server type (cx22 = 2 vCPU, 4GB)")
    parser.add_argument("--location", default="fsn1", help="Hetzner location")
    parser.add_argument("--image", default="ubuntu-24.04", help="OS image")
    parser.add_argument("--token", default=None, help="Hetzner API token (or HCLOUD_TOKEN env)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    parser.add_argument("--skip-hardening", action="store_true", help="Skip hardening step")
    parser.add_argument("--skip-deploy", action="store_true", help="Skip framework deployment")
    parser.add_argument("--source-dir", default=str(Path(__file__).parent.parent), help="Source directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    token = args.token or os.environ.get("HCLOUD_TOKEN", "")
    if not token and not args.dry_run:
        logger.error("Set HCLOUD_TOKEN env var or pass --token")
        sys.exit(1)

    result = create_server(args.name, args.type, args.location, args.image, token, args.dry_run)
    ip = result.get("ip", "")

    if ip and not args.skip_hardening:
        harden_server(ip, args.dry_run)

    if ip and not args.skip_deploy:
        deploy_framework(ip, args.source_dir, args.dry_run)

    logger.info("Done. Server: %s", result)


if __name__ == "__main__":
    main()
