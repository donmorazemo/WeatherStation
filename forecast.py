#!/usr/bin/env python3
"""Pressure-trend forecasting.

Pure functions — no I/O. Given a sequence of (ts_iso, pressure_hpa) readings
from the existing weather.db, we:

  1. Downsample into fixed-width time buckets (default 10 min) by averaging.
  2. Compute the pressure change over the last 3 hours (Zambretti's window).
  3. Map that change to a plain-English forecast for the next ~12 hours.

The trend-based mapping is altitude-independent: a Δ of -5 hPa over 3 hours
means the same thing whether the sensor sits at sea level or on a mountain.
That is why we ignore absolute pressure tiers here — the BMP280 reports raw
station pressure and we do not assume a known altitude offset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


BUCKET_MINUTES = 10
TREND_HOURS = 3
NOWCAST_HOURS = 1
FORECAST_HORIZON_HOURS = 12
HISTORY_HOURS = 72


@dataclass(frozen=True)
class Bucket:
    ts: datetime          # bucket start, UTC
    pressure_hpa: float   # mean pressure within the bucket


@dataclass(frozen=True)
class Forecast:
    headline: str             # one-line verdict
    detail: str               # longer plain-English explanation
    trend_3h_hpa: float | None
    trend_1h_hpa: float | None
    current_hpa: float | None
    horizon_hours: int
    sample_count: int


def _parse_ts(ts: str) -> datetime:
    # Tolerate both "2026-06-12T10:00:00+00:00" and "...Z"
    s = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def bucketize(
    readings: Iterable[tuple[str, float]],
    bucket_minutes: int = BUCKET_MINUTES,
) -> list[Bucket]:
    """Average raw readings into fixed-width time buckets, sorted ascending."""
    width = timedelta(minutes=bucket_minutes)
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


def _pressure_at(buckets: list[Bucket], target: datetime, tolerance_min: int = 20) -> float | None:
    """Return the bucketed pressure nearest `target`, within tolerance, else None."""
    if not buckets:
        return None
    nearest = min(buckets, key=lambda b: abs(b.ts - target))
    if abs(nearest.ts - target) <= timedelta(minutes=tolerance_min):
        return nearest.pressure_hpa
    return None


def trend(buckets: list[Bucket], hours: int) -> float | None:
    """Pressure Δ over the last `hours` hours (hPa). None if not enough data."""
    if not buckets:
        return None
    latest = buckets[-1]
    past_target = latest.ts - timedelta(hours=hours)
    past = _pressure_at(buckets, past_target, tolerance_min=20)
    if past is None:
        return None
    return latest.pressure_hpa - past


def _verdict(delta_3h: float | None) -> tuple[str, str]:
    """Map 3-hour Δ (hPa) to (headline, detail).

    Thresholds follow standard meteorological rules of thumb used by consumer
    weather stations (Davis, Acurite, Zambretti). Pressure falling > 2 hPa/h
    sustained is the classic storm signal.
    """
    if delta_3h is None:
        return ("Collecting data", "Need at least 3 hours of readings to forecast.")
    d = delta_3h
    if d <= -6.0:
        return (
            "Storm likely within hours",
            "Pressure is falling rapidly (more than 6 hPa in 3 hours). "
            "Expect strong winds and heavy rain soon. Secure loose items outside.",
        )
    if d <= -1.5:
        return (
            "Rain or clouds within 12–24 hours",
            "Pressure is falling steadily. A weather front is moving in — "
            "expect increasing cloud, then rain within a day.",
        )
    if d < 1.5:
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


def forecast(buckets: list[Bucket]) -> Forecast:
    """Build the full forecast object from bucketed history."""
    current = buckets[-1].pressure_hpa if buckets else None
    d3 = trend(buckets, TREND_HOURS)
    d1 = trend(buckets, NOWCAST_HOURS)
    headline, detail = _verdict(d3)
    return Forecast(
        headline=headline,
        detail=detail,
        trend_3h_hpa=d3,
        trend_1h_hpa=d1,
        current_hpa=current,
        horizon_hours=FORECAST_HORIZON_HOURS,
        sample_count=len(buckets),
    )


if __name__ == "__main__":
    # Quick smoke test with synthetic data: a 5 hPa drop over 3h → "Rain likely"
    import random

    now = datetime.now(timezone.utc)
    rng = random.Random(0)
    synthetic: list[tuple[str, float]] = []
    for i in range(HISTORY_HOURS * 60):  # 1-minute samples
        t = now - timedelta(minutes=HISTORY_HOURS * 60 - i)
        # Flat at 1015 for 69h, then drop 5 hPa linearly over last 3h
        hours_from_end = (HISTORY_HOURS * 60 - i) / 60
        if hours_from_end < 3:
            p = 1015 - (3 - hours_from_end) / 3 * 5
        else:
            p = 1015
        p += rng.uniform(-0.05, 0.05)
        synthetic.append((t.isoformat(timespec="seconds"), p))

    bs = bucketize(synthetic)
    f = forecast(bs)
    print(f"Buckets: {len(bs)}")
    print(f"Current: {f.current_hpa:.2f} hPa")
    print(f"Δ 3h: {f.trend_3h_hpa:+.2f} hPa")
    print(f"Δ 1h: {f.trend_1h_hpa:+.2f} hPa")
    print(f"Verdict: {f.headline}")
    print(f"Detail: {f.detail}")
