# System Architecture

## Data Flow Diagram

```mermaid
flowchart TB
    subgraph VenusOS["Venus OS (Cerbo GX)"]
        INV_CTRL["inverter-control"]
        ESP32["ESP32 BMS x8"]
        MQTT["MQTT Broker"]
    end

    subgraph NAS["Synology NAS"]
        TEL["Telegraf\nMQTT → InfluxDB"]
        INF["InfluxDB\nTime-series DB"]
        GRA["Grafana\nDashboards"]
        LOK["Loki\nLog aggregation"]
    end

    subgraph Remote["Remote Access"]
        WEB["Webhook\nAuto-deploy"]
    end

    INV_CTRL -->|"inverter/state"| MQTT
    ESP32 -->|"battery/*"| MQTT
    MQTT -->|"subscribe"| TEL
    TEL -->|"write"| INF
    INF -->|"query"| GRA
    GRA -->|"logs"| LOK

    TEL -.->|"MQTT collect"| MQTT
    GRA -.->|"visualize"| INF

    style GRA fill:#FF9900,color:#fff
    style INF fill:#22AD9B,color:#fff
    style TEL fill:#439EF7,color:#fff
    style LOK fill:#FF9900,color:#fff
```

## Service Dependencies

```mermaid
graph LR
    subgraph VenusOS["Venus OS"]
        ICM["inverter-control"]
        DMB["dbus-mqtt-battery"]
        MQTT["MQTT Broker"]
    end

    subgraph NAS["Synology NAS"]
        TEL["Telegraf"]
        INF["InfluxDB"]
        GRA["Grafana"]
    end

    ICM -->|"MQTT"| TEL
    DMB -->|"MQTT"| TEL
    TEL -->|"collect"| INF
    INF -->|"query"| GRA

    style GRA fill:#FF9900,color:#fff
    style INF fill:#22AD9B,color:#fff
    style TEL fill:#439EF7,color:#fff
```

## Data Collection Flow

```mermaid
sequenceDiagram
    participant Venus as Venus OS
    participant MQTT as MQTT Broker
    participant TEL as Telegraf
    participant INF as InfluxDB
    participant GRA as Grafana

    Venus->>MQTT: Publish sensor data
    MQTT-->>TEL: Subscription callback
    TEL->>INF: Write measurement point
    loop Dashboard refresh
        GRA->>INF: Query time range
        INF-->>GRA: Return data points
        GRA-->>User: Render dashboard
    end
```

## MQTT Topics Mapping

```mermaid
graph TB
    subgraph Topics["MQTT Topics"]
        INV["inverter/state<br/>Power, SOC, grid"]
        BAT1["battery/+/+<br/>Chain 1 data"]
        BAT2["battery2/+/+<br/>Chain 2 data"]
        MPPT["N/+/solarcharger/+/+/<br/>MPPT data"]
    end

    subgraph Influx["InfluxDB Measurements"]
        I_INV["inverter"]
        I_BAT1["battery_chain1"]
        I_BAT2["battery_chain2"]
        I_MPPT["mppt"]
    end

    Topics --> Influx

    style INV fill:#4ecdc4,color:#fff
    style BAT1 fill:#ff6b6b,color:#fff
    style BAT2 fill:#ff6b6b,color:#fff
```

## Runbook: Troubleshooting

### No Data Appearing in Grafana

**Symptoms:**
- Dashboard shows "No data"
- InfluxDB queries return empty

**Actions:**
\`\`\`bash
# Verify Telegraf is running
docker ps | grep telegraf

# Check Telegraf logs
docker logs telegraf -f

# Test MQTT subscription
docker exec telegraf mosquitto_sub -v -t "#"

# Verify InfluxDB connectivity
docker exec telegraf nc -zv influxdb 8086
\`\`\`

### High Memory Usage from Telegraf

**Symptoms:**
- NAS memory nearly full
- Telegraf container using excessive RAM

**Actions:**
\`\`\`bash
# Reduce Telegraf buffer size in telegraf.conf
[agent]
  metric_buffer_limit = 1000

# Or restrict collected topics
[[inputs.mqtt_consumer]]
  topics = ["inverter/state", "battery/+/+/state"]
\`\`\`

### Grafana Dashboard Not Loading

**Symptoms:**
- Blank panels
- Timeout errors

**Actions:**
\`\`\`bash
# Check Grafana container
docker ps | grep grafana
docker logs grafana --tail 50

# Verify data source
curl -s http://localhost:3000/api/datasources

# Restart container
docker restart grafana
\`\`\`

---

## Related Documentation

- [inverter-control System Architecture](../inverter-control/.github/docs/system-architecture.md)
- [ADR-001: Grid-Zero Architecture](../inverter-control/.github/docs/adr-001-grid-zero-architecture.md)
