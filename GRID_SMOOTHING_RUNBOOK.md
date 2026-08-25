# Grid Smoothing Tuning Runbook

End-to-end loop: analyzer → apply coefficients → verify → deploy → observe.
Say **"follow GRID_SMOOTHING_RUNBOOK.md"** and execute this file top-to-bottom.

Background: raw CT grid (`gt`) from the VM-3P75CT sawtooths around zero.
inverter-control blends it with a Vue-derived estimate
(`derived_gt = home_total − pv_total`) and EMAs the result. Coefficients are
learned from data by `analysis/grid_correlation.py`, never guessed.

## 1. Run analyzer (on the Synology NAS)

SSH tunnel does NOT work (Synology sshd sets `AllowTcpForwarding no`) — run on
the NAS itself:

```bash
ssh synology
cd /volume1/docker/inverter-monitoring && git pull   # git missing on NAS → scp analysis/grid_correlation.py instead
set -a; . ./.env; set +a                             # supplies INFLUX_TOKEN / org / bucket
python3 analysis/grid_correlation.py --hours 24 \
    --url http://localhost:8086 --token "$INFLUX_TOKEN"
```

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

Append the printed block to `/Users/vmedvedev/victron/inverter-control/local_config.py`:

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
cd /Users/vmedvedev/victron/inverter-control && python3 -c "
from inverter_control import config as c
for k in ['ENABLE_GRID_SMOOTHING_WITH_HOME','GRID_SMOOTHING_HOME_WEIGHT',
          'GRID_SMOOTHING_DERIVED_ALPHA','EMA_ALPHA']:
    assert getattr(c, k) is not None; print(k, '=', getattr(c, k))
d = {k: getattr(c, k) for k in c.EXPORTED_KEYS}
assert 'GRID_SMOOTHING_HOME_WEIGHT' in d and 'GRID_SMOOTHING_DERIVED_ALPHA' in d
print('OK')"
```

Must print exactly the local_config values (not defaults `False/0.7/0.1/0.3`).
If defaults appear → values not wired; check `_import_local_config()` in
`inverter_control/config.py` and that both `GRID_SMOOTHING_*` keys are in
`EXPORTED_KEYS` (both were broken once and fixed 2026-08-23).

## 4. Deploy to Cerbo

```bash
cd /Users/vmedvedev/victron/inverter-control && ./deploy.sh
```

Ships whole working tree (uncommitted WIP included!) via tar over SSH, then runs
`update.sh` remotely with `PUSH_LOCAL_CONFIG=1`, which copies local_config.py to
the install dir + setup options dir, restarts the service, waits for heartbeat.
Expect `pushed local_config.py (PUSH_LOCAL_CONFIG=1)` and `Service status: up`.

Spot-check on device:

```bash
ssh Cerbo 'tail -12 /data/inverter-control/local_config.py'
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
Convergence usually takes 2–3 rounds.

## Gotchas (learned the hard way)

- Vue total circuit is `loads_totalusage` (name changed across firmware
  versions); match regex `/^loads_total/`.
- Raw grid lands in InfluxDB measurement `inverter` as field `grid_power`
  (json_v2 renames `gt`).
- NAS system python 3.8 works for the analyzer (stdlib only); no pip needed.
- If `filtered_gt ≡ raw` in the analyzer output → ENABLE flag off somewhere.
- First live windows after enabling the `vue` input are too short — see §1 table.
