# Phase 2 — Working Catalog and Reproducible Startup

> **For the implementer:** use `superpowers:executing-plans`; carry out the work directly, with real checks after every block. Do not return to interviewing the owner about technical alternatives.

**Goal:** deliver a locally runnable catalog project with verified seller, buyer, and staff journeys, instructions, and an archive without secrets.

**Architecture:** the existing Django/PostgreSQL project; the new domain module `catalog` uses only the public interfaces of identity, access, seller_onboarding, and audit. Server-rendered HTML forms remain the foundation; a small amount of custom JavaScript handles automatic filters, scrolling, and position restoration. No orders, payments, public server, or new external infrastructure.

**Tech Stack:** the currently pinned Python/Django/PostgreSQL versions, Pillow for validating and safely saving photos, and FastEmbed with a local multilingual ONNX model for semantic search. New library versions are pinned in pyproject.toml and uv.lock after dependency resolution. The search model does not replace the leading Hermes model or call a paid API.

**Spec:** `docs/superpowers/specs/2026-09-14-phase-2-catalog-design.md`. All CAT decisions remain in force, including common cards, semantic search, storage locations, and digital drafts.

## Authorization and Boundaries

Vladislav delegated the remaining decisions to the implementer and explicitly required work without further questions and delivery of a finished result; he then confirmed “continue.” This authorizes implementation of the agreed catalog and safe local checks, not merely a document. The decisions below belong to the architect; they are not invented individual answers from Vladislav.

- Working copy: `D:/Open_Marketplace/.worktrees/phase2-catalog`, branch `phase2-catalog`, base `547970d986e9d8555dd4b5272ca768835df74e67`.
- Leave the main branch, previous worktree, old containers, databases, and secrets unchanged. Isolated Compose project: `omp-phase2-20260915`; use only this project's `postgres-test` test database and this project's Mailpit.
- Do not copy the original `.env`. The new working copy has its own `.env` with fresh random values generated without displaying them; `.env` is excluded from Git and the final archive.
- Publication of the source and completed release in the existing private GitHub repository was separately authorized by Vladislav's direct instruction: “I need a finished project on github.” Do not change visibility, real access permissions, or external infrastructure, and do not connect paid APIs. Publish only the verified package without secrets or installation data.
- Do not launch a separate reviewing model. The leading model remains the one selected by the user.
- Context7 resolve requests for Django and FastEmbed ended with `TypeError: fetch failed`. MCP settings were not changed. Official primary sources were used: Django stable/5.2.x `docs/topics/db/transactions.txt`; Qdrant FastEmbed `fastembed/text/text_embedding.py`, `pooled_embedding.py`; Pillow `docs/handbook/tutorial.rst`. Check subsequent APIs against source code or official documentation; do not invent Context7 results.

## Recorded Implementation Decisions

### Permissions and Initial Setup

- Private catalog: an active, verified personal account plus explicit `Participant` admission in this installation. Registration alone does not grant access to the catalog, images, or search suggestions.
- The existing `security_admin` grants or revokes admission; this does not grant a staff role or seller rights. The same staff member manages the directory, common cards, and moderation through the new narrow permissions `catalog.read` / `catalog.manage`. No additional roles are introduced in this version.
- Preserve the current session, email verification, account locks, seller admission, and mandatory TOTP. Staff catalog management requires the existing fresh-authentication check.
- Keep seller and staff accounts separate. The guide explains initial administrator creation through the existing supported procedure, inviting a seller reviewer, registering a participant, and granting catalog admission.

### Data and Transitions

