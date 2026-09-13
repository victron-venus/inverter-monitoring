"""Tests for the GitHub webhook listener (webhook/server.py)."""

import base64
import hashlib
import hmac
import logging
import secrets
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from webhook import server


@pytest.fixture()
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture()
def signed_requests(client, monkeypatch):
    """Sign functional-test deliveries using the exact JSON bytes sent to Flask."""
    secret = secrets.token_hex(32)
    monkeypatch.setattr(server, "WEBHOOK_SECRET", secret)
    original_post = client.post

    def signed_post(path, *, json, headers=None, **kwargs):
        payload = server.app.json.dumps(json).encode("utf-8")
        request_headers = dict(headers or {})
        request_headers["X-Hub-Signature-256"] = signed(payload, secret)
        return original_post(
            path, data=payload, content_type="application/json", headers=request_headers, **kwargs
        )

    monkeypatch.setattr(client, "post", signed_post)


# ---------------------------------------------------------------- sanitize_for_logging


def test_sanitize_empty():
    assert server.sanitize_for_logging("") == "<empty>"


def test_sanitize_clean_value_kept():
    assert server.sanitize_for_logging("release-1_2") == "release-1_2"


def test_sanitize_dirty_value_base64():
    out = server.sanitize_for_logging("v1; rm -rf /")
    assert out == base64.b64encode(b"v1; rm -rf /").decode("ascii")


def test_sanitize_truncates_long_input():
    assert len(server.sanitize_for_logging("a" * 80)) == 50


# ---------------------------------------------------------------- verify_signature

PAYLOAD = b'{"action": "published"}'


def signed(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def test_verify_rejects_when_no_secret(monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "")
    assert server.verify_signature(PAYLOAD, "") is False


def test_verify_rejects_missing_signature(monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "s3cret")
    assert server.verify_signature(PAYLOAD, "") is False


def test_verify_accepts_valid_signature(monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "s3cret")
    assert server.verify_signature(PAYLOAD, signed(PAYLOAD, "s3cret")) is True


def test_verify_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "s3cret")
    assert server.verify_signature(PAYLOAD, "sha256=" + "0" * 64) is False


# ---------------------------------------------------------------- run_command


def test_run_command_success():
    ok, output = server.run_command(["echo", "hi"])
    assert ok is True
    assert "hi" in output


def test_run_command_failure_returns_output():
    ok, output = server.run_command(["sh", "-c", "echo boom >&2; exit 1"])
    assert ok is False
    assert "boom" in output


def test_run_command_timeout():
    ok, output = server.run_command(["sleep", "5"], timeout=1)
    assert ok is False
    assert output == "Command timed out"


def test_run_command_exception_is_reported():
    ok, _output = server.run_command(None)  # type: ignore[arg-type]
    assert ok is False


# ---------------------------------------------------------------- update_inverter_control


def test_update_control_rejects_injection_tag():
    ok, msg = server.update_inverter_control("v1.0.0'; rm -rf /;")
    assert ok is False
    assert msg == "Failed: invalid tag format"


def test_update_control_success(monkeypatch):
    calls = []

    def fake_run(cmd, timeout=300):
        calls.append(cmd)
        return True, ""

    monkeypatch.setattr(server, "run_command", fake_run)
    ok, msg = server.update_inverter_control("v1.2.3")
    assert ok is True
    assert msg == "Updated to v1.2.3"
    # Two commands: install + version verification.
    assert len(calls) == 2
    assert all(c[0] == "ssh" for c in calls)
    assert "refs/tags/v1.2.3" in calls[0][2]


def test_update_control_failure_returns_generic_message(monkeypatch):
    monkeypatch.setattr(server, "run_command", lambda cmd, timeout=300: (False, "ssh down"))
    ok, msg = server.update_inverter_control("v1.2.3")
    assert ok is False
    # Raw remote output must not reach the HTTP response.
    assert msg == "Failed: see server logs"
    assert "ssh down" not in msg


