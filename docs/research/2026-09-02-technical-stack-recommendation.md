# Open Marketplace — Technical Stack Recommendation

**Date:** 2026-09-02\
**Status:** approved by Vladislav without changes on 2026-09-02; no product code was created\
**Basis:** `D:\Open_Marketplace\docs\superpowers\specs\2026-09-02-open-marketplace-design.md`

## 1. Summary Decision

The following baseline stack is recommended for the first phase of Open Marketplace:

- **language:** Python 3.13;
- **server framework:** latest patched version of Django 5.2 LTS;
- **future HTTP API:** a compatible patched version of Django REST Framework after the first JSON channel appears; it is not installed in the local first phase;
- **primary database:** PostgreSQL;
- **architecture:** modular monolith;
- **background actions in the first phase:** a separate worker process and a reliable PostgreSQL table of jobs/outgoing events;
- **local environment:** Linux containers on Docker Desktop through WSL 2;
- **local environment orchestration:** Docker Compose;
- **public beta:** Linux containers with a Russian provider and managed PostgreSQL;
- **first-version search:** PostgreSQL capabilities without a separate search cluster;
- **do not add at startup:** Kubernetes, microservices, Redis, Kafka, Elasticsearch/OpenSearch, or a separate task broker.

This decision minimizes the number of infrastructure components while preserving the required properties: transactions, migrations, permissions, auditing, background retries, and verifiable recovery.

## 2. Why Django Was Chosen

Django 5.2 is an LTS release and receives security updates for at least three years after release.[1][26]

It officially supports Python 3.10–3.14; Python 3.13 was chosen as a conservative compatible foundation, not as the newest possible interpreter.[26]

Django's transition to a future annual release cycle does not cancel its previously stated support commitments for the 5.2 LTS branch.[25]

Django provides managed transactions, schema migrations, and a built-in administrative interface.[2][3][4] For an early marketplace, the administrative interface matters not as an end-user dashboard but as a protected operational tool for verifying sellers, investigating orders, and performing controlled manual actions.

Django REST Framework supports Django 5.2 and Python 3.13 and provides serialization, authentication, permission policies, and test HTTP clients.[27][28][29] After the JSON API appears, it is used only as the entry HTTP layer: order, inventory, payment, and permission rules must not live in views or serializers.

### Required Mitigation for Django's Weakness

Django applications do not by themselves guarantee strict isolation of domain modules. Therefore, the project introduces its own rules:

1. files are grouped by domain rather than by shared technical folders;
2. each module publishes a small explicit interface;
3. direct access to other modules' models and internal functions is forbidden except through approved interfaces;
4. dependencies between modules are checked by an automated test;
5. HTTP, Django Admin, and background workers call the same application operations;
6. business rules are tested without HTTP and without the administrative interface.

## 3. Why Not NestJS

NestJS provides modules, dependency injection, and good unit and end-to-end testing tools.[5][6]

However, working with SQL, migrations, and transactions depends on a separately selected ORM integration, while the official NestJS queue uses additional packages and a Redis-compatible server.[7][8] For the first small team, this adds several decisions that Django already covers with one integrated set of tools.

NestJS remains an acceptable option if a single TypeScript language across the entire product becomes the primary constraint or an experienced TypeScript team appears. At present, this does not outweigh the additional data and operations decisions.

## 4. Why Not Spring Boot

Spring Modulith can analyze the modular structure, check dependencies, and run tests for individual modules.[9][10]

Spring Boot also has mature support for Testcontainers and operational observability endpoints through Actuator.[11][12]

This is the strictest of the options considered for a formal modular monolith. It was not selected because of its higher complexity threshold, configuration volume, and maintenance cost for a small initial team. Returning to it would be justified if a strong Java/Kotlin team appeared or if formal corporate requirements emerged that Django could not satisfy without excessive customization.

## 5. PostgreSQL and Transactions

PostgreSQL remains the single source of truth for users, sellers, permissions, products, inventory, orders, payment records, disputes, and auditing.

PostgreSQL provides transaction isolation and explicit row locks.[13][14] The following rules are established on this basis:

1. one application operation opens one short transaction;
2. checking inventory and reserving the last unit are performed within one transaction;
3. locking is applied only to the specific rows being changed;
4. unique database constraints prevent a repeated external identifier and a duplicate idempotency key;
5. monetary amounts are stored in the smallest integer units of the currency, not as binary floating-point numbers;
6. allowed states and relationships are protected by database constraints and the application model;
7. an external network request is not executed inside a long database transaction;
8. an indeterminate partner response creates a reconciliation-pending state, not an assumed success or failure.

Django `transaction.atomic()` defines the transaction boundary, and actions after a successful commit are started through the `on_commit()` mechanism.[2]

### Migrations

The schema is changed only through versioned Django migrations.[3]

Every migration must have:

- application to an empty database;
- application on top of the previous version;
- a test verifying preservation of existing data;
- a separate solution for a long-running change to a large table;
- a tested release rollback plan that does not assume automatic loss of new data.

Manual changes to the production schema outside migrations are forbidden.

## 6. Background Tasks Without Premature Redis

The first phase uses PostgreSQL tables for:

- **outgoing events** — what must be sent after a confirmed change;
- **background jobs** — what must be performed outside the HTTP request;
- **attempts and errors** — retry state and the last safe reason for failure.

The domain change and outgoing event are recorded in one transaction. A separate worker process selects, locks, and processes ready rows. PostgreSQL explicitly states that `SKIP LOCKED` does not provide a consistent view of the data, but is suitable for multiple consumers of a queue-like table.[14]

The processing guarantee is **at least once**, not the unproven “exactly once.” Therefore, every handler must be idempotent: a safe retry does not create a second order, refund, email, or inventory change.

Redis, Celery, or a separate broker are added only after a measured limitation of the PostgreSQL queue or before AI/media workloads for which separate requirements emerge. They are not needed for the initial server foundation.

## 7. Data Testing

Transaction and integration tests run against real PostgreSQL, not SQLite. The following are tested:

- concurrent purchase of the last unit;
- repetition of an identical request;
- loss of the response after confirmation of an external operation;
- reprocessing of a background job;
- locking and release of a reservation;
- partial failure of a multi-seller purchase;
- migration of existing data;
- queue recovery after the worker process stops.

Fast pure business rules can be tested without a database. HTTP permissions are additionally tested with Django REST Framework tools.[28][29]

## 8. Deployment Scheme

### 8.1 Development and Early Environment

Minimum composition:

- application container;
- background worker container from the same image;
- local PostgreSQL;
- Docker Compose;
- separate test database.

Docker Compose describes a multi-container application with one set of files and supports separate production settings.[19][20]

### 8.2 Russian Public Beta

Before working with real money, the minimum production scheme is increased to:

- two identical stateless web application instances;
- a load balancer;
- a separate background worker with the ability to run a second one;
- managed PostgreSQL with a primary node and a replica;
- a private network between the application and database;
- S3-compatible object storage for files;
- centralized logs, metrics, and notifications;
- a separate test environment;
- an independent backup mechanism.

**Stateless** means that an application instance does not store the sole copy of user state on its disk. Restarting or replacing an instance does not lose a confirmed order.

Kubernetes is not required for this scheme. Docker Compose on controlled Linux nodes is sufficient until a measured need for a more complex orchestrator appears.

## 9. Selectel and Yandex Cloud

Selectel Managed Databases documents automatic backups, point-in-time recovery, monitoring, replicas, and failover.[21] For PostgreSQL, seven-day retention and recovery to a selected point within that period are documented; built-in copies cannot be downloaded.[22]

Yandex Managed Service for PostgreSQL also documents automatic backups, replication, and point-in-time recovery.[23][24]

### Recommendation

Working hypothesis for subsequent contract and pricing verification:

- primary application and managed PostgreSQL — Selectel;
- independent encrypted logical copy — S3-compatible storage in a separate environment, with Yandex Object Storage as a candidate.

This is not yet a contractual decision. Before selection, the following are mandatory:

1. a Russian legal review of data hosting and processing;
2. a cost calculation for two applications, the database with a replica, traffic, storage, and support;
3. verification of the private network and available regions;
4. definition of the RPO — the acceptable amount of data loss measured in time;
5. definition of the RTO — the acceptable recovery time;
6. verification of full recovery, not merely the presence of a backup file.

## 10. Backups

The cloud provider's built-in copy is not considered the only protection.

Two layers are used:

1. managed point-in-time recovery for PostgreSQL;
2. an independent encrypted logical copy in a separate storage environment.

Recovery is tested regularly in an isolated database. The test checks not only that PostgreSQL starts, but also the consistency of users, permissions, orders, inventory, monetary records, disputes, and background events.

PostgreSQL documents logical backups, file-system backups, and continuous WAL archiving for point-in-time recovery.[15][16]

## 11. Windows Development and Linux Release

Docker Desktop supports Linux containers through WSL 2; Docker recommends WSL 2 and separately documents file-system practices.[17][18]

The following were verified by reading on Vladislav's computer:

- WSL 2 is enabled;
- the Ubuntu distribution is running;
- Docker Desktop is running with the Linux engine through WSL 2;
- Docker Compose is available;
- the installed native Python is 3.11.

Therefore, local Python 3.11 is not used as the production foundation. Recommended mode:

1. the documents and future repository remain under `D:\Open_Marketplace`;
2. the application, migrations, and full test suite run in a pinned Python 3.13 Linux container;
3. PostgreSQL runs through Docker Compose;
4. secrets are stored only in `.env`, which is included in `.gitignore`; production secrets are supplied through the provider's secrets manager;
5. CI also runs on Linux;
6. if measurement shows unacceptable file-operation speed on `D:`, the working tree is moved to the WSL file system through a separate agreed decision, not in advance.

This keeps Windows as the workstation while making the execution environment match the Linux release environment.

## 12. Boundary of the First Subordinate Specification

The next specification covers only the server foundation:

- Django project structure and module rules;
- user identity;
- roles and permissions;
- the seller and sole account owner;
- auditing;
- idempotent commands;
- the outgoing-event and background-execution table;
- PostgreSQL, migrations, and the test environment;
- the containerized local environment;
- module-boundary checks.

It does not include the catalog, inventory, cart, payments, delivery, files, disputes, public applications, or AI. These parts receive their own specifications and plans later.

## 13. Decisions That Remain Input Conditions

Before creating the local plan for the first phase, the following must be approved separately:

1. creation of the Git repository and its exact path;
2. exact pinned versions of Python, Django, and PostgreSQL after verifying available images;
3. the dependency and lock-file management tool;
4. the format of automated module-boundary checks.

The Django stack from this report is already approved. Django REST Framework is not installed in the first phase because the approved user-facing result does not include a JSON API.

Before a separate plan for the external environment, but not before the local first phase, the following must be approved:

1. RPO and RTO values;
2. the primary and backup cloud environments;
3. the production secrets-storage solution.

None of these items authorizes deployment or spending without Vladislav's separate approval.

## 14. Final Verdict

**Django 5.2 LTS + PostgreSQL is the recommended foundation for the local first phase; Django REST Framework is approved for the future JSON API.**

The verdict is based not on Django's absolute superiority, but on its fit for the current constraints:

- small team;
- complex transactional domain;
- need for protected manual operations;
- requirement for minimal infrastructure;
- Windows development and Linux release;
- prohibition on premature microservices;
- need for verifiable recovery.

NestJS remains the second option if a single TypeScript language is prioritized. Spring Boot + Spring Modulith remains an option for a larger experienced JVM team.

The technical research completes the choice of direction, but it is not authorization to create a repository, write product code, or purchase cloud resources.

## Sources

[1] https://www.djangoproject.com/download — Django supported versions
[2] https://docs.djangoproject.com/en/5.2/topics/db/transactions — Django database transactions
[3] https://docs.djangoproject.com/en/5.2/topics/migrations — Django migrations
[4] https://docs.djangoproject.com/en/5.2/ref/contrib/admin — Django admin
[5] https://docs.nestjs.com/modules — NestJS modules
[6] https://docs.nestjs.com/fundamentals/testing — NestJS testing
[7] https://docs.nestjs.com/techniques/queues — NestJS queues
[8] https://docs.nestjs.com/techniques/database — NestJS database techniques
[9] https://spring.io/projects/spring-modulith — Spring Modulith
[10] https://docs.spring.io/spring-modulith/reference/testing.html — Spring Modulith testing
[11] https://docs.spring.io/spring-boot/reference/testing/testcontainers.html — Spring Boot Testcontainers
[12] https://docs.spring.io/spring-boot/reference/actuator/index.html — Spring Boot Actuator
[13] https://www.postgresql.org/docs/current/transaction-iso.html — PostgreSQL transaction isolation
[14] https://www.postgresql.org/docs/current/explicit-locking.html — PostgreSQL explicit locking
[15] https://www.postgresql.org/docs/current/continuous-archiving.html — PostgreSQL continuous archiving
[16] https://www.postgresql.org/docs/current/backup.html — PostgreSQL backup and restore
[17] https://docs.docker.com/desktop/features/wsl — Docker Desktop WSL
[18] https://docs.docker.com/desktop/features/wsl/best-practices — Docker WSL best practices
[19] https://docs.docker.com/compose — Docker Compose
[20] https://docs.docker.com/compose/how-tos/production — Docker Compose production
[21] https://docs.selectel.ru/en/managed-databases/about/about-managed-databases — Selectel Managed Databases
[22] https://docs.selectel.ru/en/managed-databases/postgresql/backups — Selectel PostgreSQL backups
[23] https://yandex.cloud/en/services/managed-postgresql — Yandex Managed PostgreSQL
[24] https://yandex.cloud/en/docs/managed-postgresql/operations/cluster-backups — Yandex PostgreSQL backups
[25] https://www.djangoproject.com/weblog/2026/aug/10/annual-release-cycle — Django annual release cycle
[26] https://docs.djangoproject.com/en/6.1/releases/5.2 — Django 5.2 release notes
[27] https://www.django-rest-framework.org — Django REST framework
[28] https://www.django-rest-framework.org/api-guide/permissions — DRF permissions
[29] https://www.django-rest-framework.org/api-guide/testing — DRF testing
