"""What the condorin.pe panel shows an ONG member, and the doors into the expediente."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from core import gcs
from core.exceptions import BaseError
from detections.models import Alert, Detection, SatelliteImage, default_expiry
from detections.services import dispatch
from expedientes.models import Expediente
from expedientes.services import missing_fields
from ongs.models import Member, Ong

INCIDENT_LIMIT = 50


class NoOngAvailable(BaseError):
    status_code = 503
    default_detail = 'Todavía no hay una ONG para unirte. Escríbenos y te ayudamos.'


def default_ong() -> Ong | None:
    # TODO: demo only. Every new person joins one ONG; replace with real invitations later.
    ongs = Ong.objects.filter(active=True)
    if settings.DEFAULT_ONG_ID:
        return ongs.filter(pk=settings.DEFAULT_ONG_ID).first()
    return ongs.order_by('pk').first()


def member_for_phone(phone: str) -> tuple[Member, bool]:
    """The ONG member behind a condorin.pe sign in. Returns (member, joined_now).

    Someone already in an ONG keeps it. Anyone else joins the default ONG (demo only, see default_ong).
    """
    member = (Member.objects.select_related('ong')
              .filter(phone=phone, active=True, ong__active=True).order_by('pk').first())
    if member:
        return member, False
    ong = default_ong()
    if ong is None:
        raise NoOngAvailable()
    # The name is asked in the first expediente ("quién firma") and remembered from there.
    member, created = Member.objects.select_related('ong').get_or_create(
        ong=ong, phone=phone, defaults={'full_name': ''},
    )
    if not member.active:
        raise PermissionDenied('Tu acceso a esta ONG está desactivado. Escríbele a tu ONG.')
    if created:
        send_latest_alert(member)
    return member, created


def send_latest_alert(member: Member) -> Alert | None:
    """A new member gets the ONG's most recent alert by WhatsApp at once, so they see how Condorin works."""
    image = (SatelliteImage.objects
             .filter(river__in=member.ong.rivers.all(), detections__confidence__gte=settings.ALERT_MIN_CONFIDENCE)
             .order_by('-captured_at').first())
    if image is None:
        return None
    alert, created = Alert.objects.get_or_create(image=image, member=member)
    if created:
        transaction.on_commit(lambda: dispatch(image.pk))
    return alert


def incidents(ong: Ong) -> list[tuple[SatelliteImage, list[Detection], Expediente | None]]:
    """Scenes on the ONG's rivers that alerted someone, newest first, with the ONG's expediente if any."""
    alerting = Detection.objects.filter(confidence__gte=settings.ALERT_MIN_CONFIDENCE).order_by('-confidence')
    images = list(
        SatelliteImage.objects
        .filter(river__in=ong.rivers.all(), detections__confidence__gte=settings.ALERT_MIN_CONFIDENCE)
        .distinct().select_related('river')
        .prefetch_related(Prefetch('detections', queryset=alerting, to_attr='alerting'))
        .order_by('-captured_at')[:INCIDENT_LIMIT]
    )
    expedientes = {
        e.image_id: e for e in Expediente.objects.filter(ong=ong, image__in=images)
        .select_related('updated_by').prefetch_related('authorities', 'filings')
    }
    return [(image, image.alerting, expedientes.get(image.pk)) for image in images]


def open_from_panel(member: Member, image_id: int) -> Alert:
    """The member's personal link to the expediente of one scene, created when they had no alert for it."""
    image = SatelliteImage.objects.filter(pk=image_id, river__ongs=member.ong).first()
    if image is None or not image.alerting_detections().exists():
        raise NotFound('No encontramos esa detección en los ríos de tu ONG.')
    alert, _ = Alert.objects.get_or_create(image=image, member=member, defaults={'status': Alert.Status.PANEL})
    if alert.is_expired:
        # The member is signed in, so an old link of theirs can simply be renewed.
        alert.expires_at = default_expiry()
        alert.save(update_fields=['expires_at', 'updated'])
    return alert


def sign_in_by_link(token: str) -> Member:
    """The member a WhatsApp alert link was sent to, if that link may still sign them in.

    Only links actually delivered by WhatsApp count (whoever holds them holds that phone's chat), and
    only for LINK_SIGN_IN_DAYS after delivery. Anything else gets the same 404, so nothing leaks.
    """
    alert = (Alert.objects.select_related('member__ong')
             .filter(token=token, status=Alert.Status.SENT, member__active=True, member__ong__active=True)
             .first())
    window = timedelta(days=settings.LINK_SIGN_IN_DAYS)
    if alert is None or alert.is_expired or not alert.sent_at or timezone.now() > alert.sent_at + window:
        raise NotFound('Este enlace no permite iniciar sesión.')
    return alert.member


def missing_count(expediente: Expediente) -> int:
    return len(missing_fields(expediente))


def crop_url(detection) -> str | None:
    """Signed link to the pinned version of a detection's crop, or None when it cannot be signed."""
    if not detection.crop_uri:
        return None
    try:
        bucket, name, generation = gcs.parse_gs_uri(detection.crop_uri)
    except ValueError:
        return None
    return gcs.signed_url(bucket, name, detection.crop_generation or generation)
