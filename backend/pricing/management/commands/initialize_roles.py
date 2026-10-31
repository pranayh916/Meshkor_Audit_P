from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.core.management.base import BaseCommand

from pricing.permissions import ADMIN_GROUP, VIEWER_GROUP


class Command(BaseCommand):
    help = "Create the application's built-in authorization groups."

    def handle(self, *args, **options):
        for name in (ADMIN_GROUP, VIEWER_GROUP):
            _, created = Group.objects.get_or_create(name=name)
            self.stdout.write(f"{'Created' if created else 'Ready'} role: {name}")
        admin_group = Group.objects.get(name=ADMIN_GROUP)
        user_ct = ContentType.objects.get_for_model(get_user_model())
        group_ct = ContentType.objects.get_for_model(Group)
        admin_permissions = Permission.objects.filter(
            Q(content_type=user_ct, codename__in=("add_user", "change_user", "view_user"))
            | Q(content_type=group_ct, codename__in=("add_group", "change_group", "view_group"))
        )
        admin_group.permissions.add(*admin_permissions)
        self.stdout.write("Admin role can manage users and application role groups.")
