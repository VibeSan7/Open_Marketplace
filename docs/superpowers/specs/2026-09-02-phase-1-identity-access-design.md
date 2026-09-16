# Open Marketplace — Phase One: Identity, Access, and Seller Admission

**Date:** 2026-09-02\
**Status:** approved by Vladislav on 2026-09-02; implementation not started\
**Type:** subordinate specification for the first implementable phase\
**Overall specification:** `D:\Open_Marketplace\docs\superpowers\specs\2026-09-02-open-marketplace-design.md`\
**Technical research:** `D:\Open_Marketplace\docs\research\2026-09-02-technical-stack-recommendation.md`\
**Working interview decisions:** `D:\Open_Marketplace\phase-1-design-notes.md`

## 1. Goal

Phase one creates a self-contained working vertical flow:

1. a person registers;
2. confirms their email;
3. signs in and manages account security;
4. submits a test application for seller status;
5. a staff member reviews the application;
6. the system approves, rejects, or returns the application for changes;
7. permissions are checked on the server;
8. protected actions can be reconstructed from immutable audit records;
9. emails and other background actions can be safely retried after a failure.

The phase proves the server-side foundation of the future marketplace, but does not begin trading.

## 2. Technology Direction

- Python 3.13;
- latest patch release of Django 5.2 LTS;
- PostgreSQL;
- Linux containers;
- Docker Compose;
- modular monolith;
- server-rendered Django pages for ordinary users;
- Django Admin for staff operations;
- PostgreSQL-backed outbox queue for outgoing events and background deliveries;
- no Redis, Celery, Kafka, Kubernetes, or separate search server.

The technical research approved Django REST Framework for a future JSON API, but JSON is absent from phase one, so the unused dependency is not installed. Exact patched versions of the packages and container images used are recorded in a lock file in the implementation plan after a separate check of available releases. An unpinned version range must not be used in a reproducible build.

## 3. Scope

### 3.1 Included

- registration by email and password;
- mandatory email confirmation;
- sign-in, sign-out, password reset, and password change;
- active sessions and their revocation;
- second factor through an authenticator app;
- one-time recovery codes;
- protected second-factor recovery;
- ordinary buyer account;
- test seller application;
- application versions and lifecycle;
- separate seller profile after approval;
- separate account and seller states;
- staff reviewer and security administrator roles;
- secure creation of the first administrator;
- personal staff invitations;
- server-side permission checks;
- immutable audit;
- reliable outgoing events and background jobs;
- local test mailbox;
- minimal HTML pages;
- Docker Compose and PostgreSQL for development and tests;
- test database restoration.

### 3.2 Excluded

- catalog, products, variants, and inventory;
- search;
- cart, order, payment, and payout;
- shipping and digital fulfillment;
- disputes, returns, and reviews;
- real seller documents;
- seller payment details;
- external KYC/AML provider;
- production email provider;
- social sign-in;
- SMS sign-in and SMS second factor;
- OAuth, public API keys, and third-party applications;
- multiple owners of one seller;
- seller employees;
- separate frontend framework;
- cloud deployment;
- AI;
- real purchases and personal documents.

## 4. Canonical Terms

- **Account** — the identity of one person and their protected sign-in methods.
- **Ordinary account** — an account that can act as a buyer and the owner of one seller.
- **Service account** — a separate account for a marketplace employee that does not participate in purchases or sales.
- **Session** — a time-limited confirmation of a particular account's sign-in.
- **Second factor** — a one-time authenticator-app code after the password.
- **Recovery code** — a one-time way to replace the app code when the device is lost.
- **Seller application** — a version of information submitted by an ordinary account for review.
- **Seller profile** — a separate entity created after an application is approved.
- **Seller owner** — the single ordinary account managing the seller in the first version.
- **Seller reviewer** — a staff role for application decisions.
- **Security administrator** — a staff role for employees and protected recovery.
- **Application operation** — a single server-side entry point into a business rule regardless of whether it is called by HTML, Admin, a command, or a background worker.
- **Audit** — a history of protected actions that is appendable without subsequent modification.
- **Outgoing event** — a confirmed record of the need to notify another module or an external adapter.
- **Background job** — confirmed work performed outside a user request.

