# Open Marketplace — Concept and Architecture Specification

**Date:** 2026-09-02\
**Status:** approved by Vladislav without changes on 2026-09-02\
**Working title:** Open Marketplace; not a public brand\
**Source of detailed decisions:** `D:\Open_Marketplace\concept-protocol.md`

## 1. Purpose

Open Marketplace is a Russian commerce platform for independent sellers and buyers.

Public positioning:

> **A marketplace with sellers' own branded storefronts and protected transactions.**

The platform combines:

1. a shared catalog, search, and protected purchasing;
2. individual branded seller storefronts;
3. portable seller data through open formats and a documented API;
4. limited AI design tools;
5. seller verification, disputes, and protected payouts through a payment partner.

Core product balance:

- the seller retains the brand, independently set price, and ability to take their own data with them;
- the platform is responsible for access rules, the authoritative order state, buyer protection, and verifiable dispute resolution.

The official service is not open source: its source code remains closed. Data formats, schemas, version history, and the documented API are open. Therefore, the term *Open Source Marketplace* is not used for the public product.

## 2. Goals of the Russian Public Beta

The public beta is the first open launch in Russia with real registrations, orders, and payments, but with limitations published in advance.

Before opening, three areas must be combined:

1. **Seller tools:** verification, products, inventory, import, export, storefront, and sales.
2. **Buyer marketplace:** catalog, search, cart, protected purchasing, orders, disputes, and reviews.
3. **Open data infrastructure:** formats, API, import, export, synchronization, and secure integrations.

The complete protected cycle is validated for:

- physical products;
- downloadable files from the platform's managed storage.

The primary success criterion is reliability of the complete cycle:

`payment → order handover → fulfillment → payout → cancellation, return or dispute if needed`

A critical error in money, access rights, the order, digital delivery, or state recovery blocks recognition of the pilot as successful.

Turnover, seller activity, repeat purchases, and revenue are considered additionally, but do not replace reliability.

## 3. First-Version Boundaries

### 3.1 Included

- Russia;
- individual entrepreneurs, legal entities, and self-employed persons after applicable verification;
- a shared catalog and individual branded storefronts;
- physical products;
- downloadable files;
- purchases from multiple sellers with independent order parts;
- protected payouts through a payment partner;
- disputes, returns, verified reviews, and public metrics;
- free basic data portability;
- a limited API for the catalog and seller data;
- a public catalog of verified third-party applications;
- an AI designer as an optional limited beta.

### 3.2 Excluded

- international launch;
- a separate B2B channel for a major supplier and a local seller;
- license and activation keys, subscriptions, and online services as digital-fulfillment methods;
- management of the full order lifecycle through a third-party API;
- application access to payments, escrow, disputes, identity documents, and private messages;
- external digital-product delivery through a mutable link;
- video, audio, and complex AI effects;
- paid placement in the catalog and search;
- hidden behavioral personalization of results;
- a starting architecture based on microservices;
- built-in payment and subscriptions for third-party applications through the platform.

## 4. Architectural Approach

### 4.1 Modular Monolith

The first version is created as a single server application with independent internal modules and clear interfaces between them.

A microservice is not created in advance. A module may be extracted into a separate service only after a confirmed need for independent scaling, risk isolation, or a separate lifecycle.

The specific language, framework, database, cloud, and deployment scheme are selected after this specification and a separate technical study are approved.

The technical study is complete and approved: Python 3.13, Django 5.2 LTS, Django REST Framework, and PostgreSQL in the form of a modular monolith have been selected for the first phase. The full rationale is in `D:\Open_Marketplace\docs\research\2026-09-02-technical-stack-recommendation.md`.

### 4.2 Server as the Single Source of Truth

Only the server stores and changes:

- users, sellers, and permissions;
- listings, variants, and actual inventory;
- carts, orders, and their states;
- payment records, holds, refunds, and payouts;
- versions of digital files and access rights;
- disputes, decisions, and appeals;
- application connections and logs of their actions;
- the history of published listings and AI media.

The browser and future mobile applications display state and send commands, but are not the sole place where protected or shared data is stored.

### 4.3 Modules

