# Open Marketplace — Phase 2: Catalog, Variants, Stock, and Search

**Status:** implementation was authorized by Vladislav's direct instruction to work independently without further interviewing and confirmed with “continue.” The individual CAT decisions below are preserved. The remaining technical decisions were made by the implementer and recorded separately in `../plans/2026-09-15-phase-2-catalog-implementation.md`; they are not presented as separate user answers. Readiness is verified by actual tests and startup, not by this status.

**Agreement started:** 2026-09-14.

**Current authorization:** Vladislav authorized independently bringing the agreed catalog to a working result and publishing the project in the existing GitHub repository, without further interviewing. Technical decisions and constraints are recorded in the implementation plan. Repository visibility, real access, an external server, and paid APIs do not change. The agreement history is preserved below; the former interview constraints and the wording “not implemented yet” describe the corresponding checkpoint, not current readiness. Actual acceptance is in the [validation report](../../security/phase-2-local-validation.md).

## Sources and Scope

- [Approved general specification](2026-09-02-open-marketplace-design.md), especially sections 5–8 and 15.
- [Concept protocol](../../../concept-protocol.md), especially sections 6–7 and 15.

According to the approved sequence, Phase 2 covers the catalog, variants, stock, search, and a minimal buyer interface. The cart, orders, payments, and physical and digital fulfillment belong to the next stage. Preliminary delivery calculation for comparing seller offers has also been moved to the next stage under CAT-COMPARE-DELIVERY-SCOPE-01; in Phase 2, this comparison temporarily uses only the item price with an explicit warning. The detailed work scope and criteria for all of Phase 2 are still being agreed.

The public beta's general concept already provides for physical goods and downloadable files, sellers' own cards, common cards for demonstrably identical mass-produced goods, an independently set seller price, and a single stock amount for a physical variant across storage locations. This document does not re-open those decisions. The public beta rule from the protocol's “Downloadable File Storage” section remains in force: before publication, the file being sold must be uploaded to platform-managed storage and pass permitted-format and malicious-content checks. In Phase 2, downloadable goods are available only as non-public drafts under CAT-DIGITAL-SCOPE-01. Upload, managed storage, and checks of the files being sold, as well as delivery to the buyer, belong to the next stage.

## Agreed Decisions

### CAT-PUBLISH-01 — Independent First Publication

**Status:** approved by Vladislav on 2026-09-14; option “2” was selected in response to the choice of first-publication workflow.

For a regular card created manually by a seller:

- the seller publishes the card independently after successful automated completeness checks;
- after such publication, the card is visible to buyers without waiting for mandatory approval by a marketplace staff member;
- a staff member reviews the card later, for example in response to a complaint;
- no mandatory manual queue before the first publication is introduced.

Seller admission and review of the seller's card remain separate procedures. This decision does not change the previously approved AI-media rules and does not define how an already published card is edited. Downloadable goods are subject to the separate Phase 2 restriction CAT-DIGITAL-SCOPE-01: only non-public drafts are available, with no publication capability.

Verifiable consequences for future implementation:

- when automated checks succeed, first publication does not require a prior staff decision;
- a new card that fails mandatory automated checks does not become available to buyers.

These are requirements for future checks, not a report of completed tests. CAT-PUBLISH-MINIMUM-01 defines the minimum data for publishing the seller's own physical card. The complete set of technical checks, file restrictions, and the process for subsequent staff review still need to be defined.

### CAT-EDIT-01 — Description and Photo Draft

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for changing the description and photos of a published card.

- The seller edits the description and photos in a separate draft.
- Until the changes are published, buyers continue to see the card's previous published version.
- To apply the prepared changes, the seller independently performs the “Publish changes” action.
- After successful automated checks, the new version replaces the previous public version.
- Prior marketplace-staff approval is not required.

Price and stock are not part of the description and photo draft; CAT-OFFER-01 defines how they are changed. For the seller's own published physical-goods card that is not attached to a common card, the name, selected category, and attribute values are part of the same draft under CAT-EDIT-FIELDS-01.

Verifiable consequences for future implementation:

- saving a description and photo draft does not change the public card;
- successful publication applies the prepared changes together rather than showing them to buyers in pieces;
- an unsuccessful automated check does not replace the previous published version.

These are requirements for future checks, not a report of completed tests.

### CAT-OFFER-01 — Separate Saving of Price and Stock

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for changing the price and quantity of goods in stock.

- The seller changes the price or the quantity of goods in stock and performs a separate “Save” action.
- After successful automated checks, the corresponding active value is updated immediately.
- Saving does not depend on the readiness of the description and photo draft and does not require the “Publish changes” action.
- Saving the price or stock does not itself publish the description and photo draft.
- Prior marketplace-staff approval is not required.

Verifiable consequences for future implementation:

- the active price and stock can be updated while the seller prepares a description and photo draft;
- a change rejected by automated checks does not replace the corresponding active value;
- subsequently publishing a previously created description and photo draft does not return the price or stock to its old values.

These are requirements for future checks, not a report of completed tests. The decision does not add orders, payments, or item reservation.

### CAT-AVAILABILITY-01 — Out-of-Stock Card by Direct Link

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for direct-link access to a card for an out-of-stock physical good.

- If a seller's previously published physical good is out of stock in all variants, the lack of stock does not by itself hide its public page.
- The published description and photos remain available through the direct link.
- The page prominently displays the “Out of stock” label.
- An unpublished description and photo draft does not become available to buyers.

The decision concerns only the lack of stock and direct-link access. It does not cancel voluntary unpublishing or separate security and moderation restrictions. Display in the general catalog and search is governed by CAT-SEARCH-01; this decision does not determine the state of a common card with offers from other sellers.

Verifiable consequences for future implementation:

- after all variants are exhausted, the previously published card opens at its former link with the published description, photos, and “Out of stock” label;
- the lack of stock does not expose draft changes;
- the page-preservation rule does not make previously unpublished cards public and does not restore cards hidden for other reasons.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-01 — Lack of Stock in the General Catalog and Search

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for displaying physical goods without available stock in the general catalog and search.

- If a physical good is not in stock with any suitable seller, it is not shown in the general catalog or general search by default.
- A lack of stock with one seller does not by itself exclude the good as a whole if another seller has a suitable offer in stock.
- Excluding it from results does not cancel the agreed direct-link access under CAT-AVAILABILITY-01.
- This is an availability filter, not the complete set of display conditions. Publication, permissions, security restrictions, and the remaining search criteria continue to be considered separately.

The decision does not revisit section 8.1 of the general specification: offers without stock are excluded before seller offers for an identical good are sorted. This clarifies the display of goods in the overall results, not the ordering of offers within one common card.

Verifiable consequences for future implementation:

- a physical good with no available in-stock offers is absent from the normal general-catalog and search results;
- a suitable offer from at least one seller means the good cannot be considered entirely unavailable;
- the previously agreed direct-link access remains;
- after successfully replenishing stock for a previously published offer, republishing the description and photos is not needed to pass the availability filter; other grounds for hiding it are not canceled by this.

These are requirements for future checks, not a report of completed tests.

### CAT-MATCH-01 — Confirmation of Attachment to a Common Card

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for confirming that the seller's good matches the common card.

For demonstrably identical mass-produced physical goods:

- the seller proposes attaching their offer to a suitable common card;
- an authorized marketplace staff member checks that the model, attributes, package contents, and condition match under the general concept's approved identity rules;
- attachment is performed only after staff confirmation; automated checks alone do not replace this confirmation;
- while the match is being checked, the seller may independently publish their own card under CAT-PUBLISH-01;
- until confirmation, the card may remain unmatched, as provided by the general concept.

Rejection of the match does not by itself prohibit independent publication of the seller's own card. The remaining publication conditions and separate security and moderation restrictions remain in force. Price and stock remain data belonging to the specific seller and are governed by CAT-OFFER-01.

Verifiable consequences for future implementation:

- an offer is not attached to a common card without confirmation by an authorized staff member;
- a match confirmed by a staff member permits attachment;
- a pending or rejected match does not by itself block independent publication of the seller's own card when the remaining conditions are met.

These are requirements for future checks, not a report of completed tests. The decision concerns matching goods from different sellers to a common card, not importing into the seller's own catalog.

### CAT-COMMON-EDIT-01 — Changes to Common-Card Content

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for changing the description, attributes, and photos of an already created common card.

- Sellers propose corrections to common data.
- An authorized marketplace staff member reviews and publishes the proposed corrections.
- A seller cannot independently change the public content of a common card for the other attached sellers.
- Automated checks alone do not replace staff review and publication.
- The price and stock of the seller's offer remain under the seller's independent control under CAT-OFFER-01 and are not common card data.

The approved requirements for demonstrable product identity remain mandatory: the right to edit a common card does not permit turning it into a different good under the previously attached offers. This decision concerns edits to an existing common card, not the process for creating a new one.

Verifiable consequences for future implementation:

- a seller's correction proposal does not by itself change the public content of the common card;
- common edits are published only after review by an authorized staff member;
- a seller's independent change to their own card does not automatically overwrite common data;
- editing common content does not change the prices or stock of attached sellers.

These are requirements for future checks, not a report of completed tests.

### CAT-TAXONOMY-01 — Categories and Attribute Sets

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for managing the shared directory of categories and attributes.

- Authorized marketplace staff create and maintain categories and attribute sets, including field requirements.
- The seller independently selects an available category and fills in the provided fields for their card.
- If a category or attribute is missing, the seller proposes an addition to a staff member.
- The seller does not independently add to or change the general catalog structure.
- Normal completion and publication of a card under the current rules do not require a new manual review; CAT-PUBLISH-01 applies.

The decision concerns the shared directory, not personal storefront collections. It does not establish a specific list of categories permitted for sale, replace the necessary legal review, or permit bypassing category restrictions. CAT-TAXONOMY-CHANGE-01 defines how a normal new required field is applied to already published cards.

Verifiable consequences for future implementation:

- the seller may select an available category and fill in its fields, but cannot directly change the shared directory;
- a seller's proposal for a new field or category does not by itself change the shared directory;
- a correctly completed card does not enter the mandatory manual queue merely because it uses an existing category.

These are requirements for future checks, not a report of completed tests.

### CAT-TAXONOMY-CHANGE-01 — New Required Field on Published Cards

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for the normal addition of a required field — do not hide old cards.

- Cards published before the normal addition of a new required field are not hidden solely because this value is missing.
- The seller can see that the data needs to be completed.
- The new field is required when publishing new cards and when next publishing content edits to a previously published card.
- Separate saving of the price and quantity under CAT-OFFER-01 continues to work and is not blocked solely because the new descriptive value is missing.
- Until content edits pass checks and are published, buyers see the previous published version. Saving the price or stock does not publish this draft.

The decision concerns a normal update to product-description requirements. It does not cancel urgent legal, security, or moderation restrictions, other visibility conditions, or previously agreed rights to edit a common card. This decision does not establish specific required fields, their values, the notification channel, or the deadline for completing data in bulk.

Verifiable consequences for future implementation:

- adding a normal required field does not by itself hide the previous publication at its direct link or exclude it from the catalog or search when the remaining display conditions are met;
- publishing a new card and publishing edits to an old one are rejected when the new required value is missing; rejecting the edits does not hide the previous public version;
- after the new field is completed, publication is possible when the remaining conditions are met and the previously agreed review process is preserved;
- the lack of a new descriptive value does not by itself prevent correctly changing the price or stock separately.

These are requirements for future checks, not a report of completed tests.

