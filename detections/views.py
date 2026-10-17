from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import authenticate_detector
from .serializers import DetectionWebhookSerializer
from .services import idempotency_key, ingest


class DetectionWebhookView(APIView):
    """POST /api/v1/detections: the detector reports what it found in one scene.

    201 on a new delivery, 200 when the Idempotency-Key was already processed.
    Alerts go out after the response, so the detector never waits on WhatsApp.
    """

    def get_authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when the bearer is missing or wrong.
        return 'Bearer'

    def post(self, request):
        authenticate_detector(request)
        serializer = DetectionWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        key = idempotency_key(request.headers.get('Idempotency-Key', ''), data['image'])
        image, created = ingest(data, key, raw=request.data)
        return Response(
            {
                'id': image.pk,
                'duplicate': not created,
                'detections': image.detections.count(),
                'alerts': image.alerts.count(),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
