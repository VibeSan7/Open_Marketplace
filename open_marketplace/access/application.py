from datetime import datetime, timedelta
from hashlib import sha256
from re import compile
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, connection, transaction
from django.db.models import Q

from open_marketplace.access.domain import (
    PermissionCode,
    RoleAssignmentView,
    StaffAcceptanceResult,
    StaffAcceptanceSetup,
    StaffInvitationQuery,
    StaffInvitationView,
    StaffRole,
)
from open_marketplace.access.models import (
    RoleAssignment,
    StaffInvitation,
    StaffInvitationAcceptance,
)
from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.crypto import generate_one_time_token, hash_one_time_token
from open_marketplace.common.errors import (
    AuthenticationDenied,
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.public import (
    AccountQuery,
    add_totp_requirement,
    enable_invited_service_totp,
    get_account_snapshot,
    remove_totp_requirement,
    require_live_session_security_snapshot,
    revoke_sessions_for_security_event,
    provision_service_account_for_invitation,
    query_accounts,
)
from open_marketplace.outbox.public import enqueue_outbox_message

ROLE_REASON_MAX_LENGTH = 1024

_PERMISSION_CODES = (
    "seller_application.read",
    "seller_application.review",
    "staff.invite",
    "staff.invitation_revoke",
    "staff.role_revoke",
    "account.read",
    "account.block",
    "account.unblock",
    "identity.mandatory_totp_recover",
    "seller.read",
    "seller.suspend",
    "seller.restore",
    "seller.revoke",
    "audit.read",
    "outbox.manual_retry",
)
_ROLE_ORDER = ("seller_reviewer", "security_admin")
_ROLE_PERMISSIONS = {
    "seller_reviewer": frozenset(
        {
            "seller_application.read",
            "seller_application.review",
            "audit.read",
        }
    ),
    "security_admin": frozenset(
        {
            "staff.invite",
            "staff.invitation_revoke",
            "staff.role_revoke",
            "account.read",
            "account.block",
            "account.unblock",
            "identity.mandatory_totp_recover",
            "seller.read",
            "seller.suspend",
            "seller.restore",
            "seller.revoke",
            "audit.read",
            "outbox.manual_retry",
        }
    ),
}
_SENSITIVE_PERMISSIONS = frozenset(
    {
        "seller_application.review",
        "staff.invite",
        "staff.invitation_revoke",
        "staff.role_revoke",
        "account.block",
        "account.unblock",
        "identity.mandatory_totp_recover",
        "seller.suspend",
        "seller.restore",
        "seller.revoke",
        "outbox.manual_retry",
    }
)
_AUDIT_SCOPES = {
    "seller_reviewer": (
        "audit:object_type:seller_application",
        "audit:object_type:seller_application_version",
        "audit:object_type:seller_review_decision",
    ),
    "security_admin": (
        "audit:object_type:account",
        "audit:object_type:session",
        "audit:object_type:staff_invitation",
        "audit:object_type:role_assignment",
        "audit:object_type:seller_profile",
        "audit:object_type:outbox_message",
    ),
}
_OPERATION_SOURCES = frozenset({"html", "admin", "command", "worker"})
_INVITATION_QUERY_MAX_LIMIT = 100
_INVITATION_STATES = frozenset({"pending", "accepted", "expired", "revoked"})
_TOKEN_PATTERN = compile(r"^[A-Za-z0-9_-]{43}$")


def _acquire_advisory_xact_lock(namespace, *scope_values):
    material = "\x00".join((namespace, *(str(value) for value in scope_values)))
    lock_key = int.from_bytes(
        sha256(material.encode("utf-8")).digest()[:8], byteorder="big", signed=True
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))


def _reject(message):
    raise InputRejected(message)