- `Category`: name, availability, version. `Attribute`: key, label, category, required flag, and list of permitted values; a text value is allowed for an attribute without a list. All fields have explicit limits at the external boundary. Only staff can modify the directory; seller suggestions are stored separately.
- `Product`: UUID, owner UUID / seller UUID (empty only for a common card), physical/digital/common kind, pc/kg/m unit, unit-lock flag, draft content, published snapshot, draft and publication versions, and staff block. No seller ORM model in the catalog module.
- `Variant`: UUID, product, its own price and price version, snapshots of attributes and photo links, draft/published/withdrawn state, and a separate staff block. The offer remains the same variant with the same stock.
- `StorageLocation`: UUID, seller, name; `Stock`: variant + storage location, exact quantity, and version. One row per variant/location pair. The first location has the “Main storage location” label (UI text: `Основное место хранения`); the owner creates additional locations. Do not combine stock across different variants or sellers. Buyers receive availability only.
- Saving content, adding a variant, and choosing to restore it change only the shared draft. Publication is one transaction that validates current requirements for every variant being published or restored. Failed validation leaves the previous publication unchanged.
- Price and stock are saved separately with the expected version of the specific field. Lock the row during validation and writing. Changing another field must not cause a false conflict. On conflict, the interface shows the current value and retains the entered value for an explicit retry, without automatically overwriting anything.
- Withdrawing a variant is a separate operation that preserves its quantity. Restoration is explicitly marked in the draft together with the withdrawal version; an old draft must not restore a withdrawn variant. The seller cannot remove a staff block. Withdrawing the last variant hides the card content, unlike ordinary zero stock.
- Price: RUB, Decimal with up to two decimal places; quantity: whole pieces or Decimal with up to three decimal places for kg/m. Input accepts ordinary decimal notation with a dot or comma, without exponents, NaN, or infinity. Empty input is not zero; reject values that require rounding. The technical limit is 16 integer digits, with a clear error when exceeded. Saving a zero price also locks the unit.
- Publication does not copy numeric data from the draft. The server prohibits publishing digital goods and accepting the digital file being sold.

### Photos

- Accept JPEG, PNG, and WebP up to 8 MiB and 20 million pixels, with a single frame only. Validate decoding, not just the extension. Re-save the image without EXIF or other original metadata under a server-generated UUID; do not accept SVG/HTML or arbitrary paths.
- The uploader confirms that the image is a real photo of the corresponding product without AI-generated additions. File validation is not presented as proof of authenticity. No image generation.
- `Photo` belongs to one card; a photo can be linked to several of that card's variants. The cover is selected separately. Publication verifies ownership, availability, and at least one photo for every variant being published.
- Files are stored in a private directory on a persistent Docker volume and served only through a handler that checks permissions. Do not add a public MEDIA_URL. Account blocking or revoked participation must also apply to direct image URL requests.
- When no photos are available, show the agreed notice, not another gallery. A loading error has a different message. Withdrawing a card does not irreversibly delete its photos.

### Common Cards

- A staff member creates a common card with its own common attributes and photos. A seller submits a request to match their own published variant to a variant of the common card.
- `MatchRequest` stores specific content versions, the rationale, and the decision; `OfferLink` connects the source variant to the common one only after a staff member checks the model, attributes, included items, condition, and identical unit. Content that has changed since submission requires another review.
- Sellers submit textual suggestions for correcting a common card; they do not modify the common data themselves. Editing an identifying attribute of a common card must not silently replace the product behind already linked offers: those links require renewed confirmation.
- Prices and stock are read from the source offer, not copied. Matched offers are grouped in the common card; a rejected or pending request does not prevent the seller's own publication. Comparison includes only available, in-stock offers at the current price per one unit, with the “Delivery has not been calculated yet” notice.

### Search and Browser Behavior

