import json

import pytest
from django.core import signing

from accounts import session
from accounts.models import Member as SiteUser
from ongs.models import Member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _demo(settings):
    settings.DEFAULT_ONG_ID = 0


def post(client, path, data, **headers):
    return client.post(path, json.dumps(data), content_type='application/json', **headers)


def ask_code(client, phone='936282808'):
    return post(client, '/api/v1/auth/codigo', {'phone': phone, 'consent': True})


def code_from(sent):
    phone, template, components = sent[-1]
    assert template == 'condorin_codigo'
    return phone, components[0]['parameters'][0]['text']


def test_happy_path(client, ong, sent):
    resp = ask_code(client, '+51 936 282 808')
    assert resp.status_code == 202
    body = resp.json()
    assert body['phone'] == '51936282808'
    phone, code = code_from(sent)
    assert phone == '51936282808'
    assert code not in body['pending']  # only an HMAC of the code travels

    resp = post(client, '/api/v1/auth/entrar', {'pending': body['pending'], 'code': code})
    assert resp.status_code == 200
    entered = resp.json()
    assert entered['member'] == {'name': 'María Huamán Ríos', 'phone': '51936282808'}
    assert entered['ong'] == {'name': 'Amazonía Viva'}
    user = SiteUser.objects.get(phone='51936282808')
    assert user.consent_at and user.last_sign_in_at

    me = client.get('/api/v1/me', HTTP_AUTHORIZATION=f'Bearer {entered["token"]}')
    assert me.status_code == 200
    assert me.json()['member']['name'] == 'María Huamán Ríos'
    assert set(me.json()) == {'member', 'ong', 'totals', 'incidents'}

    # The same pending value never signs in twice.
    again = post(client, '/api/v1/auth/entrar', {'pending': body['pending'], 'code': code})
    assert again.json()['type'] == 'code_expired'


def test_new_number_joins_the_default_ong(client, ong, sent):
    pending = ask_code(client, '911222333').json()['pending']
    _, code = code_from(sent)
    resp = post(client, '/api/v1/auth/entrar', {'pending': pending, 'code': code})
    assert resp.status_code == 200
    assert Member.objects.get(phone='51911222333').ong == ong


def test_wrong_code_and_attempt_limit(client, ong, sent):
    pending = ask_code(client).json()['pending']
    _, code = code_from(sent)
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(5):
        resp = post(client, '/api/v1/auth/entrar', {'pending': pending, 'code': wrong})
        assert resp.status_code == 400 and resp.json()['type'] == 'code_invalid'
    resp = post(client, '/api/v1/auth/entrar', {'pending': pending, 'code': code})
    assert resp.json()['type'] == 'code_expired'


def test_too_soon(client, ong, sent):
    assert ask_code(client).status_code == 202
    resp = ask_code(client)
    assert resp.status_code == 429
    assert resp.json()['type'] == 'code_too_soon'
    assert len(sent) == 1


def test_expired_pending(client, ong, sent, monkeypatch):
    pending = ask_code(client).json()['pending']
    _, code = code_from(sent)
    monkeypatch.setattr(session, 'CODE_SECONDS', -1)
    resp = post(client, '/api/v1/auth/entrar', {'pending': pending, 'code': code})
    assert resp.status_code == 400 and resp.json()['type'] == 'code_expired'


def test_forged_pending(client, ong):
    forged = signing.TimestampSigner(salt='session').sign_object({'p': '51936282808', 'h': 'x'})
    resp = post(client, '/api/v1/auth/entrar', {'pending': forged, 'code': '123456'})
    assert resp.json()['type'] == 'code_expired'


@pytest.mark.parametrize('data, field', [
    ({'phone': '123', 'consent': True}, 'phone'),
    ({'phone': '936282808'}, 'consent'),
    ({'phone': '936282808', 'consent': 'yes'}, 'consent'),
])
def test_bad_input(client, ong, data, field):
    resp = post(client, '/api/v1/auth/codigo', data)
    assert resp.status_code == 400
    assert field in resp.json()['field_errors']


@pytest.mark.parametrize('header', ['', 'Bearer', 'Bearer nonsense', 'Basic abc',
                                    f'Bearer {signing.TimestampSigner(salt="otp-pending").sign("51936282808")}'])
def test_bad_bearer(client, ong, header):
    headers = {'HTTP_AUTHORIZATION': header} if header else {}
    resp = client.get('/api/v1/me', **headers)
    assert resp.status_code == 401
    assert resp.json()['type'] == 'session_invalid'


def test_expired_session(client, ong, monkeypatch):
    token = session.session_token('51936282808')
    monkeypatch.setattr(session, 'SESSION_SECONDS', -1)
    assert client.get('/api/v1/me', HTTP_AUTHORIZATION=f'Bearer {token}').status_code == 401


def test_me_opens_an_expediente(client, ong, sent, post_detection, payload):
    post_detection(payload)
    token = session.session_token('51936282808')
    image_id = client.get('/api/v1/me', HTTP_AUTHORIZATION=f'Bearer {token}').json()['incidents'][0]['id']
    resp = client.post(f'/api/v1/me/incidentes/{image_id}/expediente', HTTP_AUTHORIZATION=f'Bearer {token}')
    assert resp.status_code == 200 and resp.json()['token']
    assert client.post('/api/v1/me/incidentes/999999/expediente',
                       HTTP_AUTHORIZATION=f'Bearer {token}').status_code == 404


@pytest.mark.parametrize('raw, phone', [
    ('936282808', '51936282808'), ('+51 936-282-808', '51936282808'), ('5491122334455', '5491122334455'),
    ('12345', None), ('', None), (None, None), ('1234567890123456', None),
])
def test_normalize_phone(raw, phone):
    assert session.normalize_phone(raw) == phone
