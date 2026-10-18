"""Routes the condorin.pe server calls for the ONG panel and the WhatsApp link sign in.

GET   /api/v1/panel                                  the member, their ONG and its incidents
POST  /api/v1/panel/incidentes/<id>/expediente       the member's link to that incident's expediente
POST  /api/v1/panel/enlace  {"token"}                which member a WhatsApp alert link signs in

Every call carries `Authorization: Bearer <PANEL_API_SECRET>`; the first two also `X-Condorin-Phone`.
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from core import gcs
from core.geo import coord, maps_url, utm
from detections.text import fecha_larga
from expedientes.drafting import place_sentence

from .auth import authenticate_frontend, member_phone
from .services import incidents, member_for_phone, missing_count, open_from_panel, sign_in_by_link

# How many crops of one scene the panel card shows.
CARD_CROPS = 4


class FrontendView(APIView):
    throttle_scope = 'panel'

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        authenticate_frontend(request)


def _crop_url(detection) -> str | None:
    if not detection.crop_uri:
        return None
    try:
        bucket, name, generation = gcs.parse_gs_uri(detection.crop_uri)
    except ValueError:
        return None
    return gcs.signed_url(bucket, name, detection.crop_generation or generation)


def _incident(image, detections, expediente) -> dict:
    best = detections[0]
    lat, lon = coord(best.lat), coord(best.lon)
    return {
        'id': image.pk,
        'river': {'slug': image.river.slug, 'name': image.river.name, 'protected_area': image.river.protected_area},
        'place': place_sentence(image.river),
        'satellite': image.satellite,
        'captured_at': image.captured_at,
        'captured_at_label': fecha_larga(image.captured_at),
        'model': f'{image.model_name} {image.model_version}',
        'detections': len(detections),
        'top_confidence': round(best.confidence, 3),
        'lat': lat,
        'lon': lon,
        'utm': utm(float(best.lat), float(best.lon))['label'],
        'maps_url': maps_url(lat, lon),
        'crops': [url for url in (_crop_url(d) for d in detections[:CARD_CROPS]) if url],
        'evidence_pinned': bool(image.md5_hash),
        'expediente': expediente and {
            'status': expediente.status,
            'status_label': expediente.get_status_display(),
            'folio': expediente.folio,
            'updated_at': expediente.updated,
            'updated_by': expediente.updated_by.full_name if expediente.updated_by else None,
            'missing': missing_count(expediente) if expediente.status == expediente.Status.DRAFT else 0,
            'authorities': [a.name for a in expediente.authorities.all()],
            'filings': len(expediente.filings.all()),
        },
    }


class PanelView(FrontendView):
    def get(self, request):
        member, joined = member_for_phone(member_phone(request))
        ong = member.ong
        rows = [_incident(*row) for row in incidents(ong)]
        statuses = [r['expediente']['status'] if r['expediente'] else 'none' for r in rows]
        return Response({
            'member': {'name': member.full_name, 'phone': member.phone, 'joined_now': joined},
            'ong': {
                'name': ong.display_name,
                'rivers': [{'slug': r.slug, 'name': r.name, 'protected_area': r.protected_area}
                           for r in ong.rivers.all()],
                'members': ong.members.filter(active=True).count(),
            },
            'totals': {
                'incidents': len(rows),
                'without_expediente': statuses.count('none'),
                'draft': statuses.count('draft'),
                'ready': statuses.count('ready'),
                'filed': statuses.count('filed'),
            },
            'incidents': rows,
        })


class PanelExpedienteView(FrontendView):
    def post(self, request, image_id):
        member, _ = member_for_phone(member_phone(request))
        alert = open_from_panel(member, image_id)
        return Response({'token': alert.token})


class LinkSignInView(FrontendView):
    throttle_scope = 'panel_link'

    def post(self, request):
        member = sign_in_by_link(str(request.data.get('token', '')).strip())
        return Response({'phone': member.phone, 'name': member.full_name})
