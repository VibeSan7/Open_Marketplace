from open_marketplace.identity.application import (
    authenticate_account,
    change_password,
    get_session_security_snapshot,
    list_sessions,
    log_out_session,
    register_account,
    request_password_reset,
    reset_password,
    revoke_other_sessions,
    revoke_session,
    revoke_sessions_for_security_event,
    verify_email,
)
from open_marketplace.identity.domain import (
    AccountId,
    AccountSnapshot,
    AuthenticationResult,
    NeutralAccepted,
    SessionRevocationReason,
    SessionSecuritySnapshot,
    SessionView,
)
from open_marketplace.identity.models import Account


def get_account_snapshot(account_id: AccountId) -> AccountSnapshot:
    account = Account.objects.get(pk=account_id)
    return AccountSnapshot(
        id=account.id,
        email=account.email,
        kind=account.kind,
        state=account.state,
        email_verified_at=account.email_verified_at,
        totp_enabled=False,
    )


__all__ = (
    "AccountSnapshot",
    "AuthenticationResult",
    "NeutralAccepted",
    "SessionRevocationReason",
    "SessionSecuritySnapshot",
    "SessionView",
    "authenticate_account",
    "change_password",
    "get_account_snapshot",
    "get_session_security_snapshot",
    "list_sessions",
    "log_out_session",
    "register_account",
    "request_password_reset",
    "reset_password",
    "revoke_other_sessions",
    "revoke_session",
    "revoke_sessions_for_security_event",
    "verify_email",
)
