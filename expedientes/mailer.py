"""Email the final PDF to the ONG, and to any authority that takes denuncias by email."""
import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def _filename(expediente) -> str:
    return f'{expediente.folio}.pdf'


def _steps(expediente) -> str:
    lines = []
    for i, authority in enumerate(expediente.authorities.filter(active=True), start=1):
        where = authority.submit_url or authority.address or authority.phone
        lines.append(f'{i}. {authority.name}' + (f': {where}' if where else ''))
        if authority.instructions:
            lines.append(f'   {authority.instructions}')
    return '\n'.join(lines)


def send_to_ong(expediente, member) -> list[str]:
    """Returns the addresses it went to (empty if none or if sending failed)."""
    recipients = sorted({e for e in [expediente.notify_email, member.email] if e})
    if not recipients:
        return []
    body = (
        f'Hola {member.first_name},\n\n'
        f'Adjuntamos el expediente {expediente.folio} listo para presentar.\n\n'
        f'Código de integridad (SHA-256) del PDF: {expediente.pdf_sha256}\n\n'
        'Dónde presentarlo:\n'
        f'{_steps(expediente)}\n\n'
        'Cuando lo presentes, registra el número que te den en Condorin para hacer seguimiento.\n\n'
        'Condorin'
    )
    message = EmailMessage(
        subject=f'Expediente {expediente.folio}: denuncia lista para presentar',
        body=body, to=recipients,
    )
    message.attach(_filename(expediente), bytes(expediente.pdf), 'application/pdf')
    try:
        message.send()
    except Exception as exc:
        logger.error('expediente %s: email to the ONG failed: %s', expediente.pk, exc)
        return []
    return recipients


def send_to_authorities(expediente) -> list[str]:
    """Authorities with a confirmed email get the PDF directly, with the ONG as reply to."""
    sent = []
    for authority in expediente.authorities.filter(active=True).exclude(email=''):
        message = EmailMessage(
            subject=f'Denuncia por presunta minería ilegal, {expediente.image.river.name} ({expediente.folio})',
            body=(
                f'Señores {authority.name}:\n\n'
                f'{expediente.ong_name} presenta la denuncia adjunta por presunta minería ilegal en '
                f'el río {expediente.image.river.name}, con evidencia satelital.\n\n'
                f'Código de integridad (SHA-256) del PDF: {expediente.pdf_sha256}\n'
                f'Correo para notificaciones: {expediente.notify_email}\n\n'
                f'{expediente.rep_name}\n{expediente.rep_position}\n{expediente.ong_name}'
            ),
            to=[authority.email],
            cc=[expediente.notify_email] if expediente.notify_email else [],
            reply_to=[expediente.notify_email] if expediente.notify_email else [],
            from_email=settings.DEFAULT_FROM_EMAIL,
        )
        message.attach(_filename(expediente), bytes(expediente.pdf), 'application/pdf')
        try:
            message.send()
            sent.append(authority.email)
        except Exception as exc:
            logger.error('expediente %s: email to %s failed: %s', expediente.pk, authority.code, exc)
    return sent
