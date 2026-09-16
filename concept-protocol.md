# Open Marketplace Concept Protocol

**Status:** working product-idea protocol, not a final specification or development plan\
**Recorded:** 31 August 2026\
**Purpose:** preserve the decisions from the current discussion, separate them from proposals, and list the questions that still need to be resolved.

**Working project name:** Open Marketplace. It is used exclusively inside the project to designate the concept and must not be presented as the public brand or final product name.

## Definitions

- **Approved** — a decision made by Vladislav.
- **Working hypothesis** — a recommended direction that can still be changed.
- **Open question** — a decision has not yet been made or requires research.

---

## 1. Brief Product Description

A Russian marketplace is being created for independent sellers and buyers. It combines:

1. a common marketplace with a catalog, search, and protected purchasing;
2. individual branded seller storefronts;
3. portable seller data through open formats and a documented API;
4. AI tools for designing a store and creating product cards, images, and video;
5. seller quality control, dispute resolution, and protected payouts through a payment partner.

The central idea is to combine seller freedom with the platform's responsibility to the buyer.

### Approved Public Positioning

> **A marketplace with sellers' own branded storefronts and protected transactions.**

This is the main message for a first introduction to the product. The AI designer, data portability, open API, and commission of up to 10% are explained as subsequent benefits rather than being mixed into one overloaded statement.

**Working slogan:** “Freedom for the seller. Protection for the buyer.”

The slogan has not yet been approved as a name or advertising statement.

### Approved: Public Brand Architecture

The public name must be short, neutral, and memorable. It does not have to literally contain all of the product's properties at the same time.

The three main meanings are conveyed through the slogan, description, and presentation:

1. trust and protected purchasing;
2. seller freedom and individuality;
3. open data formats and a documented API.

The public name itself has not yet been chosen. The type of name has been approved: one existing English or internationally understandable word, rather than a coined word or a descriptive phrase. It must be easy for a Russian-speaking user to pronounce.

Before approval, candidates must be checked for comprehensibility, pronunciation, undesirable meanings, domains, matches with existing services, and the possibility of legal trademark protection.

**Deferred:** Vladislav decided to return to the public name later. The semantic field and specific candidates are not being selected yet; Open Marketplace remains only the internal working name.

---

## 2. Terminology and the Boundary of Openness

### Approved

The official service's source code remains closed. Data formats and the API are what become open.

Therefore, the product cannot be called **Open Source Marketplace**: the term *open source* means open program code distributed under an open license.

The correct working definition is:

> **An open marketplace is a closed service with open data formats and a documented API.**

An API is a documented interface through which other programs can safely exchange data with the platform.

### Public Part

The following are planned to be made open:

- seller profile format;
- catalog and product-card format;
- product-variant format;
- inventory format;
- attributes and media format;
- import and export rules;
- API and event description;
- integration toolkits;
- format version history.

### API Scope at the First Public Launch

By the first public launch, the API must support three levels:

1. reading the permitted public part of the catalog;
2. importing, exporting, and synchronizing seller data, including the catalog, prices, and inventory;
3. allowing a third-party site to create a secure link that takes the buyer to protected checkout inside the platform interface.

The third-party site does not determine the trusted price, inventory, or total amount: before payment, the platform retrieves them again from its own authoritative version of the data and displays them to the buyer.

Full order creation and lifecycle management, including fulfillment, cancellations, and returns, through a third-party API are not part of the first public launch. This level will be designed after a successful pilot as a separate critical channel with its own security and access-control review.

### Free Basic API and Paid Tiers

Documentation, machine-readable schemas, a test environment, reading the permitted public part of the catalog, creating secure checkout links, and a seller's work with their own portable data are available through the API free of charge within reasonable safe limits. A full manual export of one's own portable data remains free regardless of the API tier.

Higher request frequency and volume, managed connectors, very frequent synchronization, advanced monitoring and operation history, and a guaranteed level of availability and support may be paid features. Exact limits and prices are determined after measuring load and cost; they must not turn obtaining one's own data into a paid exit from the platform.

Each third-party application is connected to a seller separately. Before connecting, the seller sees the application's identity and the exact set of requested permissions, such as reading the catalog, changing prices, changing inventory, or receiving events, and explicitly confirms them. Expanding critical permissions requires a new confirmation. The account password is not given to the application, and one shared, perpetual key is not used for different integrations. The seller can see each application's activity log and immediately revoke only that application's access without changing the password or disabling other connections. The exact technical protocol is determined during the architecture stage.

The seller may create a private integration for their own account without a mandatory manual platform queue, while retaining the common constraints on permissions, limits, and logging. An application that a developer offers for connection by several independent sellers must register and pass a security and rules-compliance review before public distribution. Approval of an application does not give it permissions without the separate consent of each seller and may be suspended when a substantiated risk is identified.

Before approving an application for multiple sellers, the platform checks the developer's identity and business contacts, the scope and necessity of the requested permissions, the technical security of the connection, the stated rules for data storage, transfer, and deletion, the privacy policy, the support channel, and the incident-reporting process. A critical expansion of permissions requires a repeat review. Submission of all source code is not a single mandatory condition for every application, but in the presence of elevated risk the platform may request additional verifiable materials and tests. Approval confirms that the published minimum controls were passed, but it is not a guarantee of the developer's business quality.

When a credible security incident occurs, the platform immediately restricts the affected permissions or disables the application if retaining access creates a significant risk. It preserves logs and evidence, revokes compromised access, notifies the developer and affected sellers, and conducts an investigation. The connection is restored only after a confirmed fix and any required repeat review. The developer may appeal the decision, but an appeal does not delay urgent user protection. The initial report alone does not mean that the application will be permanently removed without an investigation.

After approval, the application remains under continuous automated monitoring. A repeat review is mandatory after a critical expansion of permissions, a change of ownership or a substantial infrastructure change, a material change in data-storage, transfer, or deletion rules, a confirmed incident, or the emergence of a new significant risk. High-risk applications also undergo scheduled periodic reviews. The interval and risk criteria are established before launch based on the threat model and operational data.

Minimum read permissions remain active until revoked by the seller, with the connection continuously visible, and expire after a predetermined prolonged period of inactivity. Permissions to change prices, inventory, and other trusted data are time-limited and require the seller's periodic explicit reconfirmation. Failure to reconfirm ends only the application's expired permissions and does not transfer control to the developer or support. Exact periods are established before launch based on the risk level and operational data.

The platform publishes a single permissions-risk matrix: for each available action, it specifies the risk level, validity period, and need for reconfirmation. The same permissions receive the same rules for comparable integrations. The matrix is approved by those responsible for security and product, and reviewed based on incidents, new threats, and operational data. No application developer, seller, or individual employee may unilaterally downgrade a permission's criticality.

The first public version of the API allows reading the open catalog and, after the seller's separate consent, managing only that seller's own cards, prices, and inventory. It does not give third-party applications access to payments, escrow, disputes, identity documents, or private messages. Extending the API to these areas requires a separate product decision, threat model, legal review, and new user consent.

After receiving the relevant permissions, an application may automatically change prices and inventory only within the explicitly granted scope and the seller's and platform's protective limits. Every change is recorded in an immutable log, made visible to the seller, and has an understandable source. Exceeding the permitted limits is blocked or requires the seller's separate confirmation. The seller receives notifications about significant changes, can immediately revoke access, and can restore the previous value if it is still permissible under the product's current state.

The platform sets mandatory safe limits for automatic changes and recommended default values. The seller may make them stricter for the account or an individual application, but may not weaken a mandatory platform limit. Specific numeric values are determined before launch after risk modeling and are tested during the pilot.

An operation that exceeds a protective limit is rejected. After repeated excesses or other anomalous behavior, the platform automatically suspends the application's critical permissions, notifies the seller and developer, and starts a review. Safe reading may continue only when it is unrelated to the identified risk. Critical permissions are restored after the seller's explicit confirmation for an understandable non-critical reason, or after a platform review when the cause or risk requires investigation.

For catalog, price, and inventory changes, the platform sends the application signed event notifications. The signature allows the application to verify the message's source and integrity. Periodic reconciliation of the permitted state recovers missed notifications. Every event has a stable identifier, and redelivery of the same event must not apply the change again.

The platform maintains a public catalog of approved third-party applications. Each listing shows the verified developer, purpose, exact requested permissions, rules for data storage, transfer, and deletion, support channel, price, and date of the latest review. Private integrations for a single seller are not published in the catalog. Approval and review information mean that the published minimum controls were passed, but are not a guarantee of the developer's business quality.

Only a seller who actually connected an application may rate and review it. The review is marked as verified use. Ratings for usefulness, reliability, and support are shown separately from the security-review status and cannot raise or replace it. Rules against manipulation, removal, and appeals of reviews are applied through the platform's general verifiable procedure.

In the first version of the catalog, the developer of a paid application independently issues invoices and accepts payment outside the platform. Before connection, the application listing clearly shows the price, payment period, payment method, cancellation terms, and party responsible for refunds. The platform is not the seller of such an application and does not withhold a commission from its payment. Built-in subscriptions, commissions, refunds, and payment disputes for applications require a separate product, legal, and technical decision after demand has been tested.

The developer is responsible for the application's operation, commercial support, invoicing, subscription cancellation, and refunding payments received by the developer. The platform is responsible for secure connection, granting and revoking permissions, its own logs, the application catalog, and reviewing complaints about rule violations. These boundaries of responsibility and contact channels are shown to the seller before connection. The platform retains the right to restrict an application in response to risk or a violation, but does not promise a commercial refund of money it did not receive.

If the developer stops supporting the application, the platform stops new connections and gives active sellers advance notice. In the absence of a significant risk, sellers receive a limited transition period to export data, disconnect, and choose a replacement. After the period ends, permissions are revoked, and the developer must confirm deletion of the received data under the published procedure. In the presence of a significant risk, access is disabled immediately, and export is performed securely from the platform's data when possible.

### Closed Part

The following remain closed:

- the official platform server;
- the AI designer;
- anti-fraud and internal risk assessment;
- the dispute and moderation system;
- payment logic;
- operational infrastructure.

### Access Principle

An open format does not make the data itself public. Only the owner or a system explicitly authorized by the owner receives access to the data after permissions are checked.

### Separate Wholesale B2B Flow

#### Approved

Wholesale trade between a large supplier and local sellers is a separate **B2B flow** (*business-to-business* — trade between companies and other business entities).

The relationship `large supplier → local seller` is separated from the retail relationship `seller → end buyer`. The B2B flow cannot be treated as merely a large order in an ordinary buyer cart or automatically subjected to all retail-transaction rules.

The exact participant roles, admission conditions, wholesale prices and lots, documents, payments, logistics, and returns have not yet been defined and must be agreed separately.

#### Approved: Introduction Stage

Live B2B transactions are not part of the first public retail launch. First, the platform must successfully complete the retail pilot and confirm the reliability of the full order, payment, return, and dispute cycle.

At the same time, the data model and module boundaries of the first launch must not exclude the later addition of a B2B flow or require it to be mixed with the rules of a retail transaction. After a successful retail pilot, the wholesale B2B flow is designed and launched as a separate pilot with its own specification.

---

## 3. Product Values

### For the Seller

- their own individual storefront;
- a portable profile and catalog;
- portable cards, variants, inventory, and media;
- a transparent commission;
- no dependence on one platform's closed internal format;
- AI tools for design and content creation;
- analytics, automation, and integrations.

### For the Buyer