def test_update_control_fails_on_version_check(monkeypatch):
    calls = []

    def fake_run(cmd, timeout=300):
        calls.append(cmd)
        return len(calls) == 1, ""  # install ok, verification fails

    monkeypatch.setattr(server, "run_command", fake_run)
    ok, _msg = server.update_inverter_control("v1.2.3")
    assert ok is False


# ---------------------------------------------------------------- update_inverter_dashboard


def test_update_dashboard_success(monkeypatch):
    monkeypatch.setattr(server, "run_command", lambda cmd, timeout=60: (True, ""))
    ok, msg = server.update_inverter_dashboard("v2.0.0")
    assert ok is True
    assert "v2.0.0" in msg


def test_update_dashboard_failure(monkeypatch):
    monkeypatch.setattr(server, "run_command", lambda cmd, timeout=60: (False, "curl: (7) refused"))
    ok, msg = server.update_inverter_dashboard("v2.0.0")
    assert ok is False
    # Raw curl output must not reach the HTTP response.
    assert msg == "Failed: see server logs"
    assert "refused" not in msg


# ---------------------------------------------------------------- deploy script paths


def fake_completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def push_payload(branch="main", repo="inverter-monitoring"):
    return {
        "ref": f"refs/heads/{branch}",
        "repository": {"name": repo},
        "pusher": {"name": "ci-bot"},
        "commits": [{"id": "abc"}],
    }


def test_push_to_main_never_runs_deploy(client, signed_requests, monkeypatch):
    deploy = Mock(side_effect=AssertionError("Push must not execute a deployment"))
    monkeypatch.setattr(server.subprocess, "run", deploy)
    resp = client.post("/webhook", json=push_payload(), headers={"X-GitHub-Event": "push"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ignored"
    deploy.assert_not_called()


def test_explicit_deploy_failure(client, signed_requests, monkeypatch):
    monkeypatch.setattr(
        server.subprocess, "run", lambda *a, **k: fake_completed(returncode=1, stderr="boom")
    )
    with server.app.app_context():
        resp, status = server.run_deploy_script()
    assert status == 500
    assert resp.get_json()["status"] == "failed"


def test_explicit_deploy_timeout(client, signed_requests, monkeypatch):
    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="deploy", timeout=300)

    monkeypatch.setattr(server.subprocess, "run", raise_timeout)
    with server.app.app_context():
        resp, status = server.run_deploy_script()
    assert status == 500
    assert resp.get_json() == {"status": "timeout"}


# ---------------------------------------------------------------- webhook routing


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


@pytest.mark.parametrize("event", ["push", "release"])
def test_missing_secret_rejects_delivery_before_dispatch(client, monkeypatch, event):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "")
    handler = Mock()
    monkeypatch.setattr(server, f"handle_{event}_event", handler)

    response = client.post("/webhook", json={}, headers={"X-GitHub-Event": event})

    assert response.status_code == 503
    assert response.get_json() == {"error": "Webhook secret is not configured"}
    handler.assert_not_called()
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "signature", ["", "sha256=" + "0" * 64, "sha256=not-a-digest", "sha256=" + "\u00e9" * 64]
)
@pytest.mark.parametrize("event", ["push", "release"])
def test_invalid_signature_rejects_delivery_before_dispatch(client, monkeypatch, event, signature):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", secrets.token_hex(32))
    handler = Mock()
    monkeypatch.setattr(server, f"handle_{event}_event", handler)

    response = client.post(
        "/webhook",
        json={},
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": signature},
    )

    assert response.status_code == 401
    handler.assert_not_called()


def test_body_changed_after_signing_rejects_delivery(client, monkeypatch):
    secret = secrets.token_hex(32)
    monkeypatch.setattr(server, "WEBHOOK_SECRET", secret)
    handler = Mock()
    monkeypatch.setattr(server, "handle_release_event", handler)
    response = client.post(
        "/webhook",
        data=PAYLOAD + b" ",
        content_type="application/json",
        headers={"X-GitHub-Event": "release", "X-Hub-Signature-256": signed(PAYLOAD, secret)},
    )
    assert response.status_code == 401
    handler.assert_not_called()


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "s3cret")
    resp = client.post("/webhook", data=PAYLOAD, headers={"X-GitHub-Event": "push"})
    assert resp.status_code == 401


