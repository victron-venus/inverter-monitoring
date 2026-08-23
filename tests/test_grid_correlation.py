"""Tests for the grid smoothing analyzer (offline, synthetic data)."""

from __future__ import annotations

import math
import random

import pytest

from analysis.grid_correlation import (
    best_lag,
    demo_data,
    ema,
    jitter,
    near_zero_pct,
    pearson,
    simulate_blend,
    stddev,
    sweep,
    zero_crossing_rate,
)


def test_pearson_perfect_and_uncorrelated():
    a = [float(i) for i in range(100)]
    assert pearson(a, a) == pytest.approx(1.0)
    rng = random.Random(1)
    noise = [rng.gauss(0, 100) for _ in range(200)]
    other = [rng.gauss(0, 100) for _ in range(200)]
    assert abs(pearson(noise, other)) < 0.3


def test_ema_reduces_noise():
    rng = random.Random(2)
    signal = [100.0] * 500
    noisy = [v + rng.gauss(0, 50) for v in signal]
    assert stddev(ema(noisy, 0.3)) < stddev(noisy)


def test_zero_crossing_rate_detects_sawtooth():
    calm = [10.0] * 100
    sawtooth = [150.0 if i % 20 < 10 else -150.0 for i in range(100)]
    assert zero_crossing_rate(calm) == 0.0
    assert zero_crossing_rate(sawtooth) == pytest.approx(9 / 99)


def test_near_zero_pct():
    assert near_zero_pct([50, -50, 100, 101]) == 75.0


def test_best_lag_finds_known_delay():
    rng = random.Random(3)
    a = [rng.gauss(0, 0.1) + math.sin(t / 20.0) * 10 for t in range(300)]
    delay = 7
    # b[t] = a[t - delay]: b events happen `delay` samples after a's
    b = [a[0]] * delay + a[: len(a) - delay]
    lag, r = best_lag(a, b, max_lag=15)
    assert lag == delay
    assert r > 0.99


def test_demo_data_has_sawtooth_raw_and_smooth_truth():
    data = demo_data()
    raw = data["grid_power"]
    derived = [h - p for h, p in zip(data["home_total"], data["pv_total"])]
    # raw carries the +/-180 W flipping bias -> far rougher sample-to-sample
    assert jitter(raw) > jitter(derived) * 3
    assert len(raw) == len(derived)


def test_jitter_distinguishes_sawtooth_from_slow_swing():
    sawtooth = [150.0 if i % 20 < 10 else -150.0 for i in range(200)]
    slow = [300.0 * math.sin(i / 30.0) for i in range(200)]
    assert jitter(sawtooth) > 50
    assert jitter(slow) < 15


def test_sweep_prefers_blending_over_raw_for_sawtooth():
    data = demo_data()
    raw = data["grid_power"]
    derived = [h - p for h, p in zip(data["home_total"], data["pv_total"])]
    top = sweep(raw, derived, top_n=3)
    best = top[0]
    # blending must beat the raw signal on near-zero share
    assert best.weight > 0
    assert best.near_zero > near_zero_pct(raw)
    # and the simulated result should be smoother than raw
    sim = simulate_blend(raw, derived, best.weight, best.derived_alpha, best.ema_alpha)
    assert stddev(sim) < stddev(raw)


def test_simulate_blend_weight_zero_returns_filtered_raw():
    xs = list(range(100))
    out = simulate_blend(xs, xs, weight=0.0, derived_alpha=0.1, ema_alpha=1.0)
    assert out == xs  # no blend, no EMA smoothing