## 5. Architecture

Phase one is one Django project and one PostgreSQL database. Code is divided by domain modules, not by shared technical folders.

### 5.1 `identity` module

Responsible for:

- account;
- email and email confirmation;
- password;
- second factor;
- recovery codes;
- reset and recovery;
- one-time confirmation and recovery tokens;
- sessions.

It knows nothing about applications or sellers.

Public application operations:

- `register_account`;
- `verify_email`;
- `authenticate_account`;
- `log_out_session`;
- `request_password_reset`;
- `reset_password`;
- `change_password`;
- `enable_totp`;
- `replace_recovery_codes`;
- `disable_optional_totp`;
- `recover_mandatory_totp`;
- `list_sessions`;
- `revoke_session`;
- `revoke_other_sessions`;
- `block_account`;
- `unblock_account`.

### 5.2 `access` module

Responsible for:

- roles;
- exact permissions;
- role assignments and revocations;
- staff invitations;
- permission checks;
- initial creation of the security administrator.

It does not decide seller applications.

Public application operations:

- `check_permission`;
- `invite_staff_member`;
- `accept_staff_invitation`;
- `revoke_staff_invitation`;
- `revoke_staff_role`;
- `bootstrap_security_admin`.

A staff role is activated only by accepting a personal invitation or an initial invitation. No universal external operation for directly granting a role exists.

### 5.3 `seller_onboarding` module

Responsible for:

- application draft;
- versions;
- submission and withdrawal;
- review queue;
- decision and reason;
- seller-profile creation;
- single-owner association;
- seller-admission state.

Public application operations:

- `create_seller_application`;
- `update_seller_application_draft`;
- `submit_seller_application`;
- `withdraw_seller_application`;
- `start_seller_application_review`;
- `request_seller_application_changes`;
- `approve_seller_application`;
- `reject_seller_application`;
- `activate_seller_after_totp`;
- `suspend_seller`;
- `restore_seller`;
- `revoke_seller`.

### 5.4 `audit` module

Responsible for appending and reading permitted audit records.

Public operations:

- `append_audit_entry`;
- `query_audit_entries` for separately authorized staff viewing.

Changing or deleting an existing record through the application is prohibited.

### 5.5 `outbox` module

Responsible for:

- outgoing events;
- background jobs;
- retries;
- attempt state;
- manual review of an irrecoverable job.

Public operations:

- `enqueue_outbox_message` inside the domain transaction;
- `claim_ready_messages`;
- `mark_message_succeeded`;
- `schedule_message_retry`;
- `mark_message_for_manual_review`;
- `retry_message_from_manual_review` with a mandatory reason.

### 5.6 Dependency Rules

- `identity` does not depend on `seller_onboarding`.
- `access` references accounts only through the public identity interface and stable identifiers.
- `seller_onboarding` uses the `identity` and `access` interfaces, but they do not import `seller_onboarding` internals.
- each changing module may add an audit and an outbox record through their public interfaces;
- `audit` and `outbox` do not call domain operations covertly;
- circular dependencies are prohibited;
- a shared package is allowed only for genuinely shared primitives: identifiers, time, and basic result types; domain rules are not moved there.

Forms, Django Admin, commands, and the worker do not duplicate business rules. Django signals do not coordinate protected domain transitions. Each protected application operation checks the actor, their permission, and the current state itself; a preliminary check only in an external adapter is insufficient.

Boundaries are checked by an automated import test.

## 6. External Adapters

### 6.1 HTML

Minimal server-rendered Django pages:

- registration;
- email confirmation;
- sign-in and sign-out;
- password-reset request and execution;
- account security;
- second-factor enrollment;
- one-time display of recovery codes;
- session list and revocation;
- application draft and submission;
- application state, reason, and new version.

The page calls an application operation and does not change models directly.

### 6.2 Django Admin

Django Admin provides:

