#!/usr/bin/env python3
"""
GitHub Webhook Listener for Auto-Deploy

Handles:
- push events: update telegraf/promtail configs
- release events: update inverter-control and inverter-dashboard

Run with: python server.py
Or as Docker container alongside other services.
"""

import os
import re
import hmac
import hashlib
import subprocess
import base64
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DEPLOY_SCRIPT = os.environ.get("DEPLOY_SCRIPT", "/app/deploy-local.sh")
ALLOWED_BRANCHES = ["main", "master"]

# SSH config for Cerbo (mounted from host or configured in container)
CERBO_HOST = os.environ.get("CERBO_HOST", "Cerbo")

# Git tags are restricted to this pattern before they are ever interpolated
# into a remote shell command (see update_inverter_control) to prevent
# command injection via a crafted release tag name.
TAG_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature"""
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set, skipping verification")
        return True

    if not signature:
        return False

    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected, signature)


def run_command(cmd: list, timeout: int = 300) -> tuple:
    """Run command and return (success, output)"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def update_inverter_control(tag: str) -> tuple:
    """Update inverter-control on Cerbo via SSH.

    Downloads the release tarball for `tag` and unpacks the packaged files
    (main.py, the inverter_control/ package, version, gitHubInfo) into
    /data/inverter-control, preserving local-only config (local_config.py,
    ui_config_local.py, certificates, services/).

    `tag` is otherwise attacker-controlled (comes from the GitHub release
    payload) and is interpolated into a command run by a remote shell, so it
    is validated against TAG_PATTERN above (restricted to a safe character
    set) and wrapped in single quotes before being embedded here. Note:
    shlex.quote() is not usable since `tag` is embedded inside a string that
    is already single-quoted for the remote shell.
    """
    if not TAG_PATTERN.match(tag):
        logger.warning("Rejected release tag with invalid format")
        return False, "Failed: invalid tag format"

    logger.info(f"Updating inverter-control to {sanitize_for_logging(tag)}")

    commands = [
        # Download the release tarball and unpack the packaged files.
        # `set -e` + `curl -f` abort on any failure (a 404 must not be
        # treated as success - curl -sL would return exit 0 on HTTP 404).
        "set -e; "
        "DEPLOY=/data/.inverter-control-deploy; "
        'rm -rf "$DEPLOY"; mkdir -p "$DEPLOY"; '
        f"curl -fsSL 'https://codeload.github.com/victron-venus/inverter-control/tar.gz/refs/tags/{tag}' "
        '| tar -xz -C "$DEPLOY" --strip-components=1; '
        'cp "$DEPLOY"/main.py /data/inverter-control/main.py; '
        'cp -r "$DEPLOY"/inverter_control /data/inverter-control/; '
        'cp "$DEPLOY"/version /data/inverter-control/version; '
        'cp "$DEPLOY"/gitHubInfo /data/inverter-control/gitHubInfo; '
        # Best effort: remove 404 stubs written by older flat-file deploys
        "cd /data/inverter-control; "
        "for f in config.py console_server.py homeassistant.py keepalive.py mqtt_bridge.py ui_config.py victron.py; do "
        'if [ "$(cat "$f" 2>/dev/null)" = "404: Not Found" ]; then rm -f "$f"; fi; done; '
        'rm -rf "$DEPLOY"',
        # Restart the service
        "svc -t /service/inverter-control",
    ]

    for cmd in commands:
        success, output = run_command(["ssh", CERBO_HOST, cmd])
        if not success:
            return False, f"Failed: {output}"

    return True, f"Updated to {tag}"


def update_inverter_dashboard(tag: str) -> tuple:
    """Trigger inverter-dashboard self-update"""
    logger.info("Triggering inverter-dashboard update to %s", sanitize_for_logging(tag))

    # inverter-dashboard has self-update mechanism
    # We just need to send MQTT command or wait for it to auto-update
    # For now, restart the container to trigger update on startup
    success, output = run_command(
        [
            "curl",
            "-s",
            "--unix-socket",
            "/var/run/docker.sock",
            "-X",
            "POST",
            "http://localhost/containers/inverter-dashboard/restart",
        ],
        timeout=60,
    )

    if success:
        return True, f"Restarted dashboard container to update to {tag}"
    return False, output


