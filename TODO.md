# TODO — Home & Grid Monitoring Upgrade

Goal: ingest everything new published by `inverter-control` v1.21+, visualize it,
and build an analysis loop that tunes the GRID smoothing coefficients until the
grid line sits flat near zero most of the time (VM-3P75CT raw readings currently
sawtooth above/below zero).

## Phase 1 — Data ingestion (Telegraf)

- [x] 1.1 Parse new scalar fields from `inverter/state` into the `inverter`
      measurement: `solar_forecast.today_kwh`, `solar_forecast.tomorrow_kwh`,
      `daily_stats.produced_yesterday`.
- [x] 1.2 Add a second MQTT consumer on `inverter/state` using the v1 JSON
      parser into a `vue` measurement — nested objects flatten to fields
      (`loads.Total` → `loads_Total`, `loads.garage` → `loads_garage`, …), so all
      16+1 Emporia Vue circuits are captured without listing names. Exclude bulky
      nested mirrors (`mppt_data_*`, `batteries_*`, `mppt_chargers_*`,
      `ui_config_*`, `perf_*`) via `fieldexclude`.
- [x] 1.3 Validate locally that both measurements receive data (or unit-test the
      config shape if no broker available).

## Phase 2 — Dashboards (Grafana)

- [x] 2.1 New provisioned dashboard `grafana/dashboards/home-grid.json`
      ("Home & Grid Analysis") with rows:
  - Home & Grid overview: Home power (Vue `Total`), SetPoint, Consumption;
    Grid raw vs filtered vs derived (`Home − PV`) timeseries.
  - Circuit breakdown: stacked timeseries of every `loads_*` circuit except
    `Total` (16+1 channels).
  - Solar forecast & production: stat panels — forecast today/tomorrow kWh,
    produced today/yesterday kWh; timeseries of production counters.
  - Smoothing quality: grid raw vs filtered overlay; stat panels for hourly
    stddev of raw vs filtered grid (sawtooth indicator).
- [x] 2.2 Extend `inverter-overview.json` System Overview row with Forecast
      Today / Tomorrow and Produced Today stats.
- [x] 2.3 Update README data-flow tables (new fields, `vue` measurement,
      dashboards list).

## Phase 3 — Smoothing-tuning analysis loop

- [x] 3.1 Add `analysis/grid_correlation.py` (stdlib only):
  - pulls `grid_power`/`gt`, `filtered_gt`, `loads_totalusage`, `pv_total` from
    InfluxDB over a configurable window (HTTP + Flux API);
  - computes Pearson correlation raw-grid ↔ derived-grid, cross-correlation
    lag scan (Vue vs CT meter delay), zero-crossing rate ("sawtooth score"),
    near-zero time share, stddev raw vs filtered;
  - sweeps candidate weights (`GRID_SMOOTHING_HOME_WEIGHT`,
    `GRID_SMOOTHING_DERIVED_ALPHA`, `EMA_ALPHA`) simulating the inverter-control
    blend formula offline, ranks by near-zero time + low residual variance;
  - prints a report plus a ready-to-paste `local_config.py` snippet with the
    recommended coefficients;
  - `--demo` mode generates synthetic sawtooth data so it runs without a live
    stack.
- [x] 3.2 Document the feedback workflow in README: run analysis → paste
      recommended block into inverter-control `local_config.py` → observe
      Smoothing-quality row → repeat.
- [x] 3.3 Unit tests (`tests/test_grid_correlation.py`) covering correlation,
      lag detection, and weight search on synthetic data; wire `--demo` into a
      test.

## Phase 4 — Release hygiene

- [x] 4.1 Fix version drift: `pyproject.toml` 0.0.0 → match `version` file.
- [x] 4.2 Run full local checks: ruff format/check, pylint on touched Python,
      gitleaks, pytest.
- [x] 4.3 Branch → commit → PR with `auto-merge` label → CI green → merge.
- [x] 4.4 Tag `v1.3.0` (version file + pyproject + tag in sync) → Release Bot
      publishes GitHub Release.

## Notes / assumptions

- Vue channel count/names are dynamic (16+1 today); ingestion must not depend
  on fixed names — hence the flattened-v1-parser approach.
- `ENABLE_GRID_SMOOTHING_WITH_HOME` must be enabled on-site for the derived
  blend to be active; the analysis script flags this when `filtered_gt == gt`
  exactly for long stretches (blend disabled symptom).
