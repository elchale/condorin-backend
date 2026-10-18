"""Settings for pytest. Same Postgres server as DATABASE_URL, but Django creates a separate
`test_condorin` database for the run and drops it after, so production rows are never touched.
Nothing goes out: WhatsApp is logged, email stays in memory, GCS is off."""
from backend.settings import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = False
WA_SEND_ENABLED = False
ALERTS_INLINE = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
GCS_CREDENTIALS_JSON = ''
GCS_EXPEDIENTES_BUCKET = ''
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
