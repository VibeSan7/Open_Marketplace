from django.contrib.auth.base_user import BaseUserManager

from open_marketplace.identity.domain import canonicalize_email


class AccountManager(BaseUserManager):
    use_in_migrations = True

    def _create_account(self, email, password, *, kind, **extra_fields):
        account = self.model(
            email=canonicalize_email(email),
            kind=kind,
            **extra_fields,
        )
        account.set_password(password)
        account.save(using=self._db)
        return account

    def create_user(self, email, password=None, **extra_fields):
        return self._create_account(
            email,
            password,
            kind=self.model.Kind.ORDINARY,
            **extra_fields,
        )

    def create_service_account(self, email, password=None, **extra_fields):
        return self._create_account(
            email,
            password,
            kind=self.model.Kind.SERVICE,
            **extra_fields,
        )

    def create_superuser(self, *args, **kwargs):
        raise RuntimeError(
            "Use bootstrap_security_admin instead of create_superuser."
        )
