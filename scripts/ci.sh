#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == security || "${1:-}" == bandit ]]; then
  uvx --from bandit==1.8.6 bandit -r . -lll -x .git,.venv,.venv-ci,tests,scripts/release.py,scripts/release_control.py
  if [[ "${1:-}" == security ]]; then
    command -v trivy >/dev/null || { echo 'Trivy is required for the complete local security gate.' >&2; exit 1; }
    trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 --skip-dirs .git,.venv,.venv-ci,release-dist,dist,build .
  fi
  exit 0
fi
uv sync --locked --all-extras
uv run --locked --with ruff==0.16.5 ruff check .
uv run --locked --with ruff==0.16.5 ruff format --check .
uv run --locked --with mypy==2.3.1 mypy .
uv run --locked --with pytest-cov==7.1.0 pytest --cov=. --cov-report=xml