- an understandable origin for ratings and reviews;
- protected payment;
- platform assistance in a dispute;
- oversight of discrepancies from the description, defects, and deadlines;
- consistent, understandable trust elements in any storefront design;
- the ability to buy physical and digital goods, subscriptions, and services.

---

## 4. Scope of the Public Pilot Launch

### Launch Terms

The pilot is the first public launch, in **public beta** status. Registration is open, and transactions and payments are real, but limits published in advance apply to participants and operations. Beta status does not permit weakening the protection of money, orders, access rights, or personal data.

In public beta, a single temporary maximum order value applies to physical goods and downloadable files. The exact amount is determined and published before launch after selecting a payment partner, calculating potential loss, and reviewing the refund scheme. The limit may be increased only after stable operation has been confirmed; participants are notified of the change in advance.

Each seller is also subject to a single temporary maximum number of active listings. Draft and archived cards are counted separately and are not considered available for purchase. The exact number of active listings is determined before launch based on load-test results and an assessment of moderation capacity. During public beta, a paid tier does not increase this limit.

After the successful-pilot criteria have been met, critical bugs have been fixed, and operational readiness has been confirmed, the platform moves to a full general release without pilot restrictions. Hereafter in this document, “pilot” and “first public launch” refer to the same public beta; “full release” refers to the next stage.

### Approved

All three directions must be ready for the public pilot launch:

1. **Seller tools** — data portability, product management, storefront, and sales.
2. **Buyer marketplace** — common catalog, search, cards, cart, protected purchasing, orders, disputes, and reviews.
3. **Open data infrastructure** — formats, API, import, export, and synchronization.

This does not mean that all subsystems must be developed simultaneously. Within the project, they are created in stages and connected before public release.

### Approved: AI Designer at Launch

The AI designer launches on the day of the public launch as a limited beta.

Access to the beta is granted by application to selected sellers who have already passed the platform's review. Lack of access to the AI designer does not limit ordinary product publication or sales.

The initial beta includes:

- a short text interview;
- several visual directions to choose from;
- creation of the seller's design system;
- assembly of the storefront from safe blocks;
- conversational edits;
- safe processing of real product photographs: background, lighting, cropping, and composition;
- comparison of the result with the source and seller confirmation before publication.

Video, audio, and complex visual effects generation are not included in the initial beta and are added later after the core cycle has been tested.

During the limited beta, access is free for selected participants, but strict usage limits apply. Participants are shown their available remaining allowance and the beta terms in advance; there are no hidden charges.

After the beta, the basic payment model is a subscription with an included allowance and additional credits beyond the allowance. Exact allowances and pricing are determined after measuring the actual cost and quality of generations.

### Approved: Conditions for the AI Designer to Exit Limited Beta

To open the AI designer to all verified sellers, four mandatory conditions must be met simultaneously:

1. **Quality** — the seller receives a usable result without an unacceptable amount of repeated generation and manual reworking.
2. **Safety** — the system must not invisibly distort product properties or publish prohibited and dangerous content; the seller confirms the result before publication.
3. **Stability** — the core cycle of creation, editing, review, and publication operates reliably and recovers from failures without losing the project.
4. **Economics** — the measured cost of generation and support fits within the future subscription, allowances, and additional credits without hidden charges.

The planned date, beta duration, or number of participants do not replace these conditions on their own.

Numeric thresholds for quality, safety, stability, and economics are determined after the internal prototype and the first limited-beta data have been obtained. They must be recorded before the decision to open the AI designer to all verified sellers, so that the decision is assessed against criteria established in advance rather than metrics selected after the fact.

### Main Criterion for a Successful Russian Pilot

The main criterion is the reliability of the full order cycle, not turnover or the number of registrations.

The pilot must confirm through real orders that the following work reliably for physical goods and downloadable files:

- payment;
- handoff of the order to the seller;
- fulfillment and confirmation of the result;
- payout to the seller;
- cancellation and refund;
- opening and resolution of a dispute;
- preservation of money, order data, and action history.

Critical errors in the movement of money, access rights, product delivery, or state recovery must prevent the pilot from being deemed successful. Seller activity, repeat purchases, turnover, and platform revenue remain mandatory additional metrics.

Exact numeric thresholds and the measurement period are determined before the pilot begins.

---

## 5. Geography

### Approved

The first public launch is in Russia only.

At the same time, the architecture must immediately separate:

- country;
- currency;
- language;
- category rules;
- payment partner;
- logistics partner.

This will allow other countries to be added later without reworking the common core.

### Approved: Conditions for Expansion to Other Countries

The platform does not set a calendar date for international expansion in advance. First, it must confirm stable operation in Russia according to the criteria for the pilot and full release. Then one next country is selected, for which law and taxes, payments and currency, localization, logistics, support, and buyer protection are separately checked before launch. Entry begins with a limited pilot in that country; a technical interface translation alone is insufficient.

---

## 6. Categories and Types of Listings

### Approved

The platform is not limited to one narrow product niche. A common core with additional fields for different categories is used.

### Seller Admission

The first wave admits any seller who has passed the review and operates in an allowed category. Previous sales experience on Ozon, Wildberries, or another platform is not required.

In public beta, each seller automatically becomes able to sell immediately after successfully completing all applicable reviews. There is no additional activation queue, manual batch selection, or paid place in the queue. An application that is still under review or requires additional documents is not considered to have successfully completed the review.

Permitted seller forms are: individual entrepreneur, legal entity, or self-employed person.

Seller review has three levels:

1. **Basic level for everyone** — verification of the person or organization, active status, contact details, and payment details.
2. **Category requirements** — product documents or proof of the right to sell where required by law or platform rules.
3. **Risk-based enhanced review** — manual analysis and additional confirmations for suspicious data, a higher-risk category, or a problematic history.

The exact list of documents and risk criteria must be defined after legal review.

### Registration and Payout Details

The seller registers using the official data for their status, not only an ordinary user profile.

During registration, the seller provides:

- business form: individual entrepreneur, legal entity, or self-employed person;
- official name or designation;
- identification and registration data applicable to the selected status;
- contact details for an authorized person;
- bank details for payouts accepted by the selected payment partner.

After successful fulfillment of an order, the payment partner transfers the amount due to the seller using the verified details, taking commissions and refunds into account.

The term “settlement account” is not used as a single requirement for all seller forms: the exact type of permitted account and the verification method depend on the seller's status and the payment partner's rules.

### Buyer Registration

For an ordinary purchase, confirming a phone number or email address is sufficient. Full identity verification is not required for every buyer.

Additional verification is applied only in the presence of a substantiated risk, a disputed transaction, or where the rules of a specific category require it. The risk criteria and list of such transactions are defined separately.

Examples of extensions:

- clothing — size, color, size chart;
- furniture — dimensions, weight, material, assembly;
- other categories — their own set of attributes.

### Physical Module

It is responsible for:

- product variants;
- inventory;
- warehouses;
- delivery;
- returns;
- confirmation of receipt.

During the pilot, products are stored by the seller; the platform does not create its own warehouse or fulfillment operation.

Two delivery methods are allowed:

1. a delivery service connected to the platform;
2. the seller's own delivery.

In both cases, receipt must be confirmed by a verifiable event: the integrated service's status, a pickup code, or the buyer's explicit confirmation. The seller's one-sided “delivered” mark is not sufficient for an automatic payout.

For the seller's own delivery, the primary confirmation method is a one-time code created by the platform and available to the buyer. The buyer gives the code to the seller when the product is actually handed over, after which the seller enters it into the order.

The code records the fact and time of receipt, but does not confirm product quality or deprive the buyer of the subsequent period for opening a dispute. This period begins after the handover is confirmed.

### Return-Shipping Cost

In public beta, the platform arranges return shipping for a physical product through a verifiable channel and, when necessary, advances the cost from a limited fund so that the buyer does not have to wait for dispute resolution or arrange payment with the seller independently.

After the cause is established, the final cost is assigned to the responsible party: the seller in the event of a confirmed defect, wrong product, or material discrepancy; the delivery service in the event of its confirmed fault and the ability to recover the cost under the contract; or the buyer in the event of an allowed return of an undamaged product based on a personal decision. If actual recovery is impossible, the uncovered amount is treated as platform risk within the pre-approved liability limit.

Before return shipment is confirmed, the buyer is shown the delivery method, full cost, and the party provisionally considered responsible. After the dispute is decided, the platform recalculates the amount and records the basis in the order log.

This is a preliminary product policy. A specialist lawyer must review it; the buyer's mandatory rights take priority.

### Timing of the Refund

After the return is approved, the buyer hands over the product through a verifiable channel. After confirmed delivery, the seller has 2 business days to check its condition and completeness.

If the seller confirms the return or does not submit a specific, substantiated objection with evidence within this period, the payment partner automatically refunds the buyer. A request for additional time without a demonstrable reason does not extend the period. A timely objection opens a dispute in which the platform reviews both parties' evidence. The seller's silence cannot delay the refund.

The minimum set for a seller's objection includes the return number and carrier details, photographs of the outer packaging before opening, photographs of the product, its completeness, seals, and available unique identifiers immediately after opening, an exact description of the discrepancy, and the original data about the shipped product for comparison. If damage during return shipping is alleged, the carrier's report is attached when it can be obtained. Continuous opening video is additional but not mandatory evidence. No item has predetermined decisive force: the moderator compares the entire order log and the evidence from both parties.

To open a dispute about a physical product, the buyer selects a specific reason, describes the difference between what was promised and what was received, and attaches available photographs of the product, packaging, markings, contents, and visible defect. Carrier data or messages and the product's unique identifier are attached when they relate to the problem. An unboxing video and an expert opinion are additional but not mandatory materials. The platform automatically adds the product listing and terms at the time of purchase, the order log, and available delivery data. For a concealed or technically complex defect, the moderator may request a reasonable additional check, but the dispute is not automatically rejected solely because the buyer did not obtain a prepaid expert examination.

This is an internal maximum service period. A mandatory shorter period under applicable law takes priority; evidence requirements undergo legal review before launch.

### Partial Refund Without Shipping the Product

A partial refund is allowed only with the buyer's explicit consent to keep the physical product. The order records the amount, reason, initiator of the offer, and buyer confirmation. After consent, the payment partner refunds the specified amount, and the remaining seller payout is recalculated automatically.

The seller may propose a partial refund, or the platform may assign one as the result of a dispute, but it cannot be imposed on the buyer instead of a full refund available to them. The buyer's mandatory statutory rights take priority.

The exact hierarchy of delivery evidence and protection against false confirmations are defined separately.

### Digital Module

The public beta includes one digital fulfillment method — a downloadable file.

After the pilot, the target model must support four different digital fulfillment methods:

1. downloadable file;
2. license or activation key;
3. subscription;
4. online service.

Keys, subscriptions, and services are not included in public beta. The order in which they are added after a successful pilot is determined separately.

They use a common order and payment, but differ in fulfillment:

- file — automatic protected delivery after confirmed payment;
- key — automatic delivery of one unique code from the seller's available stock;
- subscription — automatic activation of the paid period and subsequent renewal;
- service — seller acceptance of the order, an agreed schedule and stages, delivery of the result, and acceptance confirmation.

Automatic delivery of a digital product does not mean an immediate payout to the seller. The payout is made after the relevant fulfillment method is confirmed and taking the established dispute period into account.

### Storage of Downloadable Files in Public Beta

In public beta, the seller uploads a downloadable file only to the platform's managed storage. Before publication, the platform checks the permitted format and malicious content, stores the verified version, and keeps a log of delivery to the buyer.

