"""Only the condorin.pe server calls the panel routes: shared secret plus the member's phone.

The Next.js app checks its own session cookie (signed WhatsApp sign in) and forwards the phone in
X-Condorin-Phone. The secret never reaches a browser, so the header cannot be forged from outside.
"""
import hmac

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, ValidationError

from core.auth import bearer_token
from core.phone import PHONE_RE


def authenticate_frontend(request) -> None:
    secret = settings.PANEL_API_SECRET
    token = bearer_token(request)
    if token is None:
        raise NotAuthenticated('Falta el encabezado Authorization: Bearer.')
    if not secret or not hmac.compare_digest(token.encode(), secret.encode()):
        raise AuthenticationFailed('Credencial inválida.')


def member_phone(request) -> str:
    phone = request.headers.get('X-Condorin-Phone', '').strip()
    if not PHONE_RE.match(phone):
        raise ValidationError({'phone': ['Falta el número del miembro.']})
    return phone
