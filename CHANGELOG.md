# Changelog

## [1.3.5] - Development line

### Release overview

Provides monitoring dashboards, telemetry analysis and an optional authenticated deployment webhook. The existing README documents configuration and external interfaces for this development line.

### Maintenance

- Publish reviewed release notes from the exact source commit used to build each candidate, preserving build provenance.
- Document contribution checks, confidential security reporting and the project-specific trust boundaries.
- Require complete Bandit scans with no unresolved findings; reject malformed or incomplete scanner output. Document narrowly reviewed tooling and synthetic-fixture exceptions.

### Upgrade

Compose now requires nonempty `INFLUX_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`
and `INFLUX_TOKEN`. Published ports default to `127.0.0.1`; anonymous Grafana
viewing defaults to disabled. Existing volumes and stored credentials are not
rotated by editing `.env`. Follow [the migration guide](docs/secure-deployment.md)
to preserve data, replace any old default credentials and arrange remote access
before recreating services. Automated checks do not establish hardware acceptance.

### Security

Remove known default admin passwords and require explicit credentials before
Compose can start the stack. Limit default host port exposure to loopback and
require explicit opt-in for anonymous Grafana viewing. These defaults do not
replace TLS, host access controls or credential rotation on existing instances.


Pin uv 0.12.18 in CI and the webhook image, retaining an immutable image digest.
This replaces the version listed in
[GHSA-2cv4-cqwr-gwf7](https://github.com/advisories/GHSA-2cv4-cqwr-gwf7); that
upstream issue affects Windows wheel installation, not this Linux webhook.

Private vulnerability reporting and response policy are documented in SECURITY.md. This maintenance update strengthens release evidence and review instructions; it does not replace deployment authentication, network isolation or independent equipment safeguards. No new project CVE is announced by these changes.
