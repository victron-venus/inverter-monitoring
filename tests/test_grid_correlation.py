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
    # Deterministic synthetic telemetry for analysis/tests, never cryptographic randomness.
    rng = random.Random(1)  # nosec B311
    noise = [rng.gauss(0, 100) for _ in range(200)]
    other = [rng.gauss(0, 100) for _ in range(200)]
    assert abs(pearson(noise, other)) < 0.3


def test_ema_reduces_noise():
    # Deterministic synthetic telemetry for analysis/tests, never cryptographic randomness.
    rng = random.Random(2)  # nosec B311
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
    # Deterministic synthetic telemetry for analysis/tests, never cryptographic randomness.
    rng = random.Random(3)  # nosec B311
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


@pytest.mark.parametrize(
    ("filtered", "expected_jitter"),
    [
        ([0.0] * 30 + [math.nan] + [1000.0] * 30, "0.0"),
        ([0.0, math.nan] * 50, "n/a"),
        ([0.0, 10.0] * 30, f"{jitter([0.0, 10.0] * 30):.1f}"),
    ],
)
def test_filtered_jitter_uses_only_adjacent_available_samples(filtered, expected_jitter):
    from analysis.grid_correlation import analyze  # pylint: disable=import-outside-toplevel

    data = {
        "grid_power": [100.0] * len(filtered),
        "home_total": [200.0] * len(filtered),
        "pv_total": [100.0] * len(filtered),
        "filtered_gt": filtered,
    }
    report = analyze(data)
    line = next(line for line in report.splitlines() if line.startswith("  filtered_gt"))
    assert line.split("jitter=", 1)[1].split(" W", 1)[0].strip() == expected_jitter
    assert "sigma=" in line
    assert "near-zero=" in line


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


def test_flux_query_parses_csv_with_annotations_and_multiple_tables(monkeypatch):
    from analysis import grid_correlation as gc  # pylint: disable=import-outside-toplevel

    csv_body = (
        "#datatype,string,long,dateTime:RFC3339,double,string\r\n"
        ",result,table,_time,_value,_field\r\n"
        ",_result,0,2026-08-23T10:00:00Z,4,grid_power\r\n"
        "\r\n"
        "#datatype,string,long,dateTime:RFC3339,double,string\r\n"
        ",result,table,_time,_value,_field\r\n"
        ",_result,0,2026-08-23T10:00:10Z,7,pv_total\r\n"
        ",_result,1,2026-08-23T10:00:20Z,9,pv_total\r\n"
    )

    class FakeResp:  # pylint: disable=missing-class-docstring
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return csv_body.encode()

    class FakeOpener:  # pylint: disable=missing-class-docstring
        def open(self, req, timeout):
            assert req.get_header("Authorization") == "Token t"
            assert timeout == 60
            return FakeResp()

    monkeypatch.setattr(gc.urllib.request, "build_opener", lambda *handlers: FakeOpener())
    rows = gc.flux_query("http://localhost:8086", "t", "home", 'from(bucket: "inverter")')
    assert [r["_value"] for r in rows] == ["4", "7", "9"]
    assert [r["_field"] for r in rows] == ["grid_power", "pv_total", "pv_total"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://localhost/data", "http:///query"])
def test_flux_query_rejects_non_http_endpoints_before_opening(monkeypatch, url):
    from analysis import grid_correlation as gc  # pylint: disable=import-outside-toplevel

    def unexpected_open(*_args):
        pytest.fail("Invalid InfluxDB URL must not create an opener")

    monkeypatch.setattr(gc.urllib.request, "build_opener", unexpected_open)
    with pytest.raises(ValueError, match="invalid InfluxDB URL"):
        gc.flux_query(url, "private-token", "home", "query")


def test_flux_query_rejects_redirects_without_forwarding_token():
    from http.server import (  # pylint: disable=import-outside-toplevel
        BaseHTTPRequestHandler,
        HTTPServer,
    )
    from threading import Thread  # pylint: disable=import-outside-toplevel

    from analysis import grid_correlation as gc  # pylint: disable=import-outside-toplevel

    requests = []

    class RedirectHandler(BaseHTTPRequestHandler):  # pylint: disable=missing-class-docstring
        def do_POST(self):  # pylint: disable=invalid-name
            requests.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", "https://example.invalid/redirect-target")
            self.end_headers()

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), RedirectHandler) as server:
        server.timeout = 5
        worker = Thread(target=server.handle_request, daemon=True)
        worker.start()
        try:
            with pytest.raises(ValueError, match="InfluxDB redirects are not allowed"):
                gc.flux_query(
                    f"http://127.0.0.1:{server.server_port}", "private-token", "home", "query"
                )
        finally:
            worker.join(timeout=6)
        assert not worker.is_alive()
    assert requests == ["Token private-token"]


