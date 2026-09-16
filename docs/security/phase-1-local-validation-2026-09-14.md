# Phase 1 — validation after R-01/R-03/R-05, 2026-09-14

**The full application suite passed: 411/411. Final validation of the entire phase is NOT complete: a separate first-startup instruction failure, VAL-001, was found.**

This is local validation, not a new independent assessment and not authorization for commit, push, merge, publication, or closure of Task 20.

## Scope and isolation

- The `task20-phase1-completion` working tree was checked after the approved R-01, R-03, and R-05 changes, together with the earlier uncommitted changes.
- A separate copy of 202 tracked/new non-ignored files was created. Application code, tests, dependencies, README, and the restoration script were not fixed.
- Docker project: `omp-post-review-20260913t220613z`. Only its own `postgres-test` and Mailpit, plus one-time validation containers, were run.
- The test PostgreSQL data was in `tmpfs`; the database port was not published. The tests did not connect to the old database or mail. The persistent store and manual Chrome acceptance were not run again.
- The main suite used a separate private copy of the existing working `.env`, not a hard link. Working values were not printed or changed. This is validation with ready-made settings, not evidence that their initial generation works.
- Only three loopback port bindings were changed in the copy’s `compose.yaml`: 18000/18025/11025. The ordinary web server was not run in this pass; its port is not evidence of a working site.

## What actually passed

- Runtime and test images were built, exit code 0.
- `makemigrations --check --dry-run`: `No changes detected`, code 0.
- `migrate --noinput` and `migrate --check`: code 0.
- `check --deploy` with the ready working environment: only four expected local-HTTP warnings — `security.W004`, `security.W008`, `security.W012`, `security.W016`. They must not be carried into a published configuration without separate HTTPS configuration.
- `lint-imports --no-cache`: **11 kept, 0 broken**.
- Full `open_marketplace` suite: **Ran 411 tests in 186.669s**, **OK**, code 0. There were no errors, failed tests, or skips.
- **411 unique successful test identifiers** were matched against the full log, not only the final counter line.
- All **17** scenarios from `test_full_flows.py`, **8** migration checks, and **5** phase-boundary checks passed within 411. Their names were extracted from the actual source. These groups are not added to 411 again.
- **39** related invitation/sensitive-link checks covering R-01/R-03/R-05 and `test_cookie_security_defaults_and_secure_mode` passed within the full suite.
- All **202 files** in the snapshot were checked byte-for-byte by checksum in both images. There were no mismatches; `/app/.env` and `/app/.git` are absent; the validation-process UID is 10001, not root.
- A limited search for the specified private-key patterns and non-empty assignments of the six project secrets in the 202 source files found no matches. `.env` is Git-ignored and untracked. This is not a universal guarantee that all secrets are absent.
- `git diff --check` and `bash -n ops/verify_restore.sh` passed before the run; final documents were checked separately.

Full-suite command run from the isolated-copy directory:

```bash
docker compose -p omp-post-review-20260913t220613z -f compose.yaml -f compose.test.yaml run --rm --no-deps --pull never -T test python manage.py test open_marketplace --noinput --verbosity 2
```

## VAL-001 — first-startup instruction failure, OPEN

**Priority:** medium, functional first-startup blocker; this is not a discovered security bypass. **Fix owner:** project maintainer. The fix was not separately approved or implemented.

### Actual reproduction

1. The generator code published in the unchanged `README.md:24–46` was taken exactly as written, without substituting any of its lines.
2. It was run in a new empty directory with a copy of `.env.example`. A new separate test `.env` was created; working keys were not used or overwritten in this validation.
3. A real newly built runtime image was started with this file through `docker run --rm --network none --env-file ... python manage.py check --deploy`.
4. Result — **code 1**, **`RuntimeError: THROTTLE_HASH_KEY is invalid`**. The application stops while loading settings, before checking the database connection. Key values were not printed.

### Confirmed cause

`README.md:36` uses `secrets.token_urlsafe(32)` for `THROTTLE_HASH_KEY`. The resulting value has 43 characters and lacks trailing Base64 padding. `open_marketplace/config/settings.py:18–24,34–38,189` requires strict Base64 decoding and at least 32 decoded bytes. Checking the actually generated value with the same decoder returned **`Incorrect padding`**. The value itself was not retained in the report.

