from uuid import uuid4

from django.core.management.base import BaseCommand
from django.utils import timezone

from open_marketplace.access.public import bootstrap_security_admin
from open_marketplace.common.types import OperationContext


class Command(BaseCommand):
    help = "Create the first security-admin staff invitation."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        invitation_id = bootstrap_security_admin(
            email=options["email"],
            context=OperationContext(
                actor_account_id=None,
                session_id=None,
                request_id=uuid4(),
                source="command",
                source_address=None,
                now=timezone.now(),
            ),
        )
        self.stdout.write(f"Security-admin invitation: {invitation_id}")
