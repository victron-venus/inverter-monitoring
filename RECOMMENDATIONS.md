# Historical v1.3.0 monitoring and tuning notes

This page records the **2026-08-23** rollout of v1.3.0 and its initial tuning
proposal. Its measurements, completed checklist items and site observations apply
to that rollout only. They do not establish the state of a current installation.

For current operation, use [README.md](README.md),
[secure deployment](docs/secure-deployment.md), and the
[grid analysis runbook](GRID_SMOOTHING_RUNBOOK.md). The analyzer below models legacy
per-sample EMA filters; current controller defaults use time-based filters that
it does not simulate. Check applicability before using any proposed coefficients.

---

## 1. What ships where (data flow)

```
Cerbo GX (inverter-control v1.21+)
  └─ MQTT broker, topic inverter/state (retained JSON)
       ├─ Telegraf input #1 (json_v2) ──► measurement `inverter`
       │     gt, filtered_gt, setpoint, battery_*, pv_total, solar_total,
       │     forecast_today_kwh, forecast_tomorrow_kwh,
       │     produced_today_kwh, produced_yesterday_kwh, daily_stats.*
       └─ Telegraf input #2 (v1 json parser) ──► measurement `vue`
             loads_<Channel>   ← every Emporia Vue circuit incl. loads_Total (16+1)
             plus scalar mirrors of the inverter fields (ignored by dashboards)
                   ▼
              InfluxDB v2 (org=home, bucket=inverter)
                   ▼
              Grafana (provisioned from grafana/dashboards/)
```

Key point about the `vue` measurement: it uses Telegraf's **v1** JSON parser, which
flattens nested objects into field names (`loads.Total` → `loads_Total`). New Vue
circuits appear automatically — no config change needed when channels are added.

⚠️ **Field-name gotcha (verified on the live stack 2026-08-23):** the whole-home total
circuit is published as **`loads_totalusage`**, not `loads_Total` — the channel name
comes from inverter-control's acload discovery and has changed spelling across
versions. All dashboards therefore match it with the Flux regex
`r._field =~ /^loads_total/` (and exclude it from the per-circuit breakdown with
`!~ /^loads_total/`). The analyzer tries `loads_totalusage`, then `loads_Total`.
If a future firmware renames it again, check with:

```flux
from(bucket: "inverter")
  |> range(start: -10m)
  |> filter(fn: (r) => r._measurement == "vue" and r._field =~ /^loads_/)
  |> group(columns: ["_field"]) |> last()
```

## 2. Where to look — Grafana

Dashboard **"Home & Grid Analysis"** (`uid home-grid-analysis`):

| Panel | Query target | What it tells you |
|---|---|---|
| Home Power (Emporia Vue) | `vue` regex `/^loads_total/` | Whole-home consumption as seen by Vue |
| Grid smoothed | `inverter.filtered_gt` | Value the controller actually acts on |
| Forecast Today / Tomorrow | `forecast_*_kwh` | Solar forecast pushed by solar-forecast-langgraph via inverter-control |
| Produced Today / Yesterday | `produced_*_kwh` | Daily energy counters |
| Home / Grid / PV / Setpoint timeseries | `loads_Total`, `gt`, `pv_total`, `setpoint` | Overall system behaviour |
| **Grid Raw vs Smoothed** | `gt` (thin) vs `filtered_gt` (thick), zero-centered axis | Sawtooth check — raw should flip ±, smoothed should sit near 0 |
| Home Circuits Breakdown | regex `^loads_` minus `Total`, stacked | Which circuits drive consumption |
| Derived Grid (Home − PV) | Flux join `home_w - pv_w` | The alternative grid signal used by blending |
| **Grid σ 1h (raw vs smoothed)** | `std()` per hour, both signals | Quantitative sawtooth metric over time |
| Production vs Forecast | step-after kWh series | Forecast accuracy |

The overview dashboard also gained an "Solar Forecast & Production" row (stats:
Forecast Today/Tomorrow, Produced Today, Home Power Vue).

## 3. Historical legacy-EMA tuning proposal

Background: the VM-3P75CT CT reading (`gt`) shows a sawtooth bias flipping above/below
zero roughly every ~20 s. inverter-control blends it with the Vue-derived grid
(`Home total − PV total`) and applies EMA:

```python
effective_gt = GRID_SMOOTHING_HOME_WEIGHT * ema(derived_gt, GRID_SMOOTHING_DERIVED_ALPHA)
             + (1 - GRID_SMOOTHING_HOME_WEIGHT) * raw_gt
filtered_gt  = ema(effective_gt, EMA_ALPHA)
```

### Step-by-step

1. **Collect ≥ 24 h of data** after enabling the `vue` measurement (both inputs write
   continuously once deployed).
2. Run the analyzer **on the host that can reach InfluxDB** (Cerbo or the NAS — the
   NAS system python 3.8 works; stdlib only, no pip installs):
   ```bash
   ssh synology
   cd /volume1/docker/inverter-monitoring && git pull   # or scp analysis/grid_correlation.py
   set -a; . ./.env; set +a                             # supplies INFLUX_TOKEN/org/bucket
   python3 analysis/grid_correlation.py --hours 24 \
       --url http://localhost:8086 --token "$INFLUX_TOKEN"
   ```
   The original Synology host disabled SSH forwarding. This was site-specific;
   current access should follow [secure deployment](docs/secure-deployment.md).
   Offline sanity mode (no InfluxDB): add `--demo`.