def run_deploy_script():
    """Execute the deploy script and handle results"""
    try:
        result = subprocess.run(
            [DEPLOY_SCRIPT], capture_output=True, text=True, timeout=300, check=False
        )

        if result.returncode == 0:
            logger.info("Deploy successful")
            return jsonify({"status": "deployed"})

        logger.exception("Deploy failed: %s", sanitize_for_logging(result.stderr))
        return jsonify({"status": "failed", "error": result.stderr}), 500

    except subprocess.TimeoutExpired:
        logger.exception("Deploy timed out")
        return jsonify({"status": "timeout"}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


@app.route("/webhook", methods=["POST"])
def webhook():
    """GitHub webhook endpoint"""
    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, signature):
        logger.warning("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 401

    # Parse event
    raw_event = request.headers.get("X-GitHub-Event", "")
    event = sanitize_for_logging(raw_event)
    logger.info("Received %s event", event)

    if event == "release":
        return handle_release_event(request.json)

    if event == "push":
        return handle_push_event(request.json)

    logger.info("Ignoring event: %s", event)
    return jsonify({"status": "ignored", "event": event})


def sanitize_for_logging(value: str) -> str:
    """Sanitize user input for logging - prevents injection, preserves data.

    Allows alphanumeric, dash, underscore. Encodes other chars via base64.
    Truncates to 50 chars to prevent log flooding.
    """
    if not value:
        return "<empty>"
    if all(c.isalnum() or c in "-_" for c in value):
        return value[:50]
    return base64.b64encode(value.encode("utf-8")).decode("ascii")[:50]


def handle_release_event(payload: dict):
    """Handle GitHub release event"""
    action = payload.get("action", "")
    if action != "published":
        logger.info(f"Ignoring release action: {sanitize_for_logging(action)}")
        return jsonify({"status": "ignored", "action": action})

    release = payload.get("release", {})
    tag = release.get("tag_name", "")

    if not tag:
        return jsonify({"status": "ignored", "reason": "no tag"})

    repo = payload.get("repository", {}).get("name", "")
    logger.info(f"Processing release {sanitize_for_logging(tag)} for {sanitize_for_logging(repo)}")

    results = {}

    if repo == "inverter-control":
        success, msg = update_inverter_control(tag)
        results["inverter-control"] = {"success": success, "message": msg}

    elif repo == "inverter-dashboard":
        success, msg = update_inverter_dashboard(tag)
        results["inverter-dashboard"] = {"success": success, "message": msg}

    else:
        return jsonify({"status": "ignored", "repo": sanitize_for_logging(repo)})

    status = "deployed" if all(r["success"] for r in results.values()) else "partial"
    return jsonify({"status": status, "tag": tag, "results": results})


def handle_push_event(payload: dict):
    """Handle GitHub push event"""
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "")

    if branch not in ALLOWED_BRANCHES:
        logger.info(f"Ignoring push to branch: {sanitize_for_logging(branch)}")
        return jsonify({"status": "ignored", "branch": branch})

    repo = payload.get("repository", {}).get("name", "")

    if repo != "inverter-monitoring":
        logger.info(f"Ignoring push to repo: {sanitize_for_logging(repo)}")
        return jsonify({"status": "ignored", "repo": repo})

    commits = payload.get("commits", [])
    pusher = payload.get("pusher", {}).get("name", "unknown")

    logger.info(
        f"Received push to {sanitize_for_logging(branch)} by {sanitize_for_logging(pusher)} ({len(commits)} commits)"
    )

    return run_deploy_script()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9000))
    host = os.environ.get("HOST", "127.0.0.1")
    logger.info(f"Starting webhook server on {host}:{port}")
    app.run(host=host, port=port)