- application queue;
- viewing versions and reasons;
- calling permitted decision operations;
- staff invitations;
- account blocking;
- protected second-factor recovery;
- viewing permitted audit records and outbox problems.

Protected models are available for reading, but direct `save`/`delete` to bypass an application operation is prohibited.

### 6.3 Local Command

`bootstrap_security_admin` creates the first security administrator.

The command:

- works only when no active security administrator exists;
- accepts a specific email;
- does not accept or print a shared password;
- creates a one-time invitation;
- records an audit entry;
- does not create a second live initial invitation while the first awaits acceptance;
- after the initial invitation expires or is explicitly revoked, allows a new one to be created if there is still no active security administrator.

### 6.4 Email

The mail adapter receives an outbox message and sends the email.

Development uses a local test mailbox. No production provider is selected in this phase.

## 7. Domain Model

### 7.1 `Account`

Fields by meaning:

- stable identifier;
- canonical unique email: after outer whitespace is removed, the entire value is compared case-insensitively;
- Django's standard protected password hash, never the cleartext password;
- state;
- email confirmation;
- account kind: ordinary or service;
- creation and modification time;
- version for safe concurrent changes.

States:

- `pending_email_verification`;
- `active`;
- `blocked`.

Allowed transitions: `pending_email_verification` → `active` after email confirmation; `active` → `blocked`; `blocked` → `active` by a separate security-administrator decision. Self-blocking an administrator is prohibited. In the `blocked` state, the account must store the reason, administrator UUID, time, and UUID of the related audit record; when unblocked, the current fields are cleared and the history is preserved in immutable audit.

### 7.2 `Session`

- owner;
- unpredictable server-side session identifier that is not logged or shown to the user;
- creation;
- last activity;
- absolute expiry;
- idle expiry for a service session; not applied to an ordinary session in phase one;
- permitted device description;
- revocation time and reason.

### 7.3 `TotpCredential`

- owner;
- secret encrypted with integrity verification;
- confirmation time;
- whether it is mandatory for current staff roles or the seller profile;
- disable time, or no value for an active credential.

The encryption key is stored separately from the database and repository. The secret is available only to the TOTP verification operation, is not logged, and is not returned after enrollment is completed.

### 7.4 `RecoveryCode`

- owner;
- irreversibly protected value;
- time the set was issued;
- time used;
- time the set was revoked.

### 7.5 `OneTimeToken`

- purpose: email confirmation, password reset, or mandatory TOTP reconfiguration;
- account;
- irreversibly protected token value;
- creation and expiry;
- time used;
- revocation time and reason.

The cleartext value exists only when the link is created. A new token with the same purpose revokes all earlier active tokens for that purpose.

### 7.6 `StaffInvitation`

- specific email;
- specific role;
- creating administrator or system source `bootstrap`;
- irreversibly protected one-time token;
- creation and expiry;
- acceptance or revocation.

States:

- `pending`;
- `accepted`;
- `expired`;
- `revoked`.

Inviting an ordinary account by email is prohibited. A new invitation creates a service account; an invitation to an existing service account may add another independent staff role after sign-in with a password and TOTP.

### 7.7 `RoleAssignment`

- account;
- role;
- state;
- who assigned it and why;
- who revoked it and why;
- start and end time.

States:

- `active`;
- `revoked`.

Phase-one roles:

- `seller_reviewer`;
- `security_admin`.

Buyer capabilities are the basic capabilities of an active ordinary account. The seller owner is determined only by the association in `SellerProfile`, not by a second duplicate role. A service account may have both staff roles, but each is assigned and revoked independently.

### 7.8 `SellerApplication`

- applicant;
- current version;
- state;
- creation and submission;
- current reviewer;
- latest decision and reason.

States:

- `draft`;
- `submitted`;
- `under_review`;
- `changes_requested`;
- `approved`;
- `rejected`;
- `withdrawn`.

Allowed transitions:

- creation → `draft`;
- `draft` → `submitted` or `withdrawn`;
- `submitted` → `under_review` or `withdrawn`;
- `under_review` → `changes_requested`, `approved`, `rejected`, or `withdrawn`;
- `changes_requested` → `submitted` with a new version or `withdrawn`.

`approved`, `rejected`, and `withdrawn` are terminal states for a specific application. After `rejected` or `withdrawn`, an account without a seller may create a new application with a separate history. An account has no more than one application simultaneously in `draft`, `submitted`, `under_review`, or `changes_requested` states.

### 7.9 `SellerApplicationVersion`

Minimal test fields:

- business form: sole proprietor, legal entity, or self-employed;
- test display name;
- test official name;
- test registration identifier;
- contact email;
- confirmation that the test information is correct.

After submission, a version is immutable. Real documents and payment details are prohibited by the interface and test-environment instructions.

### 7.10 `SellerReviewDecision`

- application and version;
- decision;
- reason;
- reviewer;
- time;
- operation identifier.

Decisions:

- `request_changes`;
- `approve`;
- `reject`.

### 7.11 `SellerProfile`

- stable identifier;
- sole owner;
- approved application and version;
- state;
- reason for the current restriction;
- creation and modification.

States:

- `awaiting_owner_totp`;
- `active`;
- `suspended`;
- `revoked`.

Allowed transitions:

- creation directly in `active` if the owner has confirmed TOTP;
- creation in `awaiting_owner_totp` with transition to `active` after TOTP confirmation;
- `active` → `suspended` or `revoked`;
- `suspended` → `active` or `revoked`;
- `awaiting_owner_totp` → `revoked`.

`revoked` is a terminal state. Only the security administrator performs `suspend`, `restore`, and `revoke`, with a mandatory reason; changing seller status does not change the ordinary state of the owner account.

### 7.12 `AuditEntry`

- time;
- actor or system executor;
- actor role;
- action type;
- object and identifier;
- result;
- reason;
- request/operation identifier;
- permitted before and after information;
- source: HTML, Admin, command, or worker.

### 7.13 `OutboxMessage`

- stable identifier;
- type;
- format version;
- safe payload;
- idempotency key;
- creation;
- attempt count;
- next-attempt time;
- capture time, worker identifier, and processing lease expiry;
- state;
- last safe error;
- success time.

States:

- `pending`;
- `processing`;
- `retry_wait`;
- `succeeded`;
- `manual_review`.

An expired `processing` lease returns a message to safe retry processing. A successful message is not selected again; after retries are exhausted, a message moves to `manual_review`.

The mandatory TOTP recovery link uses a separate closed type `identity.mandatory_totp_recovery` version 1: the safe payload contains only `account_id` and `token_id`, while the encrypted delivery part contains only `recipient` and `absolute_token_url`. The cleartext token is not stored in the payload, audit, or database.

## 8. Invariants

1. After outer whitespace is removed, the entire email is compared case-insensitively and is unique in this canonical form.
2. The kind of a created account—ordinary or service—does not change.
3. An unconfirmed account cannot perform protected actions.
4. An ordinary account owns no more than one seller.
5. One seller has exactly one owner in phase one.
6. An ordinary account has no more than one unfinished seller application at a time.
7. A new application after `rejected` or `withdrawn` receives a new history; after `approved`, a new application is prohibited.
8. A service account is neither a buyer nor a seller owner.
9. Public registration never creates a service account or staff role.
10. A staff role arises only from an accepted personal or initial invitation.
11. The `seller_reviewer` and `security_admin` roles are assigned and revoked independently.
12. The mandatory second factor is enabled before a protected staff action and before seller activation.
13. Optional TOTP cannot be disabled while an active staff role or non-revoked seller profile exists.
14. Access to the email alone does not disable the mandatory second factor.
15. A recovery code is used no more than once.
16. A one-time token is accepted only for its own purpose, before expiry, and no more than once.
17. A submitted application version is immutable.
18. A staff member does not edit applicant data.
19. A reason is mandatory for an application decision and for changing seller admission.
20. Repeating approval of one version does not create a second seller.
21. Seller status does not automatically block the ordinary account.
22. The sole source of seller ownership is the owner association in `SellerProfile`; a staff role does not duplicate it.
23. Password change or reset, manual TOTP recovery, account blocking, and a staff-role change revoke affected sessions.
24. Audit contains no password, TOTP secret, recovery code, token, or other secret.
25. An existing audit record is not changed or deleted through the application interface.
26. The domain change, related audit, and outbox record are committed atomically.
27. An expired background-processing lease is recovered, and a job retry does not repeat the domain action.
28. An unexpected error does not leave a partially committed state.

