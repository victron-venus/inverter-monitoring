"""Tests for the GitHub webhook listener (webhook/server.py)."""

import base64
import hashlib
import hmac
import subprocess
from types import SimpleNamespace

import pytest

from webhook import server


@pytest.fixture()
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture()
def no_secret(monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "")


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


def test_verify_skips_when_no_secret(monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "")
    assert server.verify_signature(PAYLOAD, "") is True


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


def test_update_control_fails_on_first_command(monkeypatch):
    monkeypatch.setattr(server, "run_command", lambda cmd, timeout=300: (False, "ssh down"))
    ok, msg = server.update_inverter_control("v1.2.3")
    assert ok is False
    assert msg == "Failed: ssh down"


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
    assert "refused" in msg


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


def test_push_to_main_runs_deploy(client, no_secret, monkeypatch):
    monkeypatch.setattr(
        server.subprocess, "run", lambda *a, **k: fake_completed(stdout="", stderr="")
    )
    resp = client.post("/webhook", json=push_payload(), headers={"X-GitHub-Event": "push"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deployed"}


def test_push_deploy_failure(client, no_secret, monkeypatch):
    monkeypatch.setattr(
        server.subprocess, "run", lambda *a, **k: fake_completed(returncode=1, stderr="boom")
    )
    resp = client.post("/webhook", json=push_payload(), headers={"X-GitHub-Event": "push"})
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "failed"


def test_push_deploy_timeout(client, no_secret, monkeypatch):
    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="deploy", timeout=300)

    monkeypatch.setattr(server.subprocess, "run", raise_timeout)
    resp = client.post("/webhook", json=push_payload(), headers={"X-GitHub-Event": "push"})
    assert resp.status_code == 500
    assert resp.get_json() == {"status": "timeout"}


# ---------------------------------------------------------------- webhook routing


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(server, "WEBHOOK_SECRET", "s3cret")
    resp = client.post("/webhook", data=PAYLOAD, headers={"X-GitHub-Event": "push"})
    assert resp.status_code == 401


def test_webhook_ignores_unknown_event(client, no_secret):
    resp = client.post("/webhook", json={}, headers={"X-GitHub-Event": "ping"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ignored"


def release_payload(action="published", tag="v1.0.0", repo="inverter-control"):
    return {
        "action": action,
        "release": {"tag_name": tag},
        "repository": {"name": repo},
    }


def test_release_unpublished_action_ignored(client, no_secret):
    resp = client.post(
        "/webhook", json=release_payload(action="created"), headers={"X-GitHub-Event": "release"}
    )
    assert resp.get_json()["status"] == "ignored"


def test_release_without_tag_ignored(client, no_secret):
    payload = release_payload(tag="")
    resp = client.post("/webhook", json=payload, headers={"X-GitHub-Event": "release"})
    assert resp.get_json()["reason"] == "no tag"


def test_release_unknown_repo_ignored(client, no_secret):
    resp = client.post(
        "/webhook",
        json=release_payload(repo="some-other-repo"),
        headers={"X-GitHub-Event": "release"},
    )
    assert resp.get_json()["status"] == "ignored"


def test_release_updates_inverter_control(client, no_secret, monkeypatch):
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


def test_release_updates_dashboard(client, no_secret, monkeypatch):
    monkeypatch.setattr(server, "update_inverter_dashboard", lambda tag: (False, "nope"))
    resp = client.post(
        "/webhook",
        json=release_payload(repo="inverter-dashboard"),
        headers={"X-GitHub-Event": "release"},
    )
    body = resp.get_json()
    assert body["status"] == "partial"
    assert body["results"]["inverter-dashboard"]["success"] is False


def test_push_other_branch_ignored(client, no_secret):
    resp = client.post(
        "/webhook", json=push_payload(branch="feature"), headers={"X-GitHub-Event": "push"}
    )
    assert resp.get_json()["branch"] == "feature"


def test_push_wrong_repo_ignored(client, no_secret):
    resp = client.post(
        "/webhook", json=push_payload(repo="elsewhere"), headers={"X-GitHub-Event": "push"}
    )
    assert resp.get_json()["status"] == "ignored"
