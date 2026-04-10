#!/bin/bash
#
# Local deploy script called by webhook server
# Runs inside the webhook container with access to host docker socket
#

set -e

DEPLOY_DIR="/deploy"  # Mounted from host

cd "$DEPLOY_DIR"

echo ">>> Pulling latest changes..."
git pull --ff-only origin main

echo ">>> Restarting services..."
docker-compose stop telegraf loki promtail 2>/dev/null || true
docker-compose up -d telegraf loki promtail

echo ">>> Deploy complete"
