from open_marketplace.identity.domain import AccountId, AccountSnapshot
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
