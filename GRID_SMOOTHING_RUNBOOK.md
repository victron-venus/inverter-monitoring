# Grid Smoothing Tuning Runbook

Use this guide to inspect recorded grid data and evaluate the analyzer's legacy
EMA model. Applying coefficients and deploying the controller are separate
operator actions after checking that the model matches the installed version.

## Model applicability

[`analysis/grid_correlation.py`](analysis/grid_correlation.py) compares raw CT
readings with a home-minus-PV estimate. It sweeps the legacy per-sample
`GRID_SMOOTHING_DERIVED_ALPHA` and `EMA_ALPHA` settings on one-minute aggregates.
Those aggregates cannot reproduce control-cycle timing or prove grid stability.

Current [inverter-control configuration](https://github.com/victron-venus/inverter-control/blob/main/inverter_control/config.py)
defaults to background time-based filters: `GRID_FILTER_TAU=2.0` and
`GRID_SMOOTHING_DERIVED_TAU=3.2`. Positive values replace the corresponding
per-cycle alpha filters. The analyzer does not simulate those time constants;
its printed alpha block is not a validated tuning recommendation for that path.
Do not disable the time-based filters merely to apply the analyzer output.

Check the installed version and settings before interpreting candidate rankings.
The steps below that apply coefficients are for a deliberately selected legacy
filter configuration, followed by a separately planned deployment and observation.

## 1. Run analyzer on a host with InfluxDB access

Run from the monitoring checkout on the host that can reach InfluxDB. The example
uses its local loopback listener and privately managed `.env`; set the organization
and bucket to match the installation. Remote access depends on the host's SSH
policy; see [secure deployment](docs/secure-deployment.md#remote-access).

```bash
cd /path/to/inverter-monitoring
set -a; . ./.env; set +a
python3 analysis/grid_correlation.py --hours 24 \
    --url http://localhost:8086 --org "$INFLUX_ORG" --bucket "$INFLUX_BUCKET"
```

The analyzer reads `INFLUX_TOKEN` from the environment.

Offline sanity mode (no InfluxDB): add `--demo`.

### Read the report

| Line | Good | Bad |
|---|---|---|
| `time-intersection: M aligned buckets` | ≥ 1440 (a full day) | < several hours → provisional, wait |
| `corr(raw, derived)` | > +0.8 | < 0.5 → Home Total misses loads or PV mismatch; do NOT tune |
| `best lag` | 1–2 samples (Vue lags) | large → MQTT/dbus latency hurting blend |

Night-time windows inflate near-zero% for every candidate — ranking degenerates
(all rows ~100%). Wait for a window that includes a sunny midday.

## 2. Apply block to inverter-control

After checking model applicability, replace the matching settings in your
controller checkout's private `local_config.py`. Keep a copy of the previous
values for rollback; do not append duplicate definitions:

```python
ENABLE_GRID_SMOOTHING_WITH_HOME = True   # ← without this nothing changes
GRID_SMOOTHING_HOME_WEIGHT = <weight>
GRID_SMOOTHING_DERIVED_ALPHA = <derived_alpha>
EMA_ALPHA = <ema_alpha>
```

Analyzer caps weight at 0.95 so some raw CT feedback always remains.

The analyzer is ABSOLUTE, not incremental: each run re-sweeps the full
coefficient grid from raw signals and the printed block replaces the old one
wholesale. Never add/subtract deltas relative to the currently deployed values;
iteration exists only to feed it better/more varied data and to verify the live
controller matches the simulation.

## 3. Verify consumption chain (local machine)

```bash
cd /path/to/inverter-control && python3 -c "
from inverter_control import config as c
for k in ['ENABLE_GRID_SMOOTHING_WITH_HOME','GRID_SMOOTHING_HOME_WEIGHT',
          'GRID_SMOOTHING_DERIVED_ALPHA','EMA_ALPHA',
          'GRID_FILTER_TAU','GRID_SMOOTHING_DERIVED_TAU']:
    assert getattr(c, k) is not None; print(k, '=', getattr(c, k))
d = {k: getattr(c, k) for k in c.EXPORTED_KEYS}
assert 'GRID_SMOOTHING_HOME_WEIGHT' in d and 'GRID_SMOOTHING_DERIVED_ALPHA' in d
print('OK')"
```

Confirm that the values match the intended private configuration and revisit
model applicability if either time constant is positive. This reads the local
checkout, not the device's currently loaded configuration.

## 4. Deploy to Cerbo

```bash
cd /path/to/inverter-control
./deploy.sh your-cerbo-ssh-alias
```

Ships whole working tree (uncommitted WIP included!) via tar over SSH, then runs
`update.sh` remotely with `PUSH_LOCAL_CONFIG=1`, which copies local_config.py to
the install dir + setup options dir, restarts the service, waits for heartbeat.
Expect `pushed local_config.py (PUSH_LOCAL_CONFIG=1)` and `Service status: up`.

Spot-check on device:

```bash
ssh your-cerbo-ssh-alias 'grep -E "^(ENABLE_GRID_SMOOTHING_WITH_HOME|GRID_SMOOTHING_HOME_WEIGHT|GRID_SMOOTHING_DERIVED_ALPHA|EMA_ALPHA|GRID_FILTER_TAU|GRID_SMOOTHING_DERIVED_TAU)[[:space:]]*=" /data/inverter-control/local_config.py'
```

Note: release/webhook deploys WITHOUT `PUSH_LOCAL_CONFIG=1` preserve the
device's existing local_config.py (`LOCAL_ONLY` list in update.sh) — config
survives releases.

## 5. Observe & iterate

Watch Grafana panels **"Grid Raw vs Smoothed"** and **"Grid σ 1h"** for several
hours / a day:
- smoothed σ clearly below raw σ (target ≥ 50 % reduction initially);
- near-zero share (|grid| ≤ 100 W) rising toward analyzer prediction;
- persistent offset between smoothed and derived lines → Vue calibration drift,
  lower the weight.

Re-run analyzer (it also reads stored `filtered_gt`) and repeat steps 2–5.
Candidate rankings are exploratory; no fixed number of iterations guarantees
a stable or accurate controller.

## Gotchas (learned the hard way)

- Vue total circuit is `loads_totalusage` (name changed across firmware
  versions); match regex `/^loads_total/`.
- Raw grid lands in InfluxDB measurement `inverter` as field `grid_power`
  (json_v2 renames `gt`).
- NAS system python 3.8 works for the analyzer (stdlib only); no pip needed.
- Identical recorded `filtered_gt` and raw values are a diagnostic clue, not
  proof that a particular setting is disabled. Inspect the actual filter path.
- First live windows after enabling the `vue` input are too short — see §1 table.
