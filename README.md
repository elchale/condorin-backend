# Condorin API

Backend for [condorin.pe](https://condorin.pe), deployed at **api.condorin.pe**. It receives what the
satellite detector finds on Amazon rivers, alerts the ONGs that watch each river by WhatsApp, and helps
them turn that evidence into a denuncia they can file with the Fiscalía and OEFA the same day.

Django 5.2 + DRF on Postgres (Neon), with no task queue. It shares the database with the Next.js app, and Django
owns the schema and every migration (see [Shared database](#shared-database)).

## How it works

```
detector ──POST /api/v1/detections──▶ store scene + detections (idempotent)
                                        │
                                        ▼ after commit, on a thread
                    pin evidence: GCS md5/crc32c of the scene, SHA-256 of each crop
                                        │
                                        ▼
         WhatsApp template condorin_alerta to every member of every ONG that watches the river
         [crop image]  "Hola María, Condorin detectó 1 posible draga en el río Yaguas..."
         [Crear expediente → condorin.pe/expediente/<token>]   [Ver ubicación → Google Maps]
                                        │
                                        ▼ member taps
   condorin.pe/expediente/<token>  ──GET──▶ expediente for (image, ONG), created and prefilled
         member fixes what is missing ──PATCH──▶ autosave; answers remembered for next time
         "Confirmar" ──POST /enviar──▶ WhatsApp code (condorin_codigo) to that member
         code ──POST /enviar──▶ folio CND-2026-00001, final PDF, emailed to the ONG
         files it on the FEMA and OEFA forms, types the receipt number ──PATCH──▶ status filed
```

- **One expediente per image and ONG.** Every member of the ONG who taps the alert opens the same one,
  so two people never file duplicates. Each ONG gets its own.
- **The token is personal** (one per member per image) and expires after `ALERT_LINK_DAYS`. A forwarded
  link can read and edit the draft, but finalizing needs the WhatsApp code sent to that member's phone.
- **Evidence is pinned.** The scene is referenced by `gs://bucket/object#generation`, an immutable
  version, together with GCS's own MD5 and CRC32C. Each crop gets a SHA-256. All of it goes in the PDF annexes, and
  the PDF's own SHA-256 goes in the email. Links shown to the user are V4 signed URLs for that exact version.
- **The PDF** follows what NCPP art. 328 and DAR's 2025 guide ask for: denunciante, numbered hechos
  (drafted by Condorin), ubicación in WGS84 and UTM, presuntos responsables, fundamentos (CP 307-A/B,
  DL 1100, Ley 26834 inside a protected area), medios probatorios, petitorio (constatación fiscal,
  interdicción) and a signature block. Annexes include the crops, scene custody data, earlier detections within
  3 km and the Copernicus credit. Drafts carry a BORRADOR watermark.
- **Where it is filed.** FEMA (Ministerio Público, Denuncias en línea) is the main route because illegal mining is a crime.
  OEFA (Servicio Nacional de Denuncias Ambientales, which replaced SINADA in May 2026) leaves an administrative record.
  SERNANP is added when the river is inside a protected area. None of them publishes an email for
  complaints, so the PDF is emailed to the ONG with step by step links. An authority gets it by email
  only if an admin enters a confirmed address.

## API

Ten routes in total: three for the expediente, four for the condorin.pe server, the webhook, and the pages.

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/api/v1/detections` | detector | `Authorization: Bearer <Google ID token or shared secret>`, `Idempotency-Key`. 201 new, 200 duplicate. |
| GET | `/api/v1/expedientes/<token>` | ONG member | Opens (and on first tap creates) the expediente, with everything the page needs. `?formato=pdf` returns the PDF. |
| PATCH | `/api/v1/expedientes/<token>` | ONG member | Any subset of the fields (autosave), `authorities: [codes]`, `filings: [{authority, receipt_number, filed_at}]`, `reopen: true`. |
| POST | `/api/v1/expedientes/<token>/enviar` | ONG member | `{}` checks completeness and sends the code (202). `{"code": "123456"}` finalizes and emails (200). |
| GET | `/api/v1/panel` | condorin.pe server | `Authorization: Bearer <PANEL_API_SECRET>`, `X-Condorin-Phone`. The member, their ONG and its incidents with the next action. Joins the default ONG on first call (demo only). |
| POST | `/api/v1/panel/incidentes/<id>/expediente` | condorin.pe server | Same headers. The member's personal expediente token for that incident, created if they had no alert. |
| POST | `/api/v1/panel/enlace` | condorin.pe server | `{"token"}` → the member a WhatsApp alert link may sign in (sent, under `LINK_SIGN_IN_DAYS`), else 404. |
| GET | `/api/v1/panel/actividad?limit=N` | condorin.pe server | Secret only, no phone. The admin live feed: the last N scenes received (default 20, max 50), newest first, each with its detections, the ONGs that watch the river, their alerts and expediente, and the 8 decision steps (contract in `condorin/src/lib/admin/activity.ts`). |
| GET | `/` and `/healthz/` | anyone | Landing page with the logo; liveness probe. |
| | `/admin/` | staff | ONGs, members, rivers, authorities, detections, alerts, expedientes. |

Errors always come back as `{"message", "type", "field_errors"}`. With a 400 from `/enviar`,
`field_errors` lists exactly what is still missing, so the page can jump to it. Error `type`s the page
should handle: `link_expired` (410), `code_invalid`, `code_expired`, `code_too_soon` (429),
`expediente_locked` (409), `whatsapp_error` (502).

The frontend is connected: condorin.pe/expediente/<token> calls these routes through its own `/api/expedientes` proxy,
and condorin.pe/panel uses the panel routes. The screens are in [`docs/EXPEDIENTE_UX.md`](docs/EXPEDIENTE_UX.md).

### Signing in from the WhatsApp link

The alert button opens condorin.pe/expediente/<token> and the member is signed in without a code:

- The token is 192 random bits, one per member and image, and only reached that member's WhatsApp chat.
- The browser posts it to condorin.pe/api/enlace (link preview bots do not run JS, so they never sign in).
  That route checks the origin and asks `/api/v1/panel/enlace` with the shared secret. Only alerts WhatsApp
  delivered, within `LINK_SIGN_IN_DAYS` (7) of delivery, sign in. Anything else gets the same 404.
- The session lasts 7 days (30 with a code), and an existing session is never replaced by a link.
- The page sends `Referrer-Policy: no-referrer` and is not indexed. Confirming the denuncia still needs a fresh WhatsApp code.

### Evidence and PDFs in Cloud Storage

The service account in `GCS_CREDENTIALS_JSON` reads the scenes and crops the detector writes (to pin hashes
and sign links) and creates objects in `GCS_EXPEDIENTES_BUCKET`, where each final PDF is archived as
`expedientes/<year>/<folio>-<sha256 prefix>.pdf`, never overwritten. The database keeps its own copy,
so a failed upload never blocks a denuncia.

## Local setup

```bash
py -3.13 -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
cp .env.template .env      # fill in the values (DATABASE_URL is the Neon database)
python manage.py migrate   # also seeds FEMA, OEFA, SERNANP and the río Yaguas
python manage.py runserver
```

In `/admin`, create an ONG, tick the rivers it watches, and add its members (name and WhatsApp
number). Then:

```bash
python manage.py simulate_detection --river yaguas   # runs the real pipeline, prints each member's link
python manage.py send_pending_alerts                 # retries alerts that failed (cron or by hand)
python manage.py create_alert_template               # prints the WhatsApp template; --submit sends it to Meta
pytest
ruff check .
```

Without `WA_TOKEN`, WhatsApp messages are logged instead of sent. Without GCS credentials, the
evidence still records the URIs, but the hashes and signed links stay empty.

## Shared database

The Next.js app and this API use the same Neon database, and **Django owns the schema**: every table,
including the two the frontend uses, is created by `python manage.py migrate` here. The `accounts` app
holds those two tables: `accounts_member` (people who signed in on condorin.pe with WhatsApp) and
`accounts_admin` (Google accounts allowed into condorin.pe/admin). Columns the frontend inserts without
a value have database defaults (`db_default`), because Prisma does not run Django's Python defaults.
`condorin/prisma/schema.prisma` only maps onto these tables, and Prisma never migrates. When a migration
changes them, update that mapping and run `npx prisma generate`.

`manage.py import_prisma_backup <file.json>` loads admins and members from a JSON backup of the old
Prisma tables. That is how the users were carried over on 2026-10-17. The backup stays outside the repo.

Tests never touch production rows. pytest creates a separate `test_condorin` database on the same
server and drops it at the end.

## Deploy

Either platform works. Whichever serves `api.condorin.pe`, set the variables from `.env.template` and,
before the first real alert:

1. Submit the `condorin_alerta` template (`create_alert_template --submit`) and wait for Meta to approve it.
2. Give the GCS service account `storage.objects.get` on the detector buckets. It needs a key to sign links.
3. Configure the detector: an OIDC token with audience `https://api.condorin.pe/api/v1/detections` from a
   service account listed in `DETECTIONS_ALLOWED_SERVICE_ACCOUNTS`, or the shared secret.

### Railway

`railway.json` builds with Nixpacks (`build_scripts/build.sh`), migrates on start, and runs gunicorn with
threads. The health check is `/healthz/`.

### Cloud Run

The `Dockerfile` builds the image (`.dockerignore` keeps `.env` out of it), the entrypoint migrates
unless `RUN_MIGRATIONS=0`, and gunicorn listens on the `$PORT` Cloud Run injects.

```bash
REGION=us-central1
# Secrets go in Secret Manager; the service account needs roles/secretmanager.secretAccessor.
for s in DJANGO_SECRET_KEY DATABASE_URL WA_TOKEN DETECTIONS_SHARED_SECRET GCS_CREDENTIALS_JSON EMAIL_HOST_PASSWORD; do
  printf '%s' "<value>" | gcloud secrets create $s --data-file=-
done

gcloud run deploy condorin-api --source . --region $REGION --allow-unauthenticated \
  --no-cpu-throttling --min-instances 1 --max-instances 3 --memory 1Gi --cpu 1 --timeout 60 \
  --set-env-vars DOMAIN=api.condorin.pe,EXTRA_ALLOWED_HOSTS=.run.app,FRONTEND_URL=https://condorin.pe,WA_PHONE_NUMBER_ID=<id>,WA_WABA_ID=<id>,GCS_PROJECT_ID=<project>,DETECTIONS_ALLOWED_SERVICE_ACCOUNTS=<sa> \
  --set-secrets DJANGO_SECRET_KEY=DJANGO_SECRET_KEY:latest,DATABASE_URL=DATABASE_URL:latest,WA_TOKEN=WA_TOKEN:latest,DETECTIONS_SHARED_SECRET=DETECTIONS_SHARED_SECRET:latest,GCS_CREDENTIALS_JSON=GCS_CREDENTIALS_JSON:latest,EMAIL_HOST_PASSWORD=EMAIL_HOST_PASSWORD:latest
```

- **Continuous deploy**: after the first deploy, every push to `main` that passes Ruff and pytest ships
  through the `deploy` job in `.github/workflows/ci.yml`. It builds the image, pushes it to Artifact
  Registry and points the service at it, so env vars and secrets set on the service are kept. GitHub signs
  in as the `github-deployer` service account, whose JSON key is the `GCP_SA_KEY` repository secret. It
  only holds `roles/run.developer`, `roles/artifactregistry.writer` on the repository and
  `roles/iam.serviceAccountUser` on the runtime service account.
- **`--no-cpu-throttling` is required.** Alerts go out on a thread after the webhook responds, and by
  default Cloud Run stops giving CPU to an instance once its response is sent. `--min-instances 1` keeps
  one warm, and 1Gi leaves room for two workers rendering PDFs.
- **`--allow-unauthenticated`**: the browser and the detector call the API directly; Django checks the
  link token and the webhook bearer.
- **`GCS_CREDENTIALS_JSON` is still needed.** Cloud Run's default credentials hold no private key, so they
  cannot sign the evidence links.
- **Retries**: create a Cloud Run job from the same image running `python manage.py send_pending_alerts`
  and trigger it from Cloud Scheduler (every 15 minutes, say). With more than one instance, run
  migrations the same way (a job running `python manage.py migrate`) and set `RUN_MIGRATIONS=0` on the service.
- **Domain**: `gcloud beta run domain-mappings create --service condorin-api --domain api.condorin.pe --region $REGION`,
  then add the DNS records it prints. Not every region supports domain mappings.
- **Vercel**: the frontend calls `https://api.condorin.pe` (or the `run.app` URL until the domain is live).
  To allow preview deployments, set `CORS_ALLOWED_ORIGIN_REGEXES` to something like
  `^https://condorin-[a-z0-9-]+\.vercel\.app$`. Lists containing commas need gcloud's custom delimiter,
  e.g. `--set-env-vars "^;^ADDITIONAL_CORS_ORIGINS=a,b;DOMAIN=api.condorin.pe"`.