def test_webhook_ignores_unknown_event(client, signed_requests):
    resp = client.post("/webhook", json={}, headers={"X-GitHub-Event": "ping"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ignored"


@pytest.mark.parametrize(
    "event",
    ["ping\nFORGED", "ping\rFORGED", "ping\x1b[2JFORGED", "ping\u2028FORGED"],
)
def test_unknown_event_control_characters_never_reach_logs(client, signed_requests, caplog, event):
    """Untrusted WSGI header values cannot add content to application log records."""
    with caplog.at_level(logging.INFO, logger=server.logger.name):
        response = client.post(
            "/webhook", json={}, environ_overrides={"HTTP_X_GITHUB_EVENT": event}
        )

    assert response.status_code == 200
    assert response.get_json() == {"status": "ignored", "event": server.sanitize_for_logging(event)}
    messages = [
        record.getMessage() for record in caplog.records if record.name == server.logger.name
    ]
    assert "Ignoring unsupported GitHub event" in messages
    assert all(event not in message for message in messages)
    assert all(server.sanitize_for_logging(event) not in message for message in messages)


def release_payload(action="published", tag="v1.0.0", repo="inverter-control"):
    return {
        "action": action,
        "release": {"tag_name": tag, "prerelease": False, "draft": False},
        "repository": {"name": repo},
    }


def test_release_unpublished_action_ignored(client, signed_requests):
    resp = client.post(
        "/webhook", json=release_payload(action="created"), headers={"X-GitHub-Event": "release"}
    )
    assert resp.get_json()["status"] == "ignored"


def test_release_without_tag_ignored(client, signed_requests):
    payload = release_payload(tag="")
    resp = client.post("/webhook", json=payload, headers={"X-GitHub-Event": "release"})
    assert resp.get_json()["reason"] == "no tag"


def test_release_unknown_repo_ignored(client, signed_requests):
    resp = client.post(
        "/webhook",
        json=release_payload(repo="some-other-repo"),
        headers={"X-GitHub-Event": "release"},
    )
    assert resp.get_json()["status"] == "ignored"


def test_release_updates_inverter_control(client, signed_requests, monkeypatch):
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", True)
    seen = {}

    def fake_update(tag):
        seen["tag"] = tag
        return True, "Updated to v9.9.9"

    monkeypatch.setattr(server, "update_inverter_control", fake_update)
    resp = client.post("/webhook", json=release_payload(), headers={"X-GitHub-Event": "release"})
    body = resp.get_json()
    assert seen["tag"] == "v1.0.0"
    assert body["status"] == "deployed"
    assert body["results"]["inverter-control"]["success"] is True


def test_release_updates_dashboard(client, signed_requests, monkeypatch):
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", True)
    monkeypatch.setattr(server, "update_inverter_dashboard", lambda tag: (False, "nope"))
    resp = client.post(
        "/webhook",
        json=release_payload(repo="inverter-dashboard"),
        headers={"X-GitHub-Event": "release"},
    )
    body = resp.get_json()
    assert body["status"] == "partial"
    assert body["results"]["inverter-dashboard"]["success"] is False


def test_push_other_branch_ignored(client, signed_requests):
    resp = client.post(
        "/webhook", json=push_payload(branch="feature"), headers={"X-GitHub-Event": "push"}
    )
    assert resp.get_json()["branch"] == "feature"


def test_push_wrong_repo_ignored(client, signed_requests):
    resp = client.post(
        "/webhook", json=push_payload(repo="elsewhere"), headers={"X-GitHub-Event": "push"}
    )
    assert resp.get_json()["status"] == "ignored"