3. Read the report:
   - `fetched <key>: N minute buckets` + `time-intersection: M aligned buckets` — all
     four fields are averaged into 1-minute buckets and intersected on time, because
     they went live at different dates. If M is small (< several hours of buckets),
     the numbers are provisional: wait until the `vue` measurement has ≥ 24 h.
   - `corr(raw, derived)` — should be strongly positive (> +0.8) once enough data
     exists. If < 0.5 the script warns: Home Total must cover all loads and PV totals
     must match metered PV. On first live runs (2026-08-23) correlation was weak and
     the derived grid was *rougher* than the CT meter (σ 181 W vs 42 W) with only one
     hour of overlap — do not tune on such a window.
   - `best lag` — Vue-derived lagging raw by a couple of samples is normal;
     large lag means MQTT/dbus latency is hurting the blend.
   - Top candidates table — ranked by near-zero share first, then low σ. Beware
     night-time windows: when PV is off and loads are low, near-zero% is inflated for
     every candidate and the ranking degenerates.
4. Apply the printed block to inverter-control `local_config.py`:
   ```python
   ENABLE_GRID_SMOOTHING_WITH_HOME = True   # ← without this nothing changes!
   GRID_SMOOTHING_HOME_WEIGHT = <weight>
   GRID_SMOOTHING_DERIVED_ALPHA = <derived_alpha>
   EMA_ALPHA = <ema_alpha>
   ```
   Restart inverter-control.
5. **Observe for several hours / a day**: watch "Grid Raw vs Smoothed" and
   "Grid σ 1h". Success criteria:
   - smoothed σ clearly below raw σ (target ≥ 50 % reduction initially);
   - near-zero share (|grid| ≤ 100 W) rising toward the analyzer's prediction;
   - no visible offset between smoothed and derived lines (a persistent offset means
     Vue calibration drift — lower the weight).
6. Re-run the analyzer with the new coefficients active (it also prints the currently
   stored `filtered_gt` row) and iterate. Convergence usually takes 2–3 rounds.

### Guardrails baked into the sweep

- Weight is capped at **0.95** — some raw CT feedback always remains, so Vue
  calibration drift cannot silently bias the controller.
- If `filtered_gt` is bit-identical to `gt`, the analyzer prints a note that
  `ENABLE_GRID_SMOOTHING_WITH_HOME` is disabled — coefficients have no effect until
  enabled.

### Metric cheat-sheet

| Metric | Meaning | Good |
|---|---|---|
| jitter | stddev of first differences — sample-to-sample roughness | low |
| near-zero % | share of samples with \|grid\| ≤ 100 W | high |
| σ (stddev) | overall variance | low |
| zero-crossing rate | sign flips per sample | diagnostic only (misleading when true grid ≈ 0 — prefer jitter) |

## 4. Deployment policy

The push-triggered deployment used during the historical rollout is retired.
Current pushes to main, tag pushes and successful CI runs do not deploy the stack.
Automatic deployment is disabled by default. The optional authenticated webhook
accepts an explicitly enabled stable-release rollout as described in the
[current deployment guide](README.md#release-webhook-and-manual-deployment).
Use that guide for deployment and rollback instead of the former raw-main
configuration download procedure.

## 5. Post-release verification checklist

Status after v1.3.0 (checked 2026-08-23, ~30 min post-merge):

- [x] telegraf.conf on NAS updated at merge time, `vue` consumer present
- [x] telegraf restarted right after merge ("Up 28 minutes" vs 10-day-old siblings)
- [x] telegraf logs clean — 0 errors/fails in the last 300 log lines post-restart
- [x] measurement `vue` fresh points incl. `loads_totalusage` (~360 W at check time)
      and all 16+1 circuits
- [x] measurement `inverter` has `forecast_today_kwh` (7.1), `forecast_tomorrow_kwh`
      (6.62), `produced_today_kwh` (12.23), `produced_yesterday_kwh` (15.99),
      `filtered_gt`, `setpoint`. Note: raw grid is stored as **`grid_power`** here —
      the json_v2 input renames `gt`; the plain `gt` name only exists in `vue`.
- [x] Grafana serves dashboard `home-grid-analysis` (dashboards scp'ed manually;
      historical webhook configuration applied only to that rollout)
- [ ] Panels render non-empty for last 6 h — eyeball in browser after a few hours

These checkmarks describe the 2026-08-23 rollout. Record fresh observations for
each later installation; do not carry forward its acceptance result.

## 6. First tuning round — status and expectations

Live analyzer run 2026-08-23 (~1 h after the `vue` input went live): only 58 aligned
minute buckets, corr +0.367, derived σ ≈ 181 W vs raw σ ≈ 42 W. **Do not apply those
coefficients yet.** The weak correlation with a rougher Vue-derived signal suggests
Home Total may not cover every load (unmonitored circuits make `home − pv` drift away
from the true grid). Plan:

1. Let the stack collect ≥ 24 h (ideally including a sunny midday).
2. Compare in Grafana: "Home Circuits Breakdown" sum vs `loads_total*` — a large
   unexplained remainder means missing circuits; fix channel naming first.
3. Re-run the analyzer over a full day; only then apply its block to
   inverter-control `local_config.py` and iterate per §3.