### CAT-DIGITAL-SCOPE-01 — Downloadable Goods Only in Drafts in Phase 2

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for the Phase 2 boundary — only a digital-card draft for now.

- The seller may prepare the description and price of a downloadable good in a draft.
- In Phase 2, such a card is not published and is not visible to buyers.
- Upload, managed storage, and checks of the file itself are moved to the next stage together with digital fulfillment.
- Orders, payment, and secure delivery of the file to the buyer remain outside Phase 2.
- The deferral concerns the file being purchased itself, not the card's photos.

The decision defines the stage boundary; it does not exclude downloadable files from the public beta. The previously approved requirements for managed storage, pre-publication file checking, and the exact version in an order remain in force. Normal independent publication under CAT-PUBLISH-01 does not cancel the ban on publishing a digital card in Phase 2. An external link does not replace the deferred file upload and checks.

Verifiable consequences for future implementation:

- the seller may save the description and price of a digital draft;
- the digital draft is not shown in the buyer catalog or search and is not exposed to the buyer through a direct link;
- an attempt to publish a digital card in Phase 2 is rejected even if its description and price are completed correctly; the restriction is not limited to omitting a button from the interface;
- saving the description or price does not make the digital draft public;
- receipt and delivery of the file being sold are not implemented in Phase 2.

These are requirements for future checks, not a report of completed tests. This agreement does not authorize implementation, new infrastructure, or changes for the next stage.

### CAT-EDIT-FIELDS-01 — Name, Category, and Attributes in the Same Draft

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for the remaining fields of the seller's own card — through the same draft.

For the seller's own published physical-goods card that is not attached to a common card:

- The card's name, selected category, and attribute values are edited in the same draft as the description and photos under CAT-EDIT-01.
- Until the changes are published, buyers continue to see the previous published version of this data.
- After successful automated checks, the “Publish changes” action applies the prepared content changes together.
- Prior staff approval is not required for the normal publication of these changes.
- The price and quantity are saved separately under CAT-OFFER-01; publishing the content draft does not return them to their old values.

Selecting an existing category and filling in field values does not give the seller the right to change the shared directory under CAT-TAXONOMY-01. Checks for required fields in the selected category and CAT-TAXONOMY-CHANGE-01 remain in force. The decision does not change the process for editing a common card, creating or withdrawing variants, or taking actions on an already confirmed match.

Verifiable consequences for future implementation:

- saving the draft name, category, and attributes does not change the card's public data; the new category and draft attributes are not used as published data in the buyer catalog or search;
- successful publication applies the prepared name, category, attributes, description, and photos as one content version;
- publication checks the required fields of the category selected in the draft; an unsuccessful check applies none of the edits and does not replace the previous public version;
- separate saving of the price and quantity does not publish the draft; subsequent publication of the draft does not roll back the active price and quantity.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-ADD-01 — New Variant in the Same Card Draft

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for adding a new variant — through the same card draft.

For the seller's own already published physical-goods card that is not attached to a common card:

- The seller prepares a new variant in the same card draft as the other content changes under CAT-EDIT-01 and CAT-EDIT-FIELDS-01.
- Creating and saving a new variant in the draft does not by itself make it available to buyers.
- The seller performs the “Publish changes” action; after successful automated checks, the new variant is published together with the card's other prepared edits.
- Phase 2 does not introduce independent publication of only the new variant while leaving the other prepared edits in the draft.
- Normal publication is performed by the seller without prior staff approval. The remaining publication, display, and availability conditions remain in force.
- The price and quantity of already published variants continue to be saved separately under CAT-OFFER-01 and are not rolled back when the draft is published.

The approved principle of one actual stock amount for a variant across the seller's storage locations remains in force: publication does not create a separate copy of this stock. The decision does not define withdrawing or deleting variants, changes to a common card, or reconsidering a confirmed match.

Verifiable consequences for future implementation:

- a saved but unpublished new variant is not shown to the buyer and does not participate in buyer filters or calculations of displayed prices and availability;
- stock for an unpublished new variant does not by itself allow the card to pass the availability filter if no suitable published variants are in stock;
- successful publication applies the new variant together with the card's prepared content changes;
- an unsuccessful publication check does not show the new variant or apply any of the other draft edits; the previous public version is preserved;
- adding and publishing a new variant do not roll back the active price and quantity of existing published variants and do not create an additional copy of actual stock.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-WITHDRAW-01 — Separate Withdrawal of a Variant from Publication

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for voluntarily withdrawing a variant — immediately, as a separate action.

For the seller's own physical card that is not attached to a common card, when one published variant is withdrawn and the others remain published:

- The seller performs a separate “Withdraw from publication” action for the selected variant.
- After a successful permission check, the variant is immediately removed from the buyer's selection for this card; the readiness of the draft containing the other edits is not required for this.
- Withdrawal does not itself publish the card's other draft edits.
- Publishing a previously prepared draft does not by itself return the withdrawn variant.
- The variant's data is preserved; this action does not set its actual stock to zero or deduct it.
- The other variants are not withdrawn automatically; the remaining display conditions continue to be considered.

This is a voluntary discontinuation of the variant offer, not exhaustion of its stock. Saving or replenishing stock does not by itself cancel the withdrawal from publication: the display exclusions and restrictions under CAT-SEARCH-01 remain in force. The action does not define permanent data deletion, how the variant is returned, access through former links, or actions on a common card. CAT-CARD-WITHDRAW-01 defines the card's visibility after the last published variant is withdrawn.

Verifiable consequences for future implementation:

- a variant can be withdrawn while the card's other edits are in an unfinished draft; those edits do not become public;
- a withdrawn variant is absent from the buyer's selection and is not considered an available offer in availability filters even if its actual stock is positive;
- withdrawal does not delete the variant's data, change its actual stock, or withdraw the other variants;
- publishing a draft prepared before withdrawal does not automatically return the variant to the buyer's selection;
- separately saving the price or quantity does not by itself return the withdrawn variant to publication.

These are requirements for future checks, not a report of completed tests.

### CAT-CARD-WITHDRAW-01 — Hiding the Card after Withdrawing the Last Variant

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for card visibility after withdrawing the last published variant — hide the card content.

For the seller's own physical card that is not attached to a common card, after voluntarily withdrawing the last published variant:

- The card is not shown in the buyer catalog or search.
- At the former direct link, the buyer sees only the “Card unavailable” message, without the card's description or photos.
- The previous published content version and unpublished draft edits are not exposed to the buyer instead of this message.
- The card and variant data remains available to the seller within their normal access rights; actual stock is not set to zero or deducted.
- Changing the price or quantity does not by itself return the card to public display.

The decision concerns voluntarily withdrawing the last published variant, not merely a lack of stock. CAT-AVAILABILITY-01 remains in force: when published physical variants simply run out, the former description and photos remain at the direct link with the “Out of stock” label unless there are other grounds for hiding them. Returning voluntarily withdrawn variants is governed by CAT-VARIANT-RESTORE-01; security, legal, and moderation restrictions are not canceled.

Verifiable consequences for future implementation:

- after voluntarily withdrawing the last published variant, the card is absent from the catalog and search, and its direct link returns only an unavailable message to the buyer without the card content;
- positive actual stock in withdrawn variants does not preserve or restore the card's public display;
- hiding the card does not delete data or change actual stock;
- a hidden card exposes neither the previous content nor the draft to the buyer;
- when only the stock of variants that remain published is exhausted, CAT-AVAILABILITY-01 continues to apply, not this hiding rule.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-RESTORE-01 — Returning a Withdrawn Variant through the Same Draft

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for returning a voluntarily withdrawn variant — through the same draft.

For the seller's own physical card that is not attached to a common card, when the seller returns a previously published variant that they voluntarily withdrew:

- The seller explicitly selects the needed variant for return in the same card draft.
- Saving this selection does not yet return the variant to public display.
- After the “Publish changes” action and successful automated checks under the current rules, the selected variant returns together with the other prepared card-content edits.
- No separate action is introduced to restore the variant's previous published data without the other prepared edits.
- The other withdrawn variants are not returned automatically. The presence of a variant record in an old draft or a change to its stock does not replace the explicit choice to return this variant.
- The active price and quantity are saved under CAT-OFFER-01 and are not replaced by values from the old snapshot.

The saved variant is returned; a duplicate with separate stock is not created. If the card was hidden only because it had no published variants under CAT-CARD-WITHDRAW-01, successful publication of the explicitly selected returning variant removes that particular reason for hiding it. The remaining visibility, availability, and publication-permission conditions continue to be considered. This decision does not govern removal of a staff block, refund rules, or actions on a common card.

Verifiable consequences for future implementation:

- explicitly selecting a variant for return and saving the draft do not by themselves make it public;
- successful publication returns only the explicitly selected withdrawn variants together with the prepared content edits;
- current required conditions are checked again; an unsuccessful check does not return the variant or apply any of the draft edits;
- other withdrawn variants remain withdrawn even if their records were present in the old draft;
- returning the variant does not create a second variant or a separate copy of its actual stock and does not roll back the active price and quantity;
- when a card previously hidden because all variants were withdrawn has a variant returned, it can become available to the buyer again only when the remaining display conditions are met; other restrictions are not removed automatically.

These are requirements for future checks, not a report of completed tests.

### CAT-UNITS-01 — Pieces, Kilograms, and Meters

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for physical-goods units of measure in Phase 2 — pieces, kilograms, and meters.

- Phase 2 supports pieces, kilograms, and meters as units of measure for the physical good being sold.
- One unit is selected for each card and is the same for all its variants.
- The quantity in pieces must be an integer; the quantity in kilograms and meters may be fractional, for example “1,5 m”.
- The offer price is stated per one selected unit: piece, kilogram, or meter.
- The quantity of each variant is tracked separately by the seller's storage locations; using the same unit does not combine the stock of different variants.

The decision concerns the unit of the quantity sold and its price, not the weight and dimensions used for delivery. It does not automatically add other units, establish conversion between units, or define the permitted quantity in an order. CAT-STOCK-PRECISION-01 defines the precision of quantities in kilograms and meters; CAT-UNIT-LOCK-01 defines locking the unit of the seller's own card after saving the price or stock. The agreed category permissions and the deferral of orders, payment, and fulfillment to the next stage remain in force.

Verifiable consequences for future implementation:

- a physical card may use one of the agreed units: pieces, kilograms, or meters;
- different variants of one card do not use different units of measure;
- a fractional quantity of pieces is rejected, while fractional quantities in kilograms and meters are supported; a fractional value, for example “1,5 m”, is not converted into an integer quantity;
- the displayed price is accompanied by an indication of the selected unit for which it is set;
- changing the quantity of one variant does not change the quantities of other variants or combine their actual stock.

These are requirements for future checks, not a report of completed tests.

### CAT-UNIT-LOCK-01 — Locking the Unit after Saving Price or Stock

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for changing the unit already used by the seller's own card — lock the unit.

For the seller's own physical card that is not attached to a common card:

- After the seller's first successful saving of at least a price or stock, the card's unit of measure is locked and cannot be changed.
- Saved data for one variant is sufficient: the unit is shared by all card variants under CAT-UNITS-01.
- The restriction does not depend on whether the card is published or still in draft.
- A new card is created for another unit; the corresponding prices and quantities are entered again without automatic copying from the previous card.
- Phase 2 does not introduce a separate process for switching an existing card to another unit while replacing its prices and stock at the same time.

Creating a new card does not automatically transfer or copy actual stock, delete the previous card, or change its prices or stock. Normal updates to the price and quantity in the locked unit continue to work under CAT-OFFER-01. This decision does not define changing the unit of a common card, fractional precision, or quantity rules in an order.

