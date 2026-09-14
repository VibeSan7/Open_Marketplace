# Phase 1 security review and completion evidence

## Review scope

This review covers Task 20 in the isolated `task20-phase1-completion` worktree:

- 17 Phase 1 end-to-end acceptance scenarios;
- predecessor-to-leaf migration compatibility;
- scope, dependency and secrecy gates;
- the denial-audit rollback regression and the selected compensation design;
- local HTML/Admin/Mailpit demonstration.

The review is evidence-based. It does not claim a production deployment review, external penetration test or production backup policy.

Latest completed local checkpoint: [verification after VAL-001 on 2026-09-14](phase-1-local-validation-2026-09-14-after-val-001.md) passed **411/411 application tests** with a newly generated environment from the corrected README. It includes all 17 acceptance scenarios, eight migration checks and five scope checks, plus a separate 5/5 scope run and a **real PostgreSQL dump/restore**. Images, migrations, 11 import contracts and bounded secrecy checks passed. **VAL-001 is resolved and the agreed local gate is green.** Only one README generator line was corrected; application code, validation policy and existing working keys were unchanged. Only the new isolated project was stopped; all 14 pre-existing containers were preserved. The [earlier interrupted checkpoint](phase-1-local-validation-2026-09-14.md) remains the historical record of the actual failure.

The [2026-09-13 full gate](phase-1-local-validation-2026-09-13.md), [owner-driven Chrome acceptance](phase-1-browser-acceptance-2026-09-13.md) and [ordinary persistent-database startup](phase-1-ordinary-startup-2026-09-13.md) remain separate historical proofs. A later owner-authorized independent static review did return `APPROVE` with remarks before the three scoped fixes; it was not rerun. No new paid review, final commit, merge or deployment is authorized by this checkpoint.

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

The earlier combined acceptance/audit/staff-admin run passed 70/70, followed by a 394/394 project checkpoint. The 2026-09-13 project run passed 407/407; the post-R-01/R-03/R-05 run passed 411/411 on 2026-09-14, with all 17 scenarios present and successful. The later post-VAL-001 run again passed 411/411, this time with the freshly generated environment. Scenario 17 checks the restore command contract; the separate real restore was also executed successfully in the latest checkpoint.

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

Fresh 2026-09-14 evidence after the authorized VAL-001 correction (the agreed local gate is complete):

- `makemigrations --check --dry-run` — passed;
- `migrate --noinput` — passed;
- `check --deploy` — four expected warnings only for local HTTP (`SECURE_SSL_REDIRECT`, secure session cookie, secure CSRF cookie and HSTS); `test_cookie_security_defaults_and_secure_mode` proves the HTTPS settings switch on with `DJANGO_SECURE_COOKIES=true`;
- Import Linter — 11 contracts, 0 violations;
- full `open_marketplace` suite with a newly generated README environment — 411/411 in 191.294 seconds, no failures, errors or skips;
- `git diff --check` — passed;
- shell syntax `bash -n ops/verify_restore.sh` — passed;
- real PostgreSQL dump/restore — exit 0 after R-01/R-03/R-05/VAL-001, nine named invariants and nine migration leaves in both databases; source/target results matched, and cleanup was independently checked before PostgreSQL stopped;
- bounded private-key and six-variable non-empty secret-assignment scans across 203 tracked/new nonignored snapshot files — 0 hits; not a universal secret-detection guarantee;
- `.env` — ignored and untracked;
- runtime and test images — no `/app/.env` or `/app/.git`, non-root UID 10001, all 203 snapshot file hashes matched;
- `test_scope_boundaries.py` — 5/5 within the 411-test suite and 5/5 in the additional standalone run;
- corrected README first-time `.env` generation followed by the real runtime check — **passed**, exit 0, only documented local-HTTP warnings; an existing generated `.env` was not overwritten on a repeat invocation.

The scope test rejects unapproved direct dependencies, forbidden apps, JSON/DRF handlers, future-domain models, file/document uploads and secret-bearing fixtures. It is authoritative; production-source word searches are not used as a substitute.

## Local working-result evidence

The local stack was started with PostgreSQL, web, worker and Mailpit. A temporary Django test Client harness exercised the HTML and custom Admin view boundaries in-process against the persistent local PostgreSQL database, using real SMTP delivery to Mailpit. It did not drive an authenticated browser or send its application requests through the running web server. The following results are integration evidence, not completion of the manual browser demonstration:

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

### Historical manual-browser checkpoint (2026-09-13)

The owner completed registration/invitations, TOTP, session revocation, seller submission/approval, admission suspension/restoration and the scoped application Audit page in real Chrome. Final read-only verification found the application approved and seller admission active without an owner-account block. Five application audit entries, three admission entries and nine actual current-run Mailpit receipts were matched against the database; all thirteen scoped outbox messages succeeded. The earlier unsuccessful browser-tool attempt does not negate this later owner-driven result. See the linked browser report for evidence and explicit limitations. Ordinary startup and the fresh quality gate were subsequently verified separately; the linked 2026-09-13 reports do not claim a repeated manual flow in the new database.

