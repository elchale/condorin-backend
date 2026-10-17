"""The text Condorin writes for the ONG, so they only correct it instead of starting from a blank page."""
from datetime import timedelta

from django.conf import settings

from core.geo import coord, distance_km
from detections.models import SatelliteImage
from detections.text import dragas, fecha_corta, fecha_larga

HISTORY_DAYS = 120
HISTORY_RADIUS_KM = 3.0


def place_sentence(river) -> str:
    """'río Yaguas, cuenca del Putumayo, distrito de ..., dentro del Parque Nacional Yaguas'"""
    parts = [f'río {river.name}']
    if river.basin:
        parts.append(f'cuenca del {river.basin}')
    admin = ', '.join(p for p in [
        f'distrito de {river.district}' if river.district else '',
        f'provincia de {river.province}' if river.province else '',
        f'región {river.region}' if river.region else '',
    ] if p)
    if admin:
        parts.append(admin)
    text = ', '.join(parts)
    if river.protected_area:
        text += f', dentro del {river.protected_area}'
    return text


def earlier_sightings(image: SatelliteImage) -> list[SatelliteImage]:
    """Earlier scenes of the same river with a detection near any detection in this one."""
    points = [(float(d.lat), float(d.lon)) for d in image.alerting_detections()]
    if not points:
        return []
    since = image.captured_at - timedelta(days=HISTORY_DAYS)
    candidates = (SatelliteImage.objects
                  .filter(river=image.river, captured_at__gte=since, captured_at__lt=image.captured_at)
                  .prefetch_related('detections').order_by('-captured_at'))
    found = []
    for other in candidates:
        if any(distance_km(lat, lon, float(d.lat), float(d.lon)) <= HISTORY_RADIUS_KM
               for d in other.detections.all() if d.confidence >= settings.ALERT_MIN_CONFIDENCE
               for lat, lon in points):
            found.append(other)
    return found


def draft_facts(image: SatelliteImage) -> str:
    detections = list(image.alerting_detections())
    river = image.river
    first = detections[0] if detections else None
    paragraphs = [
        f'1. El {fecha_larga(image.captured_at)} (hora de Perú), el satélite {image.satellite} '
        f'captó una imagen del {place_sentence(river)}.',
        f'2. El análisis de esa imagen con el sistema de detección Condorin ({image.model_name} {image.model_version}) '
        f'identificó {dragas(len(detections))} de minería aurífera sobre el cauce del río'
        + (f', la principal en las coordenadas {coord(first.lat)}, {coord(first.lon)} (WGS84)' if first else '')
        + '. El detalle de cada punto y las imágenes se adjuntan como anexos.',
    ]
    history = earlier_sightings(image)
    if history:
        dates = ', '.join(fecha_corta(h.captured_at) for h in history[:5])
        paragraphs.append(
            f'3. En la misma zona, a menos de {HISTORY_RADIUS_KM:g} km, Condorin registró detecciones en '
            f'{len(history)} imágenes anteriores ({dates}), lo que indica una actividad sostenida.'
        )
    paragraphs.append(
        f'{len(paragraphs) + 1}. El uso de dragas y artefactos similares en los ríos está prohibido por el '
        'Decreto Legislativo 1100. Estos hechos constituirían presunto delito de minería ilegal y requieren '
        'la verificación en el lugar por parte de la autoridad.'
    )
    return '\n\n'.join(paragraphs)