Verifiable consequences for future implementation:

- the first successful saving of a price without stock or stock without a price locks the unit for the entire card;
- a subsequent attempt to change the unit is rejected, including through a content draft, and does not relabel prices and stock that have already been saved;
- subsequently setting stock to zero or withdrawing the card from publication does not cancel the lock created after the first data save;
- a normal change to the price and quantity in the previous unit is not blocked solely because the unit is locked;
- creating a card with another unit does not copy the old prices and stock into it or change them in the original card.

These are requirements for future checks, not a report of completed tests.

### CAT-COMPARE-DELIVERY-SCOPE-01 — Temporary Price Comparison without Delivery Calculation

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for comparing seller offers in Phase 2 — compare the item price for now and add delivery calculation in the next stage.

For seller offers of one selected physical variant in a common card:

- In Phase 2, offers are shown in ascending order of the stated item price per one identical unit of measure.
- The “Delivery has not been calculated yet” label is shown explicitly during comparison; the item price is not presented as the total purchase cost.
- Preliminary delivery calculation and comparison including it belong to the next stage. Orders, payment, and fulfillment itself also remain in the next stage.
- An unknown delivery cost is not treated as zero or free delivery. Without the relevant data, no promise is made about delivery to the address, its cost, or its time.
- Publication, availability, and selling-permission restrictions remain in force. The temporary process does not return withdrawn, blocked, or unavailable offers to the comparison.

This is an interim Phase 2 process, not a change to the target public-beta search. Before it launches, the approved rules in section 8.1 of the general specification must apply: delivery availability, total cost, time, distance, and confirmed fulfillment quality. The decision does not define ranking different goods for a search query and does not authorize connecting external services or implementing it.

Verifiable consequences for future implementation:

- suitable offers for one selected variant are compared by the active item prices for the same unit; the lower price appears before the higher one;
- unknown delivery conditions are not replaced with invented numbers and do not affect this temporary process as supposedly known free delivery;
- the buyer sees the “Delivery has not been calculated yet” warning and receives no promise of the total purchase cost;
- offers without stock, publication, or selling permission are not included in the comparison merely to sort them by price;
- readiness of the temporary comparison is not considered fulfillment of the requirements for final public-beta search.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-GROUP-01 — One Search Result per Product Card

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for representing a card with multiple variants in search — one result per product card.

For one physical card with its variants:

- In search results, the card is shown once even if several of its variants match. Its variants can be selected inside the opened card. For the seller's own physical card, CAT-SEARCH-OPEN-VARIANT-01 defines the initial selection when navigating from search.
- To appear in the results, at least one published variant must have an available offer in stock and simultaneously match the selected filters. Different variants cannot separately satisfy different filters instead of one matching variant.
- The displayed price and availability are determined only from the matching variants and offers of this card. The price of another variant that does not match by color or size is not used to attract the user to this result.
- If the result contains different matching prices, the minimum is shown with the “from…” label. If there is one price or all matching prices are the same, that price is shown without requiring the “from…” label.
- The price applies to one selected unit of measure under CAT-UNITS-01, not to the total purchase cost including delivery. The deferral of delivery calculation under CAT-COMPARE-DELIVERY-SCOPE-01 remains in force.

The decision preserves CAT-SEARCH-01 and the other publication, availability, and permission restrictions. It does not permit automatically combining independent cards from different sellers and does not change CAT-MATCH-01: variants of one existing card are grouped, not any similar goods. This decision does not define the final ranking algorithm for different goods.

Verifiable consequences for future implementation:

- several matching variants of one card produce one result, not separate results for each color and size;
- if there is no matching variant with an available offer, the card does not appear in the result even when its other variants are in stock;
- the required color matching one variant and the required size matching another do not replace a variant matching both filters at the same time;
- a cheaper variant that does not match, is unavailable, or is non-public does not lower the displayed price;
- with different matching prices, their minimum is shown with “from…”, while with one price or identical prices, the corresponding price is shown;
- opening the result leads to one card with a selection of its variants, without creating new cards or independent copies of stock.

These are requirements for future checks, not a report of completed tests.

### CAT-STOCK-PUBLIC-01 — Only Availability Status Is Public

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for public stock display in Phase 2 — only “In stock” or “Out of stock,” without the exact quantity.

For a selected physical variant from a specific seller in a public card:

- The buyer sees the “In stock” or “Out of stock” status, but not exact warehouse figures.
- The exact quantity is not sent to the buyer either as a hidden field or as other public-page data. Hiding only the visible label while leaving the number in the page data is insufficient.
- In the private dashboard, the seller still sees their exact stock and can change it under CAT-OFFER-01.
- Internal tracking is not replaced by the availability status: quantities by variant and seller storage location are preserved. Stock from different sellers and different variants is not combined into one number.
- The status does not expose data that should not be public: withdrawn, blocked, and draft offers do not become visible because of this rule.

The decision concerns public display in Phase 2. It preserves CAT-AVAILABILITY-01, CAT-SEARCH-01, and the other visibility rules. The process for rechecking and displaying trusted data during checkout and before payment in the next stage is not re-opened. This decision does not change fractional-quantity precision or access permissions.

Verifiable consequences for future implementation:

- a public card for an offer permitted to be shown reports availability without the exact quantity;
- the exact stock is present neither in visible text for the buyer nor in hidden data sent with the public page;
- exact seller-owned quantities are preserved and available to the seller in the private dashboard;
- when stock is exhausted, the agreed “Out of stock” rules and search exclusions apply rather than publishing a warehouse figure;
- switching to status display does not change actual quantities or combine stock from different variants or sellers;
- the rule does not allow the availability or stock of a non-public offer to be obtained by bypassing visibility restrictions.

These are requirements for future checks, not a report of completed tests.

### CAT-STOCK-PRECISION-01 — Stock in Kilograms and Meters to Three Decimal Places

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for stock precision in kilograms and meters — up to three decimal places.

For internal tracking of physical stock in Phase 2:

- Quantities in kilograms and meters are stored exactly in increments of 0.001 of the selected unit: one gram for kilograms and one millimeter for meters.
- Values with fewer decimal places and integer values are allowed. Entering all three places or adding zeros is not required: for example, 1.5 m is valid alongside 1.234 m.
- If a quantity cannot be stored at the selected precision without changing its value, saving is rejected with a clear explanation. The system does not round the number automatically, and the previous stock remains unchanged.
- The quantity in pieces must still be an integer under CAT-UNITS-01.
- The unit remains common to the card and its variants, while stock remains separate by variant and seller storage location. CAT-UNIT-LOCK-01 and CAT-STOCK-PUBLIC-01 remain in force.

This is accounting-stock precision, not a minimum purchase quantity or order increment. The decision does not define price precision, the maximum stock amount, or weight and dimension units for delivery. The remaining save checks and access permissions continue to apply separately.

Verifiable consequences for future implementation:

- when the remaining quantity rules are met, quantities of 1.234 kg, 1.234 m, and 1.5 m are saved without changing their numerical values;
- 1.2345 kg or 1.2345 m are rejected for insufficient precision, without rounding and without changing the previous stock;
- a positive quantity smaller than the increment, such as 0.0004 kg or 0.0004 m, is not silently turned into zero stock: such a save is rejected;
- the seller is told the reason for rejection and the permitted precision;
- fractional quantities in pieces do not become valid because three decimal places are supported for kilograms and meters;
- saving a permitted fraction does not change the card's unit or combine its stock.

These are requirements for future checks, not a report of completed tests.

### CAT-CURRENCY-01 — Rubles Only in Phase 2

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for catalog price currency in Phase 2 — rubles only.

- Sellers set catalog prices in rubles; buyers see ruble prices for offers permitted for public display.
- This rule also applies to prices in non-public drafts of downloadable goods, but does not make those drafts visible to buyers.
- Price comparison in Phase 2 does not use currency conversion and does not depend on obtaining exchange rates.
- Entering a price in another currency is not supported: that currency cannot silently be relabeled “rubles” while retaining the old number or be converted automatically without an agreed process.
- Other currencies may be added later only by a separate decision. This is a current-stage restriction, not a permanent ban on expansion.

The price currency remains a separate part of the data and is not replaced by the country or interface language. The separation of country, currency, and language from the concept protocol's “Geography” section remains in force. The initial Russian launch is not re-opened. Payment remains the next stage; this decision does not select a payment partner, price precision, price limits, or international launch. Price precision is defined separately in CAT-PRICE-PRECISION-01.

Verifiable consequences for future implementation:

- prices for physical offers and non-public digital drafts are set in rubles in Phase 2;
- a public price is explicitly labeled as a ruble price and retains the unit-of-measure indication where applicable;
- an attempt to set a price in another currency is rejected without silently relabeling or converting it and without changing the previous active price;
- saving, displaying, and comparing prices do not require an exchange-rate request;
- selecting a ruble price does not open a digital draft to the buyer or add payment.

These are requirements for future checks, not a report of completed tests.

### CAT-PRICE-PRECISION-01 — Price in Rubles and Kopecks

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for product-price precision — to kopecks, with a maximum of two decimal places.

For seller-set product prices in Phase 2:

- A price in rubles is stored and displayed exactly in increments of 0.01 ruble, without fractional kopecks.
- Integer prices and prices with fewer decimal places are also allowed; entering exactly two places is not required.
- If a value cannot be stored at this precision without changing its numerical value, the system explains the restriction and rejects saving. The previous active price remains unchanged; automatic rounding is not performed.
- The displayed price does not lose the agreed precision.
- For a physical good, this is the price for one selected unit under CAT-UNITS-01. Stock precision in kilograms and meters under CAT-STOCK-PRECISION-01 remains a separate rule.

The decision concerns the original product price, not the calculated order total. Calculating the total including quantity and delivery, rounding it, and payment rules remain for the next stage. CAT-ZERO-PRICE-01 separately defines whether a zero price is allowed; this decision does not set an upper limit. CAT-CURRENCY-01, CAT-OFFER-01, and public-display restrictions remain in force.

Verifiable consequences for future implementation:

- when the remaining rules are met, a price of 12.34 rubles is saved and displayed without changing its value;
- an integer ruble price is not rejected merely because it has no fractional part;
- a value of 12.3456 rubles is rejected for insufficient precision, without rounding and without changing the previous price;
- the seller is told the reason for rejection and the permitted precision;
- support for three decimal places in stock does not permit fractional kopecks in a price;
- changing price precision does not add order calculation or payment.

These are requirements for future checks, not a report of completed tests.

### CAT-ZERO-PRICE-01 — A Zero Price Means a Free Good

**Status:** approved by Vladislav on 2026-09-14; option “2” was selected for a zero price — allow the good itself to be free.

For product prices in Phase 2:

- A price of 0 rubles is allowed and means that the good itself is free. Zero is not a sign of an unknown or “price on request” value.
- An eligible physical offer with a zero price displays “Free.” The normal publication and separate price-change checks remain; public-display conditions for availability, permissions, and category restrictions apply separately and are not canceled.
- A zero price does not exclude a suitable published offer from the catalog, search, or price comparison merely because it is zero. It is treated as an actual price, not as a missing value.
- The free-good label does not promise free delivery or a zero total order cost. The “Delivery has not been calculated yet” warning under CAT-COMPARE-DELIVERY-SCOPE-01 remains.
- An empty price differs from zero. A draft may be saved without a price, but an offer cannot be published without a specified permitted price.
- An attempt to clear the price of an already published offer must not silently delete the active price or turn the missing value into zero.
- Downloadable goods remain non-public drafts, including when a zero price is specified.