def test_fetch_series_skips_nonfinite_and_overflow_values(monkeypatch):
    from analysis import grid_correlation as gc  # pylint: disable=import-outside-toplevel

    rows = [
        {"_time": "t1", "_value": "10.5"},
        {"_time": "t2", "_value": "nan"},
        {"_time": "t3", "_value": "inf"},
        {"_time": "t4", "_value": "-inf"},
        {"_time": "t5", "_value": "1e309"},
        {"_time": "t6", "_value": "20"},
        {"_time": "t7"},  # missing value
    ]

    monkeypatch.setattr(gc, "flux_query", lambda *args, **kwargs: rows)
    series = gc.fetch_series("http://127.0.0.1:8086", "token", "org", "bucket", 1, "inverter", "gt")
    assert series == {"t1": 10.5, "t6": 20.0}


def test_optional_filtered_gt_does_not_trim_required_window(monkeypatch):
    """filtered_gt is optional and must not shrink raw, home, or PV samples.

    Synthetic Influx CSV goes through fetch_series, load_window, analyze, and main.
    Partial and disjoint filtered timestamps stay on their own minutes (NaN holes).
    They are never compacted and zipped against a different raw minute.
    """
    import contextlib
    import io
    import json
    import math
    import re
    from datetime import UTC, datetime, timedelta

    from analysis import grid_correlation as gc  # pylint: disable=import-outside-toplevel

    timestamps = [
        (datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=i)).isoformat() for i in range(60)
    ]
    variants = {
        "absent": [],
        "partial": timestamps[:10],
        "disjoint": ["2026-09-30T00:00:00+00:00"],
        "complete": timestamps,
    }

    class _Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body.encode()

    def opener_for(filtered_times):
        class Opener:
            def open(self, request, timeout):
                assert request.get_header("Authorization") == "Token synthetic-test-token"
                query = json.loads(request.data)["query"]
                field = re.search(r'r\._field == "([^"]+)"', query).group(1)
                selected = filtered_times if field == "filtered_gt" else timestamps
                header = (
                    "#datatype,string,long,dateTime:RFC3339,double,string\n"
                    ",result,table,_time,_value,_field\n"
                )
                rows = "".join(
                    f",_result,0,{stamp},{index + 1},{field}\n"
                    for index, stamp in enumerate(selected)
                )
                return _Response(header + rows)

        return Opener()

    for name, filtered_times in variants.items():
        monkeypatch.setattr(
            gc.urllib.request,
            "build_opener",
            lambda *args, filtered_times=filtered_times, **kwargs: opener_for(filtered_times),
        )
        args = gc.argparse.Namespace(
            url="http://127.0.0.1:8086",
            # Synthetic test credentials/sentinels; not valid external-service secrets.
            token="synthetic-test-token",  # nosec B106
            org="test",
            bucket="test",
            hours=1,
        )
        data = gc.load_window(args)
        report = gc.analyze(data)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = gc.main(
                [
                    "--url",
                    args.url,
                    "--token",
                    args.token,
                    "--org",
                    "test",
                    "--bucket",
                    "test",
                    "--hours",
                    "1",
                ]
            )
        assert len(data["grid_power"]) == len(data["home_total"]) == len(data["pv_total"]) == 60
        assert exit_code == 0
        assert report.startswith("=== Grid Smoothing Analysis ===")
        assert "samples analyzed: 60" in report
        if name == "absent":
            assert data["filtered_gt"] == []
            assert "filtered_gt   : not available in bucket" in report
        elif name == "complete":
            assert data["filtered_gt"] == data["grid_power"]
            assert "not available in bucket" not in report
            assert "filtered_gt identical to raw grid" in report
        elif name == "partial":
            assert len(data["filtered_gt"]) == 60
            assert data["filtered_gt"][0] == data["grid_power"][0]
            assert math.isnan(data["filtered_gt"][10])
            assert "filtered_gt   : not available in bucket" in report
            assert "filtered_gt identical to raw grid" not in report
        elif name == "disjoint":
            assert len(data["filtered_gt"]) == 60
            assert all(math.isnan(value) for value in data["filtered_gt"])
            assert "filtered_gt   : not available in bucket" in report
            assert "filtered_gt identical to raw grid" not in report