def _validate_utc(value, *, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        _reject(f"{name} must be a timezone-aware UTC datetime.")


def _validate_context(context):
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    if context.actor_account_id is not None and not isinstance(context.actor_account_id, UUID):
        _reject("context actor_account_id must be a UUID or None.")
    if context.session_id is not None and not isinstance(context.session_id, UUID):
        _reject("context session_id must be a UUID or None.")
    if not isinstance(context.request_id, UUID):
        _reject("context request_id must be a UUID.")
    if context.source not in _OPERATION_SOURCES:
        _reject("context source is invalid.")
    _validate_utc(context.now, name="context.now")


def _validate_permission(permission):
    if not isinstance(permission, str) or permission not in _PERMISSION_CODES:
        _reject("permission is invalid.")


def _validate_uuid(value, *, name, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, UUID):
        _reject(f"{name} must be a UUID.")


def _validated_reason(reason):
    if not isinstance(reason, str):
        _reject("reason must be a string.")
    reason = reason.strip()
    if not 1 <= len(reason) <= ROLE_REASON_MAX_LENGTH:
        _reject("reason is invalid.")
    return reason


def _canonical_invitation_email(email):
    if not isinstance(email, str):
        _reject("email is invalid.")
    value = email.strip()
    try:
        validate_email(value)
    except DjangoValidationError:
        _reject("email is invalid.")
    value = value.casefold()
    if len(value) > 254:
        _reject("email is invalid.")
    return value


def _invitation_state(invitation, now):
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.accepted_at is not None:
        return "accepted"
    if now >= invitation.expires_at:
        return "expired"
    return "pending"


def _validated_invitation_token(raw_token):
    if not isinstance(raw_token, str) or not _TOKEN_PATTERN.fullmatch(raw_token):
        raise AuthenticationDenied("Staff invitation token is invalid.")
    return hash_one_time_token(raw_token)


def _validated_invitation_query(query):
    if not isinstance(query, StaffInvitationQuery):
        _reject("query must be a StaffInvitationQuery.")
    if query.state is not None and query.state not in _INVITATION_STATES:
        _reject("query state is invalid.")
    if query.role is not None and query.role not in RoleAssignment.Role.values:
        _reject("query role is invalid.")
    if type(query.limit) is not int or not 1 <= query.limit <= _INVITATION_QUERY_MAX_LIMIT:
        _reject("query limit is out of range.")
    if query.cursor is not None and not isinstance(query.cursor, UUID):
        _reject("query cursor must be a UUID or None.")
    if query.canonical_email is not None:
        canonical = _canonical_invitation_email(query.canonical_email)
        if canonical != query.canonical_email:
            _reject("query canonical_email is invalid.")


def _invitation_view(invitation, now):
    return StaffInvitationView(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        state=_invitation_state(invitation, now),
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
    )


def list_staff_invitations(
    *, query: StaffInvitationQuery, context: OperationContext
) -> tuple[StaffInvitationView, ...]:
    _validated_invitation_query(query)
    _validate_context(context)
    authorize(context=context, permission="staff.invite")
    queryset = StaffInvitation.objects.all()
    if query.role is not None:
        queryset = queryset.filter(role=query.role)
    if query.canonical_email is not None:
        queryset = queryset.filter(email=query.canonical_email)
    state_predicates = {
        "pending": Q(accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=context.now),
        "accepted": Q(accepted_at__isnull=False),
        "expired": Q(accepted_at__isnull=True, revoked_at__isnull=True, expires_at__lte=context.now),
        "revoked": Q(revoked_at__isnull=False),
    }
    if query.state is not None:
        queryset = queryset.filter(state_predicates[query.state])
    if query.cursor is not None:
        if not queryset.filter(pk=query.cursor).exists():
            _reject("query cursor is not in the authorized result set.")
        queryset = queryset.filter(pk__gt=query.cursor)
    invitations = queryset.order_by("id")[: query.limit]
    return tuple(_invitation_view(invitation, context.now) for invitation in invitations)


def _create_staff_invitation(*, email, role, created_by_id, context):
    role = getattr(role, "value", role)
    raw_token, token_digest = generate_one_time_token()
    invitation = StaffInvitation.objects.create(
        email=email,
        role=role,
        created_by_id=created_by_id,
        token_digest=token_digest,
        created_at=context.now,
        expires_at=context.now + settings.STAFF_INVITATION_TTL,
    )
    append_audit_entry(
        context=context,
        action="access.staff_invitation_created",
        object_type="staff_invitation",
        object_id=str(invitation.id),
        result="succeeded",
        reason="bootstrap" if created_by_id is None else "staff invitation",
        before={},
        after={"role": role, "state": "pending", "expires_at": invitation.expires_at.isoformat()},
        effective_role=None,
    )
    enqueue_outbox_message(
        message_type="access.staff_invitation",
        format_version=1,
        payload={"invitation_id": str(invitation.id), "role": role},
        delivery={
            "recipient": email,
            "absolute_token_url": f"{settings.APP_BASE_URL}/access/staff-invitation/{raw_token}/",
        },
        idempotency_key=f"access.staff_invitation:{invitation.id}",
    )
    return invitation.id


def invite_staff_member(*, email: str, role: StaffRole, context: OperationContext) -> UUID:
    email = _canonical_invitation_email(email)
    if role not in RoleAssignment.Role.values:
        _reject("role is invalid.")
    _validate_context(context)
    with transaction.atomic():
        decision = authorize(context=context, permission="staff.invite")
        _acquire_advisory_xact_lock("access.staff_invitation", email, role)
        accounts = query_accounts(
            query=AccountQuery(
                kind=None,
                state=None,
                canonical_email=email,
                limit=1,
                cursor=None,
            ),
            context=context,
            authorize=authorize,
        )
        if accounts and accounts[0].kind != "service":
            raise InvalidState("Staff invitations cannot target ordinary accounts.")
        if accounts and (accounts[0].state != "active" or accounts[0].email_verified_at is None):
            raise InvalidState("The service account is unavailable.")
        if accounts and RoleAssignment.objects.filter(
            account_id=accounts[0].id,
            role=role,
            state=RoleAssignment.State.ACTIVE,
        ).exists():
            raise InvalidState("The staff role is already active.")
        live = StaffInvitation.objects.filter(
            email=email,
            role=role,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=context.now,
        ).first()
        if live is not None:
            return live.id
        return _create_staff_invitation(
            email=email, role=role, created_by_id=decision.account_id, context=context
        )


def begin_staff_invitation_acceptance(
    *, raw_token: str, password: str, context: OperationContext
) -> StaffAcceptanceSetup:
    token_digest = _validated_invitation_token(raw_token)
    _validate_context(context)
    with transaction.atomic():
        invitation = StaffInvitation.objects.select_for_update().filter(
            token_digest=token_digest
        ).first()
        if invitation is None or _invitation_state(invitation, context.now) != "pending":
            raise AuthenticationDenied("Staff invitation token is invalid.")
        pending = StaffInvitationAcceptance.objects.select_for_update().filter(
            invitation=invitation,
            token_digest=token_digest,
            consumed_at__isnull=True,
            invalidated_at__isnull=True,
        ).first()
        if pending is not None:
            return StaffAcceptanceSetup(
                acceptance_id=pending.id,
                account_id=pending.account_id,
                mode=("new_service_account" if pending.totp_setup_id is not None else "existing_service_account"),
                totp_setup=None,
            )
        account_id, totp_setup = provision_service_account_for_invitation(
            email=invitation.email,
            password=password,
            invitation_id=invitation.id,
            context=context,
        )
        acceptance = StaffInvitationAcceptance.objects.create(
            invitation=invitation,
            token_digest=token_digest,
            account_id=account_id,
            totp_setup_id=totp_setup.setup_id if totp_setup is not None else None,
            created_at=context.now,
        )
        return StaffAcceptanceSetup(
            acceptance_id=acceptance.id,
            account_id=account_id,
            mode=("new_service_account" if totp_setup is not None else "existing_service_account"),
            totp_setup=totp_setup,
        )


def accept_staff_invitation(
    *, acceptance_id: UUID, raw_token: str, totp_code: str, context: OperationContext
) -> StaffAcceptanceResult:
    _validate_uuid(acceptance_id, name="acceptance_id")
    token_digest = _validated_invitation_token(raw_token)
    _validate_context(context)
    with transaction.atomic():
        invitation_id = StaffInvitationAcceptance.objects.filter(
            pk=acceptance_id, token_digest=token_digest
        ).values_list("invitation_id", flat=True).first()
        if invitation_id is None:
            raise AuthenticationDenied("Staff invitation token is invalid.")
        invitation = StaffInvitation.objects.select_for_update().filter(pk=invitation_id).first()
        if invitation is None:
            raise AuthenticationDenied("Staff invitation token is invalid.")
        if _invitation_state(invitation, context.now) != "pending":
            raise AuthenticationDenied("Staff invitation token is invalid.")
        acceptance = StaffInvitationAcceptance.objects.select_for_update().filter(
            pk=acceptance_id,
            invitation_id=invitation.id,
            token_digest=token_digest,
        ).first()
        if acceptance is None:
            raise AuthenticationDenied("Staff invitation token is invalid.")
        if acceptance.consumed_at is not None or acceptance.invalidated_at is not None:
            raise InvalidState("Staff invitation acceptance is unavailable.")
        recovery_codes = enable_invited_service_totp(
            account_id=acceptance.account_id,
            setup_id=acceptance.totp_setup_id,
            code=totp_code,
            invitation_id=invitation.id,
            context=context,
        )
        assignment_id = _activate_staff_role(
            account_id=acceptance.account_id,
            role=invitation.role,
            assigned_by_id=invitation.created_by_id,
            reason="accepted staff invitation",
            context=context,
        )
        acceptance.consumed_at = context.now
        acceptance.save(update_fields={"consumed_at"})
        invitation.accepted_at = context.now
        invitation.save(update_fields={"accepted_at"})
        append_audit_entry(
            context=context,
            action="access.staff_invitation_accepted",
            object_type="staff_invitation",
            object_id=str(invitation.id),
            result="succeeded",
            reason=None,
            before={"state": "pending", "role": invitation.role},
            after={"state": "accepted", "role": invitation.role},
            effective_role=None,
        )
        return StaffAcceptanceResult(
            assignment_id=assignment_id, recovery_codes=tuple(recovery_codes)
        )


def revoke_staff_invitation(
    *, invitation_id: UUID, reason: str, context: OperationContext
) -> None:
    _validate_uuid(invitation_id, name="invitation_id")
    reason = _validated_reason(reason)
    _validate_context(context)
    with transaction.atomic():
        decision = authorize(context=context, permission="staff.invitation_revoke")
        invitation = StaffInvitation.objects.select_for_update().filter(pk=invitation_id).first()
        if invitation is None or _invitation_state(invitation, context.now) != "pending":
            raise InvalidState("Staff invitation is unavailable.")
        invitation.revoked_at = context.now
        invitation.revoked_by_id = decision.account_id
        invitation.revoked_reason = reason
        invitation.save(update_fields={"revoked_at", "revoked_by_id", "revoked_reason"})
        StaffInvitationAcceptance.objects.select_for_update().filter(
            invitation=invitation,
            consumed_at__isnull=True,
            invalidated_at__isnull=True,
        ).update(invalidated_at=context.now)
        append_audit_entry(
            context=context,
            action="access.staff_invitation_revoked",
            object_type="staff_invitation",
            object_id=str(invitation.id),
            result="succeeded",
            reason=reason,
            before={"state": "pending", "role": invitation.role},
            after={"state": "revoked", "role": invitation.role},
            effective_role=decision.effective_roles[0],
        )


def bootstrap_security_admin(*, email: str, context: OperationContext) -> UUID:
    email = _canonical_invitation_email(email)
    _validate_context(context)
    if context.source != "command" or context.actor_account_id is not None or context.session_id is not None:
        _reject("bootstrap must run from an anonymous command context.")
    with transaction.atomic():
        _acquire_advisory_xact_lock("access.staff_invitation.bootstrap")
        active_admin_ids = RoleAssignment.objects.select_for_update().filter(
            role=RoleAssignment.Role.SECURITY_ADMIN,
            state=RoleAssignment.State.ACTIVE,
        ).values_list("account_id", flat=True)
        for account_id in active_admin_ids:
            try:
                account = get_account_snapshot(account_id)
            except ObjectDoesNotExist:
                continue
            if account.kind == "service" and account.state == "active" and account.email_verified_at is not None:
                raise InvalidState("A security administrator already exists.")
        live = StaffInvitation.objects.select_for_update().filter(
            role=RoleAssignment.Role.SECURITY_ADMIN,
            created_by_id__isnull=True,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=context.now,
        ).first()
        if live is not None:
            if live.email == email:
                return live.id
            raise InvalidState("A bootstrap invitation is already pending.")
        return _create_staff_invitation(
            email=email,
            role=RoleAssignment.Role.SECURITY_ADMIN,
            created_by_id=None,
            context=context,
        )


def _deny(*, context, permission):
    object_id = str(context.actor_account_id or context.request_id)
    append_audit_entry(
        context=context,
        action="access.permission_denied",
        object_type="account",
        object_id=object_id,
        result="denied",
        reason="permission_denied",
        before={},
        after={},
        effective_role=None,
    )
    raise PermissionDenied("Permission denied.")


def _scopes_for(permission, granting_roles):
    if permission == "outbox.manual_retry":
        return ("outbox:state:manual_review",)
    if permission != "audit.read":
        return ()
    scopes = []
    for role in granting_roles:
        for scope in _AUDIT_SCOPES[role]:
            if scope not in scopes:
                scopes.append(scope)
    return tuple(scopes)


def authorize(
    *,
    context: OperationContext,
    permission: PermissionCode,
) -> AuthorizationDecision:
    _validate_context(context)
    _validate_permission(permission)
    if context.actor_account_id is None or context.session_id is None:
        _deny(context=context, permission=permission)

    try:
        with transaction.atomic():
            active_roles = set(
                RoleAssignment.objects.select_for_update()
                .filter(
                    account_id=context.actor_account_id,
                    state=RoleAssignment.State.ACTIVE,
                )
                .values_list("role", flat=True)
            )
            account = get_account_snapshot(context.actor_account_id)
            session = require_live_session_security_snapshot(
                session_id=context.session_id,
                account_id=context.actor_account_id,
                now=context.now,
            )
    except (AuthenticationDenied, ObjectDoesNotExist):
        _deny(context=context, permission=permission)

    if (
        account.kind != "service"
        or account.state != "active"
        or account.email_verified_at is None
        or not account.totp_enabled
    ):
        _deny(context=context, permission=permission)

    granting_roles = tuple(
        role
        for role in _ROLE_ORDER
        if role in active_roles and permission in _ROLE_PERMISSIONS[role]
    )
    if not granting_roles:
        _deny(context=context, permission=permission)

    if permission in _SENSITIVE_PERMISSIONS:
        cutoff = context.now - settings.SENSITIVE_ACTION_REAUTH_TTL
        if (
            session.reauthenticated_at is None
            or session.reauthenticated_at <= cutoff
            or session.reauthenticated_at > context.now
        ):
            _deny(context=context, permission=permission)

    return AuthorizationDecision(
        account_id=account.id,
        permission=permission,
        effective_roles=granting_roles,
        scopes=_scopes_for(permission, granting_roles),
        reauthenticated_at=session.reauthenticated_at,
    )


def check_permission(
    *,
    permission: PermissionCode,
    context: OperationContext,
) -> AuthorizationDecision:
    return authorize(context=context, permission=permission)


def _to_view(assignment):
    return RoleAssignmentView(
        id=assignment.id,
        account_id=assignment.account_id,
        role=assignment.role,
        active_from=assignment.active_from,
        revoked_at=assignment.revoked_at,
    )


def list_active_roles(
    *,
    account_id: UUID,
    context: OperationContext,
) -> tuple[RoleAssignmentView, ...]:
    _validate_uuid(account_id, name="account_id")
    authorize(context=context, permission="account.read")
    assignments = RoleAssignment.objects.filter(
        account_id=account_id,
        state=RoleAssignment.State.ACTIVE,
    ).order_by("active_from", "id")
    return tuple(_to_view(assignment) for assignment in assignments)


def _enqueue_role_change(*, account, assignment, transition):
    enqueue_outbox_message(
        message_type="identity.protected_account_change",
        format_version=1,
        payload={"account_id": str(account.id), "change": "role_changed"},
        delivery={"recipient": account.email},
        idempotency_key=f"access.role_changed:{assignment.id}:{transition}",
    )


def _activate_staff_role(
    *,
    account_id: UUID,
    role: StaffRole,
    assigned_by_id: UUID | None,
    reason: str,
    context: OperationContext,
) -> UUID:
    _validate_uuid(account_id, name="account_id")
    _validate_uuid(assigned_by_id, name="assigned_by_id", nullable=True)
    if role not in RoleAssignment.Role.values:
        _reject("role is invalid.")
    reason = _validated_reason(reason)
    _validate_context(context)

    try:
        account = get_account_snapshot(account_id)
    except ObjectDoesNotExist:
        raise InvalidState("Account is unavailable.") from None
    if (
        account.kind != "service"
        or account.state != "active"
        or account.email_verified_at is None
        or not account.totp_enabled
    ):
        raise InvalidState("Account is unavailable for a staff role.")

    with transaction.atomic():
        try:
            with transaction.atomic():
                assignment = RoleAssignment.objects.create(
                    account_id=account.id,
                    role=role,
                    state=RoleAssignment.State.ACTIVE,
                    assigned_by_id=assigned_by_id,
                    assigned_reason=reason,
                    active_from=context.now,
                )
        except IntegrityError:
            raise ConcurrentConflict(
                "An active assignment for this role already exists."
            ) from None
        revoked_session_count = 0
        if context.actor_account_id is not None and context.session_id is not None:
            revoked_session_count = revoke_sessions_for_security_event(
                account_id=account.id,
                reason="role_changed",
                context=context,
            )
        add_totp_requirement(
            account_id=account.id,
            source_type="staff_role",
            source_id=assignment.id,
            context=context,
        )
        append_audit_entry(
            context=context,
            action="access.staff_role_assigned",
            object_type="role_assignment",
            object_id=str(assignment.id),
            result="succeeded",
            reason=reason,
            before={},
            after={
                "role": assignment.role,
                "state": str(assignment.state),
                "requirement_source": "staff_role",
                "revoked_session_count": revoked_session_count,
            },
            effective_role=None,
        )
        _enqueue_role_change(
            account=account,
            assignment=assignment,
            transition="assigned",
        )
        return assignment.id


def revoke_staff_role(
    *,
    assignment_id: UUID,
    reason: str,
    context: OperationContext,
) -> None:
    _validate_uuid(assignment_id, name="assignment_id")
    reason = _validated_reason(reason)
    _validate_context(context)

    with transaction.atomic():
        decision = authorize(context=context, permission="staff.role_revoke")
        assignment = (
            RoleAssignment.objects.select_for_update()
            .filter(pk=assignment_id)
            .first()
        )
        if assignment is None or assignment.state != RoleAssignment.State.ACTIVE:
            raise InvalidState("Role assignment is unavailable.")
        try:
            account = get_account_snapshot(assignment.account_id)
        except ObjectDoesNotExist:
            raise InvalidState("Account is unavailable.") from None

        assignment.state = RoleAssignment.State.REVOKED
        assignment.revoked_by_id = decision.account_id
        assignment.revoked_reason = reason
        assignment.revoked_at = context.now
        assignment.save(
            update_fields={"state", "revoked_by_id", "revoked_reason", "revoked_at"}
        )
        revoked_session_count = revoke_sessions_for_security_event(
            account_id=assignment.account_id,
            reason="role_changed",
            context=context,
        )
        remove_totp_requirement(
            account_id=assignment.account_id,
            source_type="staff_role",
            source_id=assignment.id,
            context=context,
        )
        append_audit_entry(
            context=context,
            action="access.staff_role_revoked",
            object_type="role_assignment",
            object_id=str(assignment.id),
            result="succeeded",
            reason=reason,
            before={"role": assignment.role, "state": "active"},
            after={
                "role": assignment.role,
                "state": str(assignment.state),
                "requirement_source": "staff_role",
                "revoked_session_count": revoked_session_count,
            },
            effective_role=decision.effective_roles[0],
        )
        _enqueue_role_change(
            account=account,
            assignment=assignment,
            transition="revoked",
        )
