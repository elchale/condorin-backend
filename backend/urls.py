from django.contrib import admin
from django.urls import path

from core.views import healthz, landing
from detections.views import DetectionWebhookView
from expedientes.views import ExpedienteSendView, ExpedienteView

admin.site.site_header = 'Condorin'
admin.site.site_title = 'Condorin'

urlpatterns = [
    path('', landing, name='landing'),
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),

    # The detector posts here (no trailing slash: it posts exactly this path).
    path('api/v1/detections', DetectionWebhookView.as_view(), name='detections'),

    # Opened from the WhatsApp button; the token is personal to one ONG member and one incident.
    path('api/v1/expedientes/<str:token>', ExpedienteView.as_view(), name='expediente'),
    path('api/v1/expedientes/<str:token>/enviar', ExpedienteSendView.as_view(), name='expediente-send'),
]