CAT-SEARCH-GROUP-01 remains in force: if one search result combines suitable offers with different prices, the minimum is used with the “from…” label. One free offer does not make other paid variants or card offers free. A zero price does not mean that physical stock exists and does not expose a hidden offer.

This decision does not add orders, payment, delivery, or fulfillment. Checkout and fulfillment of free orders, the final calculation, and its rounding remain for the next stage. No upper price limit is selected; the rules for free APIs, exports, and platform services are not re-opened.

Verifiable consequences for future implementation:

- a zero price passes the price-validity check and counts as a completed value when the remaining conditions are met;
- the first successful saving of a zero price also counts as saving the price for locking the unit of the seller's own card under CAT-UNIT-LOCK-01;
- an eligible physical offer with a zero price can be published and is shown as a free good itself;
- a suitable free offer participates in search and comparison but does not bypass availability, publication, or permission requirements;
- an empty price is allowed in a draft but blocks publication and is not automatically substituted with 0 rubles;
- clearing the price of a published offer does not silently erase the previous value;
- a zero price does not publish a digital draft, make a good in stock, or promise free delivery;
- when free and paid offers are mixed, the result display preserves the “from…” rule rather than declaring the entire set free.

These are requirements for future checks, not a report of completed tests.

### CAT-OFFER-CONFLICT-01 — Protecting Price and Stock from Stale Saves

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for conflicting manual saves of the price or stock — do not overwrite newer data without seller review.

The decision concerns a normal manual change to the same price or stock field from two screens, such as seller tabs. After the second tab is opened, the same value is successfully changed in the first tab; the second tab is still based on old data.

- A save from a stale screen does not automatically replace the newer active value. It is rejected as conflicting, and the previously saved value remains active.
- The seller is told that the value has changed, shown the current value, and asked to check their input and save again.
- A repeated save after the seller's review is checked for currency again. If the same field has changed again, the conflict is handled the same way rather than becoming permission for an unconditional overwrite.
- The currency check applies to the system's acceptance of the save, not only to a warning in the interface. Conflicting simultaneous changes to one field must not both silently pass based on one stale state.
- Normal permission, price-validity, and quantity-precision checks remain in force. The current value is shown only within access permissions; exact stock does not become public contrary to CAT-STOCK-PUBLIC-01.

The decision does not define merging different fields or bulk operations. It does not re-open the already prohibited rollback of price/stock from an old content draft under CAT-OFFER-01 or the rules for importing or synchronizing from an external source. The latter has a separate field-management process under the concept protocol's import and synchronization sections. This response does not select a process for conflicts in the content draft itself.

Verifiable consequences for future implementation:

- after the price is successfully changed in the first tab, a conflicting save of the same price from the stale second tab is rejected and does not replace the new value;
- the same scenario is checked separately for stock;
- the conflict message lets the seller see the current value and the need to check their input before saving again;
- after the seller's review, a repeated save against the current state is applied when the normal checks succeed; a new intervening change causes another conflict;
- the conflict also protects an allowed zero price: the fact that the good is free does not disable the currency check;
- simultaneous conflicting saves of one field do not bypass the protection;
- a save without a conflict still does not wait for publication of the content draft and does not publish it itself.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-TYPO-01 — Typo-Correction Suggestions in Phase 2

**Status:** approved by Vladislav on 2026-09-14; option “2” was initially selected for typo assistance — offer a possible correction already in Phase 2, with search for it only after the buyer selects it. The display condition is supplemented by CAT-SEARCH-TYPO-TRIGGER-01.

- If there are no exact matches for the entered query and there is a suitable possible-correction suggestion, it is shown separately, including when approximate results exist, under CAT-SEARCH-TYPO-TRIGGER-01. For example, for “sneakers” the system may suggest: “Did you mean ‘trainers’?”
- The suggestion is not presented as a reliably established buyer intent. The original query is not silently replaced, and a result for another query is not presented as the result for the original.
- Search for the suggested query starts only after the buyer explicitly selects it. Until then, the original query remains active.
- Selecting a correction preserves the selected filters. Results for the new search follow the normal visibility, availability, card-grouping, and filter-matching rules; the suggestion does not permit bypassing them.
- With an empty result and no suitable suggestion, the buyer is offered the option to check the spelling or change the filters. The system is not required to invent a correction for every empty result: typos may not be the cause.
- Suggestions must not expose information from non-public cards, drafts, or the seller's private fields.

The decision includes typo assistance in Phase 2, but does not select a dictionary, library, external service, or exact matching thresholds. This response does not authorize connecting new tools, paid services, or implementing it. The normal word-matching rules are defined separately; the text fields considered are established in CAT-SEARCH-FIELDS-01. Query matching remains the basis for ordering different goods; delivery calculation, orders, paid promotion, and hidden personalization are not added.

Immediate display of approximate results for the original query is additionally agreed in CAT-SEARCH-APPROX-01. It does not wait for selection of the corrected string and does not mean that it is silently substituted. The correction suggestion remains a separate action and, under CAT-SEARCH-TYPO-TRIGGER-01, may be shown alongside approximate results when exact results are absent.

Verifiable consequences for future implementation:

- when exact matches are absent and a suitable suggestion exists, the buyer sees it separately from the original-query results even if approximate goods have already been found;
- before the suggestion is explicitly selected, the original query is not replaced with the correction and the corrected-query result is not presented as the original; approximate results for the original query may be shown immediately under CAT-SEARCH-APPROX-01;
- after selection, search runs for the suggested query while preserving the selected filters;
- the new search applies the current visibility and availability restrictions and does not show a hidden good even if its state changed after the suggestion was displayed;
- with an empty result, the absence of a suitable suggestion is not masked by an invented correction;
- data from non-public cards, drafts, and private fields is not exposed through suggestions.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-FIELDS-01 — Search by Name, Attributes, and Description

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for search text fields — name, public attributes, and published description.

- Normal Phase 2 text search considers the card's name, public attributes, and description.
- A match only in the description may also find the card; the searched word does not have to be duplicated in the name or attributes. For example, “North Jacket” may be found by the word “waterproof” that appears only in its description.
- The active published data is considered. Draft edits and the seller's private fields do not participate in public search and are not exposed through suggestions under CAT-SEARCH-TYPO-01.
- Saving a draft name, attributes, or description does not replace the active public version for search. After successful publication, the new published version is used.
- A text match does not cancel filters, visibility and availability conditions, or card grouping. Mentioning a word in the description does not make a hidden or unavailable offer eligible for display.

The description may mention other goods and produce extra matches; this drawback of broader search was presented during the selection. CAT-SEARCH-APPROX-01 defines allowing matches by parts of words, small typos, and similar meaning. This decision does not define exact field weights, inflection rules, searching incomplete words, or a correction dictionary. Search through reviews, stores, and text inside images is not added by this response.

Verifiable consequences for future implementation:

- separately verify finding a card eligible for display by a word present only in the name, only in the public attributes, and only in the published description;
- a word added only to a draft does not create a public search match; after successful publication it is considered subject to the other search rules;
- the seller's private fields and non-public data do not become a source of public matches or suggestions exposing them;
- a match in the description does not permit bypassing filters, hiding, or the absence of available in-stock offers;
- the description remains part of the public card content, not merely search material.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-APPROX-01 — Partial Matches, Typos, and Similar Meaning

**Status:** approved by Vladislav on 2026-09-14; following the wish to “show even approximate matches,” option “3” was selected in response to the clarifying question — parts of words, small typos, and similar meaning.

For normal Phase 2 text search:

- A match on part of the query words is allowed. For “nylon backpack,” a card matching only “backpack” may be shown; matching every word is not required for an approximate result.
- Small typos are allowed: for example, “backpak” may find “backpack.”
- Similar meaning is considered even without a literal word match: for example, “rainproof” may find “waterproof.”
- Approximate results are shown immediately for the original query, without waiting for an additional buyer choice. The entered string is not silently rewritten.
- In the normal result order, exact matches appear above approximate ones. Approximate matches are clearly labeled and are not presented as exact.
- Eligible published data under CAT-SEARCH-FIELDS-01 is used. Selected filters, availability, permissions, and visibility restrictions remain mandatory; approximation does not permit weakening them.
- One card remains one result under CAT-SEARCH-GROUP-01 even if it is found in several ways. Similar meaning alone does not confirm product identity or combine different cards.

Search shows existing eligible cards; it does not invent goods or properties absent from them. The examples illustrate the required behavior and are not the only supported queries. Exact similarity thresholds, ordering within approximate results, word normalization, search technology, and the quality-verification method have not yet been selected. Image search, new tools, services, expenses, and implementation are not agreed by this response.

CAT-SEARCH-TYPO-01 preserves the separate action of selecting a corrected query. Immediate approximate results are not that selection and must not wait for it. Under CAT-SEARCH-TYPO-TRIGGER-01, the absence of exact matches permits showing a suitable suggestion even when approximate results already exist.

Verifiable consequences for future implementation:

- eligible cards found by part of the words, with a small typo, and by similar meaning without a literal match are checked separately;
- such cards are visible without clicking the correction suggestion, and the entered query is preserved;
- when exact and approximate matches exist, exact matches appear first and approximate matches have a clear label;
- matching in several ways does not duplicate the card;
- no search method bypasses selected filters, availability, or visibility restrictions or exposes drafts and private fields;
- a corrected query from a separate suggestion is applied only after the buyer explicitly selects it.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-TYPO-TRIGGER-01 — Suggestion When Exact Matches Are Absent

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for the correction-suggestion display condition — offer a suitable correction when exact matches are absent, even if approximate results already exist.

- If there are no exact matches for the original query among eligible results and a suitable correction exists, a separate suggestion is shown next to the results. A completely empty result is no longer required.
- The presence of approximate results does not hide the suggestion. For example, similar backpacks may already be visible for “backpak” while the “Did you mean ‘backpack’?” suggestion is shown at the same time.
- A suitable suggestion is also shown for a completely empty result. If there is no suitable correction, none is invented; approximate goods already found are not removed.
- The absence of exact matches concerns the current query with the current filters and display restrictions, not only the visible portion of the list. If eligible exact matches exist, this suggestion-display condition is not met.
- Similar goods are shown immediately and do not wait for a click. The corrected string is applied only after the buyer explicitly selects it; filters and the remaining restrictions are preserved.

The decision expands the condition in CAT-SEARCH-TYPO-01 but does not cancel the ban on silently replacing the query, permit exposing non-public data, or select an algorithm for forming corrections. The approximate-search methods under CAT-SEARCH-APPROX-01 remain in force.

Verifiable consequences for future implementation:

- if exact matches are absent, approximate matches exist, and a suitable correction is found, the approximate goods and a separate suggestion are visible at the same time;
- if neither exact nor approximate goods exist, a suitable suggestion is still shown;
- if no suitable correction exists, no suggestion is invented, and the presence of approximate results is not masked by an empty result;
- the presence of an eligible exact match means that this suggestion-display condition is not met;
- the suggestion is not applied automatically, and the goods found do not wait for its selection;
- selecting the correction performs a new search while preserving filters, permissions, and visibility and availability conditions.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-SCROLL-01 — Automatic Loading on Scroll

**Status:** approved by Vladislav on 2026-09-14; instead of the proposed pages or button, a specific method was set: “items are added automatically when scrolling down.”

For a long list of search results in Phase 2:

- When the buyer scrolls down to the end of the portion of the list already shown, the next batch is loaded automatically and added at the bottom.
- Results already shown remain in the list; the new batch does not replace them with another page. Normal browsing does not require clicking “Next” or “Show more.”
- The query, selected filters, and overall result order are preserved. Exact matches precede approximate ones throughout the list rather than being reordered within each batch.
- Repeated loading must not duplicate cards. The one-result-per-card rule under CAT-SEARCH-GROUP-01 remains in force.
- When available results run out, further loading stops; the list already shown remains available.
- A loading error does not erase results already shown or present an unconfirmed end of the list as confirmed.

Loaded results remain subject to availability, permission, and visibility rules. The decision does not promise that the list composition will remain unchanged after subsequent changes to product prices, availability, or publication. The batch size, technical loading mechanism, and retry process after an error have not yet been defined. CAT-SEARCH-RETURN-01 governs returning to the list after opening a card. Persistent search-session storage or synchronization between devices is not added by this response.

Verifiable consequences for future implementation:

- scrolling to the end of the loaded portion triggers retrieval of the next batch without clicking a button;
- retrieved cards are added at the bottom while preserving the previous part of the list;
- loading preserves the query, filters, and agreed order of exact and approximate results;
- repeated triggering does not add the same card again;
- after the end of the results is confirmed, new loads do not continue indefinitely;
- an error retrieving the next batch does not clear the list or present the absence of further results as confirmed.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-RETURN-01 — Returning to the Previous Place in the Results

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for returning from a product card — restore the viewed portion of the list and the scroll position.

The decision concerns the current view in the same browser tab: the buyer browsed through the results, opened a product card from them, and clicked “Back.”

- The search query, selected filters, viewed portion of the list, and scroll position are restored. If the results have not changed, the buyer continues from the previous place rather than starting to scroll again.
- If the previous card is no longer available or the result composition has changed, the return is made as close as possible to the previous place among currently eligible results.
- Preserving the position does not return a hidden card or lock in its former prices, availability, or display permission. If the data changed, the restored list does not have to exactly match the old one.
- After returning, automatic loading of subsequent results under CAT-SEARCH-SCROLL-01 remains in force without adding already restored cards again.

The decision does not add persistent search history, restoration after a browser restart, or state transfer between tabs or devices. The technical method for saving and restoring state has not yet been selected.

Verifiable consequences for future implementation:

- when the result set has not changed, returning from a card in the same tab restores the viewed portion of the list and the former position;
- the search query and filters are not reset;
- when the previous card disappears, the nearest available place is restored rather than a hidden card or an unconditionally old data snapshot;
- restoring the position does not lock in former prices and stock or bypass current visibility restrictions;
- further scrolling continues loading without duplicating restored results.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-FILTER-APPLY-01 — Automatic Filter Application

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for applying filters — automatically after a change, without a separate “Show” button.

- After a filter is changed, for example by selecting a color or size, the results update automatically. Additional confirmation with a button is not required.
- Applying the changed filter set starts the updated list from the beginning. Text entered in the field is not reset; if it has not yet been applied, changing the filter applies it at the same time under CAT-SEARCH-FILTER-TEXT-01.
- The new result and its subsequent automatic loading concern the current filter set; previously loaded portions of another set are not mixed into it.
- If the buyer changes the filters again, a late response for the previous set must not replace the current result. An update error is not presented as successful application of the new conditions.
- Approximate matches, typos, and similar meaning do not cancel selected filters. Availability and visibility restrictions and the matching-variant rule under CAT-SEARCH-GROUP-01 remain in force.

CAT-SEARCH-RETURN-01 continues to restore the position when returning from a card to the previous search; it does not preserve the previous position after another filter set is applied. This response does not select behavior while text is being entered in the search field, specific update delays, the number of network requests, or their technical handling mechanism.

Verifiable consequences for future implementation:

- changing a filter starts an update without clicking a separate confirmation button;
- after the changed filters are applied, the initial portion of the updated list is visible and the search query is not reset;
- the results and next load match the current filters, not the previous set;
- late responses for the previous set do not replace or join the new result;
- an update error is not masked by filters that were supposedly applied successfully;
- approximate search does not substitute goods that do not match the selected filters, availability, or visibility restrictions.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-FILTER-MULTI-01 — Multiple Values for One Filter

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for filters with a predefined list of values — allow multiple values as alternatives.

- In one such filter, the buyer can select multiple values. Selecting red and blue means “red OR blue,” not a required combination of two colors in one variant.
- Selecting an additional value does not replace a previously selected value in the same filter.
- Different filters continue to operate simultaneously and must match one eligible variant under CAT-SEARCH-GROUP-01. With red or blue and size M, red M or blue M is suitable.
- The required color on one variant and the required size on another do not replace one variant satisfying the entire selected set of conditions.
- Changes are applied automatically under CAT-SEARCH-FILTER-APPLY-01. Approximate search does not cancel the selected conditions, availability, or visibility restrictions.
- Multiple matching values or variants do not duplicate the card in the results. The displayed price and availability are still determined only from matching variants and offers.

The decision concerns filters with predefined values, not numeric ranges or the structure of the product's attributes. It does not permit arbitrarily changing category directories or combining different product variants.

Verifiable consequences for future implementation:

- after red and blue are selected, both values remain selected, and a variant of either color may match;
- after size M is added, red M and blue M remain eligible, but a variant of another size is not;
- matches from different filters on different variants do not produce a false matching result;
- a card with several matching variants is shown once, with the price and availability of only matching offers;
- selection changes are applied automatically and do not cancel availability and visibility restrictions.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-FILTER-AVAILABILITY-01 — Filter Values with No Matching Goods

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — keep an unselected value visible but do not allow selecting it if no suitable available goods meet the current conditions.

- Such a value is not hidden: it is shown in gray with the “No matching goods” label. Unavailability is not indicated only by presentation color.
- For example, if size M is selected, there are no suitable red variants, and red has not yet been selected, the “Red” value is visible but unavailable for a new selection.
- Already selected values remain visible and available for deselection even if they no longer have results. The system does not hide or cancel the selection on its own.
- The current search query, other filters, availability, and visibility restrictions are considered when evaluating a value. All selected attributes must match one variant under CAT-SEARCH-GROUP-01.
- An alternative color is not considered unsuitable merely because another color is currently selected. The suitability of the value being checked is evaluated with the other filters, without requiring it to match an already selected alternative in the same filter: within one filter, “OR” applies under CAT-SEARCH-FILTER-MULTI-01.
- Evaluation is not limited to the portion of the list already loaded. A matching variant in a portion of the results not yet viewed also makes the value available for selection.
- Only values and data permitted for public display are used. Drafts and hidden goods must not expose themselves through the appearance or availability of filter values.

This is a filter-display rule, not a change to the attribute directory. The absence of suitable goods for the query and filters does not mean that sellers necessarily have zero stock. A data-retrieval error does not prove that suitable goods are absent and is not presented as that state.

Verifiable consequences for future implementation:

- an unselected value with no suitable available goods remains visible with the “No matching goods” label, but cannot be selected;
- an already selected value with no results remains visible and can be deselected; the system does not cancel it on its own;
- a suitable alternative color can be selected despite another color having been selected earlier;
- a suitable variant existing only in a portion of the results not yet loaded does not make the value unavailable;
- attribute matches on different variants, drafts, and hidden goods do not create false value availability;
- a data-retrieval error is not masked by a “No matching goods” message.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-TEXT-APPLY-01 — Starting Text Search upon Confirmation

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected for searching while entering a phrase — after Enter or the “Find” button.

- The buyer enters a phrase and starts text search by pressing Enter or the “Find” button. Merely typing and pausing while typing do not start a search for the new text or rebuild the previous list around it.
- Applying a new search query starts the updated list at the top. Selected filters are preserved.
- Filter changes continue to be applied automatically under CAT-SEARCH-FILTER-APPLY-01 and simultaneously confirm the entered text under CAT-SEARCH-FILTER-TEXT-01. This is an additional way to apply text alongside Enter or the “Find” button, not a search triggered by typing itself.
- Explicitly selecting a correction suggestion remains an agreed action that performs a new search under CAT-SEARCH-TYPO-TRIGGER-01. This decision does not introduce an additional “Find” click after selecting a correction, and automatic text substitution remains prohibited.
- Further loading concerns the applied query and its filters. Responses and batches for the previous query do not replace or supplement the results for the new query already applied.
- The order of exact and approximate matches, matching-variant checks, availability, and visibility restrictions remain in force. The absence of search while typing does not mean that old prices, availability, or product-display permission are locked in.

A search error is not presented as an empty result or successful application of the new query. The decision defines the buyer action, not the search technology or network-request mechanism.

Verifiable consequences for future implementation:

- entering text and pausing without confirmation do not start a search for the new text;
- both Enter and the “Find” button can apply the entered phrase;
- applying a new query preserves the filters and shows the beginning of the updated list;
- explicitly selecting a correction suggestion still performs a new search without silently replacing the text;
- responses and loads for the previous query are not mixed with the new one;
- an error is not masked by an empty result or successful query application, and availability and visibility restrictions are not canceled.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-FILTER-TEXT-01 — Changing a Filter Confirms Entered Text

**Status:** approved by Vladislav on 2026-09-14; option “2” was selected — when a filter changes, apply the filters and the text entered in the field at the same time.

- If the search field contains text that has not yet been confirmed, changing a filter also confirms that text. An additional press of Enter or the “Find” button is not required.
- For example, after searching for “T-shirt,” the buyer types “sweatshirt” without confirming it and then selects the available blue color. The system searches for “sweatshirt” with blue, not for “T-shirt” with the new color.
- The entered text is not lost; the changed filter set is used without resetting the other selected conditions. The updated list starts at the top.
- Merely typing and pausing without a filter change or another agreed confirmation action still does not start a new search. Enter, the “Find” button, and explicit selection of a suggested correction retain their agreed actions.
- The completed result, availability of filter values, and further loading concern the jointly applied text and filters. A result for the previous text with the new filter is not presented as the result of this action; late responses for the previous conditions are not mixed into the new result.
- The rules for multiple values, one matching variant, availability, and visibility remain in force. Even if the new combination produces no results, the system does not remove filters or restore the previous query on its own.

This clarification adds changing a filter as a text-confirmation action to CAT-SEARCH-TEXT-APPLY-01, but does not enable automatic search while typing. An error in the joint update is not presented as successful application of the new conditions or an empty result.

Verifiable consequences for future implementation:

- changing a filter after entering an unconfirmed phrase starts a search for that phrase and the changed filters without an additional Enter or “Find”;
- typing and pausing without a confirmation action still do not start a new search;
- the entered text and the other selected filters are preserved, and the list starts at the top;
- the result, value availability, and loading correspond to the new “text and filters” pair without mixing in the previous conditions;
- the absence of suitable goods or an update error does not cause the query to be replaced, filters to be removed, or display restrictions to be bypassed automatically.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-LINK-01 — Passing Search Conditions through a Link

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — preserve the applied search query and filters in a copyable link.

- The buyer can copy a link to the catalog or search and send it to another person. The recipient opens the search with the same applied query and selected filters, without manually entering these conditions again.
- Only already applied conditions are included in the link. Text not yet confirmed in the search field does not replace the applied query in the link. A filter change that confirms new text under CAT-SEARCH-FILTER-TEXT-01 already creates a new applied combination of conditions.
- When the recipient first opens the link, the list starts at the top. The sender's viewed portion of the list and scroll position are not transferred; returning in the same tab under CAT-SEARCH-RETURN-01 remains a separate scenario.
- The link passes search conditions, not a fixed snapshot of results. The product set, prices, and availability are checked when it is opened; the recipient's current access applies.
- The sender's permissions are not transferred. The link does not provide access to private goods, drafts, or service data and contains no session or account-login data.
- If valid conditions no longer produce results, the query and filters are not removed automatically. An honest empty result and the previously agreed suggestion rules apply; selected filter values remain available for removal under CAT-SEARCH-FILTER-AVAILABILITY-01.

