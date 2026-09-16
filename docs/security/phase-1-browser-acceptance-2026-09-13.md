# Open Marketplace: final manual pass of the first phase

**Result: 10 of 10 browser-scenario items completed. Phase 1 as a whole has not yet been accepted.**

Final server snapshot: `2026-09-12T23:23:39.458546+00:00` (UTC), `2026-09-13T02:23:39.458546+03:00` (UTC+03:00).

## Method and scope

Vladislav performed the actions in regular Chrome and incognito mode. Screen confirmations were cross-checked against reads from the test database and actual delivery to Mailpit. This was a real manual pass through a running web server, not a substitute using the Django test Client. The automated Hermes browser was neither repaired nor used for this pass.

- Working branch: `task20-phase1-completion`.
- Isolated Compose project: `omp-browser-20260911t033934z`.
- Database: `postgres-test`; checks were performed in read-only transactions.
- Store: `http://127.0.0.1:8000`; test mail: `http://127.0.0.1:8025/`.
- Only approved test accounts and fictitious application data were used.

## Verified scenario

1. **Passed — Creating the first administrator invitation.** New live invitation and new Mailpit delivery verified
2. **Passed — Activating the administrator, Authenticator, and displaying recovery codes.** Owner confirmed Recovery codes page; admin-activation-20260912.log verifies activation without secret values
3. **Passed — Inviting a reviewer from the administrator panel.** Owner created invitation through custom Admin; reviewer-invitation-20260912.log verifies creator, role and Mailpit receipt
4. **Passed — Activating the reviewer with separate login protection.** Owner confirmed reviewer Recovery codes in incognito; reviewer-activation-20260912.log verifies TOTP and seller_reviewer-only role
5. **Passed — Seller registration, email confirmation, and login.** ordinary-registration-20260912.log verifies account and mail; ordinary-login-20260912.log verifies email confirmation and login; owner confirmed Security page
6. **Passed — Revoking the current session, logging out, and logging in again.** Owner verified current session, Revoke logout and new current session after login; session-management-20260912.log confirms revocation and replacement
7. **Passed — Creating, editing, and submitting an application.** Owner created the application, edited and saved its draft, then submitted it; seller-draft-20260912.log and seller-submission-20260912.log verify exact test-data matches and version 1
8. **Passed — Reviewing and approving the application as the reviewer.** Owner confirmed approved; review-start-verified-20260913.log and seller-approval-20260913.log verify assigned reviewer, decision for version 1, active profile and audit transition
9. **Passed — Suspending and restoring access as the administrator.** Owner confirmed suspended and then active with cleared reason. seller-suspension-20260913.log and seller-restoration-verified-20260913.log verify both admin transitions; owner account and approved application preserved.
10. **Passed — Viewing the application audit log and checking email delivery.** Owner confirmed Audit page as reviewer with five success rows. audit-mail-verification-20260913.json verifies application/profile chains and nine current-run SMTP receipts; final-browser-state-20260913.log verifies final state.

## Final state

- `admin@example.test`: active service account, only the `security_admin` role, Authenticator confirmed.
- `reviewer@example.test`: active service account, only the `seller_reviewer` role, Authenticator confirmed.
- `seller@example.test`: active ordinary account, no service roles, Authenticator confirmed.
- Application `08af376d-341e-4a68-bd2d-6c3030f9130b`: `approved`, version 1, decision `approve`.
- Access `36e9596c-f54f-42a2-bacc-64f30fd36f28`: `active`, restriction reason cleared.
- Suspending and restoring access did not lock the owner's account or revoke the application approval.

## Audit log and mail

- 5 application records checked: creation → editing → submission → review started → decision.
- 3 access records checked: creation → suspension → restoration.
- The accounts, roles, event order, and state transitions in the records were cross-checked.
- All 13 messages in the current-run queue were processed successfully. Queue state by itself was not used as evidence of email delivery.
- 10 emails were collected in Mailpit; 9 belong to the current pass, and 1 was an old invitation excluded from the current cross-check.
- Each of the 9 expected email sends was matched to a separate actual delivery by recipient, subject, and time. Content was additionally checked for notifications without secrets; the decision email contains `approve`.
- Application-submission and access-change events are processed locally, without SMTP emails: this is confirmed by `outbox/mail_delivery.py`.
- Vladislav opened the application audit log as the reviewer and confirmed five rows with `Result: success`.

## Important characteristics and limitations

- Login confirmation for sensitive actions is time-limited. After the restoration attempt was denied, access remained `suspended`; after login was confirmed again and Restore was performed immediately, it became `active`. Protection settings were not weakened.
- Roles have different audit-log scopes: `seller_reviewer` sees application history; `security_admin` sees access history and service operations. Permissions were not expanded for the check.
- The initial cause of the invitation-acceptance error was not established. The subsequent successful activation was verified; that success does not prove the cause of the earlier error.
- The recovery-code pages were shown to the user. The user's reliable long-term storage of the codes was not separately confirmed. Old Authenticator records were not deleted.
- Passwords, one-time/recovery codes, Authenticator secrets, invitation links, and encrypted delivery fields were not extracted for the final checks. Email bodies containing one-time links were not requested when delivery was cross-checked.
- The JavaScript console, responsive layout, and full visual audit were not checked. Screen confirmations were provided by the owner; automated screenshots of those screens are not claimed.
- The test database was not reset; no new database backup was created during this pass. The `postgres-test` database is temporary: this result does not guarantee that its data will survive an infrastructure restart.
- Product source code was not changed in this continuation. Existing uncommitted branch changes were preserved. No new independent reviewer was run; commit/push/merge were not performed.

## What is still required for the full phase

1. Check ordinary startup using the documented command in the approved safe configuration. This manual pass used a separate test Compose project and does not prove startup with the ordinary persistent database; Task 20 Step 5 is not yet fully closed.
2. Repeat the full automated check after updating the documentation. The result of 407 tests from 2026-09-11 remains historical, not a new run.
3. Obtain a valid independent code assessment. An additional model and its cost require separate approval.
4. Complete recording the changes after the checks and approved actions. Readiness for merge or publication is not claimed.

## Evidence

Primary local directory: `artifacts/browser-acceptance-20260911T033934Z/`. Logs remain local; this document contains a non-secret summary.

- `resume-20260912.json` — all ten items and separate historical snapshots for the steps.
- `seller-approval-20260913.log` — approval.
- `seller-suspension-20260913.log` — suspension.
- `seller-restoration-verified-20260913.log` — restoration.
- `audit-outbox-metadata-20260913.log` — action chains and queue states.
- `mailpit-metadata-batch-20260913.json` — complete collected package of mail metadata.
- `mailpit-safe-notices-20260913.json` — content check of notifications without secrets.
- `audit-mail-verification-20260913.json` — programmatic cross-check and count.
- `final-browser-state-20260913.log` — final state after confirming the Audit page.