## 9. Main Flows

### 9.1 Registration

1. Check neutral rate limits.
2. Remove outer whitespace and obtain the case-insensitive canonical email value.
3. Find the account by canonical email without disclosing the result to the user.
4. If the account does not exist, create an unconfirmed ordinary account, a one-time token, a registration audit record, and an outbox email in one transaction.
5. If the account is awaiting confirmation, revoke the previous token and create a new token, audit, and outbox email in one transaction and within the limits, without creating a second account.
6. If the account is already active or blocked, do not change its state or create a confirmation token.
7. Return the same neutral response in all cases.
8. A valid one-time link activates an awaiting account, revokes other confirmation tokens, and adds an audit record.

### 9.2 Sign-in

1. Check the password without disclosing whether the account exists.
2. Check blocking and email confirmation.
3. If a second factor is mandatory or enabled, request TOTP or a recovery code.
4. Create a new session and rotate the previous sign-in identifier.
5. Add a success audit record or safe failure metadata.

### 9.3 Password Reset

1. Accept the email and return a neutral response.
2. Create a limited one-time token and outbox email if the account is eligible.
3. Validate the link.
4. Set a new password.
5. Revoke all previous sessions and reset tokens.
6. Add an audit record and notification.

### 9.4 Second-Factor Enrollment

1. Require a recent password.
2. Create a secret and show the QR/value only until confirmation.
3. Check the first TOTP code.
4. Activate the credential.
5. Create a new set of one-time recovery codes.
6. Show the cleartext codes exactly once.
7. Add an audit record.

If a seller profile is awaiting TOTP, credential confirmation and profile activation are committed in one shared application transaction.

### 9.5 Managing Optional TOTP and Recovery Codes

1. Replacing the recovery-code set requires a recent password and the current TOTP or an unused recovery code.
2. A new set immediately revokes all previous codes and is shown in cleartext once.
3. TOTP cannot be disabled when an active staff role or non-revoked seller profile exists.
4. Permitted disabling of optional TOTP requires a recent password and the current TOTP or a recovery code.
5. After disabling, the credential and recovery codes are revoked, the other sessions are ended, and audit and notification records are created.

### 9.6 Manual Second-Factor Recovery

1. An ordinary email reset does not disable the mandatory protection.
2. Another security administrator starts a separate procedure only after manual re-verification, fresh reauthentication, and a mandatory verifiable basis; self-recovery is prohibited, and real documents are not used in the first local phase.
3. The target may only be an active account with a confirmed email, an active mandatory TOTP requirement, and either an active credential or a proven unfinished recovery with the former credential disabled and an unused recovery token. A blocked account is unblocked separately first; recovery does not change account state.
4. At administrative start, the old credential is immediately disabled, and all live sessions, old recovery codes, and unfinished TOTP setups are revoked or invalidated.
5. The previous active recovery token is revoked, and the user receives a new `OneTimeToken` valid for 30 minutes through `identity.mandatory_totp_recovery`.
6. An open administrator recovery procedure—an active mandatory TOTP requirement, no active credential, and an unused, non-revoked recovery token—closes ordinary sign-in and prohibits standard `begin_totp_setup`/`enable_totp`; the factor can be recovered only through the token-linked procedure, including reissuing an expired link. Initial mandatory TOTP enrollment without such a recovery token retains a separate limited setup flow.
7. Opening the link without signing in checks the token's purpose and expiry, then requires the current password; an email alone is insufficient. The token is not consumed yet.
8. An encrypted TOTP setup is created and linked exactly to this token and account; an ordinary setup is linked exactly to the server-side session instead.
9. Completion accepts only the linked fresh setup and the correct new TOTP code, atomically creates a new credential and 10 recovery codes, and consumes the token/setup.
10. The mandatory TOTP requirement remains; completion does not create a session or sign the user in automatically.
11. Start audit links the administrator, user, basis, and result; completion audit and outbox contain no secrets. Failed password or TOTP checks record only neutral HMAC fingerprints of the account and source; rate limiting for these attempts is added in Task 17.