Pre-published limits apply to the size of one file and the seller's total volume. Exact sizes, permitted formats, and the review procedure are determined before launch after technical tests and calculation of storage and processing costs.

Each order is linked to the exact verified version of the file purchased by the buyer. The seller uploads a change as a new version and cannot silently replace the file in an order that has already been completed.

Before payment, the listing clearly states whether future updates are included free of charge. If they are included, the buyer retains access to the purchased version and receives access to subsequent verified versions under the announced terms. If they are not included, the new version is a separate listing. The rule recorded for an order cannot be worsened retroactively.

The purchased version remains available to the buyer in their personal library without a limit on the number of repeat downloads while the account is active and the platform is required to retain the purchase. Each download link is temporary and issued only to the authorized buyer.

Removing a product from sale does not revoke access to an already purchased version. Access may be blocked only on a confirmed security or legal ground, including malicious content or infringement of third-party rights. In that case, the buyer is notified, and the question of a refund is decided separately under rules established in advance.

Before the first successful access, the buyer may cancel an unfulfilled order under the platform's rules. After successful access, a simple change of the buyer's mind does not create automatic grounds for a refund. A refund or replacement is considered in the event of unavailability, corruption, confirmed malicious content, or a material discrepancy between the verified version and the listing description.

For a dispute, the platform retains the exact version and checksum of the file, review results, the listing terms and stated system requirements at the time of purchase, delivery events, access attempts and errors, and correspondence within the order. For an ordinary digital dispute, the buyer must attach a screenshot or video of the problem, state the reason, and describe the steps that caused it. An exception applies if the server log already confirms non-delivery or a failure, or if the buyer specifically explains why creating a recording was technically impossible. The seller provides instructions relevant to the dispute, version data, and an explanation of compliance. A successful-download mark proves access, but by itself does not prove that the file works or matches the description. A user attachment does not replace the server log and is not automatically treated as true.

This is a preliminary product policy: a specialist lawyer must review it before launch, and the buyer's mandatory rights under applicable law take priority.

After the first successful access to the file, a short, predetermined period of enhanced order protection begins, during which the seller's payout remains held. If no dispute is opened, the payment partner automatically releases the payout to the seller. The buyer may explicitly confirm that the file is correct and end the waiting period early, but manual confirmation is not mandatory.

If the buyer does not access the available file, fulfillment is considered to have occurred when the verified version appears in their personal library and a notification is successfully delivered through a confirmed channel. A longer, predetermined payout-holding period begins from this event. The first successful access switches the order to the ordinary short period.

The end of either period ends only the automatic holding of the payout. It does not cancel a later substantiated dispute, the buyer's mandatory rights, or the possibility of an approved refund through the seller's reserve and the guarantee mechanism after payout. A simple change of mind after successful access does not by itself create grounds for a refund. Both durations are determined before launch, reviewed with the payment partner and a lawyer, and shown to participants in advance.

Delivery through an external link, external personal account, or third-party service is not included in public beta: an external file may change after review. External fulfillment methods are investigated after a successful pilot as a separate possibility for subsequent digital flows.

### Category Restrictions

The general direction is approved: at the first stage, all ordinary categories are available by default after the seller review and the requirements for the specific category have been passed. Food, medical, hazardous, prohibited, and other highly regulated categories are not admitted in the first stage.

The exact list of prohibited and temporarily restricted categories has not yet been compiled. It must be separately checked for Russia against legislation, the payment partner's requirements, and delivery-service capabilities; categories must not be included or excluded based on an unverified assumption.

---

## 7. Common Data Model and Portability

### Approved

The common core must cover:

- seller;
- store;
- product;
- product variant;
- attributes;
- inventory;
- media;
- review and rating;
- order;
- fulfillment method;
- payment status;
- dispute.

### Seller and Stores

The seller is a verified business entity: an individual entrepreneur, legal entity, or self-employed person. The seller is the responsible party for orders and the recipient of payouts.

A store is a separate public branded storefront with its own name, design, catalog, and link.

One seller may own multiple stores. Each store belongs to only one official seller-owner.

During the pilot, one verified seller may have only one active branded storefront. The ability to open a second and subsequent stores is added after a successful pilot. This temporary product restriction does not change the model `one seller → multiple shops`.

### Account Access at the First Launch

At the first public launch, the seller account is available only to the verified owner or an officially authorized representative of the seller. A shared login for several employees is not allowed.

Employee invitations, fixed roles, and configurable permissions are not included in the first launch and are added after the pilot. At the same time, the server-side action model must retain the author of every action and must not hinder the later addition of separate employee accounts.

### Closing a Store and Seller Account

Closing an individual store and ending the official seller's operations are different actions. When a store is closed, its storefront stops accepting new orders, but other stores belonging to the same seller may continue operating.

When the seller ends operations, new sales stop, and active orders, returns, payouts, disputes, and other obligations must be completed. The seller is provided with a free export of the data belonging to them.

Verified reputation and records necessary for transactions, accounting, buyer protection, and preventing circumvention of sanctions are not erased by closure. They are retained only to the necessary extent and for the established period, after which they are deleted or anonymized unless further retention is required. A closed storefront does not remain an indefinitely available active store.

Re-registration is linked to the same verified business entity. Verified quality history, sanctions, disputes, and unfinished obligations are not reset by creating a new account or store. A new brand and a new storefront do not create a new official seller identity.

When ownership changes, the store, data, and reputation are not transferred automatically. This requires a separate review of the transfer of rights and obligations.

### Products and Store Publications

The primary product card belongs to the seller and contains the product's common data, variants, attributes, and media.

The seller may publish a product in one or more stores belonging to them. The publication links the product to a specific storefront and controls its visibility there. The primary product card does not need to be duplicated for each store.

The common marketplace indexes published listings. For unique, original, and not-yet-matched listings, the primary card remains with the seller.

### Reference Product and Price Benchmark

#### Approved

The main problem the pricing mechanism for an identical product must solve is giving the buyer a transparent and predictable price.

For a demonstrably identical physical mass-produced product, a single reference card may be created to which verified sellers' listings are connected. To recognize identity, the manufacturer, model or SKU, variant, color or scent, volume, size or packaging, contents, and condition must match. A differing variant is a separate reference product.

The platform displays an optional price benchmark, while each seller independently sets the actual price of their listing. Sellers may compete on price, availability, service area, delivery method, cost and time, service quality, and reputation.

The price benchmark is introduced in two stages:

1. While there are not enough confirmed completed transactions for the reference product within the platform, the benchmark may be shown only from a verified external source, such as the manufacturer's or official supplier's recommended price. The source and the date it was checked must be shown next to it. If there is no suitable verified source, the benchmark is temporarily not shown.
2. After a sufficient volume of fresh, confirmed data has accumulated, the platform switches to a transparent market formula. Its primary basis is the actual prices of confirmed completed transactions within the platform. Current seller listings are used only as an additional check on market conditions and do not themselves receive equal weight with completed purchases.

The main value in the second stage is calculated as the median of suitable prices over a recent period. The median is the price in the middle of an ordered set; it prevents one extremely high or low transaction from shifting the benchmark as strongly as an ordinary arithmetic mean would.

Only fully completed transactions without a refund, confirmed manipulation, or a recognized material violation are included in the calculation. Canceled, fully or partially refunded, and confirmed artificial transactions are excluded. Delivery cost is accounted for and shown separately from the product price. AI may identify suspicious events and prepare materials, but excluding a transaction is done only under verifiable rules established in advance.

The median uses the amount due to the seller for the product itself before deduction of the platform commission. A discount funded by the seller reduces the transaction price counted. A coupon, bonus, or other temporary subsidy funded by the platform or another partner without reducing the seller's amount does not reduce the counted price. The source of each discount must be stored separately in the order data.

The transition from a verified external source to the internal median is performed automatically only after reaching a predetermined minimum of suitable recent transactions from several independent buyers and several sellers. The threshold and duration of the recent period may differ by category, but must be defined before the internal benchmark is enabled for that category. A manual decision by an employee or AI does not replace meeting the threshold.

If, after the transition, fresh internal data no longer meets the established threshold, the median is no longer shown as the current benchmark. The platform automatically returns to a fresh verified external source, or temporarily hides the benchmark if none is available. The last median may be retained in history and analytics, but is not presented to the buyer as a current value.

Current listings do not directly change the median. If their prices diverge from the internal median beyond a category-specific threshold established in advance, the benchmark is temporarily hidden from buyers and a review of data freshness, comparability, and quality is initiated. After the review, the system either publishes the benchmark again under the general rules or returns to a fresh verified external source, leaving the benchmark hidden if none is available. An employee or AI does not enter an arbitrary number in its place.

Next to the benchmark, the buyer is shown its value, source type and name, update date, calculation period, number of transactions included, and a link to a brief description of the methodology. For an external source, who provided the value and when it was checked are stated explicitly; for the internal median, it is stated that it is based on suitable completed purchases. Participant names and information about individual orders are not disclosed.

The buyer may report a possible error in the benchmark. The seller may submit a formal request concerning product matching, the external source, inclusion of their own transaction, or application of the published rules. An employee checks the source data and methodology; a confirmed error is corrected, after which the benchmark is recalculated automatically. The employee does not assign a new value manually or disclose other people's orders or participant identities to the requester.

The seller's actual price deviating from the benchmark does not by itself block publication or sale, trigger a sanction, lower reputation, or create a hidden demotion in ordinary results. The buyer sees the actual price, deviation, delivery cost, and total cost and may explicitly select sorting by price or total cost. A change in order resulting from this buyer choice is not considered a seller sanction. Measures against fraud, false descriptions, and other violations are applied separately and are not justified by a price deviation alone.

The conditions for moving to the second stage, data composition, exact formula, calculation period, and rules for excluding suspicious values have not yet been defined. They must be established in advance and applied equally to comparable products; the pricing committee or AI does not assign the benchmark arbitrarily.

The buyer sees one card for the identical product and the available seller listings. For each listing, the seller's actual price, its deviation from the benchmark, the delivery cost and time, and the total purchase cost are shown.

The price benchmark does not replace the seller's price and is not a mandatory condition for publication or sale. The platform does not hide the seller's actual price.

The independent store, not the platform, remains the legal seller for the order. The platform combines listings in the common catalog, calculates and displays the benchmark, and organizes search and the protected transaction. It does not become the owner of the product or the single seller because of the common card and price benchmark.

Original and unique products, products without reliable matching, and digital products, subscriptions, and services currently use their own card and the seller's price without an automatic price benchmark.

### Legal Caveat

In the version of Article 11 of Federal Law No. 135-FZ “On Protection of Competition” current as of 31 August 2026, agreements between competitors are prohibited if they result or may result in establishing or maintaining prices.[1] The same article separately restricts vertical agreements leading to the establishment of a resale price and coordination of economic activity leading to the consequences listed in the law, unless it falls under the provided exceptions.[1]

Article 12 allows certain types of agreements only under conditions established by law, including some vertical agreements.[2] The applicability of these exceptions to the intended platform model has not been confirmed.

An obligatory single price is no longer selected as the primary mechanism. If it is revisited later, an antitrust lawyer must check the specific contractual scheme, the roles of the platform and sellers, the mechanism for making the pricing decision, and the applicability of the exceptions before implementation. The existence of possible exceptions cannot be treated in advance as legal permission for such a model.

An optional price benchmark also requires legal and economic review: delivery rules, sanctions, or restrictions must not covertly turn it into a de facto mandatory price.

### Ranking Identical Products

