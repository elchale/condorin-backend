"""Wording of the WhatsApp alert, kept next to the template definition it has to match."""
from django.conf import settings
from django.utils import timezone

from core.geo import coord
from core.whatsapp import text

MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
          'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


def fecha_larga(value) -> str:
    """'15 de octubre de 2026 a las 05:42', in Lima time."""
    local = timezone.localtime(value)
    return f'{local.day} de {MONTHS[local.month - 1]} de {local.year} a las {local:%H:%M}'


def fecha_corta(value) -> str:
    local = timezone.localtime(value)
    return f'{local.day} de {MONTHS[local.month - 1]} de {local.year}'


def dragas(count: int) -> str:
    return '1 posible draga' if count == 1 else f'{count} posibles dragas'


# UTILITY template. {{1}} first name, {{2}} what was seen, {{3}} river, {{4}} date, {{5}} coordinates.
# Body variables never open or close the text, as Meta requires.
ALERT_BODY = (
    'Hola {{1}}, Condorin detectó {{2}} en el río {{3}} en una imagen satelital del {{4}}. '
    'La ubicación aproximada es {{5}}.\n\n'
    'Con esta evidencia puedes preparar la denuncia en pocos minutos. Toca Crear expediente para empezar.'
)
ALERT_FOOTER = 'Condorin, monitoreo satelital de la Amazonía'
ALERT_BUTTON_EXPEDIENTE = 'Crear expediente'
ALERT_BUTTON_MAP = 'Ver ubicación'
MAP_URL_BASE = 'https://www.google.com/maps/search/?api=1&query='


def alert_template_definition(header_handle: str) -> dict:
    """Body for POST /{WABA_ID}/message_templates."""
    sample_token = 'ejemplo123'
    return {
        'name': settings.WA_ALERT_TEMPLATE,
        'language': settings.WA_TEMPLATE_LANG,
        'category': 'UTILITY',
        'components': [
            {'type': 'HEADER', 'format': 'IMAGE', 'example': {'header_handle': [header_handle]}},
            {'type': 'BODY', 'text': ALERT_BODY, 'example': {'body_text': [[
                'María', '1 posible draga', 'Yaguas', '15 de octubre de 2026 a las 05:42', '-2.7706, -70.9512',
            ]]}},
            {'type': 'FOOTER', 'text': ALERT_FOOTER},
            {'type': 'BUTTONS', 'buttons': [
                {'type': 'URL', 'text': ALERT_BUTTON_EXPEDIENTE,
                 'url': f'{settings.FRONTEND_URL}/expediente/{{{{1}}}}',
                 'example': [f'{settings.FRONTEND_URL}/expediente/{sample_token}']},
                {'type': 'URL', 'text': ALERT_BUTTON_MAP,
                 'url': f'{MAP_URL_BASE}{{{{1}}}}',
                 'example': [f'{MAP_URL_BASE}-2.7706,-70.9512']},
            ]},
        ],
    }


def alert_template_components(*, member, image, count, header_url, token, lat, lon) -> list[dict]:
    """Parameters for one send of the template above."""
    return [
        {'type': 'header', 'parameters': [{'type': 'image', 'image': {'link': header_url}}]},
        {'type': 'body', 'parameters': [
            text(member.first_name or 'equipo'),
            text(dragas(count)),
            text(image.river.name),
            text(fecha_larga(image.captured_at)),
            text(f'{coord(lat)}, {coord(lon)}'),
        ]},
        {'type': 'button', 'sub_type': 'url', 'index': '0', 'parameters': [text(token)]},
        {'type': 'button', 'sub_type': 'url', 'index': '1', 'parameters': [text(f'{coord(lat)},{coord(lon)}')]},
    ]