### 9.7 Seller Application

1. An active ordinary account without a seller or unfinished application creates a draft.
2. It fills in only test fields.
3. It submits an immutable version.
4. Outbox creates a staff notification.
5. A reviewer takes the application for processing.
6. With `request_changes`, the applicant sees the reason and creates a new version.
7. With `reject`, the applicant remains a buyer and may create a new separate application.
8. With `withdraw`, the unfinished application becomes terminal, and the applicant may create a new separate application.
9. With `approve`, the decision, profile with a single owner, audit, and event are created in one transaction.
10. If the owner already has confirmed TOTP, the profile immediately becomes `active`.
11. Otherwise the profile receives `awaiting_owner_totp`; after TOTP confirmation it becomes `active` in one shared application transaction.

### 9.8 Changing Seller Admission

1. Only a security administrator starts `suspend`, `restore`, or `revoke`.
2. The operation requires recent confirmation, an explicit reason, and an allowed transition from the current state.
3. The profile change, audit, and outbox notification are committed atomically.
4. The new state is considered immediately by the next server-side permission check.
5. The owner's ordinary account remains active unless there is a separate basis for blocking it.

### 9.9 Staff Invitation

1. The security administrator selects one email and one role.
2. An ordinary account's email is rejected; the target may only be an unused email or an existing service account.
3. The system creates a single-use, time-limited invitation for one staff role and an email.
4. A new employee opens the invitation, creates a service account, sets a password, and confirms the email; before TOTP confirmation, the account has no staff role.
5. An existing service account signs in with a password and TOTP and accepts an additional role through a separate invitation.
6. After TOTP confirmation, role assignment, audit, and the applicable outbox message are committed atomically.
7. Re-accepting an accepted, expired, or revoked invitation is rejected; an already active role is not duplicated.

## 10. Initial Development Security Settings

These values are mandatory for phase-one tests, but are not a promise of external launch. A separate security review takes place before an external environment, and values may be tightened in a new specification version.

- email confirmation: 24 hours;
- password reset: 30 minutes;
- staff invitation: 24 hours;
- mandatory TOTP reconfiguration path: 30 minutes;
- recent reauthentication for a sensitive action: 15 minutes;
- recovery-code set: 10 one-time codes;
- password: 12 to 128 characters, phrases and spaces allowed, known common values prohibited;
- ordinary session: up to 30 days with immediate revocation available;
- service session: no more than 12 hours and no more than 30 minutes idle;
- failed sign-in: increasing delay after five attempts within 15 minutes, taking account and source into account;
- email retry: no more than three attempts per hour per purpose and an additional source limit;
- all values are configuration-driven and covered by boundary tests.

Indefinite account blocking solely because of someone else's failed attempts is prohibited.

## 11. Sessions

The user sees:

- creation time;
- last activity;
- permitted device description;
- current session;
- revocation option.

All affected sessions are revoked after:

- password change or reset;
- disabling optional TOTP;
- manual TOTP recovery;
- account blocking;
- staff-role change;
- detected compromise.

Revoking the current session ends the current sign-in.

## 12. Permissions

### Active Ordinary Account

- view and change their own security settings;
- manage their own sessions;
- create their own application when they have no seller and no other unfinished application;
- view all their own applications and their history;
- view reasons and create a new version;
- withdraw an application only from an allowed unfinished state.

### Seller Owner

In phase one, receives only the fact of ownership and a view of admission status. The server checks the owner association and the current `SellerProfile` state together. The catalog and trading actions are absent.

