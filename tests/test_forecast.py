"""Tests for forecast.py.

Covers:
- Bucketing correctness (averaging within a 10-min bucket, ordering).
- Trend as regression slope, not endpoint difference.
- Noise robustness: a single spiked sample doesn't swing the verdict.
- Coverage gate: sparse data => "Collecting data" even if a slope could be fit.
- Edge cases: empty input, <3 buckets, missing trend window, exactly-flat data.
- Forecast object reports honest `data_span_hours` and `trend_coverage_pct`.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `forecast` importable when running pytest from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import forecast as fc  # noqa: E402


NOW = datetime(2026, 6, 14, 5, 0, 0, tzinfo=timezone.utc)


def _series(end_p: float, start_p: float, hours: float, samples_per_hour: int = 60,
            noise: list[float] | None = None) -> list[tuple[str, float]]:
    """Linear ramp from start_p (oldest) to end_p (newest) over `hours`.

    Optional `noise` is a list of per-sample additive jitter, applied from
    oldest to newest; pad with zeros if shorter than the series.
    """
    n = int(hours * samples_per_hour)
    out: list[tuple[str, float]] = []
    for i in range(n):
        t = NOW - timedelta(seconds=(n - i) * 3600 / samples_per_hour)
        frac = i / max(1, n - 1)
        p = start_p + (end_p - start_p) * frac
        if noise is not None and i < len(noise):
            p += noise[i]
        out.append((t.isoformat(timespec="seconds"), p))
    return out


# ---------- bucketize ----------

def test_bucketize_averages_within_bucket():
    raw = [
        (NOW.isoformat(timespec="seconds"), 1000.0),
        ((NOW + timedelta(minutes=1)).isoformat(timespec="seconds"), 1002.0),
        ((NOW + timedelta(minutes=2)).isoformat(timespec="seconds"), 1004.0),
    ]
    buckets = fc.bucketize(raw, bucket_minutes=10)
    assert len(buckets) == 1
    assert buckets[0].pressure_hpa == 1002.0  # mean(1000, 1002, 1004)


def test_bucketize_sorted_ascending():
    raw = [
        ((NOW + timedelta(hours=2)).isoformat(timespec="seconds"), 1010.0),
        (NOW.isoformat(timespec="seconds"), 1000.0),
        ((NOW + timedelta(hours=1)).isoformat(timespec="seconds"), 1005.0),
    ]
    buckets = fc.bucketize(raw)
    assert [b.pressure_hpa for b in buckets] == [1000.0, 1005.0, 1010.0]


def test_bucketize_empty():
    assert fc.bucketize([]) == []


def test_bucketize_accepts_Z_suffix():
    raw = [
        (NOW.isoformat(timespec="seconds").replace("+00:00", "Z"), 1000.0),
    ]
    buckets = fc.bucketize(raw)
    assert len(buckets) == 1


# ---------- trend (slope-based) ----------

def test_trend_pure_linear_ramp_matches_endpoint_delta():
    # Perfectly linear: slope * hours == endpoint difference.
    raw = _series(end_p=1010.0, start_p=1000.0, hours=3)
    buckets = fc.bucketize(raw)
    d3 = fc.trend(buckets, hours=3)
    assert d3 is not None
    assert abs(d3 - 10.0) < 0.2


def test_trend_is_regression_not_endpoint_diff():
    """A single spiked endpoint must NOT swing the trend by the full spike."""
    raw = _series(end_p=1010.0, start_p=1010.0, hours=3)  # flat at 1010
    # Slam the very last reading 4 hPa low (sensor glitch).
    ts, p = raw[-1]
    raw[-1] = (ts, p - 4.0)

    buckets = fc.bucketize(raw)
    d3 = fc.trend(buckets, hours=3)
    # Endpoint-difference would report ~-4 hPa here. Regression should report
    # something well under 1 hPa because one bucket is being pulled toward
    # a glitch but the slope is dominated by 17 other buckets at 1010.
    assert d3 is not None
    assert abs(d3) < 1.0, f"regression too sensitive to single spike: {d3}"


def test_trend_robust_to_random_noise():
    """±0.3 hPa jitter on a flat series shouldn't trip a "rain" verdict."""
    import random
    rng = random.Random(42)
    n = 3 * 60  # 3h at 1-min
    noise = [rng.uniform(-0.3, 0.3) for _ in range(n)]
    raw = _series(end_p=1015.0, start_p=1015.0, hours=3, noise=noise)
    buckets = fc.bucketize(raw)
    d3 = fc.trend(buckets, hours=3)
    assert d3 is not None
    assert abs(d3) < 0.5, f"noise alone produced trend {d3:+.3f} hPa/3h"
    headline, _ = fc._verdict(d3)
    assert headline == "No significant change"


