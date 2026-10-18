"""DRF throttles. The scopes that guard sign in codes count in the shared cache (the `django_cache` table), so
the limits hold across every Cloud Run instance; the high volume scopes count in process memory."""
from django.core.cache import caches
from rest_framework.throttling import ScopedRateThrottle

# Counted in the shared DatabaseCache: brute force or WhatsApp spam would otherwise get one budget per instance.
SHARED_SCOPES = {'auth_code', 'auth_enter', 'expediente_send', 'panel_link'}


class ScopedThrottle(ScopedRateThrottle):
    """ScopedRateThrottle whose counters live in the shared cache for SHARED_SCOPES, in `local` otherwise."""

    def allow_request(self, request, view):
        scope = getattr(view, self.scope_attr, None)
        self.cache = caches['default' if scope in SHARED_SCOPES else 'local']
        return super().allow_request(request, view)
