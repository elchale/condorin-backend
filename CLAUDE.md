# CLAUDE.md

Ojo de Cóndor API (api.condorin.pe). Read README.md first. It has the flow, the routes and the setup.

## Layout
- `backend/settings/`: `common.py` (Django, DB, DRF, security), `integrations.py` (webhook auth, WhatsApp, GCS, email).
- `core/`: `BaseModel`, the error envelope (`exceptions.py`), middleware, the landing page, plus `gcs.py`, `whatsapp.py`, `geo.py` (UTM).
- `ongs/`: `River` (the slug matches `image.river` in the webhook), `Ong`, `Member`.
- `detections/`: the webhook (`views.py`, `auth.py`, `serializers.py`), `services.py` (ingest, pin evidence, send alerts), and `text.py` (the WhatsApp template wording and definition).
- `expedientes/`: `Authority`, `Expediente`, `Filing`; `services.py` (open, update, finalize, archive the PDF in GCS), `drafting.py` (the hechos text), `pdf.py`, `codes.py` (the WhatsApp code), `mailer.py`.
- `panel/`: routes only the condorin.pe server calls (shared `PANEL_API_SECRET`): the ONG panel, opening an expediente from it, and the WhatsApp link sign in.

## Rules
- Keep the API small. The panel routes serve the member panel on condorin.pe; the time replay dashboard still has no endpoints.
- Demo shortcut: everyone who signs in on condorin.pe joins the default ONG (`panel.services.default_ong`, marked TODO). Replace with real invitations after the demo.
- No task queue (no Redis or broker). Background work is `transaction.on_commit` plus a thread (`detections.services.dispatch`); retries go through `manage.py send_pending_alerts`.
- No dashes as punctuation in any copy users see (WhatsApp, PDF, email, landing). Legal names like "307-A" are fine.
- The repo is public: no secrets, keep `.env.template` and the README current.
- The WhatsApp body in `detections/text.py` must match the approved template exactly. Changing it means submitting a new template.
- Tests: `pytest` (offline: GCS is unreachable and WhatsApp is captured, see `conftest.py`). Lint: `ruff check .`.
