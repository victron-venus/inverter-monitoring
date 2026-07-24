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
import hmac
import hashlib
import subprocess
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def update_inverter_control(tag: str) -> tuple:
    """Update inverter-control on Cerbo via SSH"""
    logger.info(f"Updating inverter-control to {tag}")

    # Use SSH to update on Cerbo
    # Cerbo doesn't have git, so we use curl to download files
    commands = [
        # Download updated files
        f"cd /data/inverter-control && "
        f"for f in main.py config.py victron.py homeassistant.py mqtt_bridge.py ui_config.py keepalive.py console_server.py version; do "
        f"curl -sL 'https://raw.githubusercontent.com/victron-venus/inverter-control/{tag}/'$f -o $f.new 2>/dev/null && mv $f.new $f; "
        f"done",
        # Restart service
        "svc -t /service/inverter-control",
    ]

    for cmd in commands:
        success, output = run_command(["ssh", CERBO_HOST, cmd])
        if not success:
            return False, f"Failed: {output}"

    return True, f"Updated to {tag}"


def update_inverter_dashboard(tag: str) -> tuple:
    """Trigger inverter-dashboard self-update"""
    logger.info(f"Triggering inverter-dashboard update to {tag}")

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
    event = request.headers.get("X-GitHub-Event", "")
    payload = request.json
    repo = payload.get("repository", {}).get("name", "")

    logger.info(f"Received {event} event for {repo}")

    # Handle release events
    if event == "release":
        action = payload.get("action", "")
        if action != "published":
            logger.info(f"Ignoring release action: {action}")
            return jsonify({"status": "ignored", "action": action})

        release = payload.get("release", {})
        tag = release.get("tag_name", "")

        if not tag:
            return jsonify({"status": "ignored", "reason": "no tag"})

        logger.info(f"Processing release {tag} for {repo}")

        results = {}

        if repo == "inverter-control":
            success, msg = update_inverter_control(tag)
            results["inverter-control"] = {"success": success, "message": msg}

        elif repo == "inverter-dashboard":
            success, msg = update_inverter_dashboard(tag)
            results["inverter-dashboard"] = {"success": success, "message": msg}

        else:
            return jsonify({"status": "ignored", "repo": repo})

        status = "deployed" if all(r["success"] for r in results.values()) else "partial"
        return jsonify({"status": status, "tag": tag, "results": results})

    # Handle push events (for monitoring config)
    if event == "push":
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "")

        if branch not in ALLOWED_BRANCHES:
            logger.info(f"Ignoring push to branch: {branch}")
            return jsonify({"status": "ignored", "branch": branch})

        # Only for inverter-monitoring repo
        if repo != "inverter-monitoring":
            logger.info(f"Ignoring push to repo: {repo}")
            return jsonify({"status": "ignored", "repo": repo})

        commits = payload.get("commits", [])
        pusher = payload.get("pusher", {}).get("name", "unknown")

        logger.info(f"Received push to {branch} by {pusher} ({len(commits)} commits)")

        # Trigger deploy for monitoring configs
        try:
            result = subprocess.run([DEPLOY_SCRIPT], capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                logger.info("Deploy successful")
                return jsonify({"status": "deployed", "branch": branch, "commits": len(commits)})
            else:
                logger.exception(f"Deploy failed: {result.stderr}")
                return jsonify({"status": "failed", "error": result.stderr}), 500

        except subprocess.TimeoutExpired:
            logger.exception("Deploy timed out")
            return jsonify({"status": "timeout"}), 500
        except Exception as e:
            logger.exception(f"Deploy error: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    # Ignore other events
    logger.info(f"Ignoring event: {event}")
    return jsonify({"status": "ignored", "event": event})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9000))
    host = os.environ.get("HOST", "127.0.0.1")
    logger.info(f"Starting webhook server on {host}:{port}")
    app.run(host=host, port=port)
