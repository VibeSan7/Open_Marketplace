# Updated presentation validation

Validated: 2026-09-16T01:03:27.541575+00:00. Branch: `ui/presentation`, base: `5679b7a72476d1711702e518bd39421aaf69a306`.

## Scope

The global header, navigation, catalog, product pages, login and registration forms, security pages, seller dashboard, and staff panel were updated. System fonts and local CSS files are used; no new libraries, external fonts, or third-party resources were added.

Only browser tests were changed in the Python code. Application rules, roles, migrations, fields and form actions, search, and product publication were not changed. Existing English labels were not translated in full. This remains a catalog without orders or payments.

## Checks

- Full suite: **507 tests, OK**, 402.568 seconds, with no skips.
- Live Chromium: **120 checks** — 117 renderings of 39 role-and-viewport combinations at widths 320, 390, and 1440 px, plus 3 access-denial checks.
- Guest, buyer, both sellers, administrator, and reviewer were checked. Checks ran in separate temporary browser contexts with sessions for existing test accounts only. Passwords and two-step-login keys were not read or changed; temporary sessions were revoked and their browser keys deleted.
- There was no horizontal page overflow, broken images, duplicate main headings, or unhandled JavaScript exceptions in the checked states. Fields, buttons, and select lists in the main area are at least 44 px high.
- Keyboard navigation to content, filters, result loading, return to the results, photo recovery after an error, seller publication, and access revocation were checked.
- Django checks — no issues; `makemigrations --check --dry-run` — no changes; dependency checks — 12 satisfied, 0 violated; JavaScript syntax and `git diff --check` — successful.
- All 35 project templates were compiled. The 227 application files in the running image matched the working copy byte-for-byte.

## Installation preservation

Checksums of catalog records, seller applications, access assignments and accounts, as well as 10 image files, matched before and after the update. Technical logs and temporary sessions are not part of this business-data fingerprint.

The web component was replaced without removing storage or changing installation settings. The binding remains `127.0.0.1:8000`; there is no public hosting. The image contains no `.env`, `.git`, `artifacts`, or `backups`.

Current image: `sha256:24254822838608e7870c4d0da8bc025b227daa71fbfa72e28ab45634e094b732`.
The previous image was preserved as `open-marketplace:before-presentation-20260916003442` for local rollback.

## Fixes found by the checks

1. The new logout form in the global header added a random CSRF token to neutral error pages. The form was removed from the global header; the existing logout in the security section and POST-request protection were preserved. The check for identical responses to another user’s and a nonexistent application was not weakened.
2. The base Django admin template and child pages both rendered the main heading. The duplicates were removed from the child templates, and a browser check was added.

## Local evidence

In `artifacts/presentation/`: `accepted-suite.log`, `accepted-structural-checks.log`, `live-browser-checks.json`, `state-before.json`, `state-after.json`, `qa-session-cleanup.json`, `image-manifest.json`, and screenshots. The directory is excluded from Git and the Docker image. `README-UI-RU.md` contains the exact commands for switching the presentation and returning to the previous image.

The standard Hermes browser tool did not respond; live validation was performed through the Chromium already installed in the test Docker image. No new tools were installed. A GitHub release was not replaced by this local update.