Thus, the ready working environment passes the tests, while one newly created according to the README is rejected by the application. The success of 411 tests does not remove this separate defect in the instruction. The generation format in the instruction must be fixed, rather than weakening the key check in the application or replacing the existing database keys.

## What is not complete

After VAL-001 was confirmed, the remaining final-gate stages were stopped under the Task 20 rule for a discovered defect. The full suite that had already started was allowed to finish.

- **The real `ops/verify_restore.sh` was not run after R-01/R-03/R-05 in this pass.**
- Scenario No. 17 within 411 checks the restoration-command contract and does not replace a real `pg_dump`/`pg_restore`.
- No separate additional run of the five scope tests was performed; all five passed within the full suite.
- The successful actual restoration from 2026-09-13 remains a historical result of the [previous run](phase-1-local-validation-2026-09-13.md), not new evidence for this snapshot.
- The first phase, Task 20, and the PR are not closed. Separate approval of the VAL-001 fix and completion of the full gate afterward are required. Git and publication remain unauthorized.

## Relation to previous results

- R-01: explanation to a logged-in user when an invitation is rejected; previously 37/37 target tests.
- R-03: hint only during a live retry of incomplete setup for a new service account; previously 39/39 related tests.
- R-05: check of real POST requests for one form — two methods, eight variants; previously 23/23 related tests. A real HTTPS server was not run for this.
- All these sources are present in the fresh snapshot that passed 411/411.
- One approved independent static pass, `omp-phase1-review-20260913t102350z`, previously returned `APPROVE` with comments. R-02/R-06 were rejected as proposed; cosmetic R-04 was not fixed. Additional hypotheses are not declared proven vulnerabilities.
- This independent pass was **before** the R-01/R-03/R-05 fixes, not a new check of the changed code. No new reviewer or paid calls were run. The earlier `APPROVE` does not cancel VAL-001.
- The 10/10 manual Chrome acceptance and ordinary startup with a persistent database from 2026-09-13 retain their historical scope; there was no repeat manual acceptance here.

## Preservation and shutdown

Shutdown check: `2026-09-13T22:21:38.471998+00:00` (UTC, already 2026-09-14 local time).

- Only two new containers of `omp-post-review-20260913t220613z` were stopped: test PostgreSQL and Mailpit. No containers of this project are running; general Docker cleanup and removal of previous resources were not performed.
- 12 previous containers were cross-checked by exact ID: their states, times, images, storage and port attachments, and network mode matched the original snapshot. The old store was not started or restored.
- Before the final documents were written, all 202 source files and the working `.env` matched their initial checksums. After the run, only the current summary documents and the new report changed, not the application or README.
- The source snapshot in the copy and its private `.env` remained unchanged. Checking 12 logs against known key values from the working and trial environments found no matches; the values themselves are not included in the result.
- Shutting down the temporary `tmpfs` database is not a backup. This pass does not assert preservation of the old temporary manual database.

## Evidence

Local Git-ignored directory: `artifacts/post-review-local-20260913T220613Z/`.

- `preflight.json`, `gate-source-manifest.json`, `isolation-check.json` — scope, snapshot, and isolation;
- `command-results.json`, `gate-build.log`, `test-infrastructure.log` — commands, codes, and setup;
- `makemigrations.log`, `migrate.log`, `migrate-check.log`, `check-deploy.log`, `import-linter.log`;
- `full-suite.log`, `full-suite-verification.json`, `expected-test-groups.json`;
- `repository-secrecy.json`, `image-verification.json`, `web-image-check.log`, `test-image-check.log`;
- `documented-env-probe.log`, `documented-env-verification.json`, `documented-env-root-cause.json` — actual reproduction of VAL-001;
- `copy-stop.log`, `copy-stop-verification.json`, `final-verification.json` — shutdown and preservation.

**Do not archive the evidence directory in its entirety:** `source/.env` contains a private copy of working keys, while `documented-env-probe/.env` contains new one-time test keys. Only this report, without environment files, is intended for sharing.