def test_required_series_fallback_aligns_fifty_minutes_and_missing_pv_exits_zero(monkeypatch):
    """Required aliases and a 50-minute stagger, then a missing pv_total.

    grid_power contains only rejected non-finite rows, so the window uses gt.
    loads_totalusage is empty, so the window uses loads_Total. Annotated synthetic
    CSV goes through the patched opener into fetch_series, load_window, analyze,
    and main. Omitting pv_total leaves the required intersection empty.
    """
    import contextlib
    import io
    import json
    import re
    from datetime import UTC, datetime, timedelta

    from analysis import grid_correlation as gc  # pylint: disable=import-outside-toplevel

    base = datetime(2026, 10, 2, tzinfo=UTC)

    def stamp(minute):
        return (base + timedelta(minutes=minute)).isoformat()

    overlap = range(10, 60)
    expected_grid = [1000.0 + minute for minute in overlap]
    expected_home = [2000.0 + minute for minute in overlap]
    expected_pv = [300.0 + minute for minute in overlap]

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body.encode()

    def csv_for(field, samples):
        header = (
            "#datatype,string,long,dateTime:RFC3339,double,string\n"
            ",result,table,_time,_value,_field\n"
        )
        rows = "".join(f",_result,0,{when},{value},{field}\n" for when, value in samples)
        return header + rows

    def samples_for(measurement, field, include_pv):
        if measurement == "inverter" and field == "grid_power":
            return [
                (stamp(10), "nan"),
                (stamp(11), "inf"),
                (stamp(12), "-inf"),
                (stamp(13), "1e309"),
            ]
        if measurement == "inverter" and field == "gt":
            return [(stamp(minute), f"{1000 + minute}") for minute in range(60)]
        if measurement == "vue" and field == "loads_Total":
            return [(stamp(minute), f"{2000 + minute}") for minute in range(10, 70)]
        if measurement == "inverter" and field == "pv_total" and include_pv:
            return [(stamp(minute), f"{300 + minute}") for minute in overlap]
        return []

    def install(include_pv):
        calls = []

        class Opener:
            def open(self, request, timeout):
                assert request.get_header("Authorization") == "Token synthetic-test-token"
                assert timeout == 60
                assert request.full_url.startswith("http://127.0.0.1:8086/")
                query = json.loads(request.data)["query"]
                measurement = re.search(r'r\._measurement == "([^"]+)"', query).group(1)
                field = re.search(r'r\._field == "([^"]+)"', query).group(1)
                calls.append((measurement, field))
                return Response(csv_for(field, samples_for(measurement, field, include_pv)))

        monkeypatch.setattr(gc.urllib.request, "build_opener", lambda *args, **kwargs: Opener())
        return calls

    args = gc.argparse.Namespace(
        url="http://127.0.0.1:8086",
        # Synthetic test credentials/sentinels; not valid external-service secrets.
        token="synthetic-test-token",  # nosec B106
        org="test",
        bucket="test",
        hours=1,
    )
    argv = [
        "--url",
        args.url,
        "--token",
        args.token,
        "--org",
        "test",
        "--bucket",
        "test",
        "--hours",
        "1",
    ]
    expected_calls = [
        ("inverter", "grid_power"),
        ("inverter", "gt"),
        ("inverter", "filtered_gt"),
        ("vue", "loads_totalusage"),
        ("vue", "loads_Total"),
        ("inverter", "pv_total"),
    ]

    calls = install(True)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        data = gc.load_window(args)
    captured = stdout.getvalue()
    assert calls == expected_calls
    report = gc.analyze(data)
    main_out = io.StringIO()
    with contextlib.redirect_stdout(main_out):
        exit_code = gc.main(argv)

    assert calls == expected_calls + expected_calls
    assert data["grid_power"] == expected_grid
    assert data["home_total"] == expected_home
    assert data["pv_total"] == expected_pv
    assert data["filtered_gt"] == []
    assert 1000.0 not in data["grid_power"]
    assert "fetched grid_power: 60 minute buckets" in captured
    assert "fetched home_total: 60 minute buckets" in captured
    assert "fetched pv_total: 50 minute buckets" in captured
    assert "time-intersection: 50 aligned buckets (grid_power: -10, home_total: -10)" in captured
    assert report.startswith("=== Grid Smoothing Analysis ===")
    assert "samples analyzed: 50" in report
    assert "Recommended inverter-control local_config.py block:" in report
    assert "ENABLE_GRID_SMOOTHING_WITH_HOME = True" in report
    assert exit_code == 0
    assert "samples analyzed: 50" in main_out.getvalue()

    calls = install(False)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        missing = gc.load_window(args)
    missing_out = stdout.getvalue()
    assert calls == expected_calls
    missing_report = gc.analyze(missing)
    missing_main = io.StringIO()
    with contextlib.redirect_stdout(missing_main):
        missing_exit = gc.main(argv)

    assert calls == expected_calls + expected_calls
    assert missing["grid_power"] == []
    assert missing["home_total"] == []
    assert missing["pv_total"] == []
    assert missing["filtered_gt"] == []
    assert "fetched pv_total: 0 minute buckets" in missing_out
    assert "time-intersection: 0 aligned buckets (grid_power: -60, home_total: -60)" in missing_out
    assert missing_report == "Not enough overlapping samples to analyze (need >= 50)."
    assert "Recommended" not in missing_report
    assert missing_exit == 0
    assert missing_report in missing_main.getvalue()


