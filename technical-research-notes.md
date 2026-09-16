# Open Marketplace — Technical Research Notes

**Date:** 2026-09-02
**Status:** research completed and recommendation approved by Vladislav; no product code was created
**Basis:** `docs/superpowers/specs/2026-09-02-open-marketplace-design.md`

## Questions to Verify

1. Which server stack best supports a transactional modular monolith with clear module boundaries?
2. Which combination of database, migrations, and background tasks is more reliable for orders, inventory, payments, and auditing?
3. What deployment scheme is minimal for a public beta while still allowing backup and recovery to be tested?
4. How can convenient Windows development be preserved with a Linux release environment?

## Competing Hypotheses

### H1 — TypeScript / NestJS

**Pros:** one language shared with the future web interface, explicit modules and dependency injection, strict types.

**Risk:** transactions and migrations depend on the selected ORM; it is easy to assemble too many infrastructure packages.

**Initial confidence:** medium.

### H2 — Python / Django

**Pros:** mature ORM transactions, migrations, an administrative interface, and built-in tools for users and operations.

**Risk:** module boundaries and strict typing require additional discipline; background tasks usually add a separate tool.

**Initial confidence:** medium-high.

### H3 — Kotlin / Spring Boot

**Pros:** strong typing, a mature transactional ecosystem, stable interfaces, and good testing tools.

**Risk:** the highest complexity for Vladislav and a higher operational threshold for a small initial team.

**Initial confidence:** medium.

## Comparison Criteria

- correctness of transactions and concurrent changes;
- natural support for a modular monolith;
- migrations and data schema;
- background tasks and safe retries;
- testing and isolation of external adapters;
- security and administrative operations;
- development and maintenance complexity;
- Windows development and Linux release;
- dependence on a large number of packages;
- a growth path without premature microservices.

## Conclusion

Python 3.13, Django 5.2 LTS, Django REST Framework, and PostgreSQL in the form of a modular monolith are recommended.

For the initial server foundation, background actions run in a separate worker process through reliable PostgreSQL tables; Redis and a separate broker are not added without measured need.

Local development and the full test suite run in Linux containers on Docker Desktop through WSL 2. For the public beta, managed PostgreSQL in a Russian cloud, a replica, an independent encrypted copy, and recovery testing are recommended.

The cited report and full rationale:

`D:\Open_Marketplace\docs\research\2026-09-02-technical-stack-recommendation.md`
