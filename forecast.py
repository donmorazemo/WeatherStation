#!/usr/bin/env python3
"""Pressure-trend forecasting.

Pure functions — no I/O. Given a sequence of (ts_iso, pressure_hpa) readings
from the existing weather.db, we:

  1. Downsample into fixed-width time buckets (default 10 min) by averaging.
  2. Compute the pressure tendency over the last 3 hours as a *linear-regression
     slope*, not an endpoint difference. A single noisy bucket can no longer
     swing the verdict.
  3. Map that tendency to a plain-English forecast for the next ~12 hours.

The trend-based mapping is altitude-independent: a Δ of -5 hPa over 3 hours
means the same thing whether the sensor sits at sea level or on a mountain.
That is why we ignore absolute pressure tiers here — the BMP280 reports raw
station pressure and we do not assume a known altitude offset.

Coverage gate: we refuse to issue a verdict unless the trend window has at
least MIN_COVERAGE buckets actually present. A 30-minute trickle of data is
not a 3-hour forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


BUCKET_MINUTES = 10
TREND_HOURS = 3
NOWCAST_HOURS = 1
CONFIRM_HOURS = 6              # secondary window used to confirm the 3 h trend
FORECAST_HORIZON_HOURS = 12
HISTORY_HOURS = 72
BASELINE_DAYS = 7              # rolling baseline for pressure anomaly

# Need at least this fraction of the trend window populated before we'll
# publish a verdict. 60% of 3h = ~1.8 h of buckets, ~11 of 18 expected.
MIN_COVERAGE = 0.60

# Confirmation rules. The 3 h window is the primary verdict (matches WMO /
# Zambretti / METAR practice). The 6 h window confirms or downgrades it.
# A meaningful trend at 3 h is one that exceeds the steady band (±1.5 hPa).
# We call it "confirmed" iff the 6 h trend has the same sign AND magnitude
# above CONFIRM_MIN_MAGNITUDE hPa over 6h — i.e. the trend is sustained, not
# just the afternoon atmospheric tide peak.
CONFIRM_MIN_MAGNITUDE = 1.0    # hPa over the 6 h window
STEADY_BAND = 1.5              # 3 h Δ within ±STEADY_BAND is always "steady"


@dataclass(frozen=True)
class Bucket:
    ts: datetime          # bucket start, UTC
    pressure_hpa: float   # mean pressure within the bucket


@dataclass(frozen=True)
class Forecast:
    headline: str             # one-line verdict
    detail: str               # longer plain-English explanation
    trend_3h_hpa: float | None    # slope-derived Δ over the 3 h trend window
    trend_1h_hpa: float | None    # slope-derived Δ over the 1 h nowcast window
    trend_6h_hpa: float | None    # slope-derived Δ over the 6 h confirm window
    current_hpa: float | None
    horizon_hours: int
    sample_count: int             # total buckets in the input history
    data_span_hours: float        # actual span (newest − oldest) in input
    trend_coverage_pct: float     # % of the 3 h window populated with buckets
    anomaly_hpa: float | None     # current pressure minus 7-day baseline
    baseline_hpa: float | None    # 7-day mean (caller supplies, sourced from DB)
    confirmed: bool               # 3 h trend sign confirmed by 6 h trend


def _parse_ts(ts: str) -> datetime:
    # Tolerate both "2026-06-12T10:00:00+00:00" and "...Z"
    s = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def bucketize(
    readings: Iterable[tuple[str, float]],
    bucket_minutes: int = BUCKET_MINUTES,
) -> list[Bucket]:
    """Average raw readings into fixed-width time buckets, sorted ascending."""
    sums: dict[datetime, list[float]] = {}
    for ts, p in readings:
        dt = _parse_ts(ts)
        epoch = dt.timestamp()
        bucket_start = datetime.fromtimestamp(
            (epoch // (bucket_minutes * 60)) * (bucket_minutes * 60),
            tz=timezone.utc,
        )
        sums.setdefault(bucket_start, []).append(p)
    return [
        Bucket(ts=t, pressure_hpa=sum(v) / len(v))
        for t, v in sorted(sums.items())
    ]


def _window(buckets: list[Bucket], hours: float) -> list[Bucket]:
    """Buckets within `hours` of the latest bucket (inclusive of latest)."""
    if not buckets:
        return []
    cutoff = buckets[-1].ts - timedelta(hours=hours)
    return [b for b in buckets if b.ts >= cutoff]


def _slope_hpa_per_hour(window: list[Bucket]) -> float | None:
    """Least-squares slope of pressure vs time (hPa per hour) over the window.

    Robust to single-point sensor jitter: a 0.3 hPa noise spike on one bucket
    barely moves the regression line, whereas an endpoint-difference would
    pick up the full 0.3 hPa.
    """
    n = len(window)
    if n < 3:
        return None
    x0 = window[0].ts.timestamp()
    xs = [(b.ts.timestamp() - x0) / 3600.0 for b in window]  # hours
    ys = [b.pressure_hpa for b in window]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    return num / den


def trend(buckets: list[Bucket], hours: float) -> float | None:
    """Pressure Δ over the last `hours` hours, computed as slope × hours.

    Returns None if the window has too few buckets to fit a line.
    """
    win = _window(buckets, hours)
    slope = _slope_hpa_per_hour(win)
    if slope is None:
        return None
    return slope * hours


def coverage(buckets: list[Bucket], hours: float, bucket_minutes: int = BUCKET_MINUTES) -> float:
    """Fraction (0..1) of the trailing `hours` window that has buckets.

    Compared against the theoretical maximum (hours * 60 / bucket_minutes).
    """
    if not buckets:
        return 0.0
    win = _window(buckets, hours)
    expected = max(1.0, hours * 60.0 / bucket_minutes)
    return min(1.0, len(win) / expected)


def data_span_hours(buckets: list[Bucket]) -> float:
    if len(buckets) < 2:
        return 0.0
    return (buckets[-1].ts - buckets[0].ts).total_seconds() / 3600.0


def _verdict(delta_3h: float | None) -> tuple[str, str]:
    """Map 3-hour Δ (hPa) to (headline, detail).

    Thresholds follow standard meteorological rules of thumb used by consumer
    weather stations (Davis, Acurite, Zambretti). Pressure falling > 2 hPa/h
    sustained is the classic storm signal.
    """
    if delta_3h is None:
        return ("Collecting data", "Need more readings before we can forecast.")
    d = delta_3h
    if d <= -6.0:
        return (
            "Storm likely within hours",
            "Pressure is falling rapidly (more than 6 hPa in 3 hours). "
            "Expect strong winds and heavy rain soon. Secure loose items outside.",
        )
    if d <= -STEADY_BAND:
        return (
            "Rain or clouds within 12–24 hours",
            "Pressure is falling steadily. A weather front is moving in — "
            "expect increasing cloud, then rain within a day.",
        )
    if d < STEADY_BAND:
        return (
            "No significant change",
            "Pressure is steady. Whatever weather you have now is likely to "
            "persist for the next 12 hours.",
        )
    if d < 6.0:
        return (
            "Fair weather likely",
            "Pressure is rising steadily. Clouds should thin out and "
            "conditions improve over the next 12 hours.",
        )
    return (
        "Clearing rapidly — possibly windy or cooler",
        "Pressure is rising fast. A high-pressure system is moving in — "
        "expect sun, but also gustier winds and a temperature drop behind the front.",
    )


def _confirmed(delta_3h: float | None, delta_6h: float | None) -> bool:
    """True iff the 3 h trend's sign and magnitude are backed by the 6 h trend.

    Rules:
    - A 3 h reading inside the steady band is trivially "confirmed" (we're
      saying nothing is happening — no need to corroborate).
    - For a non-steady 3 h reading, require:
        * 6 h trend exists,
        * same sign,
        * |6 h Δ| ≥ CONFIRM_MIN_MAGNITUDE.
      This filters the afternoon atmospheric tide (~1 hPa over 3 h that
      doesn't continue over 6 h).
    """
    if delta_3h is None:
        return False
    if abs(delta_3h) < STEADY_BAND:
        return True
    if delta_6h is None:
        return False
    if (delta_3h > 0) != (delta_6h > 0):
        return False
    return abs(delta_6h) >= CONFIRM_MIN_MAGNITUDE


def _downgrade_unconfirmed(headline: str, detail: str, delta_3h: float,
                           delta_6h: float | None) -> tuple[str, str]:
    """Soften an unconfirmed 3 h verdict to a 'watch'."""
    d6_text = (f"{delta_6h:+.1f} hPa over 6 h" if delta_6h is not None
               else "no 6 h reading yet")
    if delta_3h < 0:
        return (
            "Watch — possible front, not yet confirmed",
            f"Pressure dipped {delta_3h:+.1f} hPa over the last 3 h, but the "
            f"6-hour view ({d6_text}) doesn't back it up. Could be an "
            f"approaching front or just the afternoon pressure tide / a local "
            f"HVAC bump. Will firm up the verdict if the drop continues.",
        )
    return (
        "Watch — possible clearing, not yet confirmed",
        f"Pressure rose {delta_3h:+.1f} hPa over the last 3 h, but the "
        f"6-hour view ({d6_text}) doesn't back it up. Could be a real high "
        f"moving in or just the morning pressure tide. Will firm up the "
        f"verdict if the rise continues.",
    )


def forecast(buckets: list[Bucket], baseline_hpa: float | None = None) -> Forecast:
    """Build the full forecast object from bucketed history.

    `baseline_hpa` is the 7-day mean pressure (caller computes from DB). When
    provided, the anomaly = current − baseline is reported.
    """
    current = buckets[-1].pressure_hpa if buckets else None
    cov_3h = coverage(buckets, TREND_HOURS)
    span = data_span_hours(buckets)

    d1 = trend(buckets, NOWCAST_HOURS)
    d3 = trend(buckets, TREND_HOURS) if cov_3h >= MIN_COVERAGE else None
    d6 = trend(buckets, CONFIRM_HOURS)
    confirmed = _confirmed(d3, d6)

    # Coverage gate: refuse to issue a real verdict if the trend window is
    # too sparse. Avoids the "30 min of data → confident 12h forecast" trap.
    if d3 is None:
        headline = "Collecting data"
        detail = (
            f"Have {span:.1f} h of readings — need at least "
            f"{TREND_HOURS * MIN_COVERAGE:.1f} h before forecasting."
        )
    else:
        headline, detail = _verdict(d3)
        # If 3 h is outside the steady band but the 6 h doesn't confirm it,
        # downgrade to a "watch" rather than a confident verdict.
        if abs(d3) >= STEADY_BAND and not confirmed:
            headline, detail = _downgrade_unconfirmed(headline, detail, d3, d6)

    anomaly = (round(current - baseline_hpa, 2)
               if (current is not None and baseline_hpa is not None) else None)

    return Forecast(
        headline=headline,
        detail=detail,
        trend_3h_hpa=d3,
        trend_1h_hpa=d1,
        trend_6h_hpa=d6,
        current_hpa=current,
        horizon_hours=FORECAST_HORIZON_HOURS,
        sample_count=len(buckets),
        data_span_hours=round(span, 2),
        trend_coverage_pct=round(cov_3h * 100, 1),
        anomaly_hpa=anomaly,
        baseline_hpa=round(baseline_hpa, 2) if baseline_hpa is not None else None,
        confirmed=confirmed,
    )