def test_trend_returns_none_with_fewer_than_3_buckets():
    raw = _series(end_p=1010.0, start_p=1010.0, hours=0.2)  # ~12 min → 2 buckets
    buckets = fc.bucketize(raw)
    assert len(buckets) <= 2
    assert fc.trend(buckets, hours=3) is None


def test_trend_returns_none_for_empty():
    assert fc.trend([], hours=3) is None


# ---------- coverage ----------

def test_coverage_full_window():
    raw = _series(end_p=1015.0, start_p=1015.0, hours=3)
    buckets = fc.bucketize(raw)
    cov = fc.coverage(buckets, hours=3)
    # 3 h / 10 min/bucket = 18 expected; we should get ~18.
    assert cov >= 0.95


def test_coverage_sparse_window():
    raw = _series(end_p=1015.0, start_p=1015.0, hours=0.5)  # only 30 min
    buckets = fc.bucketize(raw)
    cov = fc.coverage(buckets, hours=3)
    # 30 min / 3 h = ~17%
    assert 0.1 < cov < 0.25


def test_coverage_empty():
    assert fc.coverage([], hours=3) == 0.0


# ---------- forecast (coverage gate + verdict) ----------

def test_forecast_sparse_data_says_collecting():
    """30 minutes of data must not yield a confident 12h forecast."""
    raw = _series(end_p=1010.0, start_p=1015.0, hours=0.5)  # 5 hPa drop in 30 min!
    buckets = fc.bucketize(raw)
    f = fc.forecast(buckets)
    assert f.headline == "Collecting data"
    assert f.trend_3h_hpa is None
    assert f.data_span_hours < 1.0
    assert f.trend_coverage_pct < 60.0


def test_forecast_empty_input():
    f = fc.forecast([])
    assert f.headline == "Collecting data"
    assert f.current_hpa is None
    assert f.trend_3h_hpa is None
    assert f.sample_count == 0
    assert f.data_span_hours == 0.0


def test_forecast_storm_verdict():
    raw = _series(end_p=1007.0, start_p=1015.0, hours=3)  # -8 hPa/3h
    f = fc.forecast(fc.bucketize(raw))
    assert f.headline.startswith("Storm")
    assert f.trend_3h_hpa is not None and f.trend_3h_hpa < -6.0


def test_forecast_rain_verdict():
    raw = _series(end_p=1012.0, start_p=1015.0, hours=3)  # -3 hPa/3h
    f = fc.forecast(fc.bucketize(raw))
    assert "Rain" in f.headline
    assert f.trend_3h_hpa is not None
    assert -6.0 < f.trend_3h_hpa < -1.5


def test_forecast_steady_verdict():
    raw = _series(end_p=1015.0, start_p=1015.0, hours=3)
    f = fc.forecast(fc.bucketize(raw))
    assert f.headline == "No significant change"


def test_forecast_fair_verdict():
    raw = _series(end_p=1018.0, start_p=1015.0, hours=3)  # +3 hPa/3h
    f = fc.forecast(fc.bucketize(raw))
    assert "Fair" in f.headline


def test_forecast_clearing_verdict():
    raw = _series(end_p=1023.0, start_p=1015.0, hours=3)  # +8 hPa/3h
    f = fc.forecast(fc.bucketize(raw))
    assert "Clearing" in f.headline


def test_forecast_reports_span_and_coverage():
    raw = _series(end_p=1015.0, start_p=1015.0, hours=6)
    f = fc.forecast(fc.bucketize(raw))
    assert 5.5 < f.data_span_hours < 6.1
    assert f.trend_coverage_pct >= 95.0
    assert f.sample_count >= 30


def test_forecast_realistic_indoor_noise_stays_steady():
    """An indoor sensor with 1 hPa diurnal drift + 0.3 hPa jitter should
    NOT keep flipping between rain and fair across hours of operation."""
    import random
    rng = random.Random(0)
    n = 6 * 60  # 6h
    # gentle 0.5 hPa sinusoid (HVAC) + 0.25 hPa white noise on top of 1014.5
    import math
    noise = []
    for i in range(n):
        diurnal = 0.5 * math.sin(2 * math.pi * i / (6 * 60))  # one cycle in 6h
        jitter = rng.uniform(-0.25, 0.25)
        noise.append(diurnal + jitter)
    raw = _series(end_p=1014.5, start_p=1014.5, hours=6, noise=noise)
    buckets = fc.bucketize(raw)
    f = fc.forecast(buckets)
    assert f.headline == "No significant change", (
        f"realistic indoor noise tripped verdict to {f.headline} "
        f"(Δ3h = {f.trend_3h_hpa:+.3f})"
    )
