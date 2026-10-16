# Changelog

## [1.3.7] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

The release gate rejects absent or invalid fuzz evidence and unsafe seed inputs. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

## [1.3.6] - Development line

### Release candidate validation

- Require bounded fuzzing on public release candidates, with source-bound reports and retained diagnostics; beta and ordinary CI do not run mutation campaigns.
- Instrument the production webhook signature verifier through the normal import hook and reject RC fuzz startup if production instrumentation is missing.

### Changes

- Reuse blended analysis series across filter candidates while preserving report output.
- Require explicit monitoring credentials, bind published ports to loopback by default, and disable anonymous Grafana viewing unless explicitly enabled.
- Update Werkzeug and the pinned uv/webhook tooling, enforce complete security scans, and verify deterministic release archives.
- Fix release API status handling and refresh shared CI and release-helper analysis.

### Upgrade

Set nonempty `INFLUX_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` and `INFLUX_TOKEN` before recreating services. Existing stored credentials are not rotated by editing `.env`. Follow [the migration guide](docs/secure-deployment.md) to preserve data and arrange authenticated remote access.

### Security

Remove known default admin passwords and require explicit credentials before services start. Published ports default to loopback and anonymous Grafana viewing is disabled by default. Rotate any previously used default credentials on existing instances; these defaults do not replace TLS or host access controls.

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
