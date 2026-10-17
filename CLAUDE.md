# CLAUDE.md

Condorin API (api.condorin.pe). Read README.md first. It has the flow, the routes and the setup.

## Layout
- `backend/settings/`: `common.py` (Django, DB, DRF, security), `integrations.py` (webhook auth, WhatsApp, GCS, email).
- `core/`: `BaseModel`, the error envelope (`exceptions.py`), middleware, the landing page, plus `gcs.py`, `whatsapp.py`, `geo.py` (UTM).
- `ongs/`: `River` (the slug matches `image.river` in the webhook), `Ong`, `Member`.
- `detections/`: the webhook (`views.py`, `auth.py`, `serializers.py`), `services.py` (ingest, pin evidence, send alerts), and `text.py` (the WhatsApp template wording and definition).
- `expedientes/`: `Authority`, `Expediente`, `Filing`; `services.py` (open, update, finalize), `drafting.py` (the hechos text), `pdf.py`, `codes.py` (the WhatsApp code), `mailer.py`.

## Rules
- Keep the API small: three product routes. Do not add endpoints for the dashboard yet.
- No task queue (no Redis or broker). Background work is `transaction.on_commit` plus a thread (`detections.services.dispatch`); retries go through `manage.py send_pending_alerts`.
- No dashes as punctuation in any copy users see (WhatsApp, PDF, email, landing). Legal names like "307-A" are fine.
- The repo is public: no secrets, keep `.env.template` and the README current.
- The WhatsApp body in `detections/text.py` must match the approved template exactly. Changing it means submitting a new template.
- Tests: `pytest` (offline: GCS is unreachable and WhatsApp is captured, see `conftest.py`). Lint: `ruff check .`.
