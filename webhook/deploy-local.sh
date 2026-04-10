#!/bin/bash
#
# Local deploy script called by webhook server
# Runs inside the webhook container with access to host docker socket
#

set -e

DEPLOY_DIR="/deploy"

cd "$DEPLOY_DIR"

echo ">>> Pulling latest changes..."
git pull --ff-only origin main

echo ">>> Restarting telegraf..."
# Use docker CLI directly (docker-compose not available in container)
curl -s --unix-socket /var/run/docker.sock -X POST http://localhost/containers/telegraf/restart || true

echo ">>> Deploy complete"
