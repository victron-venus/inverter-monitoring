# Compose credentials and access

The supplied Compose file requires Docker Compose v2 or newer. It deliberately
has no default `INFLUX_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` or `INFLUX_TOKEN`:
a missing or empty value fails configuration validation before container startup.
Generate each value separately with `openssl rand -hex 32` for a new installation,
then store it in a private `.env` (`chmod 600 .env`). The usernames may remain
`admin`; the passwords must be unique. Never commit the file or paste rendered
configuration into reports: `docker compose config` includes resolved secrets.
Use `docker compose config --quiet` to validate without printing them.

The optional webhook remains disabled unless its profile is selected. Generate a
separate `WEBHOOK_SECRET` before enabling it; an empty secret makes the server
reject webhook requests. Automatic deployment also remains separately opt-in.

## Existing installations

Updating the Compose file does not rotate accounts, delete data or reinitialize
volumes. Keep the existing `.env` and back up the data and configuration before
making operational changes. Do not copy the blank example over existing settings
or delete volumes to apply a credential change.

1. Record the actual InfluxDB organization, bucket and token and existing Grafana
   account. Populate all required variables. Initialization passwords only create
   accounts on first setup; changing those variables does not change passwords in
   an already initialized database.
2. If any old default or example credential was used, change the actual account
   passwords through the application's supported account administration. Create a
   replacement InfluxDB token with the needed bucket permissions, update every
   consumer (including Telegraf and Grafana), verify access, then revoke the old
   token. Store the matching new values in `.env`. Plan this operation yourself;
   the repository does not automatically rotate live credentials.
3. Arrange access before recreating containers. All published ports (Grafana
   3000, InfluxDB 8086, Loki 3100 and optional webhook 9001) now bind to loopback.
   Existing containers keep their old port mappings until recreated. Validate
   with `docker compose config --quiet`, then apply the update in your maintenance
   window and verify the resulting mappings with `docker compose ps`.

Grafana's [`admin_password` is a first-run setting](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/#admin_password).
InfluxDB's [Docker setup variables initialize a new instance](https://docs.influxdata.com/influxdb/v2/install/use-docker-compose/).
Existing stored credentials need explicit administration, not just new environment
values. The Compose change preserves the named volumes and internal service URLs.

## Remote access

For administration, keep the loopback defaults and use a trusted SSH tunnel, for
example `ssh -L 3000:127.0.0.1:3000 user@monitoring-host`, then open
`http://localhost:3000` locally. Verify the SSH host key. A reverse proxy running
on the same host can also reach loopback; configure verified HTTPS and appropriate
authentication there. A proxy in another container needs an explicitly arranged
container network route, not the host's loopback address.

If direct LAN access is necessary, set `MONITORING_BIND_ADDRESS` to a specific
private host address and restrict access with the host firewall. That setting
applies to **all four** published services. Do not use `0.0.0.0` or a public address
without a deliberate exposure policy. The services' HTTP connections do not become
encrypted by changing the bind address. Loki has no authentication supplied by
this Compose file. Loopback binding does not isolate services from other local
processes, privileged users or containers attached to their network.

Anonymous Grafana viewing is off by default. Set `GRAFANA_ANONYMOUS_ENABLED=true`
only when unauthenticated viewers should be allowed to see the exposed dashboards
and data. Existing embedding clients may need login or this explicit opt-in; do
not restore public anonymous access merely to clear a login prompt.

Docker documents [required interpolation values](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
and [host IP port mappings](https://docs.docker.com/reference/compose-file/services/#ports).
Shell environment values override `.env`, so validate using the same environment
as the planned Compose invocation. The pinned or floating image choices are
unchanged by this credentials/access update; it does not certify every image's
password hashing, TLS configuration or future release.