The decision does not define a specific link format or introduce saved collections in an account or a separate link service. A valid filter with no suitable goods is not the same as a damaged or unsupported link parameter; CAT-SEARCH-LINK-VALIDATION-01 defines handling of the latter case.

Verifiable consequences for future implementation:

- the recipient of a valid link sees the same applied query and selected filters;
- changing text without confirmation does not change the query being passed, while applying text together with a filter change is reflected in the link;
- when the recipient first opens it, the beginning of the list is visible rather than the sender's scroll position;
- changes to price, availability, or visibility after the link is copied are considered when it is opened, without restoring an old snapshot;
- the link does not pass the sender's permissions or expose non-public data;
- the absence of results for valid conditions does not automatically reset the query or filters.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-LINK-VALIDATION-01 — An Invalid Link Condition Blocks Search

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — do not start search until the buyer corrects or removes the invalid link condition.

- If the link contains an invalid or no-longer-supported filter condition, search does not start. The buyer is clearly told which condition requires correction and is offered the option to correct or remove it themselves.
- The search text and the other recognized conditions are preserved. The system does not automatically delete the problem filter or search with a reduced set of conditions instead of those passed in the link.
- An unrecognized value is not replaced with a guess or a similar value. The error explanation does not expose private data or provide additional permissions.
- After the problem condition is explicitly corrected or removed, search is allowed with the valid remaining set. The agreed rules for applying text and filters, including CAT-SEARCH-FILTER-TEXT-01, apply; the other restrictions are not removed automatically.
- A valid filter that currently matches no available goods is not considered invalid. It is preserved, and search may honestly return an empty result.
- A data-retrieval failure does not prove that a filter is invalid and is not presented as such. The recipient's permissions and availability and visibility restrictions remain in force.

The decision concerns checking link conditions; it does not authorize deleting categories or attributes and does not define how the directory is changed or the format of link parameters.

Verifiable consequences for future implementation:

- an invalid or unsupported condition does not start search and is accompanied by a clear explanation with the option to correct or remove it;
- the text and other recognized conditions are not lost, and the problem condition is not removed or replaced automatically;
- explicitly correcting or removing the problem allows search with the valid remaining conditions without bypassing restrictions;
- a valid filter with an empty result does not cause a recognition error and is not deleted;
- a data-retrieval failure is not declared an invalid link condition, and messages do not expose non-public information.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-PHOTOS-01 — Photos Switch with the Variant

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — show the photos associated with a variant when it is selected.

The decision concerns the seller's own physical-goods card that is not attached to a common card, when suitable variant photos have already been published and permitted for display.

- The seller specifies which photos belong to each variant. When the buyer selects a variant, they see its associated photos rather than an unchanged common gallery of all variants.
- For example, selecting the blue T-shirt shows photos associated with the blue variant, while selecting the red one shows photos associated with the red variant.
- Photo-to-variant associations are part of the card content. The seller changes them through the agreed draft under CAT-EDIT-01; until the edits are published, the buyer continues to see the previous published content and associations.
- When the buyer switches variants, the gallery display changes, but the draft is not published and the seller's data is not changed.
- Only published images permitted for display are used. Selecting a variant does not expose draft or prohibited photos and does not cancel restrictions on displaying the variant itself.
- Photos from the previously selected variant are not presented as photos of the current one. A late load of former photos does not replace the gallery of another variant that has already been selected.

The rules for the real source, preserving product properties, labeling, and comparison from section 11 of the concept remain in force. CAT-PUBLISH-MINIMUM-01 separately defines the minimum number of photos before publishing the seller's own physical card; this decision does not establish the implementation stage for AI processing. CAT-VARIANT-PHOTOS-EMPTY-01 defines display when associated available photos are absent, and CAT-SEARCH-COVER-01 defines a separate search-result cover.

Verifiable consequences for future implementation:

- when switching between variants with published associated photos, the gallery shows photos of the selected variant;
- saving a draft photo association does not change the public gallery before content publication;
- the buyer does not receive draft or prohibited images by selecting a variant;
- a late load of photos from the previously selected variant does not replace or masquerade as photos of the current one;
- switching by the buyer does not publish changes prepared by the seller.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-PHOTOS-EMPTY-01 — Message When Variant Photos Are Absent

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — show a message instead of photos, without substituting common photos or photos of other variants.

For the seller's own physical card in the CAT-VARIANT-PHOTOS-01 scenario:

- If the selected visible variant is confirmed to have no associated photos available for public display, the “No available photos for this variant” message is shown instead of the gallery.
- The card's common gallery and photos of other variants are not substituted, even if they are published and available. Photos from a previously selected other variant do not remain as photos of the current one.
- The selected variant is not replaced automatically to obtain photos. The absence of photos does not by itself switch the buyer to another color, size, or version.
- An ongoing load and a data-retrieval error are not presented as confirmed absence of photos. Prohibited or draft photos are not used to fill the empty space.
- An invented product image is not created instead of a missing photo. Restrictions on displaying the variant itself and the concept's AI-media rules remain in force.

This is a page-display rule, not permission to publish a variant without the required real source material. CAT-PUBLISH-MINIMUM-01 separately defines the minimum photos before publishing the seller's own physical card and does not cancel this viewing state. CAT-SEARCH-COVER-01 defines the separate search-result cover.

Verifiable consequences for future implementation:

- confirmed absence of available associated photos displays the agreed message;
- the existence of common photos or photos of other variants does not cause their substitution;
- when moving from a variant with photos to one without them, the previous gallery is replaced by a message rather than presented as photos of the new selection;
- the selected variant is not changed automatically;
- a load or error is not masked as absent photos, and draft and prohibited images are not exposed.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-COVER-01 — Common Cover for the Seller's Own Card in Search

**Status:** approved by Vladislav on 2026-09-14; option “2” was selected — show the common cover selected by the seller regardless of search filters.

The decision concerns a search result for the seller's own physical-goods card that is not attached to a common card.

- The result shows the published common card cover permitted for display, with the explicit “Common product photo” label.
- Changing filters does not switch the cover to a photo of the matching or cheapest variant. It may show another color, size, or version and is not presented as a photo of the specific variant on which the price is based.
- Price and availability continue to be determined only from matching variants and offers under CAT-SEARCH-GROUP-01. A variant shown on the common cover that does not match does not lower the result price or make the card suitable for the search.
- If no suitable published offer is in stock, the card does not remain in the result merely because a cover exists.
- The seller's normal selection or replacement of the cover is part of the content and is published through a draft under CAT-EDIT-01. Saving a draft cover does not replace the public one.
- Keeping the cover constant across filters does not cancel display restrictions or the AI-media rules. In particular, hiding a disputed AI image and switching to an available real image under section 11 of the concept remain in force; a prohibited photo is not retained for the sake of consistency.
- If no permitted cover image exists, a message is shown rather than an invented photo. A load and an image-retrieval error are not presented as confirmed absence.

The rule concerns the search-result image, not the gallery inside the opened card. After selecting a variant inside it, CAT-VARIANT-PHOTOS-01 and CAT-VARIANT-PHOTOS-EMPTY-01 apply: associated photos or a message that they are absent, without substituting the common gallery.

Verifiable consequences for future implementation:

- changing filters preserves the permitted published common cover and the “Common product photo” label;
- the price is not taken from the variant shown on the cover if it does not meet the conditions, and the absence of suitable offers excludes the card from the result;
- a draft cover replacement is not visible to the buyer before content publication;
- the common cover does not cancel display prohibitions, AI labeling, or the concept's specified hiding of a disputed image;
- inside the card, selecting a variant still switches the associated photos or shows a message that they are absent;
- the absence of a permitted cover is reported honestly and is not masked with an invented image.

These are requirements for future checks, not a report of completed tests.

### CAT-SEARCH-OPEN-VARIANT-01 — Initial Variant Selection when Navigating from Search

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — immediately select the suitable available variant with the lowest price.

The decision concerns opening the seller's own physical-goods card from search results when it is not attached to a common card.

- At the time of opening, current published variants, offers, prices, availability, and display permissions are checked. One variant with the lowest matching price is selected from those that both match the passed selected filters and have an available offer in stock.
- For example, with the “blue” and “M” filters, a suitable blue M variant is selected in advance rather than the variant shown on the common search cover.
- The buyer clearly sees the selected color, size, or other attributes and the current data for the selected variant. They can change the selection manually; the original search conditions are not lost.
- The preliminary selection does not lock in the former price, availability, or result composition. If no suitable variants remain when the card is opened, the system reports this and does not substitute another color, size, or version as matching the search.
- The selected variant's gallery follows CAT-VARIANT-PHOTOS-01 and CAT-VARIANT-PHOTOS-EMPTY-01. The absence of associated available photos is not a reason to select a more expensive or unsuitable variant instead of the one chosen by the rule.
- Hidden and draft variants are not selected. Invalid passed filters are not silently removed for the sake of preliminary selection; the condition-correction process under CAT-SEARCH-LINK-VALIDATION-01 remains in force.
- The preliminary selection on the page does not purchase, reserve, or deduct anything and does not change the seller's price or stock. The cart and checkout remain the next stage.

The decision does not define the selection order among several equally inexpensive matching variants. CAT-DIRECT-OPEN-VARIANT-01 governs a normal direct link without search conditions and without a specified variant. The common result cover under CAT-SEARCH-COVER-01 remains a separate rule and does not determine which variant is selected inside the card.

Verifiable consequences for future implementation:

- when suitable available variants exist, one with the lowest current suitable price is already selected after opening the card from search;
- the selected variant simultaneously satisfies the passed filters, and its attributes and current data are clear to the buyer;
- an unsuitable variant shown on the common cover is not selected in advance;
- changes to price, availability, or visibility between the result and opening are considered, and the absence of suitable variants is not masked by another color or size;
- the absence of photos shows the agreed message rather than causing a switch to a more expensive or unsuitable variant;
- the buyer can change the selection manually, while the preliminary selection itself does not create a purchase or reservation or change stock.

These are requirements for future checks, not a report of completed tests.

### CAT-DIRECT-OPEN-VARIANT-01 — Initial Selection through a Normal Direct Link

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — immediately select the cheapest available in-stock variant.

The decision concerns the seller's own physical-goods card, not attached to a common card, with multiple variants. The buyer opens a normal direct link without search conditions and without specifying a particular variant.

- On opening, current published variants, offers, prices, availability, and display permissions are checked. One variant with an available in-stock offer and the lowest current price is selected in advance.
- The buyer immediately sees the selected color, size, or other attributes, the current price, and photos of the selected variant if available. The selection can be changed manually. This is the initial selection on opening, not a restriction that limits subsequent manual selection to the cheapest variant.
- Photos follow CAT-VARIANT-PHOTOS-01 and CAT-VARIANT-PHOTOS-EMPTY-01: when associated available photos are confirmed absent, the agreed message is shown rather than common photos or photos of another version. The absence of photos does not replace the lowest-price criterion.
- The link does not lock in the former price or availability. Hidden, draft, or withdrawn variants do not participate in the preliminary selection and do not become available because a link exists.
- If the previously published good has simply run out in all variants, CAT-AVAILABILITY-01 remains in force: the published description and photos remain available through the direct link with a prominent “Out of stock” label. Voluntary withdrawal from publication and security or moderation restrictions are not canceled by this rule.
- The preliminary selection does not purchase, reserve, or deduct anything and does not change the seller's price or stock. The cart and checkout remain the next stage.

