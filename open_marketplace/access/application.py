from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction

from open_marketplace.access.domain import (
    PermissionCode,
    RoleAssignmentView,
    StaffRole,
)
from open_marketplace.access.models import RoleAssignment
from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.errors import (
    AuthenticationDenied,
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.public import (
    add_totp_requirement,
    get_account_snapshot,
    remove_totp_requirement,
    require_live_session_security_snapshot,
    revoke_sessions_for_security_event,
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
