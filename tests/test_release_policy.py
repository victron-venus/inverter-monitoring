"""Release validation and deployment are separate, fail-closed operations."""

import hashlib
import hmac
import importlib.util
import json
import os
from unittest import mock

import pytest

from webhook import server


@pytest.fixture()
def delivery(monkeypatch):
    secret = "release-policy-test-secret"
    monkeypatch.setattr(server, "WEBHOOK_SECRET", secret)
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", False)
    fail = mock.Mock(side_effect=AssertionError("Tests must not run deployment commands"))
    monkeypatch.setattr(server, "run_command", fail)
    monkeypatch.setattr(server.subprocess, "run", fail)
    server.app.config["TESTING"] = True
    client = server.app.test_client()

    def post(event, payload):
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return client.post(
            "/webhook",
            data=body,
            content_type="application/json",
            headers={"X-GitHub-Event": event, "X-Hub-Signature-256": signature},
        )

    return post


def stable_payload():
    return {
        "action": "published",
        "release": {"tag_name": "v1.2.3", "draft": False, "prerelease": False},
        "repository": {"name": "inverter-control"},
    }


def test_manual_deployment_is_the_process_default():
    with mock.patch.dict(os.environ, {}, clear=True):
        spec = importlib.util.spec_from_file_location("isolated_monitoring_policy", server.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.AUTO_DEPLOY_STABLE_RELEASES is False


def test_stable_release_requires_operator_opt_in(delivery):
    result = delivery("release", stable_payload())
    assert result.status_code == 200
    assert result.json["reason"] == "automatic stable deployment disabled"


@pytest.mark.parametrize(
    "tag",
    ["nightly", "v1.2.3-beta.1", "v1.2.3-rc.1", "v1.2.3+build", "v01.2.3", "v1.2.3\n", "latest"],
)
def test_channel_tags_never_deploy_even_with_opt_in(delivery, monkeypatch, tag):
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", True)
    payload = stable_payload()
    payload["release"]["tag_name"] = tag
    assert delivery("release", payload).json["status"] == "ignored"


@pytest.mark.parametrize(
    "field,value",
    [("draft", True), ("prerelease", True), ("draft", None), ("prerelease", "false"), ("draft", 0)],
)
def test_unverified_release_flags_never_deploy(delivery, monkeypatch, field, value):
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", True)
    payload = stable_payload()
    payload["release"][field] = value
    assert delivery("release", payload).json["status"] == "ignored"


def test_missing_flags_never_deploy(delivery, monkeypatch):
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", True)
    payload = stable_payload()
    del payload["release"]["draft"]
    assert delivery("release", payload).json["status"] == "ignored"


@pytest.mark.parametrize(
    "event,ref",
    [
        ("push", "refs/heads/main"),
        ("push", "refs/tags/v1.2.3"),
        ("push", "refs/tags/v1.2.3-rc.1"),
        ("workflow_run", "refs/heads/main"),
    ],
)
def test_push_tag_and_ci_never_deploy(delivery, monkeypatch, event, ref):
    monkeypatch.setattr(server, "AUTO_DEPLOY_STABLE_RELEASES", True)
    payload = {
        "action": "completed",
        "ref": ref,
        "repository": {"name": "inverter-monitoring"},
        "workflow_run": {"name": "CI", "head_branch": "main", "conclusion": "success"},
    }
    assert delivery(event, payload).json["status"] == "ignored"
