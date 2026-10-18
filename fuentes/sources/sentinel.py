"""Sentinel-1 and Sentinel-2 passes over each river, from the Copernicus Data Space catalogue (no auth).

Per river: Sentinel-1 GRD passes in the last 30 days, the last one, and an estimate of the next one
(the last pass of each relative orbit plus the repeat cycle: 12 days, or 6 when two platforms share
that orbit); Sentinel-2 L2A scenes, the last one, its cloud cover and how many were under 25 % cloud.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from django.utils import timezone

from fuentes.http import Meter, get_json
from fuentes.rivers import river_points

logger = logging.getLogger(__name__)

ID = 'sentinel'
TTL_S = 6 * 3600
ATTRIBUTION = 'Copernicus Data Space Ecosystem (ESA), Sentinel-1 y Sentinel-2'
URL = 'https://dataspace.copernicus.eu/'

CATALOGUE = 'https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
DAYS = 30
CLEAR_CLOUD = 25.0
MAX_BYTES = 3 * 1024 * 1024
PRODUCT_TYPE = {'SENTINEL-1': 'IW_GRDH_1S', 'SENTINEL-2': 'S2MSI2A'}
WORKERS = 4


def iso(value: datetime | None) -> str | None:
    return value.strftime('%Y-%m-%dT%H:%M:%SZ') if value else None


def _parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def query(collection: str, lat: float, lon: float, since: datetime, meter: Meter | None = None) -> list[dict]:
    """The catalogue products over one point, newest first, flattened to {name, start, attrs}."""
    flt = (f"Collection/Name eq '{collection}'"
           f" and OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})')"
           f" and ContentDate/Start gt {since.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
           " and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType'"
           f" and att/OData.CSC.StringAttribute/Value eq '{PRODUCT_TYPE[collection]}')")
    params = {'$filter': flt, '$orderby': 'ContentDate/Start desc', '$top': '50', '$expand': 'Attributes'}
    data = get_json(CATALOGUE, params, max_bytes=MAX_BYTES, meter=meter)
    return [{'name': p['Name'].removesuffix('.SAFE'), 'start': _parse_time(p['ContentDate']['Start']),
             'attrs': {a['Name']: a.get('Value') for a in p.get('Attributes', [])}}
            for p in data.get('value', [])]


def summarize_s1(products: list[dict], now: datetime) -> dict:
    passes = {}  # one per datatake: adjacent slices over the same point are the same pass
    for p in products:
        a = p['attrs']
        key = (a.get('platformSerialIdentifier'), a.get('orbitNumber') or p['start'].date())
        if key not in passes or p['start'] > passes[key]['start']:
            passes[key] = p
    by_orbit = {}
    for p in passes.values():
        by_orbit.setdefault(p['attrs'].get('relativeOrbitNumber'), []).append(p)
    estimates = []
    for orbit_passes in by_orbit.values():
        last = max(p['start'] for p in orbit_passes)
        platforms = {p['attrs'].get('platformSerialIdentifier') for p in orbit_passes}
        step = timedelta(days=6 if len(platforms) >= 2 else 12)
        nxt = last + step
        while nxt <= now:
            nxt += step
        estimates.append(nxt)
    latest = max(passes.values(), key=lambda p: p['start'], default=None)
    return {'s1_last': iso(latest['start']) if latest else None,
            's1_last_id': latest['name'] if latest else None,
            's1_passes_30d': len(passes),
            's1_next_estimate': iso(min(estimates)) if estimates else None}


def summarize_s2(products: list[dict]) -> dict:
    scenes = {}  # a point on the edge of two tiles shows the same acquisition twice: keep the clearer
    for p in products:
        cloud = p['attrs'].get('cloudCover')
        cloud = float(cloud) if cloud is not None else None
        key = (p['name'][:3], p['start'].replace(microsecond=0))
        if key not in scenes or (cloud is not None and (scenes[key][1] is None or cloud < scenes[key][1])):
            scenes[key] = (p, cloud)
    latest = max(scenes.values(), key=lambda s: s[0]['start'], default=None)
    return {'s2_last': iso(latest[0]['start']) if latest else None,
            's2_last_cloud': round(latest[1], 1) if latest and latest[1] is not None else None,
            's2_clear_last_30d': sum(1 for _, c in scenes.values() if c is not None and c < CLEAR_CLOUD)}


def fetch(meter: Meter | None = None) -> dict:
    now = timezone.now()
    since = now - timedelta(days=DAYS)
    points = river_points()
    errors = []

    def one(point):
        slug, lat, lon = point
        out = {}
        for collection in ('SENTINEL-1', 'SENTINEL-2'):
            try:
                products = query(collection, lat, lon, since, meter)
            except Exception as exc:
                logger.warning('fuentes: %s over %s failed: %s', collection, slug, exc)
                errors.append(f'{slug} {collection}: {exc.__class__.__name__}')
                continue
            out.update(summarize_s1(products, now) if collection == 'SENTINEL-1' else summarize_s2(products))
        return slug, out

    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix='fuentes-sentinel') as pool:
        rivers = {slug: out for slug, out in pool.map(one, points) if out}
    if points and not rivers:
        raise RuntimeError('; '.join(errors[:4]))
    return {'rivers': rivers, 'warnings': errors}
