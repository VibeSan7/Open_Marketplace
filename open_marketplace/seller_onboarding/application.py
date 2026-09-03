from datetime import datetime, timedelta
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.errors import (
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import OperationContext
from open_marketplace.identity.public import get_account_snapshot
from open_marketplace.outbox.public import enqueue_outbox_message

from open_marketplace.seller_onboarding.domain import (
    SellerApplicationVersionView,
    SellerApplicationView,
    SellerDraftData,
)
from open_marketplace.seller_onboarding.models import (
    SellerApplication,
    SellerApplicationVersion,
)

_UNFINISHED_STATES = frozenset(
    {"draft", "submitted", "under_review", "changes_requested"}
)
_EDITABLE_STATES = frozenset({"draft", "changes_requested"})
_SUBMITTABLE_STATES = frozenset({"draft", "changes_requested"})
_BUSINESS_FORMS = frozenset({"sole_proprietor", "legal_entity", "self_employed"})
_MAX_NAME_LENGTH = 256
_MAX_IDENTIFIER_LENGTH = 128
_MAX_EMAIL_LENGTH = 254


def _reject(message):
    raise InputRejected(message)


def _validate_context(context):
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    if context.actor_account_id is not None and not isinstance(context.actor_account_id, UUID):
        _reject("context actor_account_id must be a UUID or None.")
    if context.actor_account_id is None:
        raise PermissionDenied("Seller applications are unavailable.")
    if context.session_id is not None and not isinstance(context.session_id, UUID):
        _reject("context session_id must be a UUID or None.")
    if not isinstance(context.request_id, UUID):
        _reject("context request_id must be a UUID.")
    if context.source not in {"html", "admin", "command", "worker"}:
        _reject("context source is invalid.")
    if (
        not isinstance(context.now, datetime)
        or context.now.tzinfo is None
        or context.now.utcoffset() != timedelta(0)
    ):
        _reject("context.now must be a timezone-aware UTC datetime.")


def _validate_application_id(application_id):
    if not isinstance(application_id, UUID):
        _reject("application_id must be a UUID.")


def _require_ordinary_account(context):
    _validate_context(context)
    try:
        account = get_account_snapshot(context.actor_account_id)
    except ObjectDoesNotExist:
        raise PermissionDenied("Seller applications are unavailable.") from None
    if (
        account.kind != "ordinary"
        or account.state != "active"
        or account.email_verified_at is None
    ):
        raise PermissionDenied("Seller applications are unavailable.")
    return account


def _validated_draft(data):
    if not isinstance(data, SellerDraftData):
        _reject("data must be SellerDraftData.")
    if (
        not isinstance(data.business_form, str)
        or data.business_form not in _BUSINESS_FORMS
    ):
        _reject("business_form is invalid.")
    if type(data.test_data_attested) is not bool:
        _reject("test_data_attested must be a boolean.")

    values = {}
    for name in ("display_name", "official_name", "registration_identifier", "contact_email"):
        value = getattr(data, name)
        if not isinstance(value, str):
            _reject(f"{name} must be a string.")
        value = value.strip()
        if not value:
            _reject(f"{name} must not be blank.")
        if name in {"display_name", "official_name"} and len(value) > _MAX_NAME_LENGTH:
            _reject(f"{name} is too long.")
        if name == "registration_identifier" and len(value) > _MAX_IDENTIFIER_LENGTH:
            _reject("registration_identifier is too long.")
        if name == "contact_email":
            if len(value) > _MAX_EMAIL_LENGTH:
                _reject("contact_email is too long.")
            try:
                validate_email(value)
            except ValidationError:
                _reject("contact_email is invalid.")
            value = value.casefold()
        values[name] = value
    return SellerDraftData(
        business_form=data.business_form,
        display_name=values["display_name"],
        official_name=values["official_name"],
        registration_identifier=values["registration_identifier"],
        contact_email=values["contact_email"],
        test_data_attested=data.test_data_attested,
    )


def _stored_draft(application):
    if any(
        getattr(application, field) is None
        for field in (
            "business_form",
            "display_name",
            "official_name",
            "registration_identifier",
            "contact_email",
        )
    ):
        _reject("Seller application data is incomplete.")
    return _validated_draft(
        SellerDraftData(
            business_form=application.business_form,
            display_name=application.display_name,
            official_name=application.official_name,
            registration_identifier=application.registration_identifier,
            contact_email=application.contact_email,
            test_data_attested=application.test_data_attested,
        )
    )


def _application_view(application):
    return SellerApplicationView(
        id=application.id,
        applicant_id=application.applicant_id,
        state=application.state,
        current_version=application.current_version,
        reviewer_id=application.reviewer_id,
        decision=application.decision,
        reason=application.reason,
        created_at=application.created_at,
        submitted_at=application.submitted_at,
    )


def _version_view(version):
    return SellerApplicationVersionView(
        application_id=version.application_id,
        version_number=version.version_number,
        data=SellerDraftData(
            business_form=version.business_form,
            display_name=version.display_name,
            official_name=version.official_name,
            registration_identifier=version.registration_identifier,
            contact_email=version.contact_email,
            test_data_attested=version.test_data_attested,
        ),
        submitted_at=version.submitted_at,
    )


def _owned_application(*, application_id, context, lock=False):
    queryset = SellerApplication.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        application = queryset.get(pk=application_id)
    except SellerApplication.DoesNotExist:
        raise PermissionDenied("Seller applications are unavailable.") from None
    if application.applicant_id != context.actor_account_id:
        raise PermissionDenied("Seller applications are unavailable.")
    return application


def _audit(*, context, application, action, before_state, before_version):
    before_state = getattr(before_state, "value", before_state)
    state = getattr(application.state, "value", application.state)
    return append_audit_entry(
        context=context,
        action=action,
        object_type="seller_application",
        object_id=str(application.id),
        result="success",
        reason=None,
        before={"state": before_state, "version": before_version},
        after={"state": state, "version": application.current_version},
        effective_role=None,
    )


def create_seller_application(*, context: OperationContext) -> UUID:
    _require_ordinary_account(context)
    application = None
    with transaction.atomic():
        try:
            with transaction.atomic():
                application = SellerApplication.objects.create(
                    applicant_id=context.actor_account_id,
                    state=SellerApplication.State.DRAFT,
                    current_version=0,
                    created_at=context.now,
                )
        except IntegrityError:
            raise ConcurrentConflict(
                "An unfinished seller application already exists."
            ) from None
        _audit(
            context=context,
            application=application,
            action="seller_onboarding.application_created",
            before_state=None,
            before_version=0,
        )
    return application.id


def update_seller_application_draft(
    *, application_id: UUID, data: SellerDraftData, context: OperationContext
) -> None:
    _require_ordinary_account(context)
    _validate_application_id(application_id)
    data = _validated_draft(data)
    with transaction.atomic():
        application = _owned_application(
            application_id=application_id,
            context=context,
            lock=True,
        )
        if application.state not in _EDITABLE_STATES:
            raise InvalidState("Seller application is not editable.")
        before_state = application.state
        before_version = application.current_version
        application.business_form = data.business_form
        application.display_name = data.display_name
        application.official_name = data.official_name
        application.registration_identifier = data.registration_identifier
        application.contact_email = data.contact_email
        application.test_data_attested = data.test_data_attested
        application.save(
            update_fields=(
                "business_form",
                "display_name",
                "official_name",
                "registration_identifier",
                "contact_email",
                "test_data_attested",
            )
        )
        _audit(
            context=context,
            application=application,
            action="seller_onboarding.application_updated",
            before_state=before_state,
            before_version=before_version,
        )


def submit_seller_application(*, application_id: UUID, context: OperationContext) -> UUID:
    _require_ordinary_account(context)
    _validate_application_id(application_id)
    with transaction.atomic():
        application = _owned_application(
            application_id=application_id,
            context=context,
            lock=True,
        )
        if application.state not in _SUBMITTABLE_STATES:
            raise InvalidState("Seller application cannot be submitted.")
        data = _stored_draft(application)
        if not data.test_data_attested:
            _reject("Test data must be attested before submission.")
        before_state = application.state
        before_version = application.current_version
        version_number = application.current_version + 1
        try:
            with transaction.atomic():
                version = SellerApplicationVersion.objects.create(
                    application=application,
                    version_number=version_number,
                    business_form=data.business_form,
                    display_name=data.display_name,
                    official_name=data.official_name,
                    registration_identifier=data.registration_identifier,
                    contact_email=data.contact_email,
                    test_data_attested=data.test_data_attested,
                    submitted_at=context.now,
                )
        except IntegrityError:
            raise ConcurrentConflict(
                "The seller application version already exists."
            ) from None
        application.current_version = version_number
        application.state = SellerApplication.State.SUBMITTED
        application.submitted_at = context.now
        application.save(update_fields=("current_version", "state", "submitted_at"))
        _audit(
            context=context,
            application=application,
            action="seller_onboarding.application_submitted",
            before_state=before_state,
            before_version=before_version,
        )
        enqueue_outbox_message(
            message_type="seller_onboarding.application_submitted",
            format_version=1,
            payload={
                "application_id": str(application.id),
                "version_id": str(version.id),
            },
            delivery=None,
            idempotency_key=f"seller_onboarding.application_submitted:{version.id}",
        )
    return version.id


def withdraw_seller_application(*, application_id: UUID, context: OperationContext) -> None:
    _require_ordinary_account(context)
    _validate_application_id(application_id)
    with transaction.atomic():
        application = _owned_application(
            application_id=application_id,
            context=context,
            lock=True,
        )
        if application.state not in _UNFINISHED_STATES:
            raise InvalidState("Seller application cannot be withdrawn.")
        before_state = application.state
        before_version = application.current_version
        application.state = SellerApplication.State.WITHDRAWN
        application.save(update_fields=("state",))
        _audit(
            context=context,
            application=application,
            action="seller_onboarding.application_withdrawn",
            before_state=before_state,
            before_version=before_version,
        )


def list_own_seller_applications(*, context: OperationContext) -> tuple[SellerApplicationView, ...]:
    _require_ordinary_account(context)
    applications = SellerApplication.objects.filter(
        applicant_id=context.actor_account_id
    ).order_by("created_at", "id")
    return tuple(_application_view(application) for application in applications)


def get_own_seller_application(
    *, application_id: UUID, context: OperationContext
) -> tuple[SellerApplicationView, tuple[SellerApplicationVersionView, ...]]:
    _require_ordinary_account(context)
    _validate_application_id(application_id)
    application = _owned_application(application_id=application_id, context=context)
    versions = SellerApplicationVersion.objects.filter(
        application_id=application.id
    ).order_by("version_number", "id")
    return _application_view(application), tuple(_version_view(version) for version in versions)