The seller cannot buy a higher position for their listing in ordinary results for an identical product. Paid positions and an advertising auction are not used for such products.

Before sorting, the platform excludes listings with no inventory, those that do not serve the buyer's address, and listings from sellers whose sales are restricted. The main direction is to show suitable sellers by distance from the buyer while separately and transparently displaying delivery cost and time, availability, reputation, and fulfillment quality.

The buyer may go from the common result to the seller's individual branded storefront. Storefront quality helps explain the brand and service, but does not buy the seller a higher position in the common results for an identical product.

After unavailable listings are excluded, the default order considers the ability to deliver to the address, total cost including delivery, delivery time, distance, and verified order-fulfillment quality. The order and its factors are published; the platform commission, payment for position, and quality of storefront design do not raise a listing. The buyer may explicitly switch to separate sorting by total cost, time, distance, or rating.

The factors and prohibition on commercial influence are fixed before implementation. Exact numeric weights are determined before public launch after modeling and pilot testing on data, and are then published as a version of the rules. One version is applied equally to comparable conditions. A change in weights receives a rationale, an entry in the version log, and advance notice; neither AI nor an employee secretly changes the order for an individual seller.

In the first public launch, seller order is not personalized according to the buyer's hidden behavioral profile. Only explicitly specified conditions are considered: delivery address, selected filters, and sorting method. The same order is applied under the same conditions. Behavioral personalization may be researched later only as a transparent and disableable feature with separate consent and an explanation of the data used.

### Common Search and Catalog

In public beta, paid placement in the catalog and search is not used. After a successful pilot, advertising may appear only in separate, clearly marked blocks that are visually distinct and do not change the organic order. Only listings that comply with the ordinary rules for safety, availability, and data quality are allowed in advertising. Payment for advertising does not raise the organic position of a product or seller.

When ordering different products, the system first considers relevance to the search query, category, and explicitly selected attributes, then availability for the buyer's address, delivery terms, and verified fulfillment quality. The factors are published, and commercial compensation to the platform does not affect the organic order. The buyer may separately sort results by total cost, recency, delivery time, or rating.

The absence of history for a new seller or product is considered neutral, not a negative indicator. The buyer is shown an “insufficient data” label without an invented rating. Relevance, availability, and delivery continue to be considered in ordering, while the new seller is subject to enhanced initial monitoring under the published rules. Newness alone does not send a listing to the end or give it an artificial first place.

### Variants and Inventory

A product variant is a specific saleable unit with its own set of values, such as color, size, or contents.

Physical-product inventory is tracked for a variant by the seller's storage locations. All publications of this variant in the seller's stores use one actual stock; a publication does not create separate inventory.

For digital listings, availability depends on the fulfillment method: a file and subscription may have unlimited availability, a key uses a limited stock of unique codes, and a service uses available fulfillment capacity.

Ordinary addition to the cart does not reserve availability. When proceeding to online payment, the platform rechecks the price and availability and creates a short temporary reservation of the physical variant, unique key, or limited service capacity. Successful payment attaches the reservation to the order; an error, cancellation, or expiration of the payment period releases it. The exact reservation duration is determined after selecting the payment partner.

### Data Portability

The seller must be able to port their own:

- profile;
- catalog;
- cards;
- variants;
- inventory;
- images and video belonging to them;
- storefront settings;
- provenance history of imported data.

### First Version of the Open Format

The first version of the open documented format contains the minimum working core for actual catalog and storefront portability: products, variants, attributes, prices, inventory, seller-owned media, categories, collections, storefront settings, and data provenance. Records have stable identifiers and contain the version of the schema applied.

The seller's own orders and verified reviews are described by separate related schemas with their own access and privacy rules. Payment secrets, closed dispute materials, internal analytics, anti-fraud signals, and risk scores are not mixed into the catalog schema. Connectors to specific external platforms convert data to or from the common format, but do not replace it with separate incompatible exports.

Every export explicitly contains the version of the schema applied. Compatible additions, such as a new optional field, do not change the meaning of existing fields or break processing of the supported version. An incompatible change receives a new major version. To end support for an old major version, the deadline, description of differences, transition rules, and migration tool are published in advance; import of supported old files is not switched off suddenly.

Import is performed as a safe two-stage operation. First, the system checks the file without changing working data, proposes matches to existing products and variants, and shows the seller the future creations, updates, skips, and conflicts. Ambiguous matches require the seller's explicit choice. Only after confirmation is the entire agreed set of changes applied. The operation, original values, conflict decisions, and result are stored in the log; the seller can roll back the entire import operation to the state before it was applied. Import does not perform unconditional overwrites or create duplicates for every match.

At the first launch, automatic synchronization is allowed in only one direction: from an external source explicitly selected by the seller to Open Marketplace. A primary source is recorded for each connected field group. The platform does not automatically send changes back to the external system; reverse portability is performed through a separate confirmed export. Full two-way synchronization is deferred until after a successful pilot and separate design of conflicts and recovery. The rule “last change wins” is not applied as a hidden universal mechanism.

In the account, a field or logical group of fields managed by an external source is explicitly marked. Before making a manual change, the seller sees a warning and must choose “take control.” After that, synchronization of only the selected field or group is suspended, while the other connected data continue to update. To re-enable it, the system first shows changes from the external source and possible conflicts. A manual edit is not silently overwritten by the next synchronization and does not unnecessarily disable the entire store connection.

If the source fails or an invalid update occurs, the platform does not clear fields or partially apply a damaged package within a related logical group. The last confirmed version is retained, synchronization receives a visible delayed status, and the seller is sent the reason and a report on the affected data. A brief delay in non-critical fields, such as a description, does not by itself stop sales. If the price or inventory remains unconfirmed longer than a safe period established in advance, the affected listings temporarily stop accepting new orders until a fresh update is successfully checked or control is explicitly transferred to manual management. Exact periods are determined after selecting sources and conducting the pilot.

The open-format specification, machine-verifiable schemas, examples, change proposals, discussions, decisions, and version log are maintained in a public repository. Any participant may propose a change. The platform team initially serves as the responsible maintainers: it accepts or rejects proposals according to published criteria of compatibility, security, privacy, and practical necessity and publishes the reasoning. Secret changes and retroactive changes to an already published version are prohibited. A general vote of all users on every technical change is not required; transferring governance to an independent organization may be considered later if there is a mature community and a functioning process.

The format specification, machine-verifiable schemas, and reference examples are published under a permissive open license that expressly allows use, independent implementation, modification, and distribution, including use in commercial products. The specific license or combination of licenses for documentation and machine files is selected after a separate legal review; publication without explicit terms of use does not count as satisfying the openness requirement.

### Order and Buyer Data in a Seller Export

The seller may export only their own orders and the minimum set of buyer data necessary to fulfill those orders, provide support, and perform mandatory accounting. The exact set of fields and the period for which the export is available must undergo legal review.

Contact details for marketing messages are included in the export only with the buyer's separate consent. Views, search queries, purchases from other sellers, internal risk assessments, and the platform's service data are not transferred to the seller.

### Buyer Personal Export

The buyer may obtain a complete personal export of their own data free of charge after enhanced access verification. It includes the profile, orders, available payment documents, their own reviews, requests, disputes, consents, and private correspondence.

The export does not include internal risk and anti-fraud assessments, other buyers' data, closed service records of sellers and the platform, or information to which the buyer has no right of access. The exact format and preparation periods for the export are determined separately.

### Deletion of a Buyer Account

After confirmed account deletion, the public profile is closed, marketing consents are withdrawn, and non-essential personal data are deleted. Records necessary for unfinished obligations, orders, returns, disputes, and mandatory accounting are retained only to the necessary extent and for the established period.

Messages and actions included in the order evidence do not disappear from the transaction history because of account deletion. After the applicable retention period ends, retained data are deleted or anonymized. The exact grounds, composition, and retention periods are determined after legal review and communicated to the user in advance.

### Important Limitation

Automatic portability from any external platform must not be promised before its official export, API, and permitted integration methods have been checked.

### Approved: Boundary Between Free Portability and Paid Automation

A full manual export of portable data belonging to the seller is always available free of charge in the open documented format, not only when the account is closed. The platform does not artificially reduce portable fields for the sake of a paid tier.

Paid features may include continuous automatic synchronization, ready-made connectors, increased operation frequencies and volumes, cleaning and matching complex data, and turnkey portability setup. The fee is charged for automation and additional service work, not for the seller's right to obtain their own data.

---

## 8. Reviews and Reputation

### Approved

Two-tier reputation is used.

#### Primary Rating

- is formed only by reviews of verified orders within our platform;
- is the main trust indicator;
- is not mixed with external reputation.

#### External Reputation

- is shown in a separate block;
- contains the source name, date, and original rating;
- does not affect the primary rating;
- preserves provenance in subsequent exports;
- is not marked as verified if the source cannot be checked.

This allows the seller to show their previous history without presenting external reviews as verified by our platform.

#### Public Seller Quality Metrics

At the first launch, the buyer is shown a limited verifiable set of operational metrics: number of completed orders, share of orders fulfilled on time, cancellations attributable to the seller, confirmed problems, and returns attributable to the seller. The calculation period and number of orders on which the statistics are based are shown next to them. If there is insufficient data, the platform states this directly and does not create the appearance of an exact rating.

The average rating, number of verified reviews, and the reviews themselves are shown separately from operational metrics. Internal anti-fraud signals, rules for detecting manipulation, and the closed risk score are not disclosed publicly and are not included in a seller or buyer export.

A complaint, open dispute, requested return, or preliminary decision does not by itself worsen the seller's public metrics. An event is counted only after the fact and the seller's responsibility have been finally confirmed: as an undisputed system event that became final under the published rules, or as a final decision by a human moderator after ordinary appeal has concluded. Canceled and rejected complaints, decisions without established seller responsibility, and problems attributable to the buyer, carrier, or platform are not included in the seller's metrics.

Total and recent history are shown separately. The total number of completed orders reflects the seller's experience over all time. Shares of timely fulfillment, cancellations, confirmed problems, and returns are calculated over an explicitly stated recent rolling period; the period dates and number of orders counted are shown next to them. These data are not combined into a single opaque score. The exact period length and minimum sample size are determined after modeling pilot data and recorded before public use.

The public profile contains a general seller overview. With a sufficient sample, separate metrics for physical products, digital products, and services are also shown. The listing prioritizes metrics for the relevant fulfillment type, while the general overview remains available. If the sample for an individual type is insufficient, the platform does not show an unreliable percentage and states the lack of data directly. The exact minimum sample size is determined from pilot data before public use.

In the private account, the seller sees the published methodology, calculation period, their own orders and final events included in each metric, and the reason for their inclusion. The seller may submit a formal request concerning a data error, attribution of responsibility, or application of the methodology. A confirmed error corrects the source data and triggers automatic recalculation; the basis, previous value, and new value are retained in the change log. Support may not arbitrarily assign or correct a final metric without correcting the source event and providing verifiable grounds. Participant identities, order contents, and closed dispute materials are not disclosed to buyers.

Verified public quality metrics may be used in ordinary results only as a limited transparent factor under a methodology published in advance; listing relevance remains the basis. The buyer has explicit filters and sorting by quality metrics, while the seller receives an explanation of the public factors used. Closed anti-fraud signals and the internal risk score are not mixed in as a hidden demotion. Sales restrictions, hiding listings, and excluding a seller are applied only through separate security and sanctions rules with a recorded basis and a right of appeal.

#### Export of Our Platform's Verified Reviews

