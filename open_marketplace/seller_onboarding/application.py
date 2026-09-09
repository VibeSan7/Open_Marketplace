from datetime import datetime, timedelta
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.errors import (
    AuthenticationDenied,
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import OperationContext
from open_marketplace.identity.public import (
    add_totp_requirement,
    get_account_snapshot,
    remove_totp_requirement,
    require_live_session_security_snapshot,
)
from open_marketplace.outbox.public import enqueue_outbox_message
from open_marketplace.access.public import authorize

from open_marketplace.seller_onboarding.domain import (
    SellerApplicationVersionView,
    SellerApplicationView,
    SellerDraftData,
    SellerProfileQuery,
    SellerProfileView,
    SellerReviewDecisionView,
    SellerReviewQuery,
)
from open_marketplace.seller_onboarding.models import (
    SellerApplication,
    SellerApplicationVersion,
    SellerProfile,
    SellerReviewDecision,
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


def _decision_view(decision):
    return SellerReviewDecisionView(
        id=decision.id,
        application_id=decision.application_id,
        version_number=decision.version_number,
        decision=decision.decision,
        reviewer_id=decision.reviewer_id,
        occurred_at=decision.occurred_at,
        request_id=decision.request_id,
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
    if SellerProfile.objects.filter(owner_id=context.actor_account_id).exists():
        raise ConcurrentConflict(
            "A seller profile already exists for this account."
        )
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


def get_own_seller_review_decision(
    *,
    application_id: UUID,
    version_number: int,
    context: OperationContext,
) -> SellerReviewDecisionView | None:
    _require_ordinary_account(context)
    _validate_application_id(application_id)
    if not isinstance(version_number, int) or isinstance(version_number, bool) or version_number < 1:
        _reject("version_number must be a positive integer.")
    application = _owned_application(application_id=application_id, context=context)
    decision = SellerReviewDecision.objects.filter(
        application_id=application.id,
        version_number=version_number,
    ).first()
    return _decision_view(decision) if decision is not None else None


def get_own_seller_application_draft(
    *, application_id: UUID, context: OperationContext
) -> SellerDraftData | None:
    _require_ordinary_account(context)
    _validate_application_id(application_id)
    application = _owned_application(application_id=application_id, context=context)
    if application.state not in _EDITABLE_STATES:
        raise InvalidState("Seller application draft is not editable.")
    if all(
        getattr(application, field) is None
        for field in (
            "business_form",
            "display_name",
            "official_name",
            "registration_identifier",
            "contact_email",
        )
    ):
        return None
    return _stored_draft(application)


# --- Task 13: review, profile and admission -------------------------------

_REVIEW_QUERY_MAX_LIMIT = 100
_PROFILE_QUERY_MAX_LIMIT = 100
_REASON_MAX_LENGTH = 1024


def _validate_reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        _reject("reason must not be blank.")
    if len(reason) > _REASON_MAX_LENGTH:
        _reject("reason is too long.")
    return reason


def _require_review_permission(context):
    authorize(context=context, permission="seller_application.review")
    _validate_context(context)


def _require_profile_read_permission(context):
    authorize(context=context, permission="seller.read")
    _validate_context(context)


def _reviewable_application(application_id, context, *, lock=False):
    _validate_application_id(application_id)
    queryset = SellerApplication.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=application_id)
    except SellerApplication.DoesNotExist:
        raise PermissionDenied("Seller applications are unavailable.") from None


def _existing_profile_for(application):
    profile = SellerProfile.objects.filter(
        application_id=application.id,
        approved_version=application.current_version,
    ).first()
    if profile is not None:
        return profile.id
    raise InvalidState("Seller application version is already decided.")


def _create_profile(application, version_number, context):
    owner = get_account_snapshot(application.applicant_id)
    state = (
        SellerProfile.State.ACTIVE
        if owner.totp_enabled
        else SellerProfile.State.AWAITING_OWNER_TOTP
    )
    try:
        with transaction.atomic():
            profile = SellerProfile.objects.create(
                owner_id=application.applicant_id,
                application=application,
                approved_version=version_number,
                state=state,
                created_at=context.now,
                updated_at=context.now,
            )
    except IntegrityError:
        existing = SellerProfile.objects.filter(
            owner_id=application.applicant_id
        ).first()
        if (
            existing is not None
            and existing.application_id == application.id
            and existing.approved_version == version_number
        ):
            return existing.id
        raise ConcurrentConflict("The seller profile already exists.") from None
    add_totp_requirement(
        account_id=profile.owner_id,
        source_type="seller_profile",
        source_id=profile.id,
        context=context,
    )
    _audit_profile(
        context=context,
        profile=profile,
        action="seller_onboarding.seller_profile_created",
    )
    enqueue_outbox_message(
        message_type="seller_onboarding.admission_change",
        format_version=1,
        payload={"seller_id": str(profile.id), "state": profile.state},
        delivery=None,
        idempotency_key=f"seller_onboarding.admission_change:{profile.id}:created",
    )
    return profile.id


def _audit_profile(context, profile, action, *, before_state=None, reason=None):
    before_state = getattr(before_state, "value", before_state)
    after_state = getattr(profile.state, "value", profile.state)
    return append_audit_entry(
        context=context,
        action=action,
        object_type="seller_profile",
        object_id=str(profile.id),
        result="success",
        reason=reason,
        before={"state": before_state},
        after={"state": after_state},
        effective_role=None,
    )


def _profile_view(profile):
    return SellerProfileView(
        id=profile.id,
        owner_id=profile.owner_id,
        application_id=profile.application_id,
        approved_version=profile.approved_version,
        state=profile.state,
        restriction_reason=profile.restriction_reason,
    )


def _validate_seller_id(seller_id):
    if not isinstance(seller_id, UUID):
        _reject("seller_id must be a UUID.")


def start_seller_application_review(*, application_id, context):
    _require_review_permission(context)
    with transaction.atomic():
        application = _reviewable_application(application_id, context, lock=True)
        if application.state != SellerApplication.State.SUBMITTED:
            raise InvalidState("Seller application cannot be reviewed.")
        before_state = application.state
        application.state = SellerApplication.State.UNDER_REVIEW
        application.reviewer_id = context.actor_account_id
        application.save(update_fields=("state", "reviewer_id"))
        _audit(
            context=context,
            application=application,
            action="seller_onboarding.application_review_started",
            before_state=before_state,
            before_version=application.current_version,
        )


def request_seller_application_changes(*, application_id, reason, context):
    _require_review_permission(context)
    reason = _validate_reason(reason)
    with transaction.atomic():
        application = _reviewable_application(application_id, context, lock=True)
        replayed = _replay_decision(
            application,
            SellerReviewDecision.Decision.REQUEST_CHANGES,
            reason,
            context,
        )
        if replayed is not None:
            return
        if application.state != SellerApplication.State.UNDER_REVIEW:
            raise InvalidState("Seller application cannot be decided.")
        _apply_decision(
            application=application,
            decision=SellerReviewDecision.Decision.REQUEST_CHANGES,
            reason=reason,
            context=context,
        )


def approve_seller_application(*, application_id, reason, context):
    _require_review_permission(context)
    reason = _validate_reason(reason)
    with transaction.atomic():
        application = _reviewable_application(application_id, context, lock=True)
        replayed = _replay_decision(
            application,
            SellerReviewDecision.Decision.APPROVE,
            reason,
            context,
        )
        if replayed is not None:
            return replayed
        if application.state != SellerApplication.State.UNDER_REVIEW:
            raise InvalidState("Seller application cannot be decided.")
        return _apply_decision(
            application=application,
            decision=SellerReviewDecision.Decision.APPROVE,
            reason=reason,
            context=context,
        )


def reject_seller_application(*, application_id, reason, context):
    _require_review_permission(context)
    reason = _validate_reason(reason)
    with transaction.atomic():
        application = _reviewable_application(application_id, context, lock=True)
        replayed = _replay_decision(
            application,
            SellerReviewDecision.Decision.REJECT,
            reason,
            context,
        )
        if replayed is not None:
            return
        if application.state != SellerApplication.State.UNDER_REVIEW:
            raise InvalidState("Seller application cannot be decided.")
        _apply_decision(
            application=application,
            decision=SellerReviewDecision.Decision.REJECT,
            reason=reason,
            context=context,
        )


def _replay_decision(application, decision, reason, context):
    """Return an idempotent replay result for the same request id, else None."""
    version_number = application.current_version
    existing = SellerReviewDecision.objects.filter(
        application_id=application.id,
        version_number=version_number,
    ).first()
    if existing is None or existing.request_id != context.request_id:
        return None
    if existing.decision != decision or existing.reason != reason:
        raise InvalidState("Seller application version is already decided.")
    if existing.decision == SellerReviewDecision.Decision.APPROVE:
        return _existing_profile_for(application)
    return True


def _apply_decision(*, application, decision, reason, context):
    version_number = application.current_version
    if version_number == 0:
        raise InvalidState("Seller application cannot be decided.")
    existing = SellerReviewDecision.objects.filter(
        application_id=application.id,
        version_number=version_number,
    ).first()
    if existing is not None:
        raise InvalidState("Seller application version is already decided.")
    try:
        with transaction.atomic():
            SellerReviewDecision.objects.create(
                application=application,
                version_number=version_number,
                decision=decision,
                reason=reason,
                reviewer_id=context.actor_account_id,
                occurred_at=context.now,
                request_id=context.request_id,
            )
    except IntegrityError:
        raise ConcurrentConflict(
            "Seller application version is already decided."
        ) from None
    application.state = (
        SellerApplication.State.APPROVED
        if decision == SellerReviewDecision.Decision.APPROVE
        else SellerApplication.State.REJECTED
        if decision == SellerReviewDecision.Decision.REJECT
        else SellerApplication.State.CHANGES_REQUESTED
    )
    application.reviewer_id = context.actor_account_id
    application.decision = decision.value
    application.reason = reason
    application.save(update_fields=("state", "reviewer_id", "decision", "reason"))
    _audit(
        context=context,
        application=application,
        action="seller_onboarding.application_decided",
        before_state=SellerApplication.State.UNDER_REVIEW,
        before_version=version_number,
    )
    enqueue_outbox_message(
        message_type="seller_onboarding.application_decision",
        format_version=1,
        payload={
            "application_id": str(application.id),
            "decision": decision.value,
        },
        delivery={"recipient": application.contact_email},
        idempotency_key=(
            f"seller_onboarding.application_decision:{application.id}:{version_number}"
        ),
    )
    if decision == SellerReviewDecision.Decision.APPROVE:
        return _create_profile(application, version_number, context)
    return None


def list_seller_review_queue(*, query, context):
    _validate_review_query(query)
    authorize(context=context, permission="seller_application.read")
    applications = SellerApplication.objects.filter(state__in=query.states)
    if query.reviewer_id is not None:
        applications = applications.filter(reviewer_id=query.reviewer_id)
    applications = applications.order_by("id")
    if query.cursor is not None:
        applications = applications.filter(id__gt=query.cursor)
    applications = applications[: query.limit]
    return tuple(_application_view(application) for application in applications)


def _validate_review_query(query):
    if not isinstance(query, SellerReviewQuery):
        _reject("query must be a SellerReviewQuery.")
    if not isinstance(query.states, tuple) or not query.states:
        _reject("query states must be a non-empty tuple.")
    allowed = set(SellerApplication.State.values)
    if not set(query.states).issubset(allowed):
        _reject("query states are invalid.")
    if query.reviewer_id is not None and not isinstance(query.reviewer_id, UUID):
        _reject("query reviewer_id must be a UUID or None.")
    if type(query.limit) is not int or not 1 <= query.limit <= _REVIEW_QUERY_MAX_LIMIT:
        _reject("query limit is invalid.")
    if query.cursor is not None and not isinstance(query.cursor, UUID):
        _reject("query cursor must be a UUID or None.")


def get_seller_application_for_review(*, application_id, context):
    authorize(context=context, permission="seller_application.read")
    application = _reviewable_application(application_id, context)
    versions = SellerApplicationVersion.objects.filter(
        application_id=application.id
    ).order_by("version_number", "id")
    return _application_view(application), tuple(
        _version_view(version) for version in versions
    )


def get_seller_profile_for_owner(*, context):
    _validate_context(context)
    if context.actor_account_id is None:
        raise PermissionDenied("Seller profile is unavailable.")
    try:
        get_account_snapshot(context.actor_account_id)
    except ObjectDoesNotExist:
        raise PermissionDenied("Seller profile is unavailable.") from None
    profile = SellerProfile.objects.filter(
        owner_id=context.actor_account_id
    ).first()
    return None if profile is None else _profile_view(profile)


def query_seller_profiles(*, query, context):
    _require_profile_read_permission(context)
    if not isinstance(query, SellerProfileQuery):
        _reject("query must be a SellerProfileQuery.")
    if query.state is not None and query.state not in SellerProfile.State.values:
        _reject("query state is invalid.")
    if query.owner_id is not None and not isinstance(query.owner_id, UUID):
        _reject("query owner_id must be a UUID or None.")
    if type(query.limit) is not int or not 1 <= query.limit <= _PROFILE_QUERY_MAX_LIMIT:
        _reject("query limit is invalid.")
    if query.cursor is not None and not isinstance(query.cursor, UUID):
        _reject("query cursor must be a UUID or None.")
    profiles = SellerProfile.objects.all()
    if query.state is not None:
        profiles = profiles.filter(state=query.state)
    if query.owner_id is not None:
        profiles = profiles.filter(owner_id=query.owner_id)
    if query.cursor is not None:
        profiles = profiles.filter(id__gt=query.cursor)
    profiles = profiles.order_by("id")[: query.limit]
    return tuple(_profile_view(profile) for profile in profiles)


def _owned_profile(seller_id, context, *, lock=False):
    _validate_seller_id(seller_id)
    queryset = SellerProfile.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        profile = queryset.get(pk=seller_id)
    except SellerProfile.DoesNotExist:
        raise PermissionDenied("Seller profile is unavailable.") from None
    if profile.owner_id != context.actor_account_id:
        raise PermissionDenied("Seller profile is unavailable.")
    return profile


def activate_seller_after_totp(*, seller_id, context):
    with transaction.atomic():
        owner = _require_ordinary_account(context)
        if context.session_id is None:
            raise PermissionDenied("Seller profile is unavailable.")
        try:
            require_live_session_security_snapshot(
                session_id=context.session_id,
                account_id=owner.id,
                now=context.now,
            )
        except AuthenticationDenied:
            raise PermissionDenied("Seller profile is unavailable.") from None
        if not owner.totp_enabled:
            raise InvalidState("Owner TOTP is not enabled.")
        profile = _owned_profile(seller_id, context, lock=True)
        if profile.state != SellerProfile.State.AWAITING_OWNER_TOTP:
            raise InvalidState("Seller profile cannot be activated.")
        before_state = profile.state
        profile.state = SellerProfile.State.ACTIVE
        profile.updated_at = context.now
        profile.save(update_fields=("state", "updated_at"))
        _audit_profile(
            context=context,
            profile=profile,
            action="seller_onboarding.seller_profile_activated",
            before_state=before_state,
        )
        enqueue_outbox_message(
            message_type="seller_onboarding.admission_change",
            format_version=1,
            payload={"seller_id": str(profile.id), "state": profile.state},
            delivery=None,
            idempotency_key=f"seller_onboarding.admission_change:{profile.id}:activated",
        )



def _change_admission(*, seller_id, reason, context, transition, permission, action):
    authorize(context=context, permission=permission)
    reason = _validate_reason(reason)
    with transaction.atomic():
        profile = _profile_for_admin(seller_id, context, lock=True)
        if profile.state not in transition["from"]:
            raise InvalidState("Seller profile cannot change admission.")
        before_state = profile.state
        profile.state = transition["to"]
        profile.restriction_reason = (
            None if profile.state == SellerProfile.State.ACTIVE else reason
        )
        profile.updated_at = context.now
        profile.save(update_fields=("state", "restriction_reason", "updated_at"))
        _audit_profile(
            context=context,
            profile=profile,
            action=action,
            before_state=before_state,
            reason=reason,
        )
        enqueue_outbox_message(
            message_type="seller_onboarding.admission_change",
            format_version=1,
            payload={"seller_id": str(profile.id), "state": profile.state},
            delivery=None,
            idempotency_key=(
                f"seller_onboarding.admission_change:{profile.id}:{profile.state}:"
                f"{context.request_id}"
            ),
        )
        if transition["to"] == SellerProfile.State.REVOKED:
            remove_totp_requirement(
                account_id=profile.owner_id,
                source_type="seller_profile",
                source_id=profile.id,
                context=context,
            )



def _profile_for_admin(seller_id, context, *, lock=False):
    _validate_seller_id(seller_id)
    queryset = SellerProfile.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=seller_id)
    except SellerProfile.DoesNotExist:
        raise PermissionDenied("Seller profile is unavailable.") from None


def suspend_seller(*, seller_id, reason, context):
    _change_admission(
        seller_id=seller_id,
        reason=reason,
        context=context,
        transition={"from": (SellerProfile.State.ACTIVE,), "to": SellerProfile.State.SUSPENDED},
        permission="seller.suspend",
        action="seller_onboarding.seller_profile_suspended",
    )


def restore_seller(*, seller_id, reason, context):
    _change_admission(
        seller_id=seller_id,
        reason=reason,
        context=context,
        transition={"from": (SellerProfile.State.SUSPENDED,), "to": SellerProfile.State.ACTIVE},
        permission="seller.restore",
        action="seller_onboarding.seller_profile_restored",
    )


def revoke_seller(*, seller_id, reason, context):
    _change_admission(
        seller_id=seller_id,
        reason=reason,
        context=context,
        transition={
            "from": (
                SellerProfile.State.ACTIVE,
                SellerProfile.State.SUSPENDED,
                SellerProfile.State.AWAITING_OWNER_TOTP,
            ),
            "to": SellerProfile.State.REVOKED,
        },
        permission="seller.revoke",
        action="seller_onboarding.seller_profile_revoked",
    )
