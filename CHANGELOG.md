# Changelog

## [1.3.5] - Development line

### Release overview

Provides monitoring dashboards, telemetry analysis and an optional authenticated deployment webhook. The existing README documents configuration and external interfaces for this development line.

### Maintenance

- Publish reviewed release notes from the exact source commit used to build each candidate, preserving build provenance.
- Document contribution checks, confidential security reporting and the project-specific trust boundaries.
- Require complete Bandit scans with no unresolved findings; reject malformed or incomplete scanner output. Document narrowly reviewed tooling and synthetic-fixture exceptions.

### Upgrade

These maintenance changes do not introduce a configuration or data migration. Retain local configuration and credentials when using the documented update procedure. Validate the candidate on an isolated system before production use; automated checks do not establish hardware acceptance.

### Security

Pin uv 0.12.18 in CI and the webhook image, retaining an immutable image digest.
This replaces the version listed in
[GHSA-2cv4-cqwr-gwf7](https://github.com/advisories/GHSA-2cv4-cqwr-gwf7); that
upstream issue affects Windows wheel installation, not this Linux webhook.

Private vulnerability reporting and response policy are documented in SECURITY.md. This maintenance update strengthens release evidence and review instructions; it does not replace deployment authentication, network isolation or independent equipment safeguards. No new project CVE is announced by these changes.
