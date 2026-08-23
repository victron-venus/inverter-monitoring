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
curl -sSL --proto '=https' --tlsv1.2 "$GITHUB_RAW/telegraf.conf" -o telegraf.conf.new
mv telegraf.conf.new telegraf.conf

echo ">>> Downloading latest promtail.yml..."
curl -sSL --proto '=https' --tlsv1.2 "$GITHUB_RAW/promtail.yml" -o promtail.yml.new
mv promtail.yml.new promtail.yml

# Grafana dashboards are bind-mounted read-only into the grafana container;
# the file provider rescans them automatically, so no restart is needed for
# new/updated dashboard JSONs - only for provisioning changes.
for f in $(curl -sSL --proto '=https' --tlsv1.2 \
    "https://api.github.com/repos/victron-venus/inverter-monitoring/contents/grafana/dashboards" \
    | grep '"name"' | cut -d'"' -f4); do
  case "$f" in
    *.json)
      echo ">>> Downloading dashboard $f..."
      curl -sSL --proto '=https' --tlsv1.2 "$GITHUB_RAW/grafana/dashboards/$f" \
          -o "grafana/dashboards/$f"
      ;;
  esac
done

echo ">>> Restarting telegraf..."
curl -s --unix-socket /var/run/docker.sock -X POST http://localhost/containers/telegraf/restart || true

echo ">>> Restarting promtail..."
curl -s --unix-socket /var/run/docker.sock -X POST http://localhost/containers/promtail/restart || true

echo ">>> Restarting grafana (picks up provisioning + datasource changes)..."
curl -s --unix-socket /var/run/docker.sock -X POST http://localhost/containers/grafana/restart || true

echo ">>> Deploy complete"
