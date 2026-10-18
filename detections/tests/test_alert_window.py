"""Who a webhook delivery alerts, and when: recent scenes only, ONG members plus admins with a phone."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import Admin
from detections.models import Alert, SatelliteImage
from ongs.models import Ong, River

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def week_window(settings):
    settings.ALERT_RECENT_DAYS = 7


@pytest.fixture
def admins(db):
    Admin.objects.create(email='carlos@example.org', name='Carlos', phone='51900000001')
    Admin.objects.create(email='nophone@example.org', name='Sin Teléfono')
    Admin.objects.create(email='gone@example.org', name='Inactivo', phone='51900000003', active=False)


def captured(days_ago: float) -> str:
    return (timezone.now() - timedelta(days=days_ago)).isoformat()


def test_recent_scene_alerts_members_and_admins(post_detection, payload, ong, admins, sent):
    payload['image']['captured_at'] = captured(1)
    resp = post_detection(payload)

    assert resp.status_code == 201
    assert resp.json()['alerted'] is True and resp.json()['reason'] == 'alerted'
    # Two ONG members and the one active admin with a phone; the admin without a phone is skipped.
    assert {phone for phone, _, _ in sent} == {'51936282808', '51999888777', '51900000001'}
    assert all(template == 'condorin_evento_v2' for _, template, _ in sent)
    admin_alert = Alert.objects.get(member__phone='51900000001')
    assert admin_alert.member.ong.internal and admin_alert.status == Alert.Status.SENT
    assert len({a.token for a in Alert.objects.all()}) == 3  # each recipient has a personal token


def test_old_scene_alerts_nobody(post_detection, payload, ong, admins, sent):
    payload['image']['captured_at'] = captured(30)
    resp = post_detection(payload)

    assert resp.status_code == 201
    assert resp.json()['alerted'] is False and resp.json()['reason'] == 'old_scene'
    assert SatelliteImage.objects.count() == 1  # still stored, still on the map
    assert not Alert.objects.exists() and not sent


def test_admin_without_phone_is_skipped(post_detection, payload, sent):
    Admin.objects.create(email='nophone@example.org', name='Sin Teléfono')
    payload['image']['captured_at'] = captured(0)
    resp = post_detection(payload)

    assert resp.json()['reason'] == 'no_recipients'
    assert not sent


def test_admin_in_a_watching_ong_gets_one_message(post_detection, payload, ong, sent):
    Admin.objects.create(email='maria@example.org', name='María', phone='51936282808')
    payload['image']['captured_at'] = captured(0)
    post_detection(payload)

    assert sorted(phone for phone, _, _ in sent) == ['51936282808', '51999888777']


def test_simulated_payload_alerts_nobody(post_detection, payload, ong, sent):
    payload['image']['captured_at'] = captured(0)
    payload['simulated'] = True
    assert post_detection(payload).json()['reason'] == 'simulated'
    assert not sent


def test_retry_picks_up_a_failed_alert(post_detection, payload, ong, admins, sent, monkeypatch):
    from core import whatsapp

    payload['image']['captured_at'] = captured(0)

    def down(phone, name, components):
        raise whatsapp.WhatsAppError('Meta is down')

    real = whatsapp.send_template
    monkeypatch.setattr(whatsapp, 'send_template', down)
    post_detection(payload)
    assert Alert.objects.filter(status=Alert.Status.FAILED).count() == 3

    monkeypatch.setattr(whatsapp, 'send_template', real)
    call_command('send_pending_alerts')
    assert Alert.objects.filter(status=Alert.Status.SENT).count() == 3
    assert len(sent) == 3


def test_new_river_is_watched_by_the_internal_team(post_detection, payload, admins, sent):
    payload['image']['captured_at'] = captured(0)
    post_detection(payload)  # creates the internal team
    team = Ong.objects.get(internal=True)

    river = River.objects.create(slug='nanay', name='Nanay')
    assert team.rivers.filter(pk=river.pk).exists()


def test_new_member_gets_no_old_alert(client, payload, ong, sent, settings, post_detection):
    from panel.services import member_for_phone

    payload['image']['captured_at'] = captured(30)
    post_detection(payload)
    member, joined = member_for_phone('51955555555')
    assert joined and not member.alerts.exists() and not sent