| ID | Severity | Finding | Evidence | State | Owner |
|---|---|---|---|---|---|
| SEC-001 | Info | Local HTTP profile emits four `check --deploy` warnings. | Fresh `check --deploy`; secure-mode test. | Resolved/documented; production must use `DJANGO_SECURE_COOKIES=true` behind HTTPS. | Deployment owner |
| SEC-002 | Info | Restore proof is disposable test evidence, not a production backup policy. | `docs/runbooks/test-and-restore.md`. | Resolved/documented; production RPO/RTO, retention and key custody remain a separate gate. | Operations owner |
| SEC-003 | Info | Recovery codes and one-time secrets must never be retained by the demo operator. | HTML flow, audit secrecy assertions and runbook. | Resolved/documented; values were discarded. | Application owner |

The earlier implementer and independent static findings do not establish absence of defects. VAL-001 was subsequently reproduced, corrected with separate authorization and verified by actual execution; the agreed local gate is now complete, not a production security sign-off.

## Independent review and scoped follow-up

The owner-authorized invocation `omp-phase1-review-20260913t102350z` returned `VERDICT: APPROVE` with six remarks and two hypotheses. This was a bounded static review, not an exhaustive audit or execution of the setup recipe. The original report and the lead agent's source-checked dispositions are retained under the local ignored `artifacts/independent-review-20260913T102350Z/` directory. It predates R-01/R-03/R-05 and was not repeated.

- **R-01 — resolved in the approved scope:** neutral sign-out guidance on rejected invitations for an already signed-in user; no automatic logout or permission change. Local evidence: `artifacts/r01-invitation-guidance-20260913T113511Z/result.md`.
- **R-03 — resolved in the approved scope:** conditional guidance only for a live retry of an unfinished new-service-account TOTP setup; no key redisclosure or security-policy change. Local evidence: `artifacts/r03-totp-retry-guidance-20260913T212517Z/result.md`.
- **R-05 — resolved in the approved scope:** real POST Origin/HTTPS Referer coverage for one form, two test methods and eight request variants; production protection was not changed. Local evidence: `artifacts/r05-csrf-form-tests-20260913T203202Z/result.md`.
- **R-02/R-06 — rejected as stated** after source/log verification. Their original historical dispositions are preserved, not silently accepted as defects.
- **R-04 — cosmetic only, not changed.**
- **H-1 — limited login path observed, privilege bypass not demonstrated. H-2 — concurrency hypothesis not reproduced.** Neither is presented as a confirmed vulnerability or automatically fixed.

### VAL-001 — first-time environment recipe failure (RESOLVED)

**Severity at discovery:** medium, functional first-run blocker, not a demonstrated security bypass. **Owner:** project maintainer. **State:** resolved in the separately authorized one-line scope.

The historical unmodified Python block at `README.md:24–46` created a file rejected by the actual runtime: exit 1, `THROTTLE_HASH_KEY is invalid`. Its former line 36 used `secrets.token_urlsafe(32)`, producing 43 characters without Base64 padding. The strict decoder at `open_marketplace/config/settings.py:18–24,34–38,189` rejected that value. The original failure report and log are preserved; no key value was printed.

After explicit approval, only the README expression for this key was changed to `base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")`. The complete corrected block ran in an empty directory with `.env.example`; the generated file passed the actual rebuilt runtime check with network disabled. The key decoded strictly to 32 bytes, and a second generator invocation refused to overwrite the existing file. That same fresh environment then passed all 411 application tests, the standalone scope suite and the real PostgreSQL restore. Application validation and existing database keys were not changed. See [the completed post-fix checkpoint](phase-1-local-validation-2026-09-14-after-val-001.md).

## Phase 1 disposition

**Agreed local verification is complete. The owner has separately authorized local commits only. Task 20 Step 7 and final owner acceptance remain open; push, merge and publication are not authorized.**

- Independent review invocation `task20-independent-review-1` returned only `HTTP 403: Access denied by security policy`. The launcher envelope reported `ok: true`, but contained neither a code review nor an `APPROVE` verdict. The source and cause of that historical HTTP denial were not established. It was not treated as approval or bypassed. The later separately authorized static review described above did produce a valid report.
- The ten-item manual browser flow and ordinary persistent-database startup have separate historical proofs. The authorized static review predates the subsequent fixes and was not repeated. The latest local gate after R-01/R-03/R-05/VAL-001 is complete, including clean environment generation and real restore. The earlier Django test Client result remains integration evidence only.
- The implementation, tests and initial documentation were committed together as `b48ea7fbe59daa593c8860b7874d1fb122a5b62b` and pushed before independent approval. This did not follow the plan's separate-fix-before-documentation commit sequence. The published history has not been rewritten; it must not be presented as evidence of approval.
- After separate owner approval on 2026-09-14, the tested application/tests, loopback binding and README correction were recorded in local commits `9270e94`, `40bc1ec` and `9a3dc2a`, respectively. Documentation is committed separately. No application or test bytes were changed during Git recording; the 411-test result belongs to the linked completed run, not a new test invocation. No server startup, new paid review, push, merge, deployment or Phase 1 closure was authorized. Task 20 Step 7 and final owner acceptance stay open.
- The pre-existing newline-only difference in `open_marketplace/audit/public.py` is deliberately left uncommitted and unchanged. This checkpoint does not claim a clean working tree or close the cosmetic R-04 remark.
