"""Signed values for the SPA sign in (contract B): the pending code and the 30 day session.

Both are `django.core.signing.TimestampSigner` values under SECRET_KEY, with their own salt so one can
never be used as the other. Nothing is stored server side except a short lived attempt counter in the
cache. The code itself never leaves the server: the pending value only carries an HMAC of it, keyed
with SECRET_KEY (a bare sha256 of a 6 digit code could be reversed offline in a millisecond).

Caveat: the attempt counter and the 45 s resend lock live in Django's cache. With the default LocMem
cache each instance counts on its own, which is fine on one Cloud Run instance; behind several the
limits are per instance until CACHES points at a shared backend.
"""
import hashlib
import hmac
import re

from django.conf import settings
from django.core import signing
from rest_framework import status

from core.exceptions import BaseError

PENDING_SALT = 'otp-pending'
SESSION_SALT = 'session'
CODE_SECONDS = 10 * 60
SESSION_SECONDS = 30 * 24 * 60 * 60

PHONE_RE = re.compile(r'^\d{10,15}$')


class SessionInvalid(BaseError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Tu sesión venció o no es válida. Vuelve a entrar.'


def normalize_phone(raw) -> str | None:
    """'936 282 808' → '51936282808'. Digits only; 9 digit Peruvian numbers get the 51 prefix."""
    digits = re.sub(r'\D', '', str(raw or ''))
    if len(digits) == 9:
        digits = f'51{digits}'
    return digits if PHONE_RE.match(digits) else None


def code_digest(phone: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f'otp|{phone}|{code}'.encode(), hashlib.sha256).hexdigest()


def pending_value(phone: str, code: str) -> str:
    return signing.TimestampSigner(salt=PENDING_SALT).sign_object({'p': phone, 'h': code_digest(phone, code)})


def read_pending(value: str) -> dict:
    """{'p': phone, 'h': digest}. Raises signing.SignatureExpired or signing.BadSignature."""
    data = signing.TimestampSigner(salt=PENDING_SALT).unsign_object(value, max_age=CODE_SECONDS)
    if not isinstance(data, dict) or not PHONE_RE.match(str(data.get('p', ''))) or not data.get('h'):
        raise signing.BadSignature('malformed pending value')
    return data


def session_token(phone: str) -> str:
    return signing.TimestampSigner(salt=SESSION_SALT).sign(phone)


def read_session(token: str) -> str | None:
    """The phone a session token belongs to, or None when it is missing, forged or older than 30 days."""
    try:
        phone = signing.TimestampSigner(salt=SESSION_SALT).unsign(token, max_age=SESSION_SECONDS)
    except signing.BadSignature:  # SignatureExpired is a subclass
        return None
    return phone if PHONE_RE.match(phone) else None


def bearer_phone(request) -> str | None:
    """The phone behind `Authorization: Bearer <session>`, or None when absent or invalid."""
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        return None
    return read_session(token.strip())


def require_session(request) -> str:
    phone = bearer_phone(request)
    if phone is None:
        raise SessionInvalid()
    return phone
