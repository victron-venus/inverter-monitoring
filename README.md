# Inverter Monitoring Stack

[![CI](https://github.com/victron-venus/inverter-monitoring/actions/workflows/ci.yml/badge.svg)](https://github.com/victron-venus/inverter-monitoring/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub last commit](https://img.shields.io/github/last-commit/victron-venus/inverter-monitoring)](https://github.com/victron-venus/inverter-monitoring/commits/main)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/victron-venus/inverter-monitoring/graphs/commit-activity)

Telegraf + InfluxDB + Grafana monitoring for Victron inverter system.

## Architecture

```mermaid
flowchart TB
    subgraph Cerbo["Cerbo GX"]
        ICM["inverter-control"]
        ESP["ESP32 BMS x8"]
    end

    subgraph NAS["Synology NAS"]
        TEL["Telegraf"]
        INF["InfluxDB"]
        GRAF["Grafana"]
    end

    ICM -->|"MQTT"| TEL
    ESP -->|"MQTT"| TEL
    TEL -->|"collect"| INF
    INF -->|"query"| GRAF

    style GRAF fill:#FF9900,color:#fff
    style INF fill:#22AD9B,color:#fff
    style TEL fill:#439EF7,color:#fff
```

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
nano .env  # Set your INFLUX_TOKEN (generate with: openssl rand -hex 32)
```

### 2. Start Full Stack

```bash
docker-compose up -d
```

This starts:
- **InfluxDB** on http://localhost:8086
- **Grafana** on http://localhost:3000 (admin/admin)
- **Telegraf** collecting MQTT → InfluxDB
- **Loki** for logs on http://localhost:3100

### 3. Access Dashboards

Open http://localhost:3000 - dashboards are auto-provisioned!

### Alternative: Use Existing InfluxDB/Grafana

If you already have InfluxDB/Grafana running, just start Telegraf:

```bash
# Edit .env to point to your existing instances
INFLUX_URL=http://your-influxdb-host:8086

# Start only Telegraf
docker-compose up -d telegraf
```

## Data Flow

## Data Flow

```mermaid
flowchart LR
    subgraph Sources["MQTT Sources"]
        INV["inverter/state"]
        BAT1["battery/+/+"]
        BAT2["battery2/+/+"]
        MPPT["N/+/solarcharger/+/*"]
    end

    subgraph Storage["TIG Stack"]
        T[Telegraf] --> I[InfluxDB] --> G[Grafana]
    end

    Sources --> T

    style G fill:#FF9900,color:#fff
    style I fill:#22AD9B,color:#fff
    style T fill:#439EF7,color:#fff
```

### MQTT Topics Collected

| Topic | Description |
|-------|-------------|
| `inverter/state` | Main inverter state (power, SOC, voltages) — consumed twice: typed fields into `inverter`, full flattened mirror into `vue` |
| `battery/+/+` | Battery chain 1 (ESP32 BMS data) |
| `battery2/+/+` | Battery chain 2 (ESP32 BMS data) |
| `N/+/solarcharger/+/*` | MPPT charger data from Cerbo |

### InfluxDB Measurements

| Measurement | Tags | Fields |
|-------------|------|--------|
| `inverter` | host | setpoint, grid_power (raw VM-3P75CT), filtered_gt (smoothed), solar_total, pv_total, battery_*, forecast_today_kwh, forecast_tomorrow_kwh, produced_today_kwh, produced_yesterday_kwh, daily per-source kWh |
| `vue` | host | `loads_<Channel>` for every Emporia Vue circuit (16+1, total circuit stored as `loads_totalusage`) + mirrored scalar state |
| `battery_chain1` | battery, field | voltage, current, soc, temp |
| `battery_chain2` | battery, field | voltage, current, soc, temp |
| `mppt` | portal_id, instance | power, voltage, current |

The `vue` measurement uses the v1 JSON parser's nested-object flattening
(`loads.Total` → `loads_Total`), so new Vue channels appear automatically;
the whole-home total matches `/^loads_total/` (currently `loads_totalusage`)
without config changes.

## Home & Grid Analysis

Dashboard **"Home & Grid Analysis"** (`home-grid.json`, auto-provisioned) shows:

- **Home / Grid / PV / Setpoint** flow — Vue home total vs raw and smoothed grid
  vs inverter-control setpoint.
- **Grid Raw vs Smoothed** — the sawtooth check: raw VM-3P75CT readings flip
  above/below zero every few seconds; the controller's `filtered_gt` should be
  the flat line near zero.
- **Home Circuits Breakdown** — all 16+1 Vue channels stacked (excludes Total).
- **Derived Grid (Home − PV)** — what the controller blends against the CT meter.
- **Grid σ 1h** — stddev of raw vs smoothed grid; if both are large, tighten
  smoothing coefficients.
- **Forecast & production stats** — solar-forecast today/tomorrow kWh,
  produced today/yesterday kWh.

## Grid Smoothing Tuning Loop

Raw GRID from the VM-3P75CT meter is noisy ("sawtooth" around zero). The
controller smooths it by blending a Vue-derived value:

```
effective_gt = w * ema(home_total - pv_total, alpha_d) + (1 - w) * raw_gt
filtered_gt  = ema(effective_gt, ema_alpha)
```

To find the coefficients empirically instead of guessing:

```bash
python3 analysis/grid_correlation.py --hours 24 \
    --url http://localhost:8086 --token $INFLUX_TOKEN
# offline sanity check without a live stack:
python3 analysis/grid_correlation.py --demo
```

The script computes correlation/lag between raw and derived grid, quantifies
sawtooth (jitter = first-difference stddev), sweeps candidate coefficients by
simulating the controller blend offline, and prints a ready-to-paste
`local_config.py` block for inverter-control:

```python
ENABLE_GRID_SMOOTHING_WITH_HOME = True
GRID_SMOOTHING_HOME_WEIGHT = 0.8  # from analysis
GRID_SMOOTHING_DERIVED_ALPHA = 0.05
EMA_ALPHA = 0.15
```

Iterate: apply on Cerbo → watch "Grid Raw vs Smoothed" and "Grid σ 1h" for a
day → re-run the analyzer → adjust. Target: raw jitter ≫ smoothed jitter and
near-zero share of `filtered_gt` as high as possible. Weight is capped at 0.95
in the sweep so the CT meter always keeps some corrective influence (Vue
calibration drift protection).

### Applying the coefficients in inverter-control

The four values the analyzer prints map onto these knobs (defaults live in
`inverter_control/config.py`, site overrides go into `local_config.py` on the
Cerbo — untracked, created from `local_config.example.py`):

| Knob | Default | Role |
|---|---|---|
| `ENABLE_GRID_SMOOTHING_WITH_HOME` | `False` | Master switch for the blend — without it the other three do nothing |
| `GRID_SMOOTHING_HOME_WEIGHT` (`w`) | `0.7` | **Weight between the two grid signals**: how much of `filtered_gt` comes from the Vue-derived value vs the raw CT meter. Higher = smoother but trusts Vue calibration more; keep ≤ ~0.95 so the CT meter can still correct drift |
| `GRID_SMOOTHING_DERIVED_ALPHA` | `0.1` | EMA speed of the *derived* signal itself. Lower = calmer derived line, slower to follow real load steps |
| `EMA_ALPHA` | `0.3` | Final smoothing of the blended value that the controller acts on. Lower = smoother setpoint behaviour, more lag |

All are validated in the 0.0–1.0 range by inverter-control at startup.

Procedure:

```bash
# on the workstation: push updated local_config.py to the Cerbo and restart
cd ../inverter-control && ./deploy.sh        # copies config + restarts the service
```

or edit `local_config.py` directly on the Cerbo and restart
(`/service/inverter-control`). Then verify:

1. Grafana "Grid Raw vs Smoothed": `filtered_gt` must visibly detach from raw.
   If it still overlaps exactly, the master switch is still `False`.
2. Re-run the analyzer after a day: its report prints both raw and stored
   `filtered_gt` metrics, so improvement is measurable (σ down, near-zero up).
3. Rollback if behaviour degrades: set `ENABLE_GRID_SMOOTHING_WITH_HOME = False`
   (blend off) rather than zeroing weights.

Tuning direction cheat-sheet: sawtooth still visible → raise
`GRID_SMOOTHING_HOME_WEIGHT` a step (e.g. +0.05–0.1); controller reacts too
slowly to real load changes → raise `DERIVED_ALPHA`/`EMA_ALPHA`; smoothed line
shows a constant offset vs reality → lower the weight (Vue calibration drift).

## Embedding in Go Dashboard

Grafana panels can be embedded via iframe:

```html
<iframe
  src="http://your-grafana-host:3000/d-solo/inverter-overview/inverter?orgId=1&panelId=1&theme=dark"
  width="100%"
  height="400"
  frameborder="0">
</iframe>
```

For public access without login, enable anonymous auth in Grafana:

```ini
# /etc/grafana/grafana.ini
[auth.anonymous]
enabled = true
org_name = home
org_role = Viewer
```

## Auto-Deploy via GitHub Webhook (Optional)

If you have Cloudflare Argo tunnel to your Synology, you can enable auto-deploy:

### 1. Generate webhook secret
```bash
openssl rand -hex 32
# Add to .env as WEBHOOK_SECRET
```

### 2. Start webhook service
```bash
docker-compose --profile webhook up -d
```

### 3. Configure Argo tunnel
Add route in Cloudflare dashboard:
- Public hostname: `deploy.yourdomain.com`
- Service: `http://localhost:9000`

### 4. Configure GitHub webhook
1. Go to repo Settings → Webhooks → Add webhook
2. Payload URL: `https://deploy.yourdomain.com/webhook`
3. Content type: `application/json`
4. Secret: your WEBHOOK_SECRET
5. Events: Just the push event

Now pushes to main branch will auto-deploy!

## Documentation

- [System Architecture](./.github/docs/system-architecture.md) - Data flow diagrams, runbook

## Files

```
inverter-monitoring/
├── docker-compose.yml      # Telegraf + Loki + Webhook stack
├── telegraf.conf           # MQTT → InfluxDB config
├── analysis/
│   └── grid_correlation.py # Grid smoothing tuning analyzer (stdlib only)
├── .env.example            # Environment variables template
├── .env                    # Your secrets (gitignored)
├── promtail.yml            # Log shipping config (optional)
├── TODO.md                 # Feature checklist / roadmap
├── webhook/                # GitHub webhook auto-deploy
│   ├── server.py           # Flask webhook listener
│   ├── Dockerfile          # Container build
│   └── deploy-local.sh     # Deploy script
└── grafana/
    └── dashboards/
        ├── inverter-overview.json  # Main dashboard
        └── home-grid.json          # Home & Grid Analysis dashboard
```
## Related Projects

This project is part of the Victron Venus OS integration suite:

| Project | Description |
|---------|-------------|
| [inverter-control](https://github.com/victron-venus/inverter-control) | Advanced ESS external control system with grid-zero targeting |
| [inverter-dashboard](https://github.com/victron-venus/inverter-dashboard) | Real-time web dashboard (Python/FastAPI) via MQTT |
| [inverter-dashboard-go](https://github.com/victron-venus/inverter-dashboard-go) | High-performance Go rewrite of the web dashboard |
| [inverter-desktop](https://github.com/victron-venus/inverter-desktop) | Native desktop application (Rust/Tauri) for system monitoring |
| [dbus-mqtt-battery](https://github.com/victron-venus/dbus-mqtt-battery) | MQTT to D-Bus bridge for JBD BMS battery integration |
| [dbus-tasmota-pv](https://github.com/victron-venus/dbus-tasmota-pv) | Tasmota smart plug integration as a PV inverter on D-Bus |
| [esphome-jbd-bms-mqtt](https://github.com/victron-venus/esphome-jbd-bms-mqtt) | ESP32 Bluetooth monitor for JBD BMS batteries |
| **inverter-monitoring** (this) | TIG (Telegraf, InfluxDB, Grafana) monitoring stack |
| [terraform-github-victron](https://github.com/4alvit/terraform-github-victron) | Infrastructure as Code for the GitHub organization |



## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature-name`)
3. Commit your changes
4. Push to the branch (`git push origin feature-name`)
5. Create a Pull Request

## Support

For issues specific to:
- **Telegraf configuration**: See [Telegraf documentation](https://docs.influxdata.com/telegraf/)
- **InfluxDB**: See [InfluxDB documentation](https://docs.influxdata.com/influxdb/)
- **Grafana**: See [Grafana documentation](https://grafana.com/docs/)
- **This integration**: Open an issue in this repository

**Note:** This is a community project and is not affiliated with Victron Energy.
