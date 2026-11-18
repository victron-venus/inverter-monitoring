# Documentation

A Grafana-based monitoring stack for a Victron installation, with the credential
handling and deployment limits that come with the supplied Compose file.

## Deploy

- [Compose credentials and access](secure-deployment.md) — the Compose requirement and what the file deliberately does not do.
- [Account password storage](password-storage.md) — how Grafana and external-user accounts are created.
- [Dashboard screenshot artwork](images/README.md) — the real Grafana capture used in the README.

## Assurance

- [Architecture, security evidence and roadmap](project-assurance.md) — the stack, what is evidenced and what is planned.
- [OpenSSF Best Practices evidence: inverter-monitoring](openssf-evidence.md) — the index behind the assessment.

## Releases

- [Release version inputs](release-versioning.md) — the `versioning` fields that identify a release.
- [CI and release operations](release-workflow.md) — `.release-policy.json` and the required status.
- [CI orchestration](CI-ORCHESTRATION.md) — how the quality gate and release pipeline divide the events.
- [Version plans and manifest synchronization](VERSIONING.md) — the versioning opt-in.
- [Release-candidate fuzz testing](fuzzing.md) — the illustrated RC fuzzing process.
- [Fuzzing release candidates](rc-fuzzing.md) — the reusable bounded fuzz workflow.
- [Release read recovery and rerun validation](release-read-safety.md) — the two fixes carried from the shared toolkit.
- [Early final-build runner check](runner-preflight.md) — why the check runs before the final build.
