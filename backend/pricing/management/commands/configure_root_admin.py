"""Keep one named system-owner superuser and preserve remaining admin accounts."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pricing.models import AuditEvent
from pricing.permissions import ADMIN_GROUP, VIEWER_GROUP


class Command(BaseCommand):
    help = "Configure one protected Root Admin and convert other superusers to Admin."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True,
                            help="Existing active account to keep as the protected Root Admin.")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        try:
            root = User.objects.select_for_update().get(username=options["username"], is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError("The selected active Root Admin account does not exist.") from exc
        if not root.is_superuser:
            raise CommandError("The selected Root Admin account must already be a superuser.")

        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
        viewer_group = Group.objects.filter(name=VIEWER_GROUP).first()
        if viewer_group:
            root.groups.remove(viewer_group)
        root.is_staff = True
        root.save(update_fields=["is_staff"])

        converted = 0
        for user in User.objects.select_for_update().filter(is_superuser=True).exclude(pk=root.pk):
            user.is_superuser = False
            user.is_staff = True
            user.save(update_fields=["is_superuser", "is_staff"])
            user.groups.remove(*([viewer_group] if viewer_group else []))
            user.groups.add(admin_group)
            converted += 1

        AuditEvent.objects.create(
            actor=root, action="root_admin_configured", entity_type="user",
            entity_id=str(root.pk), details={"other_superusers_converted": converted},
        )
        self.stdout.write(f"Protected Root Admin configured; converted {converted} other superuser(s) to Admin.")