- Candidates come only from published cards and variants permitted for the current participant, with active seller admission and positive stock. Search and suggestions do not receive drafts or exact stock quantities.
- Text normalization: Unicode, case, Cyrillic `ё`/`е` equivalence, and words. Exact matching requires all query words; partial-word matches and similar spellings appear lower with a label. Typos are compared against real words in the permitted published corpus, not a private draft dictionary.
- Semantic similarity: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` through FastEmbed, CPU, 384 components, Apache-2.0 according to the Qdrant registry. The official registry lists approximately 0.22 GB. Download the model once into local storage; after preparation, search requires no external API. A real semantic check is mandatory; do not replace it with fabricated vectors and declare search functional.
- Ordering within a group is reproducible: query relevance, then published name and UUID. One card produces one result; its price comes only from matching offers. Different prices are displayed with a “from…” prefix.
- Filters: `category` and repeated `f.<key>` parameters in the URL. OR within a key; AND between keys on the same variant. Unknown parameters, keys, or values block search while preserving the conditions and requiring the user to remove the error explicitly. Zero results are not a parameter error.
- A correction suggestion appears only when there are no exact results anywhere in the permitted set and is applied only when clicked; preserve the current filters.
- A batch contains 20 cards. Load a separate HTML fragment instead of adding a new public REST API; without JavaScript, ordinary HTML navigation and fallback paging remain available. The primary mode is automatic loading through IntersectionObserver, with one active request and protection against stale responses and duplicate cards.
- Typing text does not send a request; Enter / Search / a filter change applies the visible text. Applied conditions are reflected in the URL; copying the link does not include unfinished input.
- Back navigation uses sessionStorage only for the position and number of viewed results, not as permission to display stale data. On return, reload the list under current permissions, then restore the previous or nearest position. An error preserves the available portion and displays an error rather than the end of the list.
- A direct link selects the lowest current price among available, in-stock variants; a search link selects the lowest among variants matching the filters. Break ties by UUID. A link with `variant` preserves that exact variant. Do not substitute a hidden variant; a published variant that is out of stock remains viewable with the corresponding notice.

## Sequence and Checks

### 1. Foundation, Numbers, Access, and Publication

Files: `catalog/{apps,models,domain,policy,application,public}.py`, migrations, `catalog/tests/test_catalog.py`, narrow changes to access/public permission codes and seller_onboarding/public snapshots, settings.

- [x] Run a clean baseline check of the first phase in the new Compose project.
- [x] RED: the new functionality is absent; tests cover decimal numbers, publication/drafts, ownership, and participation.
- [x] Implement models, database constraints, migrations, operations, and safe public snapshots.
- [x] GREEN: reject publication of an incomplete draft; another person's operation changes no data; price/stock with the same version cannot accept two concurrent updates; withdrawal and zero stock are distinct.

### 2. Photos, Directory, and Common Offers

Files: `catalog/photos.py`, `catalog/common_cards.py`, `catalog/tests/test_photos.py`, `catalog/tests/test_common_cards.py`, and the corresponding HTML adapters.

- [x] RED: real decodable files, invalid formats/sizes, another person's photos, path substitution, and a matching request without staff review.
- [x] Implement photo validation and private serving, plus directory, matching, and suggestion forms.
- [x] GREEN: a linked photo does not change another card; staff review the current versions; blocks immediately prevent display.

### 3. Search and Buyer Interface

Files: `catalog/search.py`, `catalog/tests/test_search.py`, `web/catalog_views.py`, `web/catalog_forms.py`, `templates/catalog/*`, `catalog/static/catalog/*`, urls.

- [x] RED: words, descriptions, filters, different variants, prices, hidden data, an unknown link, and preselection.
- [x] Prepare the model; implement the shared exact/approximate search algorithm and safe sorting/suggestions.
- [x] Implement owner, staff, and buyer forms without manual JSON entry, photo switching, automatic scrolling, links, and return navigation.
- [x] GREEN: real Russian semantic queries without literal matches; filters and permissions apply to every search method; verify JS behavior separately rather than inferring it from a single HTTP 200.

### 4. Release, Validation, and Handoff

Files: README, the quickstart guide originally written in Russian, Dockerfile/compose for persistent photos and the model, `docs/security/phase-2-local-validation.md`, and the final archive.

- [x] Explicitly update only obsolete first-phase bans on the catalog, photos, and newly required dependencies, while retaining the bans on orders, payments, and digital delivery, secret checks, and module boundaries. Do not weaken the security parser or authorization checks.
- [x] Run the full test suite, import-boundary checks, missing-migration checks, restore verification, and an actual HTTP/browser journey in a separate copy.
- [x] Build an archive with an explicit manifest excluding `.env`, .git, databases, user photos, caches, tokens, and logs. Verify startup from the extracted archive and record actual results.
- [x] Prepare the archive, instructions, and an honest verification report for publication in the existing private GitHub repository at the owner's direct request. Do not change visibility or present the catalog as a store that supports purchases.