The seller may export all verified reviews from our platform relating to them free of charge in an open, verifiable format. The record must retain the text, rating, date, type of verified order, provenance, and verifiable platform confirmation.

The export does not contain the buyer's contact details. The seller cannot exclude only inconvenient reviews, change their content, or present them as internal reviews of another platform. The permitted public buyer identifier, visibility settings, and exact set of fields are determined after legal review.

---

## 9. Individual Seller Storefront

### Approved

Every verified seller receives a basic working branded storefront free of charge. It includes a mobile-adapted safe template, name and logo, basic colors, catalog and collections, and consistent elements for price, delivery, rating, returns, and protected purchasing.

The basic storefront can be configured manually without AI. Access to the AI designer, advanced design options, and resource-intensive media generation is a separate additional capability and does not limit ordinary product publication or sales.

The safe branded storefront option has been selected.

The seller is allowed:

- custom colors;
- fonts from the permitted set;
- composition from safe blocks;
- covers;
- collections;
- brand story;
- images and video;
- subtle animations;
- seasonal design;
- an individual public link within the platform domain.

During the pilot, sellers' own domains are not connected. Each storefront receives an address within the platform domain. Connecting a custom domain is added after a successful pilot with ownership verification and safe configuration; the platform's internal address is retained.

The following remain consistent:

- product card and critical information;
- a consistent format for showing price and total purchase cost;
- delivery;
- returns;
- rating and review status;
- cart;
- secure payment;
- performance and mobile-version requirements.

The seller does not gain the ability to upload arbitrary executable code.

---

## 10. AI Storefront Designer

### Source of the Idea

The mechanics were researched using the locally installed Open Design version 0.13.0.

Open Design scenarios reviewed:

- free-form text prompt;
- clarifying questions;
- direction selection;
- result creation;
- automated critique and iterative improvement;
- targeted refinement of an existing design;
- image, video, and audio generation;
- extraction of visual effects from a reference website;
- design systems and plugins.

The reviewed local scenarios are located in:

`C:\Users\Vladislav\AppData\Local\Programs\Open Design\resources\open-design\plugins\_official\scenarios\`

### Approved User Flow

`text and references → short interview → several design directions → selection → design system → live storefront → conversational edits → verification → publication`

### Inputs

The seller may provide:

- a text description;
- a logo;
- brand materials;
- product photographs and video;
- screenshots of pages they like;
- links to example websites;
- examples of colors, fonts, and images;
- an explanation of what exactly they like in each example.

A reference serves as direction, not permission to copy someone else's page in full.

### Seller Design System

AI forms a unified set of rules:

- palette;
- typography;
- spacing;
- element shapes;
- photography style;
- composition;
- permitted animation intensity.

Subsequent edits must preserve this system rather than turn the page into a random collection of blocks.

### Result Review

Working criteria:

- visual quality;
- clarity of the purchase process;
- trust;
- loading speed;
- mobile version;
- accessibility;
- compliance with platform rules.

---

## 11. AI Images, Video, and Product Cards

### Approved

Processing real images and assembling product cards are included in the limited beta on the day of public launch. Video generation remains a target product capability, but appears later and is not included in the initial beta.

Permitted uses:

1. improving the presentation of a real product;
2. creating advertising banners, covers, and short clips;
3. assembling a product card from source materials.

### Product Invariance Rule

AI must not change:

- shape;
- color;
- markings;
- contents;
- noticeable properties of the real product.

AI may improve:

- background;
- lighting;
- cropping;
- size;
- composition;
- surroundings and advertising presentation.

Each product listing requires source material of the real product. Before publication, the seller compares the source with the result and confirms its correctness.

A public AI-processing label is mandatory if AI created or substantially replaced the visible background, surroundings, object, or other synthetic content, as well as for a fully generated image. If AI performed only a technical correction of lighting, cropping, or size without creating new visible content or changing the product's properties, a separate public label is not required, but the source, processing history, and result are retained for review.

If a card uses an image with visible content created by AI, the gallery must retain at least one real image of the product without synthetic additions; its lighting, cropping, and size may be corrected technically without changing the product's properties. For each labeled AI version, the buyer can compare it with the specific source. An AI version cannot be the only visual evidence of the product's appearance.

It is permitted to generate brand decorative materials, patterns, banners, illustrations, seasonal design, advertising backgrounds, and surroundings entirely from scratch. If a product being sold is shown in a generated scene, the image of the product itself must come from real source material and must not change its shape, color, markings, contents, or noticeable properties. A completely fictional image of a product may not be used as an image of a real product. A fully generated scene receives a public AI label.

A labeled image with AI content may be used as the main cover of a product card if the product itself is taken from real source material and has not been changed, the AI label is already visible on the cover and in the common catalog, a real image without synthetic additions is available in the gallery, and the buyer can compare the AI cover with its source.

The source and each published version of AI processing are stored as separate immutable records. A rollback does not overwrite or delete history: it creates a new action that makes the selected previous version active again. Each order retains a snapshot of the card and media available to the buyer at the time of purchase. Unpublished draft generations may be deleted under separate rules. Exact retention periods for sources, drafts, and published versions after a product is removed from sale are determined after legal review and cost calculation.

Before publication, the system automatically compares the AI result with the source by shape, color, markings, contents, and other noticeable product properties. After the check, the seller explicitly confirms correctness and publication. A material discrepancy or insufficient confidence in the automated check blocks publication until correction or human review. A low-risk result does not require a mandatory manual queue. AI does not publish an image independently without the seller's confirmation.

If a preliminary check after publication confirms a credible risk of material product distortion, the disputed AI image is temporarily hidden from the public card but retained as evidence; an available real image becomes the cover. The seller is notified, and a person checks the source, AI version, publication history, and problem report. In the event of a false alarm, the image is restored. In the event of confirmed distortion, a corrected version is published, and the consequences are determined under the general rules with a right of appeal. A single complaint does not by itself block the seller or delete the entire card.

### Open Questions

- image and video limits;
- exact retention periods for sources, drafts, and published versions;
- thresholds for automated comparison and referral for human review.

---

## 12. Protected Transactions and Payouts

### Boundary of Protected Purchasing

A purchase started from the common catalog, a product card, or a platform branded storefront is completed only through the platform's protected transaction. Purchase buttons, requests to pay by transfer, and links to an external checkout flow are not allowed within these interfaces.

The seller's official contacts and support channels may be displayed where necessary, but must not be used to bypass payment, commission, disputes, or the rules for verified reviews. A transaction outside the platform does not receive platform protection and does not create an internal verified review.

This restriction does not cancel data portability. The seller may export data belonging to them free of charge and use it independently on their own website or in another system, but such external trade is not presented as a platform transaction.

### Buyer–Seller Private Chats

The first public launch includes an internal messenger in the form of private chats `buyer ↔ seller`. A private chat becomes available only after the first successful payment for an order from that seller; before payment, the buyer cannot start a private conversation with the seller. After the order is completed, the chat remains permanent and may be used for support and subsequent orders.

The seller may send promotional offers in this chat only with the buyer's separate consent. The buyer may prohibit promotional messages or completely block new messages from the seller without destroying the retained history of orders and evidence.

The chat supports:

- conversation history;
- attachments;
- message search;
- notifications;
- links to products and orders.

Messages, attachments, links to products and orders, and action times are stored on the server. Part of the correspondence related to an order may be used as evidence of the transaction's terms and fulfillment in a dispute.

An uploaded message may be edited, but participants are shown that it was changed, and the version history is retained. Messages included in the order history cannot be deleted from the transaction record. A user may hide a chat from their own list, but this does not delete the correspondence for the other participant or destroy evidence. Exact retention periods are determined separately after legal review.

Group chats, public channels, audio and video calls, and bot platforms are not included in the first launch.

### Pre-Payment Questions and AI Support

Before payment, the buyer may ask a public question about the product. The answer is published in the questions-and-answers section and is available to other buyers; publishing personal data in this section is prohibited. For services and custom listings, a structured requirements form is used before payment.

AI support answers only on the basis of verified card data, platform rules, and previously verified answers. The buyer is always shown that the answer was generated by AI. If verified data are insufficient, a product question is passed to the seller, while a question about payment, protection, or rules is passed to a platform employee. AI must not invent product properties, seller promises, or transaction rules.

### Payment Method During the Pilot

During the pilot, online prepayment is used before order fulfillment begins. The payment partner accepts and holds the money under the protected-transaction rules.

Payment on delivery is not included in the pilot. It is later investigated as a separate payment flow: reserving an amount on a card with final capture after receipt and paying the courier or seller directly require different rules for commissions, refunds, and evidence.

### Approved

1. The buyer pays for the order.
2. The payment partner, not the platform itself, holds the money.
3. The seller fulfills the order.
4. After fulfillment is confirmed, the partner transfers the money to the seller.
5. In a dispute, the platform collects evidence and decides on payout or refund.

### Refund Route

In public beta, any full or partial monetary refund is performed by the payment partner through the original payment channel used by the buyer to pay for the order. The platform does not issue its own monetary balance or replace a refund of paid money with non-withdrawable bonuses.

If a refund through the original channel is technically impossible, the payment partner transfers the money, after enhanced access verification, to another verified bank account or card belonging to the same buyer. The operation remains linked to the original order and the refund log. A manual transfer by the seller and replacing money with an internal balance are prohibited.

An withdrawable electronic wallet of a licensed payment partner may be added after public beta as a separate product. Before that, legal review and review of the partner's license and agreement, identification, withdrawal, limit, and commission rules are mandatory.

### Refund After Seller Payout

If a refund is approved after the seller payout has been completed, the buyer does not wait for the seller to repay it voluntarily. The payment partner performs the refund from the security provided by the scheme, and the corresponding amount becomes the seller's debt to the settlement system.

The debt is repaid from the seller's reserve, future payouts, or through separate collection. The payment partner, not the platform itself, manages the reserve and monetary operations. A seller appeal must not indefinitely block an already approved refund to the buyer.

In public beta, the payment partner withholds a single basic reserve from each seller's payouts. The reserve is not a platform commission or revenue: the unused amount is released on a rolling basis separately for each order after the applicable refund and dispute periods end.

An open dispute extends the hold only for the amount associated with the relevant order, not the seller's entire reserve. When a store is closed, the balance is held only until the applicable periods and open disputes are complete.

After sufficient verifiable history has accumulated, the reserve size may vary according to the seller's confirmed risk, including category, order value, share of returns, and substantiated disputes. The exact percentage, monetary limit, and holding periods are determined before launch after proposals from the payment partner, economic calculation, and legal review.

If a particular seller's reserve is insufficient, an approved refund is temporarily covered by a limited platform guarantee fund placed within the payment partner's settlement system. The debt remains fully owed by the seller and is repaid from future payouts or through separate collection. Other sellers' reserves are not used for this.

The guarantee fund size and the limit of the platform's total liability are determined before public beta together with the maximum order value and permissible loss. As the limit is approached, the platform reduces operational limits or suspends new risky sales rather than canceling already approved refunds.

When a seller incurs a debt to the guarantee fund, that seller's new sales and new payouts are temporarily suspended. The seller must fulfill orders that have already been paid for; access to fulfillment, returns, disputes, documents, and support is retained.

Future available payouts are directed toward repaying the debt. Restrictions are lifted after full repayment and restoration of the required reserve. Signs of fraud or refusal to repay are handled separately through enhanced review and the collection procedure.

### Multi-Seller Cart

The buyer may add products from several sellers to one cart and make one combined payment.

After checkout, the platform creates a common buyer order and a separate suborder for each seller. The following are tracked independently for each suborder:

- products and amount;
- delivery;
- fulfillment;
- confirmation of receipt;
- dispute;
- refund;
- seller payout.

The payment partner must support automatic distribution of the combined payment, separate holding of sellers' shares, and partial refunds for a specific suborder. Ordinary acceptance of a single payment without this separate accounting is unsuitable.

This is a mandatory capability when selecting the payment partner. The legal and technical feasibility of the scheme in Russia must be confirmed before implementation is fixed.

### Fulfillment Confirmation

- physical product — delivery and a short period to report a problem;
- file or key — protected delivery and availability check;
- subscription — separate fulfillment for each period;
- service — an accepted result or agreed stage.

If the buyer does not respond and no dispute is opened, the order is automatically considered fulfilled after a period known in advance. Exact periods have not yet been determined.

### Open Questions

- suitable payment partner;
- legal feasibility of the selected scheme in Russia;
- holding and automatic-acceptance periods;
- technical limitations, receipts, and accounting for partial refunds;
- handling service stages;
- exact rate, monetary limit, and release periods for the seller reserve, as well as the size of the platform guarantee fund.

---

## 13. Disputes, Quality, and Sanctions

### Approved Direction

The platform takes responsibility for maintaining order and assisting in disputed situations.

Tracked metrics:

- confirmed discrepancy from the description;
- confirmed defect;
- delays;
- cancellations attributable to the seller;
- share of substantiated disputes and returns;
- unfulfilled digital orders and services.

### Working Sanctions Policy

`evidence collection → warning → temporary restrictions → human review → decision → appeal`

Automatic permanent blocking based only on the number of complaints is not recommended: complaints may be mistaken or malicious.

### Dispute Decision in Public Beta

Predetermined indisputable technical events are processed automatically, such as expiration of the response period, system-confirmed non-delivery of a file, or official cancellation of delivery. The automatic action and its basis are recorded in the order log.

AI collects materials, builds a chronology, links claims to source evidence, and marks contradictions. It cannot invent missing facts, hide source materials, or issue a final decision.

Any decision that changes a participant's payout, refund, verified reputation, or sanctions is made by a human moderator. The decision records the rule applied, the evidence reviewed, and the rationale.

In public beta, an ordinary moderator selects the decision and reason code only from a closed list published in advance. A non-standard exception requires a senior moderator's decision, legal review, and a complete record of the grounds in the log. If a non-standard case becomes recurring, the new type of decision is first added to the general rules rather than applied as a hidden precedent.

The closed list of fulfillment and monetary decisions includes:

- reject the claim and release the held payout;
- approve a full monetary refund;
- approve a partial monetary refund only with the buyer's explicit consent under rules established previously;
- for a physical product, order return shipment followed by a full refund; when the seller's fault is confirmed, the seller bears permissible return-shipping costs;
- offer a replacement, correction, or re-performance only with the buyer's explicit consent and a recorded deadline;
- if the agreed correction is not completed on time, proceed to the applicable monetary refund.

In public beta, the moderator does not assign arbitrary fines or compensation to the buyer beyond the order amount and the rule-provided costs of initial and return shipping. The participant's mandatory rights under applicable law take priority over the internal list.

### Appeal

Each party has one ordinary appeal of a dispute decision. It is reviewed by a different human moderator who did not make the initial decision; AI is again used only to prepare a verifiable summary of the materials.

In the appeal, the party identifies new evidence, an error in the established facts, a procedural violation, or an incorrectly applied rule. Further review after the appeal is allowed only when there are new material circumstances that objectively could not have been considered earlier.

Filing an appeal does not stop an approved refund to the buyer or temporary security measures. Reversible restrictions are applied with a note that the appeal is ongoing. Irreversible sanctions, including permanent account closure and a public mark of a serious violation, are enforced after the appeal period ends or the second-instance decision is made. They may be applied immediately only in the presence of an immediate security threat or a direct legal requirement.

An appeal may be filed within 3 calendar days. The platform reviews it within no more than 3 business days. The filing period begins after the decision is published in the private account and a notification is successfully delivered through at least one confirmed participant channel; read confirmation is not required. If delivery fails, the platform resends it or uses another confirmed channel, and the period does not begin. A confirmed technical failure of the platform extends the period by the duration of the failure. These are internal target service periods; they do not limit the participant's lawful methods or periods for applying to external authorities.

### Open Questions

- evidence set for each order type;
- seller response periods;
- sanction levels;
- public visibility of quality metrics;
- protection against complaint manipulation.

---

## 14. Monetization

### Approved

1. A commission is charged only on successfully completed orders.
2. The total of mandatory withholdings by the platform and payment partner does not exceed 10% of the order value.
3. During the pilot, a single rate applies to all orders regardless of the buyer's source, product type, fulfillment method, or seller size.
4. Delivery is calculated and shown separately and transparently.
5. Seller taxes and voluntarily enabled paid services, including AI features, are not included in the commission and are shown separately.
6. The exact single rate is determined after calculating payment, support, dispute, refund, and other costs.
7. The AI designer, advanced storefront design, and resource-intensive media generation are paid features after the free limited beta. A free basic branded storefront remains available to every verified seller.
8. The third early revenue direction is analytics, automation, and integrations.

### Possible Paid AI Features

- subscription to the AI designer;
- image packages;
- separate video credits;
- product-card creation;
- generation of descriptions and attributes;
- advertising banners and clips;
- seasonal design;
- continuous conversational storefront editor.

During the limited beta, AI features are free for selected participants subject to strict limits. After the beta, a subscription with an included allowance and additional paid credits is used. Exact prices and allowance sizes have not yet been determined.

### Analytics, Automation, and Integrations

Priority ideas:

- profit calculation;
- inventory forecasting;
- warnings about rising returns;
- AI assortment recommendations;
- bulk editing;
- employee roles;
- multiple stores;
- inventory synchronization;
- integrations with accounting, warehouse, CRM, and delivery;
- expanded API limits;
- paid complex turnkey portability.

### Later Revenue Sources

- clearly labeled advertising promotion;
- buyer subscription and loyalty program;
- logistics and financial services through partners;
- corporate and branded versions of the platform.

### Recommended Monetization Prohibitions

Money should not be charged for:

- basic export of one's own data;
- removal of a bad review;
- purchase of a rating or trust status;
- an advantage in a dispute;
- basic security;
- hidden elevation in ordinary results;
- sale of personal data.

These restrictions are currently a product recommendation and must be separately approved.

---

## 15. Internal Development and Public Launch

### Approved

All three directions must be ready for public launch.

### Basic Architecture

A modular common server core with separate background workers has been selected.

The following independent modules are distinguished within the core:

- users and verification;
- sellers and stores;
- storefronts and design systems;
- catalog, variants, and inventory;
- cart, common order, and seller suborders;
- accounting for payments, holds, refunds, and payouts;
- physical fulfillment;
- digital fulfillment;
- disputes, quality, and reputation;
- open formats, API, and integrations.

AI generation, media processing, catalog import, synchronization, notifications, and other long-running operations are performed by separate background workers and do not block ordinary site operation.

Orders, inventory, movement of money, access rights to digital products, and action history are stored on the server as a single authoritative version. The browser and future mobile applications only display data and send user actions; they are not the sole place where state is stored.

Payment and logistics partners are connected through separate adapters with a common internal interface. Replacing a partner must not require changing order rules in every module.

Microservices are not used at the start. An individual module may later be extracted into a standalone service only if a confirmed need for independent scaling or isolation arises.

The specific technologies, deployment architecture, and detailed module interfaces have not yet been selected.

### Working Decomposition of Internal Development

1. server foundation of the transaction core: identity, roles, permissions, sellers, action log, and a single authoritative version of state;
2. catalog, variants, inventory, common search, and buyer interface;
3. cart, order, payment adapters, protected transaction, physical and digital fulfillment, refunds, and disputes;
4. full seller account, data import and export, and branded storefronts;
5. open format, documented API, synchronization, and third-party integrations;
6. AI designer and media as a limited beta with limits and separate readiness criteria;
7. analytics and automation in the minimum public-beta scope;
8. combined review of the security, legal, economic, and operational readiness of the Russian public pilot.

This is the approved sequence for designing and checking major parts, but it is not yet a detailed implementation plan. All directions included in the approved public-beta scope are combined and undergo a general review before it opens.

---

## 16. Main Risks

1. **Public launch that is too large.** Simultaneous readiness of all subsystems increases the timeline, cost, and number of failure points.
2. **Payment model.** The availability of the required holding and refund mechanism with a suitable partner must be confirmed.
3. **Portability from external platforms.** Capabilities depend on official exports, APIs, and the terms of specific sources.
4. **Reviews.** The provenance and rules for permissible display of external content must be checked.
5. **Broad catalog.** A universal core will require manageable attribute schemas by category.
6. **Services and subscriptions.** They are more complex than ordinary file delivery and require stages, periods, and acceptance rules.
7. **AI cost.** Video and repeated generation may make an unlimited model unprofitable.
8. **Moderation.** The platform's responsibility requires a real operations team, not only an algorithm.
9. **Two-sided market.** Sales require sellers and buyers at the same time.
10. **Trust.** Errors in disputes, ratings, or payouts may destroy the product's primary value.
11. **Price-benchmark manipulation and hidden mandatory status.** An opaque calculation or one controlled by interested participants may mislead the buyer. Sanctions, blocks, or ranking that effectively compel sellers to follow the benchmark require a separate antitrust review and must not be introduced without an opinion from a specialist lawyer.[1][2]

---

## 17. End-to-End Outcome the Product Must Achieve

The seller must be able to:

1. register and pass review;
2. import or create a profile and catalog;
3. add a physical or digital product, subscription, or service;
4. provide AI with text, materials, and references;
5. receive and edit a branded storefront;
6. publish a store and products;
7. accept a protected order;
8. fulfill it using a suitable method;
9. receive a payout after confirmation;
10. receive an internal review;
11. view analytics;
12. export portable data in an open format.

The buyer must be able to:

1. find a product in the common catalog or follow the seller's link;
2. understand the price, terms, rating, and provenance of reviews;
3. pay securely;
4. receive a product, file, key, subscription, or service;
5. open a dispute when there is a problem;
6. receive a decision and a possible refund;
7. leave a verified review.

---

## 18. Next Decisions by Priority

### Immediate Next Question

Should a technical study of stack and deployment options be conducted before the subordinate specification for the first phase of the transaction core?

Options under consideration:

1. conduct a comparative study and provide a reasoned recommendation without creating product code;
2. Vladislav will define the technology stack and deployment conditions himself;
3. pause the project at the approved common specification.

### Written Specification Approved

- Vladislav confirmed the specification without changes on 2026-09-02.
- Approval does not authorize starting implementation without the subordinate specification and first-phase plan.
- Scope review confirmed that the common document covers several independent subsystems and must not become one giant plan.
- Before the first-phase plan, the technology stack and deployment architecture must be selected and the project repository must be created or explicitly identified.

### Final Concept — Section 7 Confirmed

- Critical changes are atomic, repeated requests do not create duplicates, and an unknown partner state requires reconciliation.
- If import or synchronization fails, the last confirmed version is retained.
- An incident restricts the affected risk, preserves evidence, and permits recovery only after a confirmed fix.
- Before release, unit, integration, contract, end-to-end, security, load, and recovery checks are mandatory.
- Public beta opens only after legal, payment, security, and operational readiness and the absence of critical errors.

### Written Specification Prepared and Checked

- Path: `D:\Open_Marketplace\docs\superpowers\specs\2026-09-02-open-marketplace-design.md`.
- All seven sections of the final concept have been confirmed by Vladislav.
- A self-check of placeholders, contradictions, ambiguities, and scope has been completed.
- The specification awaits Vladislav's separate confirmation before moving to the first subordinate specification and implementation plan.

### Final Concept — Section 6 Confirmed

- The AI designer is confirmed as an optional limited beta for selected verified sellers.
- AI does not publish materials without the seller's explicit confirmation.
- The real product must come from a real source and not be distorted; synthetic content is labeled under the approved rules.
- Sources, published versions, and a snapshot of the order card are retained for comparison, rollback, and disputes.
- A material discrepancy is blocked or referred to a person; exiting beta requires quality, safety, stability, and acceptable economics.

### Final Concept — Section 5 Confirmed

- Transparent ranking rules for identical and different products without paid organic influence or hidden personalization are confirmed.
- New sellers and products receive the neutral “insufficient data” status and enhanced initial monitoring.
- There is no advertising in public beta; after the pilot, only separate labeled blocks without influence on organic results are possible.
- The price benchmark remains optional, explainable, and protected against arbitrary assignment.
- Reviews and public metrics are based on verified events; a person makes final dispute decisions under the published rules.

### Final Concept — Section 4 Confirmed

- Seller review, a free basic branded storefront, and no influence of design on organic position are confirmed.
- The seller's own portable data are available free of charge in an open documented format.
- The first-launch API is limited to the catalog, own cards, prices, inventory, and secure checkout links within the platform.
- Separate minimum application permissions, critical-permission periods, mandatory limits, logs, access revocation, and risk-based review are confirmed.
- The rules for private integrations, the public application catalog, external payment, support, and application shutdown are confirmed.

### Final Concept — Section 3 Confirmed

- Common cards for demonstrably identical products and separate cards for unique listings have been confirmed.
- The price and inventory are rechecked by the server before payment, after which a short reservation is created.
- A common purchase is divided into independently fulfilled seller parts.
- The payment partner processes money, holds, and refunds under a scheme reviewed before implementation.
- Public beta confirms the full cycle for physical products and downloadable files with the exact version of the digital product.

### Final Concept — Section 2 Confirmed

- A modular monolith with independent internal modules and no initial microservices has been confirmed.
- The server is the sole authoritative source for orders, inventory, money, permissions, digital delivery, and action history.
- Long-running operations are performed by background workers.
- Payment and logistics partners are connected through separate adapters.
- The architectural preparation sequence has been confirmed without changes.

### Final Concept — Section 1 Confirmed

- The purpose and public positioning are confirmed without changes.
- The first public launch remains a Russian public beta with real transactions and published restrictions.
- Seller tools, the buyer marketplace, and open data infrastructure are combined for launch.
- The AI designer launches as a limited beta and is not a condition for ordinary sales.
- The main success criterion is the reliability of the full order cycle for physical products and downloadable files.

### Approved: Product Preparation Sequence

- First, the transaction core is designed and checked: identity, permissions, catalog, orders, payment flow, fulfillment, disputes, and audit.
- Next, the full seller account, import, export, and branded storefronts are added.
- After that, the open format, API, synchronization, and third-party integrations are connected.
- The AI designer and media are connected last as a limited beta.
- All approved directions are combined and undergo a general review before public launch.

### Approved: International Expansion

- The date of entry into a new country is not set in advance.
- Stable operation in Russia is confirmed first.
- Countries are added one at a time.
- For each country, law, taxes, payments, currency, localization, logistics, support, and buyer protection are addressed separately.
- Entry begins with a limited pilot; an interface translation alone is insufficient.

### Approved: New Sellers and Products Without History

- The absence of history is considered neutral, not a negative indicator.
- An “insufficient data” label is shown without an invented rating.
- Relevance, availability, and delivery are considered.
- Enhanced initial monitoring under the published rules applies.
- Newness does not send a listing to the end or give it an artificial first place.

### Approved: Common Search for Different Products

- First, relevance to the query, category, and selected attributes is considered.
- Then availability for the address, delivery terms, and verified fulfillment quality are considered.
- The factors are published; commercial compensation does not affect the organic order.
- The buyer may sort by total cost, recency, delivery time, or rating.

### Approved: Advertising in the Catalog and Search

- Paid placement is absent in public beta.
- After a successful pilot, advertising is possible only in separate, clearly marked blocks.
- Advertising blocks are visually distinct and do not change the organic order.
- An advertised listing must comply with the ordinary rules for safety, availability, and data quality.
- Payment does not raise the organic position of a product or seller.

### Approved: Personalization of Seller Order

- Hidden behavioral personalization is not used in the first public launch.
- Only the explicitly specified address, filters, and sorting method are considered.
- The same order is applied under the same conditions.
- Personalization may be researched later only as a transparent, explainable, and disableable feature with separate consent.

### Approved: Numeric Weights for Listing Order

- The factors and prohibition on commercial influence are fixed before implementation.
- Exact weights are determined after modeling and pilot testing on data before public launch.
- A version of the rules is published and applied equally to comparable conditions.
- Changes receive a rationale, an entry in the version log, and advance notice.
- AI and employees cannot secretly change the order for an individual seller.

### Approved: Order of Identical-Product Listings

- First, listings without inventory, delivery to the address, or the right to sell are excluded.
- By default, delivery availability, total cost including delivery, time, distance, and verified fulfillment quality are considered.
- The rules and factors are published.
- Commission, payment for position, and storefront design do not raise a listing.
- The buyer may choose sorting by total cost, time, distance, or rating.

### Approved: Ending Application Support

- New connections stop, and active sellers are notified in advance.
- In the absence of a significant risk, a limited period is provided for export, disconnection, and choosing a replacement.
- After the transition period, permissions are revoked, and the developer confirms deletion of received data.
- In the presence of a significant risk, access is disabled immediately; an available secure export is performed from the platform's data.

### Approved: Responsibility for a Third-Party Application

- The developer is responsible for application operation, commercial support, payment, cancellation, and refunds of money received by the developer.
- The platform is responsible for connection, permissions, its own logs, the catalog, and complaints about rule violations.
- The boundaries of responsibility and contact channels are visible before connection.
- The platform may restrict access in response to risk or a violation, but does not promise a refund of money it did not receive.

### Approved: Payment for Third-Party Applications

- In the first version, the developer accepts payment outside the platform.
- Before connection, the price, period and payment method, cancellation terms, and party responsible for refunds are shown.
- The platform is not the seller of the application and does not withhold a commission from its payment.
- Built-in subscriptions, commissions, refunds, and payment disputes are designed separately after demand has been tested.

### Approved: Application Reviews

- A review may be left only by a seller who actually connected the application.
- The review is marked as verified use.
- Usefulness, reliability, and support are assessed separately from the security-review status.
- User ratings do not raise or replace the security review.
- Moderation and appeals follow the platform's general verifiable procedure.

### Approved: Public Application Catalog

- The catalog contains only approved third-party applications.
- The listing shows the developer, purpose, exact permissions, data handling, support, price, and date of the latest review.
- Private integrations for one seller are not published.
- Approval means passing minimum controls, but does not guarantee the developer's business quality.

### Approved: Event Delivery to Applications

- The platform sends signed notifications about catalog, price, and inventory changes.
- The signature confirms the notification's source and integrity.
- Periodic reconciliation of the permitted state recovers missed events.
- A stable event identifier prevents the change from being applied again upon redelivery.

### Approved: Anomalous Application Behavior

- Operations beyond protective limits are rejected.
- Repeated excesses or other anomalous behavior automatically suspend critical permissions and start a review.
- The seller and developer are notified.
- Safe reading is retained only in the absence of a related risk.
- Critical permissions are restored after the seller's confirmation for an understandable non-critical reason or after a platform review.

### Approved: Automation Protective Limits

- The platform sets mandatory safe limits and recommended default values.
- The seller may make the limits stricter for the account or application, but may not weaken a mandatory platform limit.
- Exact numeric values are determined before launch after risk modeling and tested during the pilot.

### Approved: Automatic Changes Through the API

- An application may automatically change prices and inventory only after the relevant permissions have been granted.
- Automation operates within the explicitly granted scope and the seller's and platform's protective limits.
- Every change is logged, has an understandable source, and is shown to the seller.
- Exceeding the limits is blocked or requires the seller's separate confirmation.
- Significant changes trigger a notification; the seller may immediately revoke access and, if permitted, restore the previous value.

### Approved: Boundaries of the First Public API Version

- Applications may read the open catalog.
- After the seller's separate consent, an application may manage only that seller's own cards, prices, and inventory.
- Access to payments, escrow, disputes, identity documents, and private messages is not provided.
- Extension to the excluded areas requires a separate decision, threat model, legal review, and new user consent.

### Approved: Permission Risk Classification

- The platform publishes a single risk matrix with the risk level, validity period, and reconfirmation rules for each permission.
- The same permissions receive the same rules for comparable integrations.
- Those responsible for security and product approve the matrix and review it based on incidents, new threats, and operational data.
- A developer, seller, or individual employee cannot unilaterally downgrade a permission's criticality.

### Approved: Application Permission Duration

- Minimum read permissions remain active until revoked by the seller with visible connection control.
- Access ends after a prolonged period of inactivity established in advance.
- Permissions to change prices, inventory, and other trusted data are time-limited and require the seller's periodic explicit reconfirmation.
- If confirmation is not received, only the specific application's expired permissions end.
- Exact periods are determined before launch based on the risk level and operational data.

### Approved: Repeat Application Reviews

- Continuous automated monitoring applies after approval.
- Material changes to permissions, ownership, infrastructure, or data handling, a confirmed incident, and a new significant risk trigger a repeat review.
- High-risk applications additionally undergo scheduled periodic review.
- Exact periods and risk criteria are determined before launch based on the threat model and operational data.

### Approved: Third-Party Application Incidents

- In the presence of a significant risk, the platform urgently restricts the affected permissions or disables the application.
- Logs and evidence are retained, compromised access is revoked, and the developer and affected sellers are notified.
- Access is restored only after a confirmed fix and the required repeat review.
- An appeal is available but does not delay urgent user protection.
- The initial report does not mean automatic permanent removal without review.

### Approved: Third-Party Integrations

- A seller's private integration works only with their account without a mandatory manual platform queue, but follows the common rules for permissions, limits, and logging.
- An application for several independent sellers registers and undergoes review before public distribution; each seller separately confirms its access.
- The developer and contacts, permissions, connection security, data handling, privacy, support, and incident-reporting process are checked. A critical expansion of permissions requires a repeat review.
- Submission of all source code is not mandatory for every application; additional materials and tests are requested based on risk. Approval is not considered a guarantee of the developer's business quality.

**Approved: Price Benchmark:** the benchmark is optional, each seller sets their own price, and the benchmark is introduced in two stages. Until sufficient internal history accumulates, only a separately attributed verified source is allowed; if none is available, the benchmark is not shown. The platform then switches to a transparent market formula with protection against manipulation. The primary basis of the formula is the prices of verified completed transactions within the platform; current listings are used only as an additional market check. The main value is calculated as the median of suitable prices over a recent period. Only fully completed transactions without a refund, confirmed manipulation, or a recognized material violation are included; delivery cost is accounted for separately. A seller discount reduces the counted price, while a platform or partner subsidy without reducing the seller's amount does not. The transition to the internal median is performed automatically after reaching the category-specific threshold, established in advance, of fresh suitable transactions from several independent buyers and sellers. If the data stop meeting the threshold, the platform returns to a fresh verified external source, or hides the benchmark if none is available. A substantial divergence between current listings and the median temporarily hides the benchmark and starts a data review, but does not directly change the value. The buyer is shown the value, source, update date, period, number of transactions included, and a brief methodology without participant data or individual orders. The buyer may report an error, and the seller may submit a formal request; a confirmed error corrects the data and triggers automatic recalculation, but not manual assignment of a price. Deviation from the benchmark alone does not affect sales access, sanctions, reputation, or ordinary results; the buyer may explicitly sort listings by price or total cost.

**Approved: AI Labeling and Generation:** a public label is mandatory for visible content created or substantially replaced by AI and for fully generated images. Simple technical correction of lighting, cropping, or size without new visible content does not require a public label, but the processing history is retained. If a card contains AI content, the gallery must retain a real image of the product without synthetic additions, and each labeled AI version can be compared with its specific source. Decorative materials, advertising backgrounds, and surroundings may be generated entirely; the image of the product being sold must come from a real source and must not change its properties. An AI image may be used as a cover when labeling is visible, the product is unchanged, a real image is available in the gallery, and comparison with the source is available. The source and published versions are immutable; a rollback reactivates the previous version without erasing history, and the order retains a snapshot of the card at the time of purchase. Before publication, the result is automatically compared with the source and the seller explicitly confirms it; disputed results are blocked until correction or human review. A credible risk of material distortion after publication temporarily hides only the disputed image and starts human review; a single complaint does not by itself block the seller or delete the card.

**Approved: Public Seller Metrics:** at the first launch, the number of completed orders, fulfillment timeliness, cancellations attributable to the seller, confirmed problems, and returns attributable to the seller are shown. The period and sample size are stated; insufficient data are reported directly. The rating and verified reviews are shown separately. Internal anti-fraud signals and the closed risk score are not published.

A problematic event affects public metrics only after the fact and the seller's responsibility have been finally confirmed. Open disputes, unprocessed complaints, preliminary decisions, and ongoing ordinary appeals do not worsen the metric.

Experience and current quality are shown separately: the number of completed orders covers all time, while quality shares cover an explicitly stated recent rolling period with a sample size. There is no single hidden score; the exact period is determined after modeling the pilot.

The profile contains a general seller overview and, with a sufficient sample, separate metrics for physical products, digital products, and services. The relevant fulfillment type has priority in the card; an unreliable percentage is not shown for a small sample.

The seller receives a private breakdown of their own orders and events, the published methodology, a formal error-reporting process, and a recalculation log. A confirmed error corrects the source data and starts automatic recalculation; manually assigning a final metric without grounds is prohibited.

Quality metrics affect ordinary results only as a limited transparent factor with a published methodology and user filters. Relevance remains the basis; the closed risk score is not used for a hidden demotion, and restrictions are applied through a separate sanctions procedure.

The first version of the open format covers the catalog and storefront working core: products, variants, attributes, prices, inventory, media, categories, collections, settings, and data provenance. Orders and verified reviews use separate related schemas; closed payment, dispute, and risk data are not part of the catalog.

Each export contains a schema version. Compatible additions do not break old fields; incompatible changes receive a new major version, an announced support period, transition rules, and a migration tool.

Import first undergoes checking and a preview of matches, changes, and conflicts. Writing occurs only after the seller's explicit confirmation, is retained in the log, and allows the entire operation to be rolled back; unconditional overwriting and automatic creation of duplicates are prohibited.

At the first launch, automatic synchronization runs only from the selected external source into the platform, with owners of field groups explicitly assigned. Reverse portability is performed through a separate export; two-way synchronization is deferred until separate design after the pilot.

The seller may explicitly take control of a field or logical group, after which its synchronization is suspended without disabling the other data. Re-enabling it requires a preview; silently overwriting a manual edit is prohibited.

When a failure occurs, the last confirmed version is retained, the seller is notified, and a damaged related group is not partially applied. After the safe period, affected listings with an unconfirmed price or inventory temporarily stop accepting new orders; exact periods are determined after the pilot.

The open format is governed through a public repository, open proposals, and discussions. At the start, the platform team serves as the responsible maintainers; decisions are made under published criteria and accompanied by a public rationale and version log.

The format specification, schemas, and reference examples are published under a permissive open license allowing independent and commercial implementations. The exact license is selected after legal review.

The basic safe API is free for documentation, permitted public reading, checkout links, and a reasonable amount of seller work with their own data. Higher limits, managed connectors, frequent synchronization, and guaranteed service may be paid; a full manual export remains free.

Each application receives separate minimum permissions after the seller's explicit confirmation, keeps its own log, and may be disabled immediately. The account password and a shared perpetual key are not given to applications; expanding critical permissions requires new consent.

A seller's private integration may work only with their account without a manual queue. An application for several independent sellers registers and passes a security and rules review before public distribution; each seller still confirms access separately.

Before broad approval, the developer, requested permissions, connection security, data-storage and deletion rules, privacy, support, and incident readiness are checked. A critical expansion of permissions requires a repeat review; source code is not always requested, but according to risk.

When a credible incident occurs, the significant risk is immediately restricted, logs are retained, participants are notified, and access is restored only after a confirmed fix. The developer may appeal the decision, but an appeal does not delay temporary user protection.

After approval, the application is continuously monitored and reviewed again after material changes or a new risk; high-risk applications additionally undergo scheduled review. Exact periods and criteria are established before launch.

Minimum read permissions remain active until revoked and end after prolonged inactivity. Critical permissions to change trusted data are time-limited and require the seller's periodic reconfirmation; exact periods are determined before launch based on risk.

Permission criticality and validity period are set by the platform's single published matrix. It is applied equally to comparable integrations and reviewed by those responsible for security and product based on actual risk data.

The first public API version covers reading the open catalog and managing the connecting seller's own cards, prices, and inventory. Payments, escrow, disputes, identity documents, and private messages are excluded.

Automatic changes to prices and inventory are permitted only within the granted scope and protective limits. All changes are logged and shown to the seller; excesses are blocked or require separate confirmation, and access can be revoked immediately.

The platform sets mandatory safe limits. The seller may only make them stricter; exact numbers are determined after risk modeling and the pilot.

Operations beyond the limits are rejected. Repeated or anomalous violations temporarily suspend critical permissions, notify participants, and start a review; safe reading is retained only in the absence of a related risk.

Catalog, price, and inventory changes are sent to applications as signed notifications. Periodic reconciliation recovers omissions, and the event identifier prevents the same change from being applied again.

The public catalog contains only approved applications and shows the developer, purpose, permissions, data handling, support, price, and review date. Private integrations are hidden; approval is not considered a guarantee of business quality.

Only sellers with verified use leave application reviews. User ratings of usefulness, reliability, and support are separate from the security-review status.

In the first version, paid applications are paid for to the developer outside the platform under terms visible in advance. Built-in subscriptions, refunds, and a platform commission are deferred until a separate decision after demand has been tested.

The developer is responsible for application operation, commercial support, payment, and refunds; the platform is responsible for secure connection, permissions, the catalog, and compliance with rules. The boundaries are visible before connection.

When support ends, new connections stop, sellers are notified, and, in the absence of risk, receive a transition period. Then permissions are revoked and data deletion is confirmed; significant risk is disabled immediately.

Identical-product listings are ordered by transparent utility by default: delivery availability, total cost, time, distance, and fulfillment quality. Paid elevation is prohibited, and the buyer may choose separate sorting.

Numeric factor weights are determined before launch after modeling and the pilot, then published and versioned. The same version is applied to comparable conditions; secret manual or AI changes are prohibited.

In the first public launch, there is no hidden personalization of seller order: only the explicitly specified address, filters, and sorting are considered. The order is the same under the same conditions; future personalization is possible only transparently, disableably, and with separate consent.

There is no paid placement in public beta. After the pilot, only separate, clearly marked advertising blocks that do not change organic results are possible; payment does not raise the ordinary position.

Different products in common search are ordered first by relevance to the query, category, and attributes, then by availability, delivery, and verified quality. The factors are transparent, paid influence is prohibited, and separate sorting methods are available.

The absence of history for a new seller or product is neutral: “insufficient data” is shown, enhanced initial monitoring applies, and there is no automatic lowering or raising of position.

International expansion begins only after stable operation in Russia. Countries are added one at a time after full legal, payment, tax, currency, localization, logistics, and operational preparation and a separate pilot.

Internal preparation begins with the transaction core, then adds full seller tools and storefronts, followed by the open format and API, with the AI designer connected last as a limited beta. All approved directions are combined before public launch.

1. Numeric thresholds, periods, and permitted deviations for the price benchmark by category, determined after modeling and obtaining pilot data.
2. AI media limits, version-retention periods, and automated-review thresholds after technical tests, cost calculation, and legal review.
3. Numeric thresholds for quality, safety, stability, and economics for the AI designer to exit limited beta.
4. Research and selection of the public brand, checking matches, domains, and trademarks, and exact presentation copy.
5. Numeric thresholds and measurement period for Russian pilot metrics.
6. Exact list of seller documents and criteria for enhanced review of sellers and buyers.
7. Exact composition of allowed and prohibited categories.
8. Exact single pilot commission rate after calculating mandatory costs.
9. A payment partner supporting a common payment, distribution among sellers, independent holds, and partial refunds; legal review of the scheme.
10. Initial external import sources and their official capabilities.
11. Exact rules for disputes, payouts, and automatic acceptance.
12. First version of the open data format.
13. Exact prices and limits for AI features and media.
14. Minimum analytics and integration scope for launch.
15. Detailed readiness criteria and verifiable implementation stages for each subsystem within the approved sequence.
16. Initial delivery services, hierarchy of receipt evidence, and rules for seller-owned delivery.
17. Exact evidence of digital fulfillment, dispute periods, and refund rules for files, keys, subscriptions, and services.
18. Requirements for managed storage and external delivery of digital products, including link verification and availability period.
19. Technology stack, deployment architecture, and detailed module interfaces within the approved common core.

---

## 19. What Has Not Yet Been Done

- the repository has not been created;
- no code has been written;
- a payment partner has not been selected;
- the legal model has not been reviewed;
- the product name has not been selected;
- the written architecture specification has been approved by Vladislav without changes;
- the subordinate specification for the first phase of the transaction core has not been written;
- an implementation plan has not been prepared.

This document records the concept; it does not confirm the technical or legal feasibility of all points.

---

## 20. Recommended Skills for Continuation

The next agent or a new session is recommended to use:

- `superpowers:brainstorming` — continue aligning the concept;
- `grill-with-docs` — strict question-based review of the protocol;
- `domain-modeling` — model of the seller, product, order, fulfillment, review, and dispute;
- `codebase-design` — boundaries of future subsystems;
- `wayfinder` — breaking a large program into stages;
- `grounded-citations` — checking legal and payment claims against primary sources;
- `technical-plan-validation` — checking the future technical plan;
- `superpowers:writing-plans` — only after approval of the final specification.

## Sources

[1] https://www.consultant.ru/document/cons_doc_LAW_61763/75fad2ba0bd186dad16ff04a2efe55ae3f9ff7e6 — 135-FZ “On Protection of Competition,” Article 11
[2] https://www.consultant.ru/document/cons_doc_LAW_61763/56ebcb13554d43c05bafaceb47b4e73d289fd904 — 135-FZ “On Protection of Competition,” Article 12