### Seller Reviewer

- see the queue and application versions;
- start a review;
- request changes;
- approve or reject;
- read related permitted audit records.

Does not create employees, recover TOTP, or change application data.

### Security Administrator

- create and revoke staff invitations;
- assign and revoke staff roles;
- block and restore accounts with a basis;
- perform the protected mandatory-TOTP recovery procedure;
- suspend, restore, and revoke seller admission with a mandatory reason;
- return a message from `manual_review` to retry only after review and with a mandatory reason;
- read related permitted audit records.

Does not review an application without a separate seller-reviewer role.

One service account may have both roles only as two independent assignments; having one role grants no permissions of the other.

## 13. Audit

The following are audited:

- registration and email confirmation;
- successful and failed sign-in attempts;
- password reset and change;
- TOTP enrollment, disabling, and recovery;
- issuing, replacing, and using a recovery code without storing its cleartext value;
- session creation and revocation;
- application creation and versions;
- submission, withdrawal, and decisions;
- seller creation and admission changes;
- staff invitation;
- role assignment and revocation;
- account blocking and restoration;
- moving outbox to `manual_review` and an authorized manual retry;
- protected worker actions.

The payload passes an allowlist: only predefined permitted fields are stored. Serializing an entire object or HTTP body into audit is prohibited.

## 14. Outbox and Background Jobs

The domain change, audit, and outbox message are saved in one transaction.

The worker:

1. in a short transaction selects `pending`, ready `retry_wait`, or `processing` with an expired lease;
2. safely locks the row, assigns an attempt, worker, and new limited lease, then commits `processing`;
3. executes the external adapter outside the long domain transaction;
4. in a new short transaction commits success or schedules a retry;
5. after a worker failure, the expired lease makes the message available for another claim;
6. after the permitted retries are exhausted, moves the message to `manual_review`;
7. does not lose the original safe payload.

The guarantee is at-least-once delivery. The handler must use the idempotency key.

Returning from `manual_review` is performed only by the security administrator through an application operation, is recorded in audit, and creates a new limited attempt, not a new domain object.

Phase one supports these types:

- email-confirmation message;
- password-reset message;
- staff invitation;
- internal application-submission-for-review event `seller_onboarding.application_submitted` version 1 with payload `application_id` and `version_id`, without delivery data;
- application-decision notification;
- protected-account-change notification;
- internal seller-admission creation or change event.

## 15. Errors

### Expected

- invalid field;
- unconfirmed email;
- invalid or expired token;
- invalid password/TOTP;
- prohibited state transition;
- missing permission;
- concurrent-change conflict;
- rate-limit exceeded.

The user receives a safe action without internal tracing.

### Unexpected

- the transaction is rolled back;
- the error receives a correlation ID;
- the log excludes secrets;
- the user sees a neutral message;
- the outbox is not considered successfully completed;
- confirmed state is not partially changed.

### Indeterminate External Result

If the mail adapter did not confirm delivery, the message remains ready for a safe retry. The system does not create a second domain token without necessity.

## 16. Testing

### 16.1 Domain Tests

- all allowed and prohibited account transitions;
- all allowed and prohibited application and seller transitions;
- only one unfinished application and new history after `rejected`/`withdrawn`;
- role combination and conflict;
- mandatory reason;
- single-use invitation, token, and recovery code;
- prohibition on disabling mandatory TOTP;
- independence of account and seller.

### 16.2 PostgreSQL Integration

- uniqueness of canonical email without regard to case;
- simultaneous submission of one application;
- concurrent creation of a second unfinished application;
- simultaneous decision by two reviewers;
- repeated approval;
- atomicity of decision/profile/owner/audit/outbox;
- outbox selection by multiple workers through safe locking;
- reclaiming `processing` after lease expiry;
- returning `manual_review` to retry only through an authorized operation with a reason;
- migrations on a clean and a previous schema.

SQLite is not used as a replacement for PostgreSQL in these tests.

### 16.3 HTML and Security

