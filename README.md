# Inverter Monitoring Stack

Telegraf + InfluxDB + Grafana monitoring for Victron inverter system.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Cerbo GX                                │
│  ┌──────────────────┐                                           │
│  │ inverter-control │──── MQTT ────┐                            │
│  │    (Python)      │              │                            │
│  └──────────────────┘              │                            │
│                                    │                            │
│  ┌──────────────────┐              │                            │
│  │ ESP32 BMS x8     │──── MQTT ────┤                            │
│  │ (battery data)   │              │                            │
│  └──────────────────┘              │                            │
└────────────────────────────────────┼────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────┴────────────────────────────┐
│                        Synology NAS                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │   Telegraf   │───▶│   InfluxDB   │───▶│     Grafana      │   │
│  │ (collector)  │    │  (storage)   │    │ (visualization)  │   │
│  └──────────────┘    └──────────────┘    └──────────────────┘   │
│                                                :3000            │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Setup InfluxDB

Open http://192.168.167.25:8086 and complete initial setup:
- Organization: `home`
- Bucket: `inverter`
- Save the API token!

### 2. Configure Telegraf

```bash
cp .env.example .env
# Edit .env with your InfluxDB token
nano .env
```

### 3. Deploy Telegraf

```bash
docker-compose up -d telegraf
```

### 4. Import Grafana Dashboard

1. Open http://192.168.167.25:3000 (admin/admin)
2. Add InfluxDB datasource:
   - URL: `http://192.168.167.25:8086`
   - Organization: `home`
   - Token: your API token
   - Default bucket: `inverter`
3. Import dashboard from `grafana/dashboards/inverter-overview.json`

## Data Flow

### MQTT Topics Collected

| Topic | Description |
|-------|-------------|
| `inverter/state` | Main inverter state (power, SOC, voltages) |
| `battery/+/+` | Battery chain 1 (ESP32 BMS data) |
| `battery2/+/+` | Battery chain 2 (ESP32 BMS data) |
| `N/+/solarcharger/+/*` | MPPT charger data from Cerbo |

### InfluxDB Measurements

| Measurement | Tags | Fields |
|-------------|------|--------|
| `inverter` | host | setpoint, grid_power, solar_total, battery_power, battery_soc, battery_voltage |
| `battery_chain1` | battery, field | voltage, current, soc, temp |
| `battery_chain2` | battery, field | voltage, current, soc, temp |
| `mppt` | portal_id, instance | power, voltage, current |

## Embedding in Go Dashboard

Grafana panels can be embedded via iframe:

```html
<iframe 
  src="http://192.168.167.25:3000/d-solo/inverter-overview/inverter?orgId=1&panelId=1&theme=dark"
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

## Files

```
inverter-monitoring/
├── docker-compose.yml      # Telegraf + Loki stack
├── telegraf.conf           # MQTT → InfluxDB config
├── .env.example            # Environment variables template
├── .env                    # Your secrets (gitignored)
├── promtail.yml            # Log shipping config (optional)
└── grafana/
    └── dashboards/
        └── inverter-overview.json   # Main dashboard
```
