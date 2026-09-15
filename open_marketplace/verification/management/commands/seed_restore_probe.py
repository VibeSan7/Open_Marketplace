"""Seed a deterministic linked restore-probe graph through public interfaces."""

from uuid import UUID
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from open_marketplace.catalog import public as catalog

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from open_marketplace.seller_onboarding.public import (
    SellerDraftData,
    approve_seller_application,
    create_seller_application,
    start_seller_application_review,
    submit_seller_application,
    update_seller_application_draft,
)
from open_marketplace.verification._probe import (
    accept_staff_invitation_flow,
    command_context,
    create_verified_ordinary_account,
    probe_email,
    require_marker,
)


class Command(BaseCommand):
    help = (
        "Seed deterministic linked restore-probe rows only in a disposable "
        "postgres-test database."
    )

    def add_arguments(self, parser):
        parser.add_argument("--marker", required=True, help="Deterministic restore marker.")

    def handle(self, *args, **options):
        database_name = str(connection.settings_dict["NAME"])
        database_host = str(connection.settings_dict["HOST"])
        if database_host != "postgres-test" or not database_name.startswith(
            ("test_", "restore_source_")
        ):
            raise CommandError(
                "seed_restore_probe requires a disposable postgres-test database."
            )
        try:
            marker = require_marker(options["marker"])
        except ValueError as error:
            raise CommandError(str(error)) from None
        owner_id = create_verified_ordinary_account(marker=marker)
        admin = accept_staff_invitation_flow(
            marker=marker,
            kind="admin",
            role="security_admin",
        )
        reviewer = accept_staff_invitation_flow(
            marker=marker,
            kind="reviewer",
            role="seller_reviewer",
            created_by=admin,
        )
        owner_context = command_context(actor_account_id=owner_id)
        application_id = create_seller_application(context=owner_context)
        update_seller_application_draft(
            application_id=application_id,
            data=SellerDraftData(
                business_form="sole_proprietor",
                display_name="Restore Probe Store",
                official_name="Restore Probe Store Official",
                registration_identifier="RESTORE-PROBE-001",
                contact_email=probe_email(marker, "owner"),
                test_data_attested=True,
            ),
            context=owner_context,
        )
        submit_seller_application(application_id=application_id, context=owner_context)
        reviewer_context = reviewer["context"]
        start_seller_application_review(
            application_id=application_id,
            context=reviewer_context,
        )
        approve_seller_application(
            application_id=application_id,
            reason="Restore probe approval.",
            context=reviewer_context,
        )
        category = catalog.create_category(name=f"Restore {marker}", attributes=[], context=admin["context"])
        catalog.set_participant(account_id=owner_id, allowed=True, context=admin["context"])
        product = catalog.create_product(kind="common", unit="pc", context=admin["context"])
        catalog.save_product_draft(product_id=product, expected_version=0,
            data={"title": f"Restore {marker}", "description": "Disposable restore fixture", "category_id": str(category)},
            context=admin["context"])
        image = BytesIO()
        Image.new("RGB", (8, 8), (20, 40, 60)).save(image, format="PNG")
        photo = catalog.upload_photo(product_id=product,
            uploaded_file=SimpleUploadedFile("restore-fixture.png", image.getvalue(), content_type="image/png"),
            attested=True, context=admin["context"])
        catalog.add_variant(product_id=product, expected_version=1,
            data={"label": "Restore variant", "attributes": {}, "photo_ids": [str(photo)]}, context=admin["context"])
        catalog.publish_product(product_id=product, expected_version=2, context=admin["context"])
        self.stdout.write(
            f"restore_seed_complete marker={marker} owner_id={owner_id} "
            f"admin_id={admin['account_id']} reviewer_id={reviewer['account_id']} "
            f"application_id={application_id}"
        )