1. Users, verification, and permissions.
2. Sellers, stores, and payment details.
3. Catalog, canonical products, offers, variants, and inventory.
4. Search, filters, and organic results.
5. Cart, shared order, and seller parts.
6. Payment accounting, holds, refunds, and payouts.
7. Physical fulfillment.
8. Digital fulfillment.
9. Disputes, quality, reviews, and reputation.
10. Storefronts and design systems.
11. Open formats, API, events, and integrations.
12. AI designer and media.
13. Notifications, monitoring, and auditing.

### 4.4 Background Operations

AI generation, media processing, imports, synchronization, notifications, and other long-running operations are performed by background workers.

Normal site operation does not wait for a long-running operation to finish. The user sees its status, result, or a clear error.

### 4.5 External Partners

Payment and logistics partners are connected through separate adapters with a common internal contract.

Replacing a partner must not require changing order rules in every module.

## 5. Core Domain Model

### 5.1 Participants

- **Buyer** — selects and pays for an order, receives it, opens a dispute, and leaves a verified review.
- **Seller** — an individual entrepreneur, legal entity, or self-employed person who has passed applicable verification.
- **Authorized account owner** — the sole user of the seller account in the first version.
- **Platform employee** — acts only within the assigned role; every action is logged.
- **Application developer** — responsible for their application, support, external payment, and refunds for the application.
- **Payment and logistics partners** — external systems whose state is reconciled through adapters.

### 5.2 Commerce Entities

- **Canonical product** — a shared listing for a demonstrably identical serialized product.
- **Seller offer** — the price, availability, delivery, condition, and commercial terms of a specific seller.
- **Standalone listing** — a unique offer or digital product without reliable matching; in the public beta, the only supported digital-fulfillment method is a downloadable file.
- **Variant** — a specific combination of attributes with its own inventory.
- **Inventory** — the single actual stock of a variant across the seller's storage locations.
- **Shared order** — a purchase that may include multiple sellers.
- **Seller order part** — an independently fulfilled, disputed, and returned part of a shared order.
- **Fulfillment** — physical delivery or delivery of the exact version of a downloadable file.
- **Dispute** — a formal investigation of a problem with evidence, a decision, and a possible appeal.
- **Review** — a rating linked to a verified order or verified use of an application.

### 5.3 Integration Entities

- **Third-party application** — a registered integration with a developer and verifiable data-handling rules.
- **Application permission** — the seller's separate consent to a specific action.
- **Event** — a signed notification of a change to permitted data with a stable identifier.
- **Application log** — an immutable history of actions by a specific integration.

### 5.4 AI Entities

- **AI storefront project** — the interview, selected direction, design system, and edit history.
- **Media source** — the seller's real source material.
- **AI version** — a separate verifiable result of processing or generation.
- **Order listing snapshot** — the exact listing and media available to the buyer at the time of purchase.

## 6. Mandatory Invariants

1. The seller independently sets the actual price.
2. Before payment, the server rechecks the price, inventory, delivery, and right to sell.
3. Publishing one variant in multiple storefronts does not create separate inventory.
4. Repeating an external request does not create a second order or refund or consume inventory a second time.
5. A monetary action has a verifiable history and the partner's external identifier.
6. An indeterminate partner response is not treated as success or failure without reconciliation.
7. A shared purchase is divided into independent seller parts.
8. A seller sees only their own orders and permitted buyer data.
9. Every digital-product order is linked to an exact verified file version.
10. A seller cannot silently change an already purchased file or order snapshot.
11. An open complaint and an unresolved dispute do not worsen a public metric until the event and responsibility are confirmed.
12. AI does not publish material without the seller's explicit confirmation.
13. An application does not receive the account password or a shared non-expiring key.
14. Revoking one application does not require disabling the other integrations.
15. Payment, advertising, or storefront design does not raise organic ranking.
16. The seller's own portable data is available free of charge.

## 7. End-to-End User Flows

### 7.1 Seller Onboarding

1. The seller selects a business form.
2. The seller provides official details, the authorized person's contact information, and permitted payment details.
3. The seller passes basic, category-specific, and, where necessary, enhanced verification.
4. After successfully completing the applicable checks, the seller receives the right to sell without a paid queue.
5. The seller creates or imports a catalog and receives a basic storefront.

### 7.2 Physical-Product Purchase

1. The buyer finds a product and offer.
2. Adding an item to the cart does not reserve inventory.
3. At checkout, the server rechecks the price, inventory, delivery, and restrictions.
4. A short reservation is created.
5. The payment partner confirms payment.
6. The order is passed to the seller and fulfilled.
7. After confirmation or the end of the published protection period, the payout is released.
8. If there is a problem, a dispute is opened with evidence and a possible refund.

