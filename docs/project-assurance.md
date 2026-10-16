# Architecture, security evidence and roadmap

## Getting started and boundaries

Use [README](../README.md) for the Compose stack and dashboards and
[secure deployment](secure-deployment.md) for credentials, local binding and
migration. [CONTRIBUTING](../CONTRIBUTING.md) lists repeatable local checks.
[RELEASING](../RELEASING.md) describes source-bound release qualification.

Telegraf collects MQTT readings and writes InfluxDB. Grafana queries that data;
Promtail optionally sends logs to Loki. `analysis/grid_correlation.py` performs
offline analysis of exported grid measurements. `webhook/server.py` authenticates
optional GitHub deliveries before reading their event payload. Normal operation
does not deploy releases. Published stable releases can reach explicitly enabled
SSH/container operations; branch pushes and successful CI events never do.

The application uses standard Python `hmac`/`hashlib` HMAC-SHA-256, with constant
time digest comparison. Generate independent secrets with `openssl rand -hex 32`;
32 random bytes provide 256 bits before hexadecimal encoding. The service rejects
keys shorter than 32 UTF-8 bytes. Length alone cannot prove randomness, so a long
human-selected phrase is not an acceptable substitute. The webhook does not
store password verifiers. Grafana/InfluxDB own their account databases; their
password-storage behavior is not implemented by this repository.

## Deployment authorization and transport

An authenticated payload must be a JSON object. Deployment additionally requires
`published`, a strict stable version, explicit false draft/prerelease flags,
operator opt-in and exactly `victron-venus/inverter-control` or
`victron-venus/inverter-dashboard`. A matching repository basename in a different
organization cannot trigger it.

SSH deployment uses batch-only authentication, strict known-host verification,
Ed25519 host and client keys, Curve25519 key exchange and authenticated ChaCha20
or AES-256-GCM encryption. An operator must provision the correct Ed25519 host
key out of band and a dedicated authorized Ed25519 client key. Older servers or
accounts lacking those algorithms fail; do not disable host verification to
restore connectivity. These choices provide at least 128-bit security and
forward secrecy. The remote installer is downloaded completely over verified
HTTPS before extraction in a fresh private temporary directory. Download failure
prevents extraction/execution and cleans up the directory. HTTPS is required on
redirects; GitHub release-source trust and the remote curl trust store remain
operator responsibilities. This is not a signature check for the extracted
installer. Deployment grants significant authority to the chosen upstream code.

Keep `AUTO_DEPLOY_STABLE_RELEASES=false` unless those prerequisites and a target
rollback plan have been verified. Container restart is not evidence that a
requested dashboard version was installed. The legacy `deploy-local.sh` helper
is not invoked by webhook events; it downloads current monitoring configuration
and must not be treated as a source-pinned release installer.

## Validation and evidence limits

Tests send actual signed Flask requests and execute the generated remote shell
only with isolated fake commands. They exercise malformed payloads, repository
identity, secret rejection, transfer failures, stable-release gates, Compose
credential enforcement and offline analysis. Unix-socket tests exercise real
curl responses without contacting the Docker daemon. RC fuzzing mutates the
actual HMAC verifier; it does not authorize deployment or contact devices.

Ruff, mypy, pytest, CodeQL, Bandit and dependency checks are complementary.
The Python coverage report does not measure Grafana dashboards, shell, external
containers or electrical behavior. [CHANGELOG](../CHANGELOG.md) records delivered
changes; a passing CI run is not target-device acceptance.

## Roadmap

Next steps are signed/source-pinned optional deployment end to end, broader
container integration tests and explicit review of all externally supplied
configuration. Audit maintained-source coverage before claiming the Silver 80%
threshold. Establish an independent recovery arrangement; there is currently
no backup maintainer or one-week access recovery, as stated in
[governance](../GOVERNANCE.md). A complete security assurance case, independently
reproduced identical artifacts and comprehensive accessibility are not claimed.
