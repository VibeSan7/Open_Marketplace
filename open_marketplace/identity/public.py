from open_marketplace.identity.application import (
    add_totp_requirement,
    authenticate_account,
    begin_totp_setup,
    change_password,
    disable_optional_totp,
    enable_totp,
    get_session_security_snapshot,
    require_live_session_security_snapshot,
    list_sessions,
    log_out_session,
    register_account,
    reauthenticate_session,
    remove_totp_requirement,
    replace_recovery_codes,
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
    TotpSetupView,
)
from open_marketplace.identity.models import Account, TotpCredential


def get_account_snapshot(account_id: AccountId) -> AccountSnapshot:
    account = Account.objects.get(pk=account_id)
    return AccountSnapshot(
        id=account.id,
        email=account.email,
        kind=account.kind,
        state=account.state,
        email_verified_at=account.email_verified_at,
        totp_enabled=TotpCredential.objects.filter(
            account=account,
            disabled_at__isnull=True,
        ).exists(),
    )


__all__ = (
    "AccountSnapshot",
    "AuthenticationResult",
    "NeutralAccepted",
    "SessionRevocationReason",
    "SessionSecuritySnapshot",
    "SessionView",
    "TotpSetupView",
    "add_totp_requirement",
    "authenticate_account",
    "begin_totp_setup",
    "change_password",
    "disable_optional_totp",
    "enable_totp",
    "get_account_snapshot",
    "get_session_security_snapshot",
    "require_live_session_security_snapshot",
    "list_sessions",
    "log_out_session",
    "register_account",
    "reauthenticate_session",
    "remove_totp_requirement",
    "replace_recovery_codes",
    "request_password_reset",
    "reset_password",
    "revoke_other_sessions",
    "revoke_session",
    "revoke_sessions_for_security_event",
    "verify_email",
)
