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

## Files

```
inverter-monitoring/
├── docker-compose.yml      # Telegraf + Loki + Webhook stack
├── telegraf.conf           # MQTT → InfluxDB config
├── .env.example            # Environment variables template
├── .env                    # Your secrets (gitignored)
├── promtail.yml            # Log shipping config (optional)
├── webhook/                # GitHub webhook auto-deploy
│   ├── server.py           # Flask webhook listener
│   ├── Dockerfile          # Container build
│   └── deploy-local.sh     # Deploy script
└── grafana/
    └── dashboards/
        └── inverter-overview.json   # Main dashboard
```