def _public_sweep_reference(
    raw,
    derived,
    weights=None,
    derived_alphas=None,
    ema_alphas=None,
    top_n=5,
):
    """Order candidates from public blend calls and the documented score."""
    weights = weights or [round(0.05 * i, 2) for i in range(1, 20)]
    derived_alphas = derived_alphas or [0.05, 0.1, 0.15, 0.2, 0.3]
    ema_alphas = ema_alphas or [0.15, 0.2, 0.3, 0.4]
    ranked = []
    for weight in weights:
        for derived_alpha in derived_alphas:
            for ema_alpha in ema_alphas:
                simulated = simulate_blend(raw, derived, weight, derived_alpha, ema_alpha)
                near_zero = near_zero_pct(simulated)
                sigma = stddev(simulated)
                ranked.append(
                    (near_zero, -sigma, weight, derived_alpha, ema_alpha, near_zero, sigma)
                )
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [(row[2], row[3], row[4], row[5], row[6]) for row in ranked[:top_n]]


def _sweep_rows(candidates):
    return [
        (item.weight, item.derived_alpha, item.ema_alpha, item.near_zero, item.sigma)
        for item in candidates
    ]


def test_simulate_blend_golden_vector_keeps_inputs_and_zip_length():
    raw = [0.0, 2.0, -2.0]
    derived = [2.0, 0.0, 2.0]
    raw_before = list(raw)
    derived_before = list(derived)
    assert simulate_blend(raw, derived, weight=0.25, derived_alpha=0.5, ema_alpha=0.5) == [
        0.5,
        1.125,
        0.0,
    ]
    short_derived = [2.0]
    assert simulate_blend(raw, short_derived, 0.25, 0.5, 0.5) == [0.5]
    assert raw == raw_before
    assert derived == derived_before
    assert short_derived == [2.0]
    bounded = [100.0, -100.0, 100.0000001]
    assert simulate_blend(bounded, bounded, weight=0.0, derived_alpha=0.2, ema_alpha=1.0) == bounded
    assert near_zero_pct(bounded) == pytest.approx(200.0 / 3.0)
    assert simulate_blend(bounded, [0.0, 4.0], weight=1.0, derived_alpha=1.0, ema_alpha=1.0) == [
        0.0,
        4.0,
    ]


def test_sweep_matches_public_reference_for_order_defaults_and_ties():
    raw = [0.0, 2.0, -2.0, 40.0]
    derived = [2.0, 0.0, 2.0]
    assert simulate_blend(raw, derived, weight=0.25, derived_alpha=0.5, ema_alpha=0.5) == [
        0.5,
        1.125,
        0.0,
    ]
    duplicate = sweep(
        raw,
        derived,
        weights=[0.25, 0.25],
        derived_alphas=[0.5],
        ema_alphas=[0.5, 0.5],
        top_n=4,
    )
    expected = _public_sweep_reference(
        raw,
        derived,
        weights=[0.25, 0.25],
        derived_alphas=[0.5],
        ema_alphas=[0.5, 0.5],
        top_n=4,
    )
    assert _sweep_rows(duplicate) == expected
    assert expected[0][:3] == (0.25, 0.5, 0.5)
    assert len(expected) == 4
    assert expected[0][3:] == expected[1][3:]
    empty = sweep([], [], weights=[0.2, 0.2], derived_alphas=[0.1], ema_alphas=[0.3], top_n=2)
    assert _sweep_rows(empty) == _public_sweep_reference(
        [],
        [],
        weights=[0.2, 0.2],
        derived_alphas=[0.1],
        ema_alphas=[0.3],
        top_n=2,
    )
    assert sweep(raw, derived, top_n=0) == []
    negative = sweep(
        raw,
        derived,
        weights=[0.2],
        derived_alphas=[0.1, 0.2],
        ema_alphas=[0.3],
        top_n=-1,
    )
    assert _sweep_rows(negative) == _public_sweep_reference(
        raw,
        derived,
        weights=[0.2],
        derived_alphas=[0.1, 0.2],
        ema_alphas=[0.3],
        top_n=-1,
    )
    defaults = sweep(raw, derived, weights=[], derived_alphas=[], ema_alphas=[], top_n=3)
    assert _sweep_rows(defaults) == _public_sweep_reference(raw, derived, top_n=3)
