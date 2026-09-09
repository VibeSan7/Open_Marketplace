# Phase 1 security review and completion evidence

## Review scope

This review covers Task 20 in the isolated `task20-phase1-completion` worktree:

- 17 Phase 1 end-to-end acceptance scenarios;
- predecessor-to-leaf migration compatibility;
- scope, dependency and secrecy gates;
- the denial-audit rollback regression and the selected compensation design;
- local HTML/Admin/Mailpit demonstration.

The review is evidence-based. It does not claim a production deployment review, external penetration test or production backup policy.

## Acceptance matrix

`open_marketplace/tests/test_full_flows.py` contains exactly 17 scenarios:

1. `test_registration_email_confirmation_and_login` — registration, email confirmation and login;
2. `test_expired_and_reused_links_are_rejected` — expired and replayed links;
3. `test_password_reset_revokes_previous_sessions` — reset revokes old sessions;
4. `test_totp_and_recovery_code_work_and_recovery_replay_fails` — TOTP and recovery replay;
5. `test_email_access_alone_cannot_disable_mandatory_totp` — email access does not bypass mandatory TOTP;
6. `test_initial_security_admin_bootstrap_only_once` — bootstrap is one-time;
7. `test_one_time_staff_invitation_grants_only_named_role` — invitation role boundary;
8. `test_draft_submit_changes_requested_new_version_approve` — draft/review/version/approval;
9. `test_repeated_approve_creates_no_second_seller` — approval idempotency;
10. `test_reject_leaves_ordinary_account_active` — rejection keeps account active;
11. `test_reject_or_withdraw_allows_separate_history_and_one_unfinished_application` — separate history and one unfinished application;
12. `test_security_admin_suspends_restores_seller_without_blocking_owner` — admission suspension/restoration;
13. `test_forbidden_staff_operation_is_denied_and_audited` — 403 plus denial audit;
14. `test_outbox_retry_and_expired_lease_reclaim_do_not_repeat_domain_change` — retry/reclaim idempotency;
15. `test_audit_reconstructs_action_chain_without_secrets` — audit reconstruction and secrecy;
16. `test_account_block_revokes_sessions` — account block/session revocation;
17. `test_restore_verification_command_contract_is_safe` — safe restore-verification command contract.

The combined acceptance/audit/staff-admin run passed 70/70. The final project run after migration and scope tests passed 394/394.

## Migration evidence

`open_marketplace/tests/test_migrations.py` uses PostgreSQL `MigrationExecutor` and historical app models only for predecessor seeding. It checks the five Identity migrations (`0002`–`0006`), Access `0002`, Seller onboarding `0002` and a clean migration graph. The suite passed 8/8 and restores the current leaf schema after each test.

## Root-cause fix: denial audit after rollback

Before the fix, `access.authorize()` appended `access.permission_denied` inside a business `transaction.atomic()` block. A later `PermissionDenied` rolled back both the protected operation and the denial row.

The selected variant B is intentionally scoped to `staff_admin`:

1. the common Admin action wrapper lets the protected operation leave its transaction;
2. the wrapper preserves the existing 403 response;
3. after rollback it checks `audit_entry_exists(request_id, "access.permission_denied")` through `audit.public`;
4. it appends one compensation audit entry only when the original row is absent.

The regression suite verifies nine forbidden Admin actions, 403 responses and exactly one denial audit per request. No second database alias was introduced.

## Security and secrecy gates

Fresh evidence:

- `makemigrations --check --dry-run` — passed;
- `migrate --noinput` — passed;
- `check --deploy` — four expected warnings only for local HTTP (`SECURE_SSL_REDIRECT`, secure session cookie, secure CSRF cookie and HSTS); `test_cookie_security_defaults_and_secure_mode` proves the HTTPS settings switch on with `DJANGO_SECURE_COOKIES=true`;
- Import Linter — 11 contracts, 0 violations;
- full `open_marketplace` suite — 394/394;
- `git diff --check` — passed;
- shell syntax `bash -n ops/verify_restore.sh` — passed;
- real PostgreSQL dump/restore — exit 0; temporary databases and dump files removed;
- tracked private-key scan — 0 hits;
- tracked non-empty secret-assignment scan — 0 hits;
- `.env` — ignored and untracked;
- runtime and test images — no `/app/.env` and no `/app/.git`;
- `test_scope_boundaries.py` — 5/5.

The scope test rejects unapproved direct dependencies, forbidden apps, JSON/DRF handlers, future-domain models, file/document uploads and secret-bearing fixtures. It is authoritative; production-source word searches are not used as a substitute.

## Local working-result evidence

The local stack was started with PostgreSQL, web, worker and Mailpit. The non-secret demonstration used real HTML and custom Admin view boundaries against the running local database:

- security-admin, reviewer and ordinary owner completed the invitation/registration flows;
- each TOTP setup returned 10 recovery codes once; values were discarded in memory;
- owner opened session management;
- seller draft was edited and submitted through HTML;
- reviewer used custom Admin to start and approve review;
- security-admin used custom Admin to suspend and restore admission;
- Mailpit received the staff invitation, verification and seller-decision messages;
- audit query reconstructed the five-step seller application chain and verified suspend/restore actions;
- Admin index, seller detail, audit page and session page returned HTTP 200.

The CUA browser window available on the workstation was an unrelated, timed-out external tab. No credentials were entered into it and no fabricated screenshot is included. The local result is backed by the command output above and by the automated HTML/Admin integration suite.

## Findings

| ID | Severity | Finding | Evidence | State | Owner |
|---|---|---|---|---|---|
| SEC-001 | Info | Local HTTP profile emits four `check --deploy` warnings. | Fresh `check --deploy`; secure-mode test. | Resolved/documented; production must use `DJANGO_SECURE_COOKIES=true` behind HTTPS. | Deployment owner |
| SEC-002 | Info | Restore proof is disposable test evidence, not a production backup policy. | `docs/runbooks/test-and-restore.md`. | Resolved/documented; production RPO/RTO, retention and key custody remain a separate gate. | Operations owner |
| SEC-003 | Info | Recovery codes and one-time secrets must never be retained by the demo operator. | HTML flow, audit secrecy assertions and runbook. | Resolved/documented; values were discarded. | Application owner |

Critical/high unresolved findings: **0**.

## Phase 1 disposition

Implementation and evidence gates are complete in this worktree. Final disposition remains subject to the independent reviewer approval, final documentation-aware quality rerun and the separate Task 20 commit/PR. No claim of merged or deployed status is made by this document.
