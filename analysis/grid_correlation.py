#!/usr/bin/env python3
"""Grid smoothing tuning analyzer.

Compares the raw VM-3P75CT grid reading (`gt`), the controller's smoothed value
(`filtered_gt`) and the Emporia Vue-derived grid (Home total - PV total) over a
time window, then sweeps the smoothing coefficients used by inverter-control's
blend formula to recommend values that maximize near-zero grid time.

Replicates the blend from inverter_control/logic.py::

    effective_gt = w * ema(derived_gt, alpha_d) + (1 - w) * raw_gt
    filtered_gt  = ema(effective_gt, ema_alpha)

Usage:
    python3 analysis/grid_correlation.py --hours 24 \
        --url http://localhost:8086 --token $INFLUX_TOKEN
    python3 analysis/grid_correlation.py --demo   # synthetic data, offline

Stdlib only - safe to run on Cerbo GX or any host with python3.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import sys
import urllib.request
from dataclasses import dataclass

NEAR_ZERO_W = 100.0  # Watts - "grid near zero" band used everywhere below


# --------------------------------------------------------------------------- #
# Metrics                                                                     #
# --------------------------------------------------------------------------- #


def pearson(a: list[float], b: list[float]) -> float:
    """Pearson correlation coefficient of two equal-length series."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / math.sqrt(va * vb)


def stddev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def near_zero_pct(xs: list[float], tol: float = NEAR_ZERO_W) -> float:
    """Share of samples inside the +/-tol band, percent."""
    if not xs:
        return 0.0
    return 100.0 * sum(1 for x in xs if abs(x) <= tol) / len(xs)


def zero_crossing_rate(xs: list[float]) -> float:
    """Sign changes per sample - high values indicate sawtooth behaviour."""
    signs = [1 if x >= 0 else -1 for x in xs]
    if len(signs) < 2:
        return 0.0
    changes = sum(1 for p, c in itertools.pairwise(signs) if p != c)
    return changes / (len(signs) - 1)


def jitter(xs: list[float]) -> float:
    """Stddev of first differences - sample-to-sample roughness ("sawtooth").

    Unlike zero-crossing rate this stays meaningful when the true grid value
    legitimately hovers near zero.
    """
    if len(xs) < 2:
        return 0.0
    return stddev([c - p for p, c in itertools.pairwise(xs)])


def best_lag(a: list[float], b: list[float], max_lag: int) -> tuple[int, float]:
    """Lag (in samples) that maximizes corr(a[t], b[t+lag]); returns (lag, r).

    Positive lag means `b` must be shifted left to match `a`, i.e. `b` events
    happen later than `a` events by lag samples.
    """
    best_lag_val, best_r = 0, -2.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            # pairs (a[t], b[t+lag]): positive lag means b events happen later
            seg_a, seg_b = a[: len(a) - lag or None], b[lag:]
        else:
            seg_a, seg_b = a[-lag:], b[:lag]
        if len(seg_a) < 10 or len(seg_b) < 10:
            continue
        r = pearson(seg_a, seg_b)
        if r > best_r:
            best_r, best_lag_val = r, lag
    return best_lag_val, best_r


# --------------------------------------------------------------------------- #
# Smoothing model (mirrors inverter-control logic.py)                         #
# --------------------------------------------------------------------------- #


def ema(xs: list[float], alpha: float) -> list[float]:
    out: list[float] = []
    prev: float | None = None
    for x in xs:
        prev = x if prev is None else alpha * x + (1 - alpha) * prev
        out.append(prev)
    return out


def simulate_blend(
    raw: list[float],
    derived: list[float],
    weight: float,
    derived_alpha: float,
    ema_alpha: float,
) -> list[float]:
    """Offline replica of the controller pipeline for one candidate config."""
    blended: list[float] = []
    filt_derived: float | None = None
    for r, d in zip(raw, derived):
        fd = d if filt_derived is None else derived_alpha * d + (1 - derived_alpha) * filt_derived
        filt_derived = fd
        blended.append(weight * fd + (1 - weight) * r)
    return ema(blended, ema_alpha)


@dataclass
class Candidate:
    """One smoothing-coefficient candidate with its simulated metrics."""

    weight: float
    derived_alpha: float
    ema_alpha: float
    near_zero: float
    sigma: float

    def score(self) -> tuple[float, float]:
        # maximize near-zero share, then minimize residual variance
        return (self.near_zero, -self.sigma)