### 7.3 Downloadable-File Purchase

1. The seller uploads the file to managed storage.
2. The platform checks the format and malicious content.
3. The published version receives an immutable record and checksum.
4. After payment, the buyer receives access to the exact version in the order.
5. Delivery, access, and error events are logged.
6. The payout is held for the published protection period.
7. A dispute uses the exact version, listing, system requirements, and delivery logs.

### 7.4 Dispute

1. The participant selects a specific reason and attaches available evidence.
2. The platform automatically adds the order state and applicable logs.
3. AI may prepare materials and identify risk, but does not make the final dispute decision.
4. An authorized employee applies the published rules.
5. Possible outcomes include denial, a partial refund, a full refund, or another outcome provided by law.
6. The participant receives the rationale and the available appeal procedure.

### 7.5 Application Connection

1. The seller sees the developer, purpose, price, data handling, and exact permissions.
2. Each permission is confirmed separately.
3. Critical permissions are time-limited and require reconfirmation.
4. Automatic changes operate only within the platform's mandatory limits; the seller may make them stricter.
5. All actions are logged and available to the seller.
6. An overreach is blocked; a repeated anomaly temporarily suspends critical permissions and starts an investigation.
7. The seller can immediately revoke only this connection.

### 7.6 AI Designer

1. A verified seller applies for the limited beta.
2. The seller completes a short interview and selects a visual direction.
3. AI creates a design system and a safe storefront assembly.
4. Real photographs are processed without distorting the product's properties.
5. An automated check compares the result with the source.
6. Low confidence or a material discrepancy blocks publication or routes it to a human.
7. The seller explicitly confirms publication.

## 8. Search, Pricing, and Fairness

### 8.1 Identical Product

Before sorting, offers without inventory, delivery to the address, or the right to sell are excluded.

The default order considers:

- delivery availability;
- total cost including delivery;
- timeframe;
- distance;
- verified fulfillment quality.

The buyer can sort separately by total cost, timeframe, distance, or rating.

### 8.2 Different Products

The following are considered first:

1. match to the query;
2. category and selected attributes;
3. availability for the address;
4. delivery;
5. verified fulfillment quality.

Separate sorting by total cost, recency, timeframe, and rating is available.

### 8.3 Transparency

- Factors are published.
- Numerical weights are determined after modeling and the pilot, before launch.
- Changes to weights receive a version, rationale, and advance notice.
- There is no hidden behavioral personalization in the public beta.
- The same explicitly specified context produces the same order.
- A new seller receives a neutral “insufficient data” label and enhanced initial monitoring.
- There is no advertising in the public beta.
- After the pilot, advertising is possible only in separate labeled blocks without affecting organic results.

### 8.4 Reference Price

The reference price is optional and does not replace the seller's price.

Until sufficient internal history exists, only a verified external source with a name and verification date is allowed. After sufficient history exists, a published formula based on the median of suitable completed transactions is used.

If the data is insufficient, outdated, or suspicious, the reference price is hidden or falls back to a recent verified source. An employee and AI do not assign an arbitrary value.

## 9. Portability and Open Infrastructure

### 9.1 Free Export

The seller can export their own portable data at any time:

- profile;
- catalog, listings, and variants;
- inventory;
- media they own;
- storefront settings;
- provenance of imported data.

Manual full export remains free regardless of the API plan.

### 9.2 Open Format

The following are published:

- the specification;
- machine-validatable schemas;
- reference examples;
- change proposals and discussions;
- decisions and the version log.

Changing an already published version retroactively is forbidden. A breaking change creates a new version and a transition period.

The specification and reference materials receive a permissive open license after legal review of the specific license text.

### 9.3 Initial-Launch API

The API supports:

1. reading the permitted public part of the catalog;
2. importing, exporting, and synchronizing the seller's own listings, prices, and inventory;
3. a safe link to checkout inside the platform;
4. signed events about changes to permitted data;
5. periodic reconciliation to recover missed events.

Full management of orders, payments, fulfillment, cancellations, and refunds through the API is designed only after a successful pilot, as a separate critical channel.

## 10. Third-Party Application Security

### 10.1 Admission

A private integration for one seller operates only with that seller's account and follows the common permissions, limits, and logging requirements.