- CSRF for all changes;
- cookie flags;
- neutral response for an existing and an unknown email;
- session rotation at sign-in;
- revocation after password/TOTP/role changes;
- rate limits;
- prohibition on access through another user's identifiers;
- mandatory second factor;
- TOTP-secret encryption and absence of the encryption key from the database and repository;
- absence of secrets in responses, logs, and audit.

### 16.4 Django Admin

- reviewer sees and calls only permitted operations;
- security administrator does not automatically receive review permissions;
- direct bypass of the application operation is prohibited;
- every decision requires a reason and creates an audit record;
- only the security administrator changes the admission of an already-created seller.

### 16.5 End-to-End Scenarios

1. Registration → email → confirmation → sign-in.
2. Expired and reused links are rejected.
3. Password reset revokes previous sessions.
4. TOTP and recovery codes work; reusing a recovery code is prohibited.
5. Email without a recovery code does not disable mandatory TOTP.
6. The initial security administrator is created only once.
7. A staff invitation assigns one specific role once.
8. Draft → submit → changes → new version → approve.
9. Repeated approval does not create a second seller.
10. Reject leaves the ordinary account active.
11. A new application with a separate history is created after reject or withdraw, but only one is active at a time.
12. The security administrator suspends and restores a seller without blocking the buyer account.
13. A prohibited staff operation is blocked and audited.
14. Outbox retry and recovery after an expired lease do not repeat the domain action.
15. Audit reconstructs the chain and contains no secrets.
16. Block account revokes sessions.
17. The test database is actually restored to a separate database.

## 17. Local Environment

Docker Compose starts:

- `web`;
- `worker` from the same image;
- `postgres`;
- local test mailbox.

A separate profile runs tests and restoration.

Development secrets are located only in the untracked `.env`; `.env` is included in `.gitignore`, and `.env.example` contains only variable names and safe placeholders. The TOTP encryption key is not stored in the database, image, or fixtures.

The source documents and future repository remain under `D:\Open_Marketplace` until measurement proves that the working tree needs to move to the WSL filesystem.

Locally installed Python 3.11 is not used as the canonical project environment.

## 18. Completion Criteria

The phase is complete when all of the following are true simultaneously:

1. all five modules have explicit interfaces;
2. an automated test prohibits invalid dependencies;
3. the environment starts with one documented command;
4. all tests pass in Linux containers on PostgreSQL;
5. the complete user flow is demonstrated through real HTML pages;
6. the staff flow is demonstrated through Django Admin;
7. background emails pass through the outbox and local mailbox;
8. test database restoration has actually been performed;
9. audit reconstructs the action chain and contains no secrets;
10. a recorded security check has been completed, with no unresolved critical- or high-severity defects in its register;
11. secrets are absent from Git, images, logs, and fixtures;
12. the documentation allows a new operator to repeat startup and verification;
13. catalog, money, and real documents have not entered the scope.

## 19. Preliminary Future-Project Files

This is a logical structure for the future plan; the files are not created yet:

```text
open_marketplace/
  config/
  identity/
    application/
    domain/
    adapters/
    tests/
  access/
    application/
    domain/
    adapters/
    tests/
  seller_onboarding/
    application/
    domain/
    adapters/
    tests/
  audit/
    application/
    domain/
    adapters/
    tests/
  outbox/
    application/
    domain/
    adapters/
    tests/
  web/
    html/
  staff_admin/
  templates/
  static/
  tests/
```

The final plan may refine file names, but does not change domain boundaries without a new specification review.

## 20. Conditions for Moving to the Implementation Plan

The implementation plan is created only after:

1. checking this document for placeholders, contradictions, and ambiguities;
2. Vladislav confirms the written specification;
3. separate permission is given to create a Git repository at the agreed path;
4. current library documentation is checked through Context7;
5. exact compatible versions and a lock file are recorded;
6. it is confirmed that implementation remains one active phase and does not begin the catalog or payments.

Approval of this specification by itself does not create a repository, install packages, write product code, purchase cloud resources, or perform a deployment.
