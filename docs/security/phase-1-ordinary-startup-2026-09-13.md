# Phase 1 — ordinary-startup validation 2026-09-13

Validation: `2026-09-13T05:50:07.216350+00:00`. Ordinary startup was confirmed; this is not an independent assessment or authorization to merge or publish.

## What was completed

After the owner’s one-time standard approval, the exact command from the instruction was run:

```bash
docker compose run --rm --build web python manage.py migrate --noinput && docker compose up --build
```

The command was run inside Hermes, without an external terminal window, in a separate control copy of the current working tree. Project: `omp-final-20260913t023437z`. It uses the ordinary `postgres` service with its own persistent volume `omp-final-20260913t023437z_postgres_data`, not `postgres-test`.

200 files were copied from the original working tree, and their contents were checked by checksum. Only the published local ports and `APP_BASE_URL` were changed in the copy: site `127.0.0.1:18000`, Mailpit `127.0.0.1:18025`, SMTP `127.0.0.1:11025`. This is the approved arrangement for working alongside the existing stand; simultaneous startup on its occupied ports 8000/8025/1025 is not claimed. The other approved settings matched; application code and `ops/verify_restore.sh` were not changed.

## Confirmed results

- Web and worker runtime images were built from the control copy.
- Initial migrations were applied successfully; the subsequent `migrate --check` with a read-only connection completed with code 0.
- `postgres` and Mailpit have `healthy` status; web and worker are running.
- The application and worker use `DATABASE_HOST=postgres`, run as `appuser`, and are connected only to the project’s separate network.
- `/login/` and `/register/` returned 200 and forms over real HTTP.
- The copy’s mailbox was empty before the tests; published ports are bound only to `127.0.0.1`.
- The original containers were not restarted, and their port bindings were preserved. The emails and table aggregates of the original database matched the original snapshot. The original files and `.env` were unchanged.

The first curl HTTP probe received HTTP 200 but ended with code 23 while writing the response and was not counted as successful. A subsequent independent HTTP request through the Python standard library completed successfully. The probe error is not attributed to the application.

## Result boundaries

The browser pass was not repeated in the new database: [manual acceptance](phase-1-browser-acceptance-2026-09-13.md) remains a separate previously completed piece of evidence. Together with the confirmed ordinary startup, this closes the remaining part of Task 20 Step 5. Later, the [full fresh automated gate passed](phase-1-local-validation-2026-09-13.md), after which only the control copy was stopped, with its persistent volume preserved. A valid independent assessment has not yet been obtained; Task 20 as a whole is not closed.

The `.env` in the control copy is a hard link to the original file, not a new set of keys. It must not be edited, regenerated, or included in archives/attachments. The subsequent automated gate confirmed the absence of `.env` and `.git` in the runtime and test images.

## Evidence

Local Git-ignored directory: `artifacts/final-local-20260913T023437Z/`.

- `ordinary-start.log` — actual build, migration application, and service startup;
- `ordinary-startup-verification.json` — HTTP, containers, network, volume, and limitations;
- `ordinary-migration-check.log` — migration-check output; code 0 is recorded in JSON;
- `preservation-after-startup.json` — preservation of the original stand;
- `preflight.json`, `source-manifest.json`, `isolation-config.json` — setup and isolation boundaries.
