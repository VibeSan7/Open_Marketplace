from django.core.management.base import BaseCommand, CommandError

from open_marketplace.common.errors import ApplicationError


class Command(BaseCommand):
    help = "Добавить явно учебную публичную витрину без готовых паролей и замены существующих данных."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-demo", action="store_true")

    def handle(self, *args, **options):
        from open_marketplace.verification.demo_storefront import seed_storefront

        try:
            result = seed_storefront(confirmed=options["confirm_demo"])
        except (ApplicationError, OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        status = "already_installed" if result["already_installed"] else "created"
        counts = " ".join(f"{key}={value}" for key, value in sorted(result["counts"].items()))
        self.stdout.write(f"demo_storefront {status} {counts}")
