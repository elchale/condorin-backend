"""Run a fake detector delivery through the real pipeline and print each member's expediente link."""
import uuid

from django.core.management.base import BaseCommand
from django.utils import timezone

from detections.serializers import DetectionWebhookSerializer
from detections.services import idempotency_key, ingest


class Command(BaseCommand):
    help = 'Simulate a detector webhook for a river (WhatsApp is only sent if WA_SEND_ENABLED).'

    def add_arguments(self, parser):
        parser.add_argument('--river', default='yaguas')
        parser.add_argument('--lat', type=float, default=-2.7706)
        parser.add_argument('--lon', type=float, default=-70.9512)
        parser.add_argument('--confidence', type=float, default=0.87)

    def handle(self, *args, river, lat, lon, confidence, **options):
        now = timezone.now()
        generation = str(uuid.uuid4().int)[:16]
        stamp = f'{now:%Y-%m-%dT%H%MZ}'
        raw = {
            'image': {
                'bucket': 'river-images', 'object': f'{river}/{stamp}_s1.tif', 'generation': generation,
                'river': river, 'satellite': 'Sentinel-1', 'captured_at': now.isoformat(),
            },
            'model': {'name': 'dredge-detector', 'version': 'v0.3'},
            'detections': [{
                'lat': lat, 'lon': lon, 'confidence': confidence, 'bbox': [412, 318, 14, 9],
                'crop_uri': f'gs://river-images/crops/{river}_{generation}.png',
            }],
        }
        serializer = DetectionWebhookSerializer(data=raw)
        serializer.is_valid(raise_exception=True)
        image, _ = ingest(serializer.validated_data, idempotency_key('', raw['image']), raw=raw)

        self.stdout.write(f'Image {image.pk}: {image}')
        for alert in image.alerts.select_related('member'):
            self.stdout.write(f'  {alert.member} [{alert.status}] {alert.link}')
        if not image.alerts.exists():
            self.stdout.write('  Nobody to alert: add an ONG with members that watches this river in /admin.')
