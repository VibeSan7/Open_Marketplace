# Test and restore runbook

This runbook proves that a PostgreSQL custom-format backup can be restored into a separate disposable database and that the identity, access, seller and catalog graph remains internally consistent. Photos are archived separately and restored into a different temporary directory, not read from the original source directory.

It is a **test-environment proof**, not a production backup policy. It does not establish production RPO (maximum acceptable data loss), RTO (maximum acceptable recovery time), retention, encryption-key escrow, or off-site storage.

## Safety boundary

The workflow:

- uses only the `postgres-test` service from `compose.test.yaml`;
- makes `seed_restore_probe` fail before its first write unless the active host is exactly `postgres-test` and the database name starts with `test_` or `restore_source_`;
- stores PostgreSQL data on the service's `tmpfs` memory filesystem;
- creates unique source and target databases for each run;
- never mounts or connects to `postgres_data`;
- never runs Django's test runner against the restored database;
- runs source and target verification with PostgreSQL `default_transaction_read_only=on`;
- deletes the temporary databases, database dump, photo archive and both temporary photo directories on success or failure;
- removes any previous `restore-result.txt` before starting a new proof;
- fails and removes the published result if cleanup cannot delete a temporary database or file;
- saves only `artifacts/restore-result.txt`;
- outputs safe row kinds, UUIDs, invariant results, and migration leaf names;
- does not output email addresses, passwords, one-time tokens, TOTP secrets, recovery codes, encryption keys, or database credentials.

The local `.env` file must exist and remain ignored by Git. Do not copy its values into commands, documentation, logs, issues, or Pull Requests.

## Run the proof

From the repository root, first validate shell syntax:

```bash
bash -n ops/verify_restore.sh
```

Then execute the real backup-and-restore proof:

```bash
bash ops/verify_restore.sh
```

The script performs these steps:

1. starts `postgres-test`;
2. creates a unique source database;
3. applies migrations and seeds a linked account/role/seller/audit/outbox graph through public application interfaces;
4. verifies the source graph;
5. creates a custom-format dump with `pg_dump`;
6. restores the dump into a separate unique target database using `pg_restore --exit-on-error`;
7. checks that no migration is missing and verifies the restored graph;
8. verifies that the restored database fails its catalog photo check before photos are restored, then extracts the photo archive into a separate directory and verifies the complete target again;
9. atomically publishes the safe result file;
10. deletes source database, target database, temporary archives and temporary photo directories.

## Expected result

A successful run exits with code `0` and creates:

```text
artifacts/restore-result.txt
```

The file contains both sections:

```text
database=source
database=target
```

Each required invariant appears with `ok=yes`, including account, staff role/session, seller application/version/decision, audit, outbox, seller profile, catalog product/variant/photo/participant, and migration leaves. The result ends with `media=restored_from_archive` only after successful verification against the separate restored photo directory.

No file matching these temporary patterns may remain:

```text
artifacts/phase1_*.dump
artifacts/phase2_*.tar.gz
artifacts/restore-result_*.txt
```

The source and target databases must also be absent after the script exits.

## Failure handling

A missing row, relationship, terminal state, audit entry, outbox row, or migration causes a non-zero exit. Partial result files and the dump are deleted by the cleanup trap. Cleanup failure also forces a non-zero exit and removes the new result so leftover resources cannot coexist with a successful proof.

Do not publish a failed or partial artifact as proof. Diagnose the exact failed invariant, fix the implementation or environment, rerun the whole script, and retain only the successful final result.

## Production follow-up

Before production launch, define and test separately:

- encrypted backup storage independent from the primary database provider;
- retention and deletion schedules;
- key custody and recovery access;
- periodic restore drills from production-format backups;
- measured RPO/RTO objectives;
- alerting when backups or restore drills fail.
