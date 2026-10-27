# Changelog

## [1.3.11] - 2026-10-27

### Changed

- Update the locked MarkupSafe runtime dependency to 3.0.4 and refresh the pinned Python webhook container image.
- Preserve existing monitoring and webhook configuration.
- Publish candidate assets against the known release ID and wait for Release gate propagation within the existing timeout, while rejecting mismatched or failed validation.

### Upgrade

Use the existing installation procedure and preserve local configuration and persistent volumes. Rebuild the optional webhook image to receive the locked dependency and base-image updates. No configuration migration is required. Keep the previous immutable release or image available for rollback; publishing this release does not deploy it.

### Security

Existing webhook authentication, transport verification and release-validation requirements remain in force. The dependency and image refresh does not claim to fix a newly identified application vulnerability. Candidate publication continues to reject failed checks, ambiguous release gates and unverified asset bytes; this beta does not establish physical-device acceptance.

## [1.3.10] - 2026-10-23

### Security

- Upgrade the webhook image and CI installer to uv 0.13.4, removing the distrusted emSign ECC Root CA - G3 from the bundled certificate store (GHSA-hq85-5cpj-mr62).

### Upgrade

Rebuild the webhook image to receive the corrected installer. Preserve existing configuration and data; no application dependency or configuration migration is required. Keep the previous immutable image available for rollback.

## [1.3.9] - 2026-10-18

### Changed

- Route Dependabot metadata approval through the trusted default branch while preserving the existing author and review policy.
- Refresh the documented Grafana preview and pinned shared CI workflows.

### Upgrade

Use the documented upgrade procedure and preserve local configuration and data. No configuration migration is required. Keep the previous immutable release available for rollback.

### Security

This maintenance release preserves the existing security and release-validation requirements. Publication does not deploy the service or establish physical-device acceptance.

## [1.3.8] - 2026-10-17

- Reject short webhook secrets and malformed authenticated payloads, and require the full allowed GitHub repository identity before deployment.
- Require verified Ed25519 SSH identities and forward-secret authenticated encryption for optional device deployment.
- Finish HTTPS downloads before extracting or running installers, with private temporary staging and cleanup.
- Add an explicit OpenSSL level-3 installer profile for at least 128-bit TLS certificate strength; preserve default device compatibility.
- Document governance, security assumptions and remaining assurance work.

### Upgrade

Rotate short webhook secrets on both sides using `openssl rand -hex 32`. Provision verified Ed25519 SSH host/client keys before enabling optional deployment. Existing monitoring data and volumes are unchanged.

### Security

Automatic deployment stays disabled by default. Transport verification and transfer failure handling are strengthened; source downloads still trust the configured GitHub repository and remote TLS trust store. No target deployment or acceptance is implied.

## [1.3.7] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

RC publication rejects absent or invalid source-bound fuzz reports. The fuzz runner bounds corpus paths, file types and size. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

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