Before public distribution, an application for multiple independent sellers undergoes checks of:

- the developer and contacts;
- the necessity of permissions;
- connection security;
- data storage, transfer, and deletion;
- the privacy policy;
- support;
- incident reporting.

Source code is not a mandatory uniform requirement for every application. Additional materials and testing are requested according to risk.

### 10.2 Permissions

- The platform publishes a permission-risk matrix.
- Minimal read access remains active until revoked and ends after a prolonged period of inactivity.
- Critical changes to prices, inventory, and other trusted data are time-limited.
- Expanding critical permissions requires new consent.
- The platform sets mandatory limits; the seller may only make them stricter.
- An operation outside the limits is rejected.

### 10.3 Monitoring and Incidents

The application is continuously monitored and rechecked after a material change or a new risk. High-risk applications also undergo scheduled reviews.

After a repeated anomaly, critical permissions are temporarily suspended. In the event of a material incident, affected access is restricted, evidence is preserved, participants are notified, and recovery occurs after a confirmed fix.

### 10.4 Application Catalog

Only admitted applications are published. The listing shows the developer, purpose, permissions, data handling, support, price, and verification date.

Only sellers with verified use can leave reviews. User ratings of quality and support are separate from the security status.

In the first version, the developer accepts payment outside the platform and is responsible for the application, support, cancellation, and refund of received payment. The platform is responsible for connection, permissions, security, the catalog, and complaints about rule violations.

When support ends, new connections are stopped. If there is no risk, sellers receive a limited transition period; then permissions are revoked and the developer confirms data deletion. Material risk is disabled immediately.

## 11. AI Designer and Media

### 11.1 Initial Limited Beta

Includes:

- a short interview;
- several visual directions;
- the seller's design system;
- storefront assembly from safe blocks;
- conversational edits;
- safe processing of real photographs;
- comparison of the result with the source;
- the seller's explicit confirmation.

Access to AI is not a condition of ordinary publication and sales.

### 11.2 Product-Image Rules

Background, lighting, cropping, and composition of the real source are allowed.

It is forbidden to silently change the product's shape, color, markings, contents, or other material properties.

Decorative banners and surroundings may be fully generated. If a scene shows a product for sale, the product itself must come from a real source.

### 11.3 Labeling and History

Fully created or substantially replaced AI content receives a public label. A simple technical correction without new visible content does not require a public label, but is retained in the history.

When an AI cover is used, the gallery retains a real image without synthetic additions.

The source and every published version are stored separately. A rollback creates a new record and does not erase the history.

### 11.4 Conditions for Expanding Access

Opening the AI designer to all verified sellers requires thresholds fixed in advance for:

- quality;
- security;
- stability;
- economics.

Video, audio, and complex effects are added by a separate decision after these conditions are met.

## 12. Errors and Recovery

### 12.1 Atomicity

A critical change completes in full or is not applied. A related group of imported data is not applied partially.

### 12.2 Safe Retry

Every repeatable external action receives a stable identifier. A retry after a network failure returns the existing result or safely continues the operation, but does not create a duplicate.

### 12.3 Indeterminate Partner Response

If the result of a payment, refund, or delivery is unknown, the operation enters a reconciliation-pending state. The platform requests the actual state from the partner and only then continues the order transition.

### 12.4 Synchronization Failure

For an invalid package, the last confirmed version is retained. The seller receives a visible delay status and a report of the affected data. An unconfirmed price or inventory after the safe period restricts sales of the corresponding offer.

### 12.5 Incident

1. Restrict the affected risk.
2. Preserve logs and evidence.
3. Notify participants.
4. Check the cause and scope.
5. Fix the issue and recheck it.
6. Restore access only after the fix is confirmed.

An appeal does not delay urgent temporary protection.

## 13. Observability and Auditing

The system must make it possible to determine:

- who performed the action;
- when it occurred;
- which object and version were affected;
- what the state was before and after;
- which request or event caused it;
- which external partner and identifier were involved;
- which rule caused the automatic restriction;
- who made the final manual decision and why.

Secrets, passwords, full payment details, and unnecessary personal data are not written to logs.

## 14. Quality Assurance

### 14.1 Testing Levels