def sweep(
    raw: list[float],
    derived: list[float],
    weights: list[float] | None = None,
    derived_alphas: list[float] | None = None,
    ema_alphas: list[float] | None = None,
    top_n: int = 5,
) -> list[Candidate]:
    # ponytail: cap weight at 0.95 - keep some CT-meter feedback so Vue
    # calibration drift cannot silently bias the controller
    weights = weights or [round(0.05 * i, 2) for i in range(1, 20)]
    derived_alphas = derived_alphas or [0.05, 0.1, 0.15, 0.2, 0.3]
    ema_alphas = ema_alphas or [0.15, 0.2, 0.3, 0.4]
    results: list[Candidate] = []
    for w in weights:
        for ad in derived_alphas:
            for ea in ema_alphas:
                sim = simulate_blend(raw, derived, w, ad, ea)
                results.append(
                    Candidate(
                        weight=w,
                        derived_alpha=ad,
                        ema_alpha=ea,
                        near_zero=near_zero_pct(sim),
                        sigma=stddev(sim),
                    )
                )
    results.sort(key=lambda c: c.score(), reverse=True)
    return results[:top_n]


# --------------------------------------------------------------------------- #
# InfluxDB access                                                             #
# --------------------------------------------------------------------------- #


def flux_query(url: str, token: str, org: str, query: str) -> list[dict]:
    """Run one Flux query, return parsed CSV rows as dicts."""
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/v2/query?org={org}",
        data=json.dumps({"query": query, "dialect": {"annotations": ["datatype"]}}).encode(),
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "Accept": "application/csv",
        },
        method="POST",
    )
    body: bytes = b""
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    rows: list[dict] = []
    header: list[str] = []
    for line in body.decode().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if line.startswith(",result,table,_start"):
            continue
        if not header:
            header = parts
            continue
        row = dict(zip(header, parts))
        if row.get("_value"):
            rows.append(row)
    return rows


def fetch_field(
    url: str,
    token: str,
    org: str,
    bucket: str,
    hours: int,
    measurement: str,
    field: str,
) -> list[float]:
    q = (
        f'from(bucket: "{bucket}") '
        f"|> range(start: -{hours}h) "
        f'|> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}")'
    )
    vals: list[float] = []
    for row in flux_query(url, token, org, q):
        try:
            vals.append(float(row["_value"]))
        except ValueError:
            continue
    return vals


def resample_to(xs: list[float], n: int) -> list[float]:
    """Linear-interpolate a series onto n evenly spaced points."""
    if not xs:
        return []
    if len(xs) == 1:
        return xs * n
    out: list[float] = []
    step = (len(xs) - 1) / (n - 1)
    for i in range(n):
        pos = i * step
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        frac = pos - lo
        out.append(xs[lo] * (1 - frac) + xs[hi] * frac)
    return out


def load_window(args: argparse.Namespace) -> dict[str, list[float]]:
    fields = {
        "grid_power": ("inverter", "gt"),
        "filtered_gt": ("inverter", "filtered_gt"),
        "home_total": ("vue", "loads_Total"),
        "pv_total": ("inverter", "pv_total"),
    }
    out: dict[str, list[float]] = {}
    for key, (meas, field) in fields.items():
        vals = fetch_field(args.url, args.token, args.org, args.bucket, args.hours, meas, field)
        print(f"  fetched {key}: {len(vals)} samples")
        out[key] = vals
    return out


# --------------------------------------------------------------------------- #
# Demo data                                                                   #
# --------------------------------------------------------------------------- #


