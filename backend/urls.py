from django.contrib import admin
from django.urls import path

from core.views import healthz, landing
from detections.views import DetectionWebhookView
from expedientes.views import EventoView, ExpedienteSendView, ExpedienteView
from panel.views import ActivityView, LinkSignInView, PanelExpedienteView, PanelView

admin.site.site_header = 'Ojo de Cóndor'
admin.site.site_title = 'Ojo de Cóndor'

urlpatterns = [
    path('', landing, name='landing'),
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),

    # The detector posts here (no trailing slash: it posts exactly this path).
    path('api/v1/detections', DetectionWebhookView.as_view(), name='detections'),

    # Opened from the WhatsApp button; the token is personal to one ONG member and one incident.
    path('api/v1/expedientes/<str:token>', ExpedienteView.as_view(), name='expediente'),
    path('api/v1/eventos/<str:token>', EventoView.as_view(), name='evento'),
    path('api/v1/expedientes/<str:token>/enviar', ExpedienteSendView.as_view(), name='expediente-send'),

    # Called only by the condorin.pe server (shared secret): the ONG panel, the WhatsApp link sign in
    # and the admin live feed.
    path('api/v1/panel', PanelView.as_view(), name='panel'),
    path('api/v1/panel/incidentes/<int:image_id>/expediente', PanelExpedienteView.as_view(), name='panel-expediente'),
    path('api/v1/panel/enlace', LinkSignInView.as_view(), name='panel-link'),
    path('api/v1/panel/actividad', ActivityView.as_view(), name='panel-activity'),
]
