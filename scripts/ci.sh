#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Bandit can return zero after parser/plugin exceptions; validate its report too.
run_bandit() (
  uv run --no-build --no-project --python 3.12.13 --with-requirements .github/requirements-bandit.txt python scripts/run_bandit.py
)
if [[ "${1:-}" == security || "${1:-}" == bandit ]]; then
  run_bandit
  if [[ "${1:-}" == security ]]; then
    command -v trivy >/dev/null || { echo 'Trivy is required for the complete local security gate.' >&2; exit 1; }
    trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 --skip-dirs .git,.venv,.venv-ci,release-dist,dist,build .
  fi
  exit 0
fi
# Compose tests only render temporary configuration; no Docker daemon is needed.
docker compose version
uv sync --locked --all-extras --no-build --no-install-project
uv run --no-sync --no-build --with ruff==0.16.5 ruff check .
uv run --no-sync --no-build --with ruff==0.16.5 ruff format --check .
uv run --no-sync --no-build --with mypy==2.3.1 mypy .
uv run --no-sync --no-build --with pytest-cov==7.1.0 pytest --cov=. --cov-report=xml