def demo_data(n: int = 3600) -> dict[str, list[float]]:
    """Synthetic window mimicking the production failure mode.

    True net load is smooth; the CT meter adds an alternating bias that flips
    every ~20 s (the observed sawtooth). The Vue-derived grid tracks truth with
    a small delay and light noise.
    """
    rng = random.Random(42)
    true_net: list[float] = []
    home: list[float] = []
    pv: list[float] = []
    for t in range(n):
        base = 800 * math.sin(2 * math.pi * t / 1800)  # slow appliance cycling
        steps = 600 if (t // 900) % 2 else 0
        solar = max(0.0, 3000 * math.sin(math.pi * t / n))
        true_net.append(base + steps - solar)
        home.append(base + steps + rng.gauss(0, 8))
        pv.append(solar + rng.gauss(0, 5))
    raw = [
        v + (180 if ((t // 20) % 2) else -180) + rng.gauss(0, 40) for t, v in enumerate(true_net)
    ]
    return {"grid_power": raw, "home_total": home, "pv_total": pv}


# --------------------------------------------------------------------------- #
# Report                                                                      #
# --------------------------------------------------------------------------- #


def analyze(data: dict[str, list[float]]) -> str:
    lines: list[str] = []
    raw = data["grid_power"]
    derived = [h - p for h, p in zip(data["home_total"], data["pv_total"])]
    current_filtered = data.get("filtered_gt") or []

    n = min(len(raw), len(derived))
    if n < 50:
        return "Not enough overlapping samples to analyze (need >= 50)."

    raw_n, der_n = resample_to(raw, n), resample_to(derived, n)
    filt_n = resample_to(current_filtered, n) if len(current_filtered) >= 50 else []

    lines.append("=== Grid Smoothing Analysis ===")
    lines.append(f"samples analyzed: {n}")
    lines.append("")
    lines.append("Current signals:")
    lines.append(
        f"  raw CT grid   : sigma={stddev(raw_n):7.1f} W  jitter={jitter(raw_n):6.1f} W  "
        f"zero-cross rate={zero_crossing_rate(raw_n):.4f}  near-zero={near_zero_pct(raw_n):5.1f}%"
    )
    if filt_n:
        lines.append(
            f"  filtered_gt   : sigma={stddev(filt_n):7.1f} W  jitter={jitter(filt_n):6.1f} W  "
            f"near-zero={near_zero_pct(filt_n):5.1f}%"
        )
    else:
        lines.append("  filtered_gt   : not available in bucket")
    lines.append(
        f"  derived grid  : sigma={stddev(der_n):7.1f} W  jitter={jitter(der_n):6.1f} W"
        f"  near-zero={near_zero_pct(der_n):5.1f}%"
    )
    lines.append("")

    r = pearson(raw_n, der_n)
    lag, lag_r = best_lag(raw_n, der_n, max_lag=30)
    direction = "derived LAGS raw" if lag > 0 else "derived LEADS raw"
    lines.append(
        f"corr(raw, derived) = {r:+.3f}; best lag = {lag} samples ({direction}, r={lag_r:+.3f})"
    )
    if abs(r) < 0.5:
        lines.append(
            "WARNING: weak correlation between CT grid and Vue-derived grid."
            " Check that Home Total covers all loads and PV total matches metered PV."
        )
    if filt_n and all(abs(f - g) < 1e-6 for f, g in zip(filt_n[:100], raw_n[:100])):
        lines.append(
            "NOTE: filtered_gt identical to raw grid -> ENABLE_GRID_SMOOTHING_WITH_HOME"
            " appears disabled in inverter-control; coefficients below have no effect"
            " until it is enabled."
        )
    lines.append("")

    top = sweep(raw_n, der_n)
    lines.append("Top candidates (simulated blend, objective: near-zero% then low sigma):")
    lines.append("  weight  derived_alpha  ema_alpha  near-zero%  sigma(W)")
    for c in top:
        lines.append(
            f"  {c.weight:5.2f}  {c.derived_alpha:13.2f}  {c.ema_alpha:9.2f}  "
            f"{c.near_zero:9.1f}%  {c.sigma:8.1f}"
        )
    best = top[0]
    lines.append("")
    lines.append("Recommended inverter-control local_config.py block:")
    lines.append("```python")
    lines.append("ENABLE_GRID_SMOOTHING_WITH_HOME = True")
    lines.append(f"GRID_SMOOTHING_HOME_WEIGHT = {best.weight}")
    lines.append(f"GRID_SMOOTHING_DERIVED_ALPHA = {best.derived_alpha}")
    lines.append(f"EMA_ALPHA = {best.ema_alpha}")
    lines.append("```")
    lines.append("")
    lines.append("Workflow: apply on Cerbo, watch the 'Grid Raw vs Smoothed' panel and")
    lines.append("'Grid sigma 1h' stat for a day, re-run this script, iterate.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8086", help="InfluxDB v2 base URL")
    ap.add_argument("--token", default="", help="InfluxDB token (or INFLUX_TOKEN env)")
    ap.add_argument("--org", default="home")
    ap.add_argument("--bucket", default="inverter")
    ap.add_argument("--hours", type=int, default=24, help="Analysis window in hours")
    ap.add_argument("--demo", action="store_true", help="Use synthetic data instead of InfluxDB")
    ap.add_argument("--json-out", default=None, help="Also write metrics + winner as JSON")
    args = ap.parse_args(argv)

    if args.demo:
        print("Generating synthetic demo window...")
        data = demo_data()
    else:
        token = args.token or os.environ.get("INFLUX_TOKEN", "")
        if not token:
            ap.error("--token or INFLUX_TOKEN env required without --demo")
        args.token = token
        print(f"Fetching {args.hours}h from {args.url} (org={args.org}, bucket={args.bucket})...")
        data = load_window(args)

    report = analyze(data)
    print(report)

    if args.json_out:
        raw = data["grid_power"]
        derived = [h - p for h, p in zip(data["home_total"], data["pv_total"])]
        n = min(len(raw), len(derived))
        raw_n, der_n = resample_to(raw, n), resample_to(derived, n)
        top = sweep(raw_n, der_n, top_n=1)[0]
        payload = {
            "samples": n,
            "raw_sigma_w": round(stddev(raw_n), 1),
            "raw_near_zero_pct": round(near_zero_pct(raw_n), 1),
            "corr_raw_derived": round(pearson(raw_n, der_n), 3),
            "recommended": {
                "ENABLE_GRID_SMOOTHING_WITH_HOME": True,
                "GRID_SMOOTHING_HOME_WEIGHT": top.weight,
                "GRID_SMOOTHING_DERIVED_ALPHA": top.derived_alpha,
                "EMA_ALPHA": top.ema_alpha,
                "expected_near_zero_pct": round(top.near_zero, 1),
            },
        }
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
