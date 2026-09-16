# Open Marketplace — Working Decisions for Phase One

**Date:** 2026-09-02
**Status:** interview completed; written specification approved by Vladislav on 2026-09-02
**Basis:** `docs/superpowers/specs/2026-09-02-open-marketplace-design.md`
**Technology direction:** `docs/research/2026-09-02-technical-stack-recommendation.md`

## Goal of Phase One

Phase one must provide a self-contained working vertical flow:

1. a person registers and signs in;
2. confirms their contact information;
3. submits an application for seller status;
4. a marketplace employee reviews the application in the staff panel;
5. the system grants or rejects seller rights;
6. critical actions are recorded in audit;
7. access without the required permission is blocked.

The catalog, inventory, orders, and payments are not included in phase one.

## Approved: Registration and Sign-In

The primary account identifier is email. The user sets a password and must confirm ownership of the email before accessing protected actions.

Phone and SMS sign-in are not included in phase one.

## Approved: Two-Factor Authentication

The second layer of protection uses one-time authenticator-app codes, not SMS.

- it is mandatory for a marketplace employee;
- a seller must enable it before status activation;
- it is optional for an ordinary buyer.

## Approved: Second-Factor Recovery

When enabling the second factor, the user receives one-time recovery codes. If the device and recovery codes are lost, the seller or employee undergoes manual re-verification. Access to the email alone does not allow the mandatory second protection to be disabled.

Every use of a recovery code and every manual recovery is recorded in audit; a used code becomes invalid.

## Approved: Combining Roles

An ordinary account may simultaneously be a buyer and the authorized owner of one seller account.

A marketplace employee's service account is created separately, does not participate in purchases or sales, and cannot own a seller account.

Multiple owners or employees for one seller are not supported in phase one.

## Approved: Seller-Application Data

Phase one uses minimal fields and test data to verify the application's complete lifecycle.

Real identity documents, scans, payment details, and connection to an external verification system are not included. Their composition, storage, and processing are defined by a separate legal and security specification before sellers are admitted to production.

## Approved: Application Decision

A staff member can:

- approve an application;
- reject an application;
- request changes.

A reason is mandatory for every decision. The staff member does not edit the applicant's information. The applicant creates a corrected version themselves and resubmits it. The history of versions, decisions, and participants is preserved in audit.

## Approved: Staff Roles

Phase one has two separate staff roles:

- **seller reviewer** — views applications and makes decisions;
- **security administrator** — manages service accounts and manual recovery of protected access.

The reviewer does not create employees or disable the second factor. The security administrator does not review applications without a separate seller-reviewer role assignment.

## Approved: Audit

The immutable audit contains:

- registration and email confirmation;
- successful and failed sign-in attempts;
- password reset and change;
- enabling, disabling, and recovering the second factor;
- creation, completion, and revocation of protected sessions;
- creation of and every version of a seller application;
- every application decision and its reason;
- role assignment and revocation;
- account blocking and recovery;
- protected actions by employees and background workers.

The record contains the actor, time, action type, affected object, result, request identifier, and permitted before/after information. Passwords, recovery codes, tokens, secrets, and unnecessary personal data are not recorded.

## Approved: Session Management

The user sees a list of active sessions with permitted device information and activity time and can revoke an individual session or all other sessions.

Changing or resetting a password, manually recovering the second factor, blocking an account, and changing staff privileges end all affected sessions. A particularly sensitive action requires recent re-confirmation of the password and second factor if it is mandatory.

## Approved: Independent States

The state of a person's account and the state of the seller are stored separately.

Rejecting, suspending, or revoking seller status does not block the ordinary buyer account. Full account blocking is applied by a separate decision when there is a risk, compromise, or another specified basis.

The history of applications, roles, and decisions is not deleted by changing the current status.

## Approved: Employee Creation

The first security administrator is created by a one-time local command during initial environment setup.

Subsequent service accounts are created only through a personal invitation from an active security administrator. The invitation is single-use, time-limited, and tied to a specific email and assigned role. The employee sets their own password and enables the mandatory second factor before the first protected action.

Public acquisition of a staff role, a shared service account, a shared password, and automatic assignment to the first registered user are prohibited.

## Approved: Modular Approach

Phase one is built from vertical domain modules. HTTP, the staff panel, local commands, and background workers are external entry points and call the same application operations.

Business rules are not duplicated in views, serializers, forms, Django Admin, or signals. No universal role-and-approval builder is created.

## Approved During Written-Specification Review

- separate JSON endpoints were removed from phase one; Django HTML pages and Django Admin remain;
- only the security administrator can suspend, restore, or permanently revoke an already approved seller, with a mandatory reason and audit;
- after `rejected` or `withdrawn`, a new application with a new history is allowed, but only one unfinished application may exist at a time;
- outer whitespace is removed from an email, after which the entire value is compared case-insensitively.

## Interview Status

The interview and confirmation of the sections are complete. The written subordinate specification passed self-review and was approved by Vladislav on 2026-09-02.

## Project Confirmations

- Section 1 “Phase-One Architecture” was confirmed without changes.
- Section 2 “States and Mandatory Rules” was confirmed without changes.
- Section 3 “User Flows and Interfaces” was confirmed without changes.
- Section 4 “Security and Error Handling” was confirmed without changes.
- Section 5 “Testing and Completion Criteria” was confirmed without changes.

All five sections of the phase-one project and the final written subordinate specification were approved by Vladislav. The next stage is a detailed implementation plan without starting code.

## Approved: Phase-One Interface

An ordinary user receives minimal server-rendered Django pages for registration, sign-in, account security, and the seller application.

Employees work through protected Django Admin, which calls the same application operations and does not change protected models directly.

A separate React/Next.js interface is not created in phase one.
