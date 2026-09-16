# Phase 1 — local validation 2026-09-13

Final preservation and copy-shutdown check: `2026-09-13T06:15:02.286666+00:00`. The approved local checks were completed. **This is not an independent assessment, final closure of Task 20, or authorization to merge or publish.**

## Scope

- The current working tree of branch `task20-phase1-completion` with existing uncommitted fixes was checked.
- A separate 200-file copy was prepared for ordinary startup; four updated documents were synchronized before the automated run. The final test snapshot covers 201 files.
- Application code, tests, dependencies, the restoration script, and the original `.env` were not changed during these checks. The main previously approved `compose.yaml` setting continues to bind the site to `127.0.0.1:8000`.
- Only the locally published ports and `APP_BASE_URL`, required to work alongside the old stand, differ in the copy. All other files except these two Compose files were checked by checksum.
- No new reviewing models were run. Commit, push, merge, and deployment were not performed.

## Ordinary startup

After one-time standard confirmation, the documented sequence was run:

```bash
docker compose run --rm --build web python manage.py migrate --noinput && docker compose up --build
```

It ran in project `omp-final-20260913t023437z`, with ordinary `postgres` and a separate persistent volume. The `/login/` and `/register/` pages returned 200 and forms over HTTP; the subsequent `migrate --check` completed with code 0. The copy’s site and mail service were available only on loopback ports 18000/18025/11025.

Details: [ordinary-startup record](phase-1-ordinary-startup-2026-09-13.md). [Manual 10/10 acceptance](phase-1-browser-acceptance-2026-09-13.md) was completed earlier on the preserved stand and is not presented as a repeat browser pass in the new database. Both pieces of evidence close Task 20 Step 5.

## Fresh automated results

The checks ran sequentially, after synchronizing the ordinary-startup documents, in newly built images of the copy. Only its separate `postgres-test` with data in `tmpfs` and Mailpit were used. The tests did not attach to the persistent volume of either the current stand or the copy.

- `makemigrations --check --dry-run`: `No changes detected`.
- `migrate --noinput`: successful.
- `check --deploy`: only `security.W004`, `security.W008`, `security.W012`, `security.W016` — four expected warnings for local HTTP mode. This is not authorization to use these settings for publication. `test_cookie_security_defaults_and_secure_mode` passed in the fresh suite.
- `lint-imports --no-cache`: `11 kept, 0 broken`.
- Full suite: `Ran 407 tests in 177.694s`, `OK`; there were no errors or skips.
- All 17 scenario names from `test_full_flows.py` were obtained from the actual source file, matched against the full log, and confirmed successful. Real restoration was checked by a separate script run, not only by its contract test.
- Additional separate run of `test_scope_boundaries.py`: 5/5. These five tests are already included in 407 and are not added to the unique-test count.
- Runtime and test images: `/app/.env` and `/app/.git` are absent; validation processes did not run as root.
- The specified private-key patterns and non-empty assignments of the six project secrets were not found in any of the 201 tracked or new non-ignored files. `.env` is Git-ignored and untracked. This is a limited pattern check, not a guarantee that every possible secret is absent.
- `git diff --check` and `bash -n ops/verify_restore.sh`: successful before the run; final report changes are checked separately.

The validation log was processed in full. The first large transfer of results through the tool could not be parsed as JSON; it was not used as evidence of test failure. The final numbers were obtained by parsing the complete file again and producing a short verified summary, without guessing at the unavailable part of the output.

## Real restoration

```bash
COMPOSE_PROJECT_NAME=omp-final-20260913t023437z bash ops/verify_restore.sh
```

Exit code 0. The standard unchanged script created separate temporary source and target databases, ran `pg_dump` and `pg_restore`, and then compared the data.

- All nine named data-consistency conditions and nine final migrations were successfully checked in both databases.
- The source and restored database sections matched completely, including record identifiers.
- A separate read-only query after completion confirmed the absence of temporary `restore_source_*` and `restore_target_*` databases.
- Temporary dumps and partial reports are absent. Only the safe result was preserved.

This is a test-database restoration check, not an approved backup policy for the production system.

## Preservation and state after validation

After validation, only the five containers of project `omp-final-20260913t023437z` were stopped. They were not removed; the copy’s persistent volume, files, and evidence were preserved. General Docker cleanup was not performed. The absence of temporary databases was checked before `postgres-test` was stopped, rather than inferred from the subsequent loss of its temporary memory.

For the original stand `omp-browser-20260911t033934z`:

- all four containers continue running without restart;
- the login page at `http://127.0.0.1:8000/login/` returned 200;
- the previous port bindings were preserved;
- the identifiers and count of all ten Mailpit emails matched;
- aggregates for all 17 application tables matched, including application state `approved` and seller access `active`;
- the original `.env` and pre-run file snapshot were unchanged.

After the run, only the final documents and evidence were updated; application code was not changed. The `.env` in the preserved copy is a hard link to the original file: it must not be edited or included in archives/attachments.

## Evidence and remaining conditions

Local Git-ignored directory: `artifacts/final-local-20260913T023437Z/`.

Main evidence:

- `gate-source-manifest.json`, `gate-precheck.json`, `gate-build.log`;
- `makemigrations.log`, `migrate.log`, `check-deploy.log`, `import-linter.log`;
- `full-suite.log`, `quality-gate-summary.json`, `expected-full-flows.json`, `scope-suite.log`;
- `repository-secrecy.json`, `image-secrecy.json`, `web-image-secrecy.log`, `test-image-secrecy.log`;
- `restore.log`, `restore-result.txt`, `restore-summary.json`;
- `preservation-after-startup.json`, `preservation-after-gate.json`, `preservation-after-copy-stop.json`;
- `copy-stop.log`, `copy-stop-verification.json`.

Task 20 Step 7 remains open: a valid independent assessment has not yet been obtained, and final recording of the changes is not separately authorized. Merge and publication are not being performed. Code changes after this snapshot require new corresponding validation.