The decision does not define the selection order among equally inexpensive available variants. CAT-VARIANT-LINK-01 governs a link with a specific selected variant. Navigation from search remains a separate case under CAT-SEARCH-OPEN-VARIANT-01: its selected filters cannot be replaced by the absence of conditions to select a cheaper unsuitable variant.

Verifiable consequences for future implementation:

- if available variants are in stock, a normal direct link without search conditions or a specific variant opens the card with the variant having the lowest current price among them already selected;
- the selected attributes and price are clearly shown, and the buyer can select another variant manually;
- the absence of photos for the cheapest variant shows the agreed message rather than causing substitution of someone else's photos or a more expensive variant;
- the selection considers the current price, availability, and display permissions rather than data from when the link was copied;
- when all variants normally run out, the published description and photos remain with the “Out of stock” label, without exposing drafts or bypassing withdrawal from publication;
- opening itself and the preliminary selection do not create a purchase or reservation or change stock.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-LINK-01 — Link Preserves the Selected Product Variant

**Status:** approved by Vladislav on 2026-09-14; option “1” was selected — preserve the specifically selected variant in the copyable link.

The decision concerns a link to the seller's own physical-goods card, not attached to a common card, after the buyer has selected a specific variant. Passing search conditions under CAT-SEARCH-LINK-01 remains a separate case; a checkout link is not introduced here.

- A copyable product link preserves the selected variant of this card, not only the card as a whole. For example, after selecting blue T-shirt M, the link points specifically to that variant.
- On opening, the current publication, recipient display permissions, availability, and price are checked. If the specified variant is still published, available to the recipient, and in stock, it is selected in advance even if another card variant is cheaper.
- The cheapest available item rule for a normal link without a selected variant under CAT-DIRECT-OPEN-VARIANT-01 does not replace an explicitly specified variant. A cheaper red variant is not substituted for the passed blue M.
- The recipient sees the current attributes and price of the selected variant and can change the selection manually. Photos follow CAT-VARIANT-PHOTOS-01 and CAT-VARIANT-PHOTOS-EMPTY-01; missing photos are not a reason to replace the passed variant with another.
- If the specified variant is already unavailable when the link is opened, the system reports this and does not select another variant automatically. Unavailability does not turn this link into an ordinary link without a selected variant.
- The link does not lock in the former price or availability, transfer the sender's permissions, or make draft, withdrawn, or blocked data public. The unavailability message does not expose the content or availability of a non-public variant.
- Opening the link and the preliminary selection do not create a purchase or reservation, deduct stock, or change the seller's price. The cart and checkout remain the next stage.

The distinction between normal stock exhaustion and prohibition of public display under CAT-AVAILABILITY-01, CAT-STOCK-PUBLIC-01, and CAT-CARD-WITHDRAW-01 remains in force. The decision does not define the technical link format or how it is copied. CAT-VARIANT-OUT-OF-STOCK-01 governs display of exhausted published variants in the manual-selection list inside the card.

Verifiable consequences for future implementation:

- a link after blue M is selected opens that exact variant if it is still published, available to the recipient, and in stock;
- the existence of another, cheaper variant does not change the passed selection;
- price and availability are checked when the link is opened rather than restored from the sender's state;
- missing associated photos show the agreed message and do not cause the selected variant to be replaced;
- if the specified variant is already unavailable, a message appears without automatic substitution of another version;
- the recipient does not receive the sender's permissions, hidden content, or the stock of a non-public variant;
- opening the link does not create a purchase or reservation or change actual stock.

These are requirements for future checks, not a report of completed tests.

### CAT-VARIANT-OUT-OF-STOCK-01 — Viewing a Temporarily Out-of-Stock Variant

**Status:** approved by Vladislav; option “1” was selected — keep the variant visible with an “Out of stock” label and allow viewing. Entry added on 2026-09-15.

The decision concerns manual selection inside the seller's own physical-goods card, not attached to a common card. One published variant is temporarily out of stock while other variants of the card are still in stock.

- Normal stock exhaustion does not remove this published variant from the list of variants inside the card. “Out of stock” is shown clearly next to it.
- The buyer can select the exhausted variant to view its published attributes and associated photos. Viewing does not mean that the good is in stock or available for purchase.
- Photos correspond to the selected variant under CAT-VARIANT-PHOTOS-01. When the absence of available associated photos is confirmed, CAT-VARIANT-PHOTOS-EMPTY-01 applies without substituting photos of another version.
- Exact warehouse quantities are not exposed to the buyer; CAT-STOCK-PUBLIC-01 applies. Selecting for viewing does not replenish stock, create a purchase, or reserve the good.
- Withdrawn, blocked, and draft variants do not become visible or available for selection. Zero stock and prohibition of public display remain different states.
- This does not change filters or search results. The initial selection rules for an available in-stock variant under CAT-SEARCH-OPEN-VARIANT-01 and CAT-DIRECT-OPEN-VARIANT-01 remain in force. Under CAT-VARIANT-LINK-01, the unavailability of the variant specified in a link still does not permit automatic substitution of another.

The case where all variants are exhausted remains under CAT-AVAILABILITY-01: the published description and photos are available with the “Out of stock” label unless there are other grounds for hiding them. The decision does not automatically extend to common cards and offers from other sellers.

Verifiable consequences for future implementation:

- when red M exists and published blue M is normally exhausted, both remain in the variant list, with “Out of stock” clearly shown for blue;
- blue M can be selected to view its published attributes and associated photos without presenting it as in stock;
- missing photos show the agreed message rather than photos of the red variant;
- preliminary selection of the cheapest available variant does not select an exhausted one merely because its price is lower;
- withdrawn, blocked, and draft variants are not exposed, and exact stock is not sent to the buyer;
- viewing an exhausted variant does not create a purchase or reservation or change actual stock.

These are requirements for future checks, not a report of completed tests.

### CAT-PILOT-SCOPE-01 — Initial Access as a Private Catalog without Purchases

**Status:** approved by Vladislav on 2026-09-15; option “1” was selected — first, a private trial version of the catalog for invited participants.

- Initial user access is prepared for invited sellers and buyers, not for an open public launch of the marketplace.
- Sellers create goods, and buyers search for them, select variants, and view cards. At this stage there are no orders, payments, or collection of money.
- Participant feedback is used before the next stage with purchase, payment, and fulfillment. The trial catalog is not presented as a finished store and does not replace the end goal of the general specification.
- The agreed Phase 2 scope is not reduced: similar-meaning search, common cards, and non-public digital drafts remain. Catalog access does not change a seller's rights to other people's data or staff permissions.
- For private access, the former term “public card” means published content available to an admitted participant subject to their permissions. Publishing a card within the pilot does not authorize exposing it to the entire Internet. Links, photos, results, and suggestions must not bypass the pilot access restriction.
- The method for admitting invited participants and the deployment method have not yet been selected. This response does not authorize sending invitations, external launch, connecting payments, new expenses, or implementation before the written specification is approved.

Verifiable consequences for future participant admission:

- admitted participants can perform the agreed seller and buyer actions without placing orders or making payments;
- a person outside the private test does not gain access to catalog content through a direct link, photo, search, or suggestion;
- participation in testing does not grant additional seller or staff permissions;
- the interface does not pretend that an order, payment, reservation, or item delivery has been completed;
- deployment and data protection are separately checked and agreed before external access; the catalog is not declared a full public beta.

These are requirements for future checks, not a report of completed tests.

### CAT-PUBLISH-MINIMUM-01 — Minimum Data before Publication

**Status:** approved by Vladislav on 2026-09-15; option “1” was selected — accept the proposed mandatory minimum.

The decision concerns publication of the seller's own physical-goods card, not attached to a common card, and the variants published in it. The publication minimum does not mean that an unfinished draft must be fully completed.

- The card has a name, an active category, and a non-empty description, as well as the category's required attributes.
- There is at least one variant to publish. Each variant to be published has its required attributes completed and has a specified price and stock. The unit of measure is one for the entire card under CAT-UNITS-01; its lock under CAT-UNIT-LOCK-01 remains in force.
- The price and stock are not negative. Rubles, permitted precision, and rejection without rounding under CAT-CURRENCY-01, CAT-PRICE-PRECISION-01, and CAT-STOCK-PRECISION-01 remain in force. A zero price means “Free” under CAT-ZERO-PRICE-01, not a missing value.
- Zero stock is allowed, including on first publication. “Out of stock” is shown for such a variant. If no published variant of the card has an available offer in stock, the card is not included in the catalog or search. Eligible published content remains available to a participant through the direct link within their permissions; initial zero stock does not require inventing previous availability.
- Each variant to be published has at least one associated available photo of the real good without AI additions. Permitted technical correction of lighting, cropping, and size without synthetic additions is not prohibited. One photo may be associated with multiple variants only if it truthfully shows each of them.
- Incomplete data can be saved as a draft. If publication fails, the system tells the seller what must be completed or corrected; the prepared changes are not published partially.

The separation of content from operational price/stock changes under CAT-OFFER-01, protection against stale saves, and access permissions remain in force. An incomplete draft does not by itself stop a permitted change to the active price or stock. An empty numeric field is not replaced with zero. If already published photos are unavailable, CAT-VARIANT-PHOTOS-EMPTY-01 applies; this viewing state does not replace the photo check at publication and does not expose prohibited photos.

The real-photo requirement does not assert that a normal automated check can prove a photo's authenticity. The rules for preserving the product, labeling, source material, and checking AI versions from section 11 of the concept remain in force. This decision does not add a generator or paid service. The minimum is not automatically extended to common cards or non-public digital drafts. Upper limits for price and stock, file restrictions, and technical photo processing have not yet been defined.

Verifiable consequences for future implementation:

- the absence of a name, category, description, required attribute, or variant to publish prevents publication of the seller's own physical card;
- each variant to be published must have a price and stock specified with the agreed unit and precision; a missing value differs from zero, and negative values are not eligible for publication;
- when the remaining conditions are met, first publication with a zero price and zero stock is possible; the agreed statuses are shown, and an unavailable offer is not included in search;
- the absence of an associated permitted real photo for at least one variant to be published does not result in partial publication of the other prepared changes;
- one photo that truthfully corresponds to multiple variants does not have to be duplicated in separate uploads for each of them;
- an incomplete draft remains non-public, the publication rejection contains a reason, and the previous published content is not replaced by unsuccessful edits;
- the mandatory minimum does not expose hidden data, disable the separation of price/stock from content, or create a purchase or reservation.

These are requirements for future checks, not a report of completed tests.

## Checkpoint — Path to the User Version

**Status as of 2026-09-15:** the nearest result was selected under CAT-PILOT-SCOPE-01. The specification as a whole, implementation, and external launch have not yet been approved.

Vladislav stated the goal: “we continue working toward a release result for users.” The end goal remains a full marketplace under the general specification; catalog readiness must not be presented as readiness of a public beta with purchases.

### Verified Current State

- The current main branch contains Phase 1: sign-in and accounts, permissions, seller admission, auditing, and delivery of service messages. Local validation of this phase is described in the [report](../../security/phase-1-review.md); these are historical results, not a new test run.
- This document remains a local draft of Phase 2 requirements. Recorded product decisions are not the same as implemented and tested functions.
- Under section 15 of the general specification, the catalog precedes the cart, order, payment, and fulfillment. Under section 16, the public beta requires separate legal, payment, operational, and security conditions. These conditions are not canceled for the sake of showing the interface earlier.

### Agreed Nearest Working Result

