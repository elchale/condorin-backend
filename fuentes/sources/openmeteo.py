"""Open-Meteo weather per river (no key): rain in the last 24 hours and 7 days, current temperature.

All rivers go in one request (Open-Meteo takes comma separated coordinates).
"""
from datetime import UTC, datetime, timedelta

from fuentes.http import Meter, get_json
from fuentes.rivers import river_points

ID = 'open-meteo'
TTL_S = 3 * 3600
ATTRIBUTION = 'Open-Meteo.com (CC BY 4.0)'
URL = 'https://open-meteo.com/'

FORECAST = 'https://api.open-meteo.com/v1/forecast'
MAX_BYTES = 2 * 1024 * 1024


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def summarize(location: dict) -> dict:
    current = location.get('current') or {}
    now = _utc(current['time']) if current.get('time') else datetime.now(UTC)
    hourly = location.get('hourly') or {}
    rain = [(_utc(t), v or 0.0) for t, v in zip(hourly.get('time', []), hourly.get('precipitation', []))]
    rain = [(t, v) for t, v in rain if t <= now]
    return {'rain_mm_7d': round(sum(v for t, v in rain if t > now - timedelta(days=7)), 1),
            'rain_mm_24h': round(sum(v for t, v in rain if t > now - timedelta(hours=24)), 1),
            'temp_c': current.get('temperature_2m'),
            'updated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ')}


def fetch(meter: Meter | None = None) -> dict:
    points = river_points()
    if not points:
        return {'rivers': {}}
    params = {'latitude': ','.join(str(p[1]) for p in points), 'longitude': ','.join(str(p[2]) for p in points),
              'current': 'temperature_2m,precipitation', 'hourly': 'precipitation',
              'past_days': 7, 'forecast_days': 1, 'timezone': 'UTC'}
    data = get_json(FORECAST, params, max_bytes=MAX_BYTES, meter=meter)
    locations = data if isinstance(data, list) else [data]
    return {'rivers': {slug: summarize(loc) for (slug, _, _), loc in zip(points, locations, strict=False)}}
