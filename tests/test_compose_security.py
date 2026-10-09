"""Render the real Compose model without starting containers or contacting Docker."""

import json
import os
import shutil

# Only fixed Compose config argv; no container startup or shell execution.
import subprocess  # nosec B404
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SECRETS = ("INFLUX_ADMIN_PASSWORD", "GRAFANA_ADMIN_PASSWORD", "INFLUX_TOKEN")
# Deliberately synthetic, distinct fixture values; never used with a running service.
SYNTHETIC_ENV = {
    "INFLUX_ADMIN_PASSWORD": "fixture-influx-" + "a" * 64,
    "GRAFANA_ADMIN_PASSWORD": "fixture-grafana-" + "b" * 64,
    "INFLUX_TOKEN": "fixture-token-" + "c" * 64,
    "MQTT_HOST": "mqtt.invalid",
    # Exercise the disabled, unauthenticated webhook configuration; not a credential.
    "WEBHOOK_SECRET": "",  # nosec B105
}


@pytest.fixture(scope="module")
def docker() -> str:
    executable = shutil.which("docker")
    assert executable is not None, "Docker CLI with Compose v2+ is required; no daemon is needed"
    return executable


def render(
    docker: str,
    tmp_path: Path,
    values: dict[str, str],
    *,
    example: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Ignore the operator's .env and shell overrides; render only synthetic inputs."""
    (tmp_path / "docker-compose.yml").write_bytes((ROOT / "docker-compose.yml").read_bytes())
    text = (ROOT / ".env.example").read_text() if example else ""
    text += "\n" + "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    (tmp_path / ".env").write_text(text)
    # Absolute Docker CLI, fixed config argv and an isolated synthetic .env.
    return subprocess.run(  # nosec B603
        [
            docker,
            "compose",
            "--project-name",
            "compose-security-test",
            "--env-file",
            str(tmp_path / ".env"),
            "--file",
            str(tmp_path / "docker-compose.yml"),
            "--profile",
            "webhook",
            "config",
            "--format",
            "json",
        ],
        cwd=tmp_path,
        env={key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT") if key in os.environ},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("name", REQUIRED_SECRETS)
@pytest.mark.parametrize("empty", (False, True), ids=("missing", "empty"))
def test_required_credentials_reject_missing_or_empty(
    docker: str, tmp_path: Path, name: str, empty: bool
) -> None:
    values = SYNTHETIC_ENV.copy()
    if empty:
        values[name] = ""
    else:
        del values[name]
    result = render(docker, tmp_path, values)
    assert result.returncode != 0
    assert name in result.stderr
    assert not result.stdout.strip()


def test_unchanged_example_cannot_start_with_known_credentials(docker: str, tmp_path: Path) -> None:
    result = render(docker, tmp_path, {}, example=True)
    assert result.returncode != 0
    # Compose can validate services in any order; every credential is absent.
    assert any(name in result.stderr for name in REQUIRED_SECRETS)
    assert not result.stdout.strip()


@pytest.mark.parametrize("name", REQUIRED_SECRETS)
def test_example_requires_each_credential(docker: str, tmp_path: Path, name: str) -> None:
    values = SYNTHETIC_ENV.copy()
    del values[name]
    result = render(docker, tmp_path, values, example=True)
    assert result.returncode != 0
    assert name in result.stderr
    assert not result.stdout.strip()


@pytest.mark.parametrize("example", (False, True), ids=("defaults", "filled-example"))
def test_valid_settings_keep_services_private_and_authenticated(
    docker: str, tmp_path: Path, example: bool
) -> None:
    result = render(docker, tmp_path, SYNTHETIC_ENV, example=example)
    assert result.returncode == 0, result.stderr
    model = json.loads(result.stdout)
    services = model["services"]
    for service, published in (
        ("webhook", 9001),
        ("influxdb", 8086),
        ("grafana", 3000),
        ("loki", 3100),
    ):
        ports = services[service]["ports"]
        assert len(ports) == 1
        assert ports[0]["host_ip"] == "127.0.0.1"
        assert int(ports[0]["published"]) == published
    influx = services["influxdb"]["environment"]
    grafana = services["grafana"]["environment"]
    assert influx["DOCKER_INFLUXDB_INIT_PASSWORD"] == SYNTHETIC_ENV["INFLUX_ADMIN_PASSWORD"]
    assert influx["DOCKER_INFLUXDB_INIT_ADMIN_TOKEN"] == SYNTHETIC_ENV["INFLUX_TOKEN"]
    assert grafana["GF_SECURITY_ADMIN_PASSWORD"] == SYNTHETIC_ENV["GRAFANA_ADMIN_PASSWORD"]
    assert grafana["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert services["webhook"]["environment"]["WEBHOOK_SECRET"] == ""
    assert services["webhook"]["environment"]["AUTO_DEPLOY_STABLE_RELEASES"] == "false"
    assert set(model["volumes"]) == {
        "influxdb-data",
        "influxdb-config",
        "grafana-data",
        "loki-data",
    }
    assert services["telegraf"]["environment"]["INFLUX_URL"] == "http://influxdb:8086"
    assert services["telegraf"]["depends_on"]["influxdb"]["condition"] == "service_healthy"


def test_remote_bind_and_anonymous_access_require_explicit_opt_in(
    docker: str, tmp_path: Path
) -> None:
    values = {
        **SYNTHETIC_ENV,
        "MONITORING_BIND_ADDRESS": "192.0.2.10",
        "GRAFANA_ANONYMOUS_ENABLED": "true",
    }
    result = render(docker, tmp_path, values)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in ("webhook", "influxdb", "grafana", "loki"):
        assert services[name]["ports"][0]["host_ip"] == "192.0.2.10"
    assert services["grafana"]["environment"]["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