Complete and validate Phase 2 as a working catalog for private testing: the seller creates a physical card with variants, photos, prices, and stock; the buyer finds it, filters results, views variants, and shares a link; a staff member manages directories and confirms common cards. Non-public digital drafts remain within the agreed scope.

This is not a proposal to replace the agreed similar-meaning search with simple word search or to exclude common cards. Purchases, payment, delivery, and file delivery are not simulated: they remain the next stage. Access for invited testers outside the local environment will require separate agreement on deployment and data-protection validation.

### Open Blocks before Phase 2 Implementation

- **Publication and eligible data:** the mandatory minimum is accepted in CAT-PUBLISH-MINIMUM-01, including non-negative values and a real photo for every variant to be published. The upper limits for price and stock, file restrictions, and the full set of technical checks still need to be defined. The agreed minimum is not yet a complete input-processing contract.
- **Coherent catalog:** bring the already accepted rules for the seller's own card, common card, and seller offer into a consistent scheme; close underdefined transitions and the connection to one stock amount across storage locations. Do not extend the own-card rules to a common card without a separate justified decision.
- **Search:** select and justify how search by words, typos, and similar meaning will run, how its quality will be checked, and a reproducible result order. New services, tools, and expenses remain subject to separate agreement.
- **Pilot access:** select how invited participants are admitted and the protection boundary for the catalog and photos; do not use granting staff permissions as a workaround for admitting a buyer.
- **Acceptance:** summary scenarios are collected below. After the remaining blocks are closed, detail checks for access, price and stock, photos, search, and compatibility with Phase 1; approve completion criteria and an implementation plan. Do not mark future checks complete without an actual result.

This grouping replaces another separate question about a minor interface detail, but does not authorize silently assigning missing product rules. Orders, delivery, and payments deferred to the next stage do not become conditions for completing catalog code; they remain conditions of the relevant stage and public launch.

### Summary Acceptance of the Private Catalog — Test Draft

The main user scenarios are collected below, not new readiness marks. The detailed verifiable consequences of each CAT decision remain; this list does not replace them or declare underdefined rules agreed. None of the items has been completed yet.

- [ ] **Admission and permissions.** An invited participant receives only the access they are entitled to. A person outside the pilot cannot open the catalog or photos by a workaround. The seller does not receive another person's private data; test participation does not make a buyer a staff member. Basis: CAT-PILOT-SCOPE-01 and Phase 1 access rules.
- [ ] **Creation and publication.** The seller creates and publishes a physical card after checks, without a mandatory preliminary manual queue. The accepted minimum is checked, including the data for every variant to be published, a real photo, and the acceptability of zero stock on first publication. Data that does not meet mandatory conditions is not published. Draft edits are not visible to the buyer; successful publication applies the agreed content version. Basis: CAT-PUBLISH-01, CAT-PUBLISH-MINIMUM-01, CAT-EDIT-01, CAT-EDIT-FIELDS-01; the remaining technical checks are still being agreed.
- [ ] **Price, stock, and unit.** Price or stock changes are applied separately from content. An old draft and a stale tab do not overwrite current values. The single locked unit, agreed precision, rubles, and a free zero price are respected. The buyer sees a status, not warehouse quantities. Basis: CAT-OFFER-01, CAT-OFFER-CONFLICT-01, CAT-UNITS-01, CAT-UNIT-LOCK-01, CAT-STOCK-PUBLIC-01, CAT-STOCK-PRECISION-01, CAT-CURRENCY-01, CAT-PRICE-PRECISION-01, CAT-ZERO-PRICE-01.
- [ ] **Variant lifecycle.** Adding and explicitly returning a variant go through the common draft; withdrawal occurs separately. Normal stock exhaustion is not equated with withdrawal. The last withdrawn variant, normal exhaustion of all variants, and viewing an exhausted variant beside in-stock variants are checked. Stock is not copied on publication. Basis: CAT-VARIANT-ADD-01, CAT-VARIANT-WITHDRAW-01, CAT-CARD-WITHDRAW-01, CAT-VARIANT-RESTORE-01, CAT-AVAILABILITY-01, CAT-VARIANT-OUT-OF-STOCK-01, and the principle of one actual stock amount.
- [ ] **Directories and common cards.** A staff member manages categories and confirms matching; the seller does not independently change common content. A new normal required field does not hide the old card but is checked at the next content publication. Offer comparison uses only the item price for the same unit, with a warning that delivery has not been calculated. Basis: CAT-MATCH-01, CAT-COMMON-EDIT-01, CAT-TAXONOMY-01, CAT-TAXONOMY-CHANGE-01, CAT-COMPARE-DELIVERY-SCOPE-01.
- [ ] **Search and filters.** There are matches by words, typos, and similar meaning; exact results rank above approximate ones, with no invented goods. Filters are jointly applied to one variant, and selected conditions are not weakened. The card is not duplicated; price and availability are calculated only from matching offers. Basis: CAT-SEARCH-01, CAT-SEARCH-GROUP-01, CAT-SEARCH-FIELDS-01, CAT-SEARCH-APPROX-01, CAT-SEARCH-FILTER-MULTI-01, CAT-SEARCH-FILTER-AVAILABILITY-01.
- [ ] **Search controls.** Typing alone does not start a search; Enter, “Find,” and a filter change apply text under the agreed rules. Correction suggestions, automatic loading, return to the previous position, and passing applied conditions through a link work. An invalid condition is not removed silently, a failure is not presented as an empty result, and an old response does not replace the current search. Basis: CAT-SEARCH-TYPO-01, CAT-SEARCH-TYPO-TRIGGER-01, CAT-SEARCH-SCROLL-01, CAT-SEARCH-RETURN-01, CAT-SEARCH-FILTER-APPLY-01, CAT-SEARCH-TEXT-APPLY-01, CAT-SEARCH-FILTER-TEXT-01, CAT-SEARCH-LINK-01, CAT-SEARCH-LINK-VALIDATION-01.
- [ ] **Card, photos, and links.** Opening from search, a normal direct link, and a link to a selected variant are checked separately. The common search cover does not change the price or selected variant; inside the card, photos match the selection, and missing photos are not replaced with someone else's. An unsuitable or unavailable variant is not substituted for the passed variant. Basis: CAT-VARIANT-PHOTOS-01, CAT-VARIANT-PHOTOS-EMPTY-01, CAT-SEARCH-COVER-01, CAT-SEARCH-OPEN-VARIANT-01, CAT-DIRECT-OPEN-VARIANT-01, CAT-VARIANT-LINK-01.
- [ ] **Limited digital draft.** The seller saves the description and price of a downloadable good but does not publish it, upload the file being sold, or deliver it to the buyer in Phase 2. Basis: CAT-DIGITAL-SCOPE-01.
- [ ] **End-to-end run and state protection.** The real sequential scenario “seller publishes → buyer finds → data changes → buyer sees the correct state” runs together with validation of Phase 1, migrations, and recovery. Access denials do not expose drafts, hidden variants, warehouse quantities, or secrets. Results are confirmed by actual execution, not merely by the presence of tests. This is a final-acceptance draft; the detailed validation plan still needs approval.

### Deferred Block — Admission of Private-Test Participants

**Status:** the former question about admission to a single test site was deferred after Vladislav clarified that the project would be downloaded from GitHub. Neither a manual account list nor one-time email invitations has been selected. These proposals are not a condition for preparing understandable project download and local startup. CAT-PILOT-SCOPE-01 preserves the agreed functions and restrictions of the trial catalog; the method of admission to data on a running marketplace cannot be considered selected based on the GitHub message.

Phase 1 already provides normal registration, email confirmation, and sign-in; the corresponding operations and account-state information are available in `identity.public`. Invitations in `access.public` concern staff. Their presence does not mean that buyer invitations to the pilot are ready and does not permit granting testers service roles.

History of two unaccepted proposals, not a current question for the user:

- **List of admitted accounts.** A person creates a personal account, confirms their email, and signs in. An authorized administrator separately permits that account to participate in the test. Registration alone does not open the catalog. The administrator can revoke admission without deleting the account; subsequent requests to the protected catalog and photos must be rejected.
- **Named one-time email invitations.** The administrator sends an invitation to a specific email address; the person confirms ownership of that email, accepts the active invitation, and joins the pilot. The invitation does not grant access to anyone who possesses a forwarded link. The expiration period, revocation process, and email flow require separate definition and validation.

The former recommendation favored the first method: explicit manual admission without an additional one-time-email-invitation flow for the pilot. This is not an accepted decision or an existing participant-management screen. The second method would add a separate invitation lifecycle. Neither is automatically included in the implementation.

Under both proposals, test participation does not replace Phase 1 seller admission or grant staff permissions. Account locks and the restrictions of each operation are respected. The catalog, photos, search, and suggestions are protected by the agreed pilot boundary. Neither option currently authorizes automatically sending invitations, changing real access, or starting an external server. The admission-storage format and the specific set of administrative permissions are not defined. The current clarification is given below; the former proposal cannot be considered selected based on the GitHub message.

### Working Path — Downloading the Project from GitHub and Understandable Startup

**Status as of 2026-09-15:** the user outcome is clear: a person obtains the project from GitHub and can start it using understandable instructions. Vladislav said that he does not know the technical difference between the proposed download methods. The choice between source code, an installer, and a ready-made build was removed from the current interview; asking the user to answer this menu was a mistake. None of the proposed options is recorded as his choice.

Vladislav's message: “We will put the project on GitHub right away, and people will download it from there.”

**Technical preparation basis selected by the architect:** the existing project and the local startup through Docker Compose described in `README.md` — joint startup of the web application and the services it requires. Already specified dependencies: Docker Desktop, a suitable command shell, and Python for initially creating the user's own `.env`. This is not a promise of startup without preparation and is not a ready-made installer. A new installer, a separate desktop application, a new repository, or an external server is not added to the current work.

**Downloaded-project readiness scenario — a future check not yet completed for the catalog:**

1. Obtain a clean copy of the release-designated version from GitHub, without developer-workspace files. Check specifically the acquisition method described in the instructions.
2. Prepare the required dependencies and the user's own local environment according to the instructions. Do not transfer someone else's `.env`, secrets, working databases, or user data; do not overwrite existing keys or databases.
3. Start the project and open it in a browser. The instructions must directly explain initial setup, creation of the first administrator, and safe shutdown; installing the application and signing in for the first time must not depend on user guesses.
4. Run the agreed seller and buyer scenarios: prepare and publish a physical good, find it, apply filters, select a variant, and view the card. Orders and payment are not included in this release.
5. Record the actual validation result in a clean separate environment. Current Phase 1 readiness and the presence of a startup command do not prove readiness of the catalog that has not yet been implemented.

The technical basis above is a preparation and validation method, not a new business decision by Vladislav or approval of the entire specification. Validating a local copy does not automatically determine whether user installations will be independent or connected to a shared marketplace. It does not authorize any shared connection to a production database.

**Publication boundary:** the previously checked repository `VibeSan7/Open_Marketplace` is private; section 2 of `concept-protocol.md` keeps the official service's source code private. Preparing understandable startup does not change these conditions. Changing visibility, licensing, granting real access, and the contents of an external publication require separate authorization before the respective action, but do not block local requirements preparation. No secrets, working databases, or user data are included in distributable material.

**Continuation of work:** assemble a coherent draft of requirements for the working catalog and its verifiable startup. Ground technical proposals in the existing project and mark them separately from the rules already agreed. Do not repeat the download-format menu or automatically return to admission lists or email invitations. Catalog implementation, publication, and external startup have not yet been performed.
