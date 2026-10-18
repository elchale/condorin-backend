"""NASA FIRMS active fires (VIIRS 375 m), the public 7 day CSV exports for South America. No key.

Each file is about 5 MB; it is streamed and only rows inside the Peruvian Amazon box are parsed fully.
"""
import csv
import logging
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from fuentes.http import Meter, stream_lines

logger = logging.getLogger(__name__)

ID = 'firms'
TTL_S = 3600
ATTRIBUTION = 'NASA FIRMS (VIIRS 375 m, S-NPP, NOAA-20, NOAA-21)'
URL = 'https://firms.modaps.eosdis.nasa.gov/active_fire/'

BASE = 'https://firms.modaps.eosdis.nasa.gov/data/active_fire'
FILES = {
    'S-NPP': f'{BASE}/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_America_7d.csv',
    'NOAA-20': f'{BASE}/noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_America_7d.csv',
    'NOAA-21': f'{BASE}/noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_America_7d.csv',
}
MAX_BYTES = 20 * 1024 * 1024
MAX_FIRES = 5000
# Peruvian Amazon (and a margin over the borders): lon -81 to -68, lat -18.5 to 0.5.
BBOX = (-81.0, -18.5, -68.0, 0.5)
CONFIDENCE = {'nominal': 'n', 'low': 'l', 'high': 'h', 'n': 'n', 'l': 'l', 'h': 'h'}


def parse_rows(lines, since: datetime, bbox=BBOX) -> list[dict]:
    """Fires inside bbox and after `since` from FIRMS CSV lines (header first)."""
    lines = iter(lines)
    header = next(lines, '')
    cols = {name: i for i, name in enumerate(header.strip().split(','))}
    i_lat, i_lon = cols.get('latitude', 0), cols.get('longitude', 1)
    min_lon, min_lat, max_lon, max_lat = bbox
    fires = []
    for line in lines:
        parts = line.split(',')
        if len(parts) < len(cols):
            continue
        try:
            lat, lon = float(parts[i_lat]), float(parts[i_lon])
        except ValueError:
            continue
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        row = next(csv.reader([line]))
        try:
            hhmm = row[cols['acq_time']].zfill(4)
            at = datetime.strptime(f"{row[cols['acq_date']]} {hhmm}", '%Y-%m-%d %H%M').replace(tzinfo=UTC)
            frp = float(row[cols['frp']] or 0)
        except (KeyError, ValueError):
            continue
        if at < since:
            continue
        fires.append({'lat': round(lat, 4), 'lon': round(lon, 4), 'at': at, 'frp': round(frp, 1),
                      'confidence': CONFIDENCE.get(row[cols['confidence']].strip().lower(), 'n')
                      if 'confidence' in cols else 'n',
                      'daynight': row[cols['daynight']].strip() if 'daynight' in cols else ''})
    return fires


def select(fires: list[dict], limit: int = MAX_FIRES) -> list[dict]:
    """Dedupe (about 100 m and the same day, keep the hottest) and keep the `limit` hottest, newest first."""
    best = {}
    for f in fires:
        key = (round(f['lat'], 3), round(f['lon'], 3), f['at'].date())
        if key not in best or f['frp'] > best[key]['frp']:
            best[key] = f
    top = sorted(best.values(), key=lambda f: f['frp'], reverse=True)[:limit]
    return sorted(top, key=lambda f: f['at'], reverse=True)


def to_feature(f: dict) -> dict:
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [f['lon'], f['lat']]},
            'properties': {'at': f['at'].strftime('%Y-%m-%dT%H:%M:%SZ'), 'frp': f['frp'],
                           'confidence': f['confidence'], 'sensor': 'VIIRS', 'daynight': f['daynight']}}


def fetch(meter: Meter | None = None) -> dict:
    since = timezone.now() - timedelta(days=7)
    fires, errors = [], []
    for name, url in FILES.items():
        try:
            fires += parse_rows(stream_lines(url, max_bytes=MAX_BYTES, meter=meter), since)
        except Exception as exc:  # one satellite down must not lose the others
            logger.warning('fuentes: FIRMS %s failed: %s', name, exc)
            errors.append(f'{name}: {exc.__class__.__name__}')
    if len(errors) == len(FILES):
        raise RuntimeError('; '.join(errors))
    selected = select(fires)
    return {'fires': {'type': 'FeatureCollection', 'features': [to_feature(f) for f in selected]},
            'in_bbox': len(fires), 'warnings': errors}
