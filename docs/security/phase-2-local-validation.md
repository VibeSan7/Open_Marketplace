# Catalog validation v0.2.0

Status: the catalog implementation was validated locally. This is a working release for running through Docker, **not a deployed online store and not confirmation of readiness for public operation**.

All 47 `CAT-*` decisions from the [approved specification](../superpowers/specs/2026-09-14-phase-2-catalog-design.md) were preserved. The catalog does not include orders, payments, or digital-file delivery.

## Actual results

- Full suite: **503 tests, OK, 382.331 seconds**, with no skipped tests. Validation log: `artifacts/phase2-validation/accepted-suite.log`.
- Repeat full run from a clean archive: **503 tests, OK, 366.615 seconds**, with no skips and no source substitution through a bind mount (`artifacts/release-candidate/clean-suite.log`). A freshly loaded model was used. The first attempt to create an additional test environment stopped before the tests because Docker networks were exhausted; the repeat used an already allocated temporary test environment, without changing network settings or other projects.
- Django check: `System check identified no issues`.
- Model and migration consistency: `No changes detected`.
- Module dependency constraints: **12 kept, 0 broken** (`accepted-checks.log`).
- `check --deploy --fail-level WARNING` with `DEBUG=false` and secure cookies: no warnings (`accepted-deploy-check.log`). This checks settings; it does not replace HTTPS, a production web server, or an operational audit.
- Catalog JavaScript was checked with `node --check`; `git diff --check` found no whitespace errors.
- Real Chromium performed seller creation and publication of a card, photo upload, mobile filters, text application, load error/retry, return, and access revocation. An image error is not replaced with another person’s photo.
- The real local search model was checked with Russian semantic queries without literal matches and across several product groups. Computed vectors, rather than substituted answers, were used.

## Relation to approved rules

The checks and implementation are located together; the main entry points are:

- Publication, separate draft, ownership, access, adding/removing/restoring variants, and unpublishing a card: `catalog/tests/test_catalog.py`, `test_acceptance.py`, `test_boundaries.py`.
- Required data, catalog changes, and preservation of the published snapshot: `test_acceptance.py`, `test_web_integration.py`, `test_management_queries.py`.
- Units, rubles, precision, free product, empty values, and real transaction concurrency: `test_domain.py`, `test_concurrency.py`, `test_catalog.py`.
- Shared cards, employee identity confirmation, source-offer prices, and excluding delivery from comparisons: `test_common_cards.py`, `test_web_integration.py`.
- Private photos, format/size checks, metadata removal, cover photo, and variant photos: `test_photos.py`, `test_acceptance.py`, `test_browser.py`.
- Exact/approximate matching, typos, single-variant filters, and meaning: `test_search.py`, `test_semantic.py`.
- Links, condition preservation on error, variant selection, product absence, and no substitution: `test_web.py`, `test_web_integration.py`, `test_acceptance.py`.
- Scrolling, return, text, and filters in a real browser: `test_browser.py`.
- HTML adapter forms: `web/tests/test_catalog_forms.py`. The test is located in the web module and does not bypass the prohibition on a reverse catalog-to-interface dependency.

## Clean installation

The sources were extracted with standard `git archive` without `.env`, `.git`, databases, user photos, the model, logs, or working artifacts. The README commands were run in the extracted copy:

1. A new `.env` with random values was created. A repeat generator run was checked to raise `FileExistsError` and leave the existing file unchanged.
2. The ordinary application image was built and migrations were run on an empty persistent PostgreSQL database.
3. The model was freshly loaded into empty persistent storage using `prepare_catalog_search`, which completed with code 0.
4. The application, mail sender, PostgreSQL, and Mailpit were started. Neither the original `.env` nor the working database was transferred.
5. HTTP check: `/catalog/` safely redirects an unauthenticated visitor to `/login/`; the login page, JavaScript, CSS, and local mail return HTTP 200.
6. Ordinary `down` and `up -d` were run without `-v`: the persistent database survived, and the number of applied migrations matched before and after. The built image contains no `.env`, `.git`, working-artifact directories, or backups.

The validation Compose projects are separate from other installations. Their names are not part of the user configuration. The catalog listens only on the local interface; internet access was not opened.

## Database and photo restoration

`ops/verify_restore.sh` was checked in an isolated project. It:

- creates synthetic records and checks the source database;
- makes a `pg_dump` and a separate photo archive;
- restores the database into another database and the files into another directory;
- first confirms that photo validation **does not pass** with an empty target directory;
- restores the archive and successfully checks permissions, published snapshots, variants, prices, stock, photos, and offer relationships;
- deletes only the temporary databases, directories, and archives it created; it records the result after successful cleanup.

Result: `media=restored_from_archive`, identity/access/outbox/catalog checks completed, `restored_ok`. Log: `artifacts/phase2-validation/accepted-photo-restore.log`. Working secrets, real accounts, and personal mail were not used.

## Fixes found during final validation

- An invalid link condition no longer forces all other conditions to be reset: each value can be fixed or removed separately. Before the fix, three new regression checks reproduced the errors; they then passed with the full suite.
- Zero stock is explicitly labeled; a missing variant is not offered as an available offer for comparison.
- The outdated prohibition on the word `catalog` in the previous phase’s check was removed selectively. Prohibitions on payments, KYC documents, and later product areas were preserved.
- The new migration name was shortened to `0002_common_cards.py`; the general check for long secret-like values in the restoration report was not weakened.
- Restoration now proves transfer of the photos themselves rather than reusing the original file directory.

## Evidence and publication boundaries

- GitHub Actions is not configured in the repository: the listed results came from real local execution, not remote CI.
- No separate reviewing model was run; no independent security audit is claimed.
- `.env`, caches, logs, dumps, and user photos are excluded from Git and the Docker context. The Git index was checked for known secret values from two local `.env` files and characteristic key formats; no matches were found. This is a limited check, not a guarantee that all possible secrets are absent.
- The repository remains private. Visibility, license, real user permissions, domain, and external infrastructure were not changed.
- The new installation is intentionally empty: administrator, participant, and first-product setup is described in the [catalog quickstart guide](../runbooks/catalog-quickstart-en.md).
- Logs remain only in local ignored artifacts: test traces may contain temporary identifiers. This cleaned report, rather than raw logs, is included in the release sources.
