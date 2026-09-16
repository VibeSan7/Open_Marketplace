# Phase 1 — full local run after VAL-001, 2026-09-14

**VAL-001 fixed. The entire approved local validation set after R-01/R-03/R-05 and the README fix passed, including actual restoration of the test PostgreSQL database.**

This is not authorization for commit, push, merge, publication, or automatic closure of Task 20. No new independent reviewing model was run.

## What was fixed

One line of the `THROTTLE_HASH_KEY` generator was changed in `README.md:36`:

```python
    "THROTTLE_HASH_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
```

The new method preserves the required Base64 padding, the encoding format for the key’s random bytes. The previous `secrets.token_urlsafe(32)` removed the padding, so the application’s strict check rejected the result. Each key still receives separate random bytes.

- README change — **+1/−1 line**, all other bytes preserved.
- Application code, test code, key validation, dependencies, and the restoration script **were not changed**.
- The working `.env` was not replaced, regenerated, or copied to a new stand. Existing database keys were not changed.
- After validation, only the current summary documents were updated. The previous [VAL-001 failure report](phase-1-local-validation-2026-09-14.md) was retained as historical.

## Checking the instruction itself

1. The previous real RED was preserved: the runtime exited with code 1 and `THROTTLE_HASH_KEY is invalid`. Before the fix, checksums confirmed an exact match between the README and the runtime source in the failed snapshot. The old run is not being claimed as a repeat here.
2. The complete fixed Python block was extracted directly from the README and run in a new empty directory with `.env.example`. Key values were not printed.
3. The new key passed the strict decoder: **44 encoded characters, 32 decoded bytes**. The key itself is not included in the report.
4. A real newly built runtime with the new settings file, without network access (`--network none`), ran `check --deploy` with **code 0**. Only the four documented local HTTP warnings remained.
5. A repeat run of the generator refused to overwrite the already created `.env` (`FileExistsError`). The file checksum did not change.
6. This exact new environment, without content changes, was used for the entire full suite and actual database restoration. This was not validation with old pre-generated keys.

## Fresh results

Docker project: `omp-val001-20260913t230642z`. The isolated copy contained **203 files** from the current `task20-phase1-completion` working tree, including the earlier uncommitted R-01/R-03/R-05 changes. The fixed README was included in both images before the tests ran.

- Runtime and test images built: code 0.
- `makemigrations --check --dry-run`: `No changes detected`, code 0.
- `migrate --noinput` and `migrate --check`: code 0.
- `check --deploy`: only `security.W004`, `security.W008`, `security.W012`, `security.W016`; there were no other warnings. This is local HTTP mode, not a publication configuration. The secure-mode enablement test also passed.
- `lint-imports --no-cache`: **11 kept, 0 broken**.
- Full suite: **Ran 411 tests in 191.294s**, **OK**, code 0. **There were no errors, failed tests, or skips.**
- **411 unique successful test identifiers** were cross-checked against the full log, not only the final counter line.
- Within 411, **17 core scenarios**, **8 migration checks**, **5 phase-boundary checks**, and **39 related invitation/sensitive-link checks** covering R-01/R-03/R-05 passed. These groups are not counted again in the total.
- Separate additional run of `test_scope_boundaries.py`: **5/5**, code 0. This repeats the same group; they are not new unique tests.
- Checksums of all **203 files** matched the snapshot in both images; `/app/.env` and `/app/.git` are absent, and the validation-process UID is 10001, not root.
- A limited search for the specified private-key patterns and non-empty assignments of the six project secrets found no matches; `.env` is Git-ignored and untracked. This is not a universal guarantee that all secrets are absent.
- `git diff --check` and `bash -n ops/verify_restore.sh`: code 0. Final documents were checked separately.

Full-suite command run from the copy directory:

```bash
docker compose -p omp-val001-20260913t230642z -f compose.yaml -f compose.test.yaml run --rm --no-deps --pull never -T test python manage.py test open_marketplace --noinput --verbosity 2
```

