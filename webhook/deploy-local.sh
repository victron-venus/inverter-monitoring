#!/bin/bash
#
# Local deploy script called by webhook server
# Downloads latest config files from GitHub and restarts services
#

set -e

DEPLOY_DIR="/deploy"
GITHUB_RAW="https://raw.githubusercontent.com/victron-venus/inverter-monitoring/main"

cd "$DEPLOY_DIR"

echo ">>> Downloading latest telegraf.conf..."
curl -sSL "$GITHUB_RAW/telegraf.conf" -o telegraf.conf.new
mv telegraf.conf.new telegraf.conf

echo ">>> Downloading latest promtail.yml..."
curl -sSL "$GITHUB_RAW/promtail.yml" -o promtail.yml.new
mv promtail.yml.new promtail.yml

echo ">>> Restarting telegraf..."
curl -s --unix-socket /var/run/docker.sock -X POST http://localhost/containers/telegraf/restart || true

echo ">>> Restarting promtail..."
curl -s --unix-socket /var/run/docker.sock -X POST http://localhost/containers/promtail/restart || true

echo ">>> Deploy complete"
