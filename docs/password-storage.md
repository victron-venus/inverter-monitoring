# Account password storage

The supplied Compose deployment creates external-user accounts in Grafana and
InfluxDB, so their password storage is part of this project's assessment even
though the implementations are upstream. The webhook instead verifies delivery
HMACs; an HMAC secret is not a stored password verifier.

## Reviewed versions

`docker-compose.yml` pins the following official multi-platform images. On
2026-10-16 these were exactly the images selected by the former `latest` and
`2.7` tags; pinning does not start or upgrade any running container.

- Grafana `13.2.4`, manifest
  `sha256:dbbc38ea21103cefb50396340cd88afec779c7e070b0a7bf5a75b4ce46651d3f`.
- InfluxDB `2.7.12`, manifest
  `sha256:b8d940ca9376f85118260f5b6bd236b8a00b1749c3350c5578d4cde8e27f31f2`.

Grafana creates a random per-user salt and stores a PBKDF2-HMAC-SHA-256 password
verifier using 10,000 iterations. The salt is generated through Go's
cryptographic random generator. This is a description of upstream behavior,
not a claim that its work factor meets every current password-hardening guide.
See the reviewed [user creation code](https://github.com/grafana/grafana/blob/6259becc8e86265fdf35a73e08eef5bd92b5cd73/pkg/services/user/userimpl/legacy_user.go)
and [password encoding and randomness](https://github.com/grafana/grafana/blob/6259becc8e86265fdf35a73e08eef5bd92b5cd73/pkg/util/encoding.go).

InfluxDB stores a bcrypt password verifier using the Go bcrypt default cost
of 10. Bcrypt generates a fresh 16-byte random salt per verifier and embeds it
in the stored value. See the reviewed
[password service](https://github.com/influxdata/influxdb/blob/ec9dcde5d6f0e1c4d15ff2332127987a42ca30fc/tenant/service_user.go),
[dependency version](https://github.com/influxdata/influxdb/blob/ec9dcde5d6f0e1c4d15ff2332127987a42ca30fc/go.mod)
and [bcrypt implementation](https://github.com/golang/crypto/blob/v0.36.0/bcrypt/bcrypt.go).

Both implementations use iterated hashes with per-user salts. API tokens,
Grafana data-source credentials and the bootstrap environment have separate
protection requirements: do not mistake a hashed login password for encryption
of all deployment secrets. Keep `.env`, persistent volumes and their backups
private, and follow [secure deployment](secure-deployment.md).

## Updates and verification scope

Review upstream security advisories and update these versions and digests through
a tested PR. Recheck the password implementation when changing versions.
Compose configuration tests validate required credentials, private binding and
preserved service wiring without starting containers. This source review does
not inspect an operator's existing account database or certify its migration
history; operators must follow upstream account/password migration guidance.