## Actual restoration

The standard unchanged script was run:

```bash
COMPOSE_PROJECT_NAME=omp-val001-20260913t230642z bash ops/verify_restore.sh
```

**Exit code 0.** Separate temporary source and target databases were created in a new `postgres-test`; real `pg_dump` and `pg_restore` were run. Scenario No. 17 checks only the command contract and does not substitute for this separate run.

- **9 named consistency checks** passed and **9 final migrations** were checked in both databases.
- The pre- and post-restoration result sections matched completely, including test-record identifiers.
- Checks of the source and restored databases ran in write-prohibited mode.
- A separate read-only query **before PostgreSQL shutdown** confirmed the absence of temporary `restore_source_*` and `restore_target_*` databases.
- Temporary dumps and partial reports are absent. The validation result was preserved.

This is evidence of restoring a one-time test database, **not** a backup policy for the production system and not restoration of the previous manual stand.

## Preservation and shutdown

Shutdown check: `2026-09-13T23:23:10.799352+00:00` (UTC, 2026-09-14 local time).

- Only the project’s own `postgres-test`, Mailpit, and one-time validation containers were run. The database port was not published; the old database and mail were not used.
- Only three loopback bindings, 18000/18025/11025, differ in the copy’s `compose.yaml`. The ordinary web server and manual browser acceptance were not run here.
- Only two new service containers were stopped. No project containers are running; general Docker cleanup and removal of previous resources were not performed.
- **14 previous containers** were cross-checked by exact ID: their states, times, restart counts, images, storage, port bindings, and network mode did not change.
- Before the reports were updated, the only source change was one README line. The application and tests are unchanged. After the run, only the recording of results changes, not the code or commands.
- The working `.env`, the new test environment throughout the gate, and the original copy snapshot were unchanged. Git `HEAD` was preserved; there were no commits or publication.
- **16 logs** were checked against known key values from the new test environment; there were no matches. The values were not printed in the report.
- The temporary `tmpfs` database is not intended to persist after shutdown. This result does not claim that old data or mail was restored.

## Current result

**VAL-001 is closed within the approved scope. The full approved local gate is complete**, including actual restoration after R-01/R-03/R-05 and VAL-001.

The 10/10 manual Chrome acceptance and ordinary startup with a persistent database from 2026-09-13 remain separate historical evidence. The only approved independent static review occurred before the subsequent fixes and is not presented as a new check of this version. Paid models were not run in this step.

**Task 20 Step 7, final recording in Git, and the owner’s decision to complete the first phase remain separate.** Merge, publication, and the production server were not touched.

## Evidence

Local Git-ignored directory: `artifacts/val-001-final-local-20260913T230642Z/`.

- `preflight.json`, `README-before.md`, `readme-only.diff`, `red-evidence.json`;
- `generator-verification.json`, `generator-green.log`;
- `gate-source-manifest.json`, `isolation-check.json`, `command-results.json`;
- `gate-build.log`, `test-infrastructure.log`, `makemigrations.log`, `migrate.log`, `migrate-check.log`, `check-deploy.log`, `import-linter.log`;
- `full-suite.log`, `full-suite-verification.json`, `expected-test-groups.json`;
- `scope-suite.log`, `scope-suite-verification.json`;
- `repository-secrecy.json`, `image-verification.json`, `web-image-check.log`, `test-image-check.log`;
- `restore.log`, `restore-result.txt`, `restore-verification.json`, `restore-database-cleanup.log`;
- `copy-stop.log`, `copy-stop-verification.json`, `final-verification.json`.

`source/.env` and `fresh-environment/.env` contain new test keys: they must not be included in attachments or an archive of the directory. Only this report is intended for sharing.

Python documentation was checked through Context7 against version 3.13.9; additional parameters from newer Python versions were not used. Primary source: https://github.com/python/cpython/blob/v3.13.9/Doc/library/base64.rst .
