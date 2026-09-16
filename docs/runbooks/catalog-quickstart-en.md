# Using the catalog

[Русский](catalog-quickstart-ru.md) | English

The [English README](../../README.en.md) contains the installation commands. This guide covers what to do after startup. It does not change the application's interface language; Russian button labels are shown alongside their English meanings.

For the complete first run, start with the [installation runbook](initial-setup-en.md), then open the [built-in read-only guide](http://127.0.0.1:8000/setup/) in your copy. That page creates no accounts and changes no data.

## Keep account roles separate

This installation has three account roles to distinguish:

- The **security administrator** invites staff, grants participation, and manages categories and attributes.
- The **seller reviewer** reviews seller applications. This role alone does not grant permission to change the catalog.
- A **personal account** is used to browse and, after seller approval, sell products.

For local testing, use separate browser profiles or a normal and a private window to keep sign-ins separate. Do not put passwords, authenticator secrets, or recovery codes in the project or a report.

## First administrator

1. Run the `bootstrap_security_admin` command from the README or the [installation runbook](initial-setup-en.md).
2. Open the local inbox: <http://127.0.0.1:8025/>.
3. Open the invitation email and follow its link. Do not copy the one-time link into a public chat.
4. Set a password, add the account to an authenticator app, and confirm the current code.
5. Save the recovery codes in a secure location. They are displayed only once.
6. Sign in at <http://127.0.0.1:8000/admin/>. Invite another staff account with the `seller_reviewer` role. The invited reviewer also completes setup through Mailpit.

If a sensitive action requires reauthentication, open <http://127.0.0.1:8000/security/reauthenticate/>, confirm your identity, and repeat the action immediately. Do not disable the time-limited protection.

## Set up a personal seller account

1. Open <http://127.0.0.1:8000/register/> and register a separate personal account.
2. Verify the email using the Mailpit link and sign in.
3. Enable two-factor authentication at <http://127.0.0.1:8000/security/>. This adds an authenticator code to the sign-in process.
4. Open <http://127.0.0.1:8000/seller/applications/create/>, complete the seller application, and submit it.
5. In another browser window, sign in as the reviewer. Open the application queue in the staff panel, start the review, and approve the application.
6. The administrator opens <http://127.0.0.1:8000/catalog/manage/>, enters the seller's email, enables participation, and saves it.

Admission does not replace seller approval. Public listings are visible without signing in. Saved products and public-product demo orders require an active personal account with verified email; private listings additionally require admission. Buyers do not need seller applications.

## Create a category

In catalog management, create a category such as Clothing. Add attributes such as Color, Size, and, if needed, Material.

- A stable key is a short internal name: `color`, `size`, or `material`. If left blank, it is generated from the label. Avoid changing it once products use it.
- For a list of choices, enter one value per line. An empty choice list allows free text.
- The required-field setting is checked at publication. Incomplete drafts can still be saved.
- A newly required descriptive field is checked the next time content is published; it does not prevent separate price or stock updates.

## Add the first product

1. The seller opens <http://127.0.0.1:8000/catalog/own/> and clicks "Создать карточку" (Create listing).
2. Choose a physical product and its unit: individual units, kilograms, or meters.
3. Enter the title, description, and category, then save the draft. The category's attributes appear after selecting it.
4. Upload real photos and confirm their origin. JPEG, PNG, and WebP are accepted; files are checked and saved without their original metadata.
5. Create a variant, such as Red S, fill in its attributes, and select the photos that belong to that variant.
6. Save the price and stock separately. An empty field is not zero. Enter `0` for a free product or `0` stock when it is out of stock.
7. Click "Опубликовать" (Publish). If anything is missing, fix the reported issue and publish again.
8. Separately enable "Открыть публичный показ" for guest visibility, then open the catalog and check the listing. Existing listings never become public automatically. A product with zero stock does not appear in search, but its published description remains available through a direct link.

Listing-level attributes must be the same for every variant. Color and size normally belong to variants, rather than having conflicting values at both listing and variant level.

The unit is locked after the first price or quantity is saved. Create a different listing to sell in another unit. Prices allow two decimal places in rubles; kilograms and meters allow three decimal places; individual units must be whole numbers. Values that would require rounding are rejected.

## Edit, withdraw, and restore

- Edit the content and save a draft. Buyers still see the previous published version.
- "Опубликовать" (Publish) validates the whole set being published. An error does not result in partial publication.
- Price and stock are saved immediately using separate buttons. An old draft does not roll them back.
- If another update has changed a value, a conflict is shown. Compare the current value with the input preserved in the form, then explicitly confirm another update.
- "Снять вариант" (Withdraw variant) and "Снять всю карточку" (Withdraw entire listing) take effect immediately, without deleting photos or quantities.
- To restore a withdrawn variant, explicitly request its return, save the variant, and publish the listing. This does not remove a staff-imposed block.
- Create additional storage locations in the editor. Enter stock at each location separately for each relevant variant.

## Shared listings and offer comparison

The administrator creates a shared listing through "Мои карточки" (My listings), with a shared description, category, attributes, variants, and photos. Prices and stock are not entered there; they come from seller offers.

In the editor for a published variant, the seller selects the matching shared variant and submits a reason for the match. A shared variant can be selected before it has its first offer.

A staff member checks the model, attributes, included items, condition, and unit. Only explicit approval adds the offer to the shared listing. Semantic search does not confirm that products are identical. Changes to identifying information require the link to be approved again.

In-stock offers are compared by price for the same unit. "Доставка ещё не рассчитана" means "Delivery has not been calculated yet": the displayed price is not a final purchase total. This version does not support purchases.

## Search and links

- Type a query and press Enter or click "Найти" (Search). Typing alone does not run a search.
- Changing a filter immediately applies both that filter and the text currently typed in the search field.
- Multiple values for one attribute mean "or". Different attributes must match the same product variant.
- Gray values currently have no matching products. A selected unavailable value is not removed automatically.
- Exact results come first, followed by labeled approximate results. A suggested query correction is applied only when clicked and preserves the filters.
- Scrolling loads more listings. On an error, click "Повторить" (Retry); previously loaded results should remain visible.
- "Поделиться условиями поиска" (Share search conditions) copies the applied conditions, not unfinished text in the input field.
- A variant link preserves the selected variant, not an old price or access permission. It does not buy or reserve the product.
- Links containing `127.0.0.1` work only on the same computer. Access from another computer requires a separately configured server; sharing a local link does not create one.

## Backups and updates

The database and photos are stored separately. Restoration requires **the database, photos, and the original `.env`**. Without the original keys, encrypted data cannot be considered restored. The search model can be downloaded again.

The commands below apply to your local installation. Backups contain sensitive data: keep them out of public cloud folders, restrict access, and encrypt the storage you choose. Git and the Docker image exclude `backups/`.

Stop application writes while creating a consistent backup:

```bash
docker compose stop web worker
```

```bash
mkdir -p backups
```

```bash
docker compose exec -T postgres sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' > backups/catalog.dump
```

```bash
docker compose run --rm --no-deps -T web tar -czf - -C /app/private-media . > backups/photos.tar.gz
```

```bash
cp -p .env backups/.env
```

```bash
docker compose up -d
```

Do not publish this directory or upload it as a GitHub artifact. Move the backup to secure storage. Completing a copy command does not prove that restoration works: test it in a separate installation, not over your only working database.

Keep a verified backup before updating. Update the code in the same directory while retaining the original `.env` and Docker project name, then run migrations and rebuild using the README commands. If the update fails, stop the new version and restore the **matching backup set** in a separate environment. Do not combine old keys with an unrelated new database or delete volumes by trial and error.

## Troubleshooting

- **Docker does not respond:** start Docker Desktop, wait until it is ready, then repeat the command.
- **A port is busy:** another application is using 8000, 8025, or 1025. Do not stop another project blindly. Configure separate ports for your copy and update `APP_BASE_URL` in `.env` accordingly.
- **The model is not prepared:** repeat `docker compose run --rm web python manage.py prepare_catalog_search`. Internet access is needed for the download, not for normal searches afterward.
- **Email does not arrive:** check `docker compose ps`, then run one delivery pass with `docker compose run --rm web python manage.py run_outbox_worker --once`. Check the local Mailpit inbox, not an external mailbox.
- **No private-listing access:** verify your email and ask the administrator to check admission. Public listings do not require signing in. The editor also requires an active seller and two-factor authentication.
- **No products:** a new installation is empty, and published variants with zero stock do not appear in search.
- **Reauthentication required:** open the identity confirmation page and repeat the action immediately after confirmation.