1. **Module business rules:** permitted order transitions, permissions, reservations, payouts, refunds, and disputes.
2. **Module and data integration:** transactions, constraints, concurrent inventory changes, versions, and migrations.
3. **Adapter contracts:** payment, delivery, notifications, import, and public API.
4. **End-to-end scenarios:** a physical product and a downloadable file from seller registration through payout or refund.
5. **Security:** seller isolation, least privilege, access revocation, expiration, and reconfirmation.
6. **Resilience:** retries, delays, lost responses, partial partner unavailability, and background-operation recovery.
7. **Load:** catalog, search, checkout, concurrent inventory, import, and AI background tasks.
8. **Recovery:** verifiable restoration of data and working state after a failure.

### 14.2 Mandatory End-to-End Scenarios

- purchase of one physical product;
- purchase from multiple sellers;
- concurrent purchase of the last unit;
- payment failure and safe release of the reservation;
- loss of the response after a successful payment without a second charge;
- partial refund of one part of a shared order;
- dispute over a physical product;
- purchase and delivery of the exact file version;
- dispute over failure to deliver or file incompatibility;
- revocation of a critical application permission;
- redelivery of one event without a repeated change;
- safe hiding and recovery of AI media;
- recovery after a failure without losing confirmed state.

## 15. Preparation Sequence

1. Server foundation: identity, roles, permissions, sellers, auditing, and a single authoritative version of state.
2. Catalog, variants, inventory, search, and a minimal buyer interface.
3. Cart, order, payment adapters, physical and digital fulfillment, refunds, and disputes.
4. Full seller dashboard, import, export, and branded storefronts.
5. Open format, API, events, synchronization, and third-party applications.
6. AI designer and media as a limited beta.
7. Minimal analytics and automation for the public beta.
8. Combined legal, security, economic, and operational review of the Russian pilot.

This is not a detailed implementation plan. After the specification is approved, separate verifiable criteria and tasks are created for each stage.

## 16. Public Beta Admission Conditions

Before opening, the following are mandatory:

- a verified legal model;
- a selected payment partner with the required operations;
- published limits on order value and active offers;
- approved seller categories and documents;
- verified rules for physical delivery and digital delivery;
- published periods for protection, disputes, refunds, and payouts;
- monitoring, auditing, notifications, and incident procedures;
- working support, moderation, and appeal procedures;
- verified recovery;
- no critical errors in money, access, orders, or delivery;
- completion of the mandatory end-to-end scenarios;
- separate limits and criteria for the limited AI beta.

Limits are increased only after stable operation has been confirmed and participants have been notified in advance.

## 17. Decisions Requiring Research Before the Relevant Stage

These items are not hidden assumptions and must not be filled with arbitrary values:

1. The payment partner and the legal feasibility of holds, splits, and partial refunds.
2. The exact pilot commission after mandatory costs are calculated.
3. Permitted and prohibited categories and documents under Russian law.
4. Numerical limits for orders, active offers, reservations, disputes, and payouts.
5. Delivery services, proof of receipt, and the rules for seller-managed delivery.
6. Permitted formats, sizes, and retention periods for digital files.
7. Exact thresholds for the reference price and protection against manipulation.
8. The first version of the open format and the specific open license.
9. The first officially supported import sources.
10. The API-permission risk matrix, reconfirmation periods, and mandatory limits.
11. Numerical weights for organic results after modeling and the pilot.
12. Limits, prices, and criteria for the limited AI beta.
13. The technology stack, deployment, and detailed module interfaces.
14. Numerical success criteria for the Russian pilot.

Each decision is made before the dependent stage begins and receives a source, an owner, a verification method, and a review criterion.

## 18. International Expansion

An international date is not set in advance.

Stable operation in Russia is confirmed first. Then one country is selected, for which the following are addressed separately:

- law and taxes;
- payments and currency;
- localization;
- logistics;
- support;
- buyer protection.

The launch begins with a limited pilot in one country. Translating the interface is not enough.

## 19. Readiness Criteria for This Specification

The specification is ready to transition to an implementation plan if:

1. Vladislav has confirmed all seven sections of the concept.
2. The document does not contradict `concept-protocol.md`.
3. The document contains no hidden product decisions presented as technical details.
4. Unresearched numbers, partners, and legal questions are documented as mandatory inputs for the relevant stages.
5. The document is treated as a general architecture specification, not the scope of one implementation: each major phase receives a separate subordinate specification and plan; the first phase is the server foundation of the transactional core.
6. Implementation does not begin until this written specification is separately approved.
