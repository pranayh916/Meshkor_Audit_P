"""Recreate the configured application database and restore its initial state."""
import os
import secrets
import string

import psycopg
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connections
from psycopg import sql

from pricing.permissions import ADMIN_GROUP, VIEWER_GROUP


def generated_password(length=24):
    alphabet = string.ascii_letters + string.digits + "!@#$%_-"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(ch.islower() for ch in value) and any(ch.isupper() for ch in value)
                and any(ch.isdigit() for ch in value) and any(ch in "!@#$%_-" for ch in value)):
            return value


class Command(BaseCommand):
    help = "Drop and recreate PostgreSQL, then create exactly one Admin and one Viewer account."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="MeshKor")
        parser.add_argument("--viewer-username", default="viewer")
        parser.add_argument("--admin-user", default=os.environ.get("POSTGRES_ADMIN_USER", "postgres"),
                            help="PostgreSQL role with CREATEDB and drop permissions (default: postgres).")

    def handle(self, *args, **options):
        cfg = settings.DATABASES["default"]
        db_name, app_user = cfg["NAME"], cfg["USER"]
        admin_username, viewer_username = options["admin_username"], options["viewer_username"]
        if not db_name or db_name in {"postgres", "template0", "template1"}:
            raise CommandError("Refusing to reset a PostgreSQL maintenance/template database.")
        if admin_username.casefold() == viewer_username.casefold():
            raise CommandError("Admin and Viewer usernames must be different.")

        # Do not destroy the existing DB unless the requested replacement can be created.
        try:
            with psycopg.connect(host=cfg.get("HOST") or "127.0.0.1",
                                 port=cfg.get("PORT") or 5432,
                                 dbname="postgres", user=options["admin_user"],
                                 password=os.environ.get("POSTGRES_ADMIN_PASSWORD") or None,
                                 connect_timeout=5, autocommit=True) as admin:
                with admin.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [app_user])
                    if not cur.fetchone():
                        raise CommandError(f"Configured application role {app_user!r} does not exist.")
                    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name)))
                    cur.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(db_name), sql.Identifier(app_user)))
        except psycopg.Error as exc:
            raise CommandError(
                "PostgreSQL administrator connection or database recreation failed. "
                "Set POSTGRES_ADMIN_USER/POSTGRES_ADMIN_PASSWORD to a role allowed to drop and create databases."
            ) from exc

        for conn in connections.all():
            conn.close()
        call_command("migrate", interactive=False, verbosity=0)
        call_command("initialize_roles", verbosity=0)
        User = get_user_model()
        admin_group = Group.objects.get(name=ADMIN_GROUP)
        viewer_group = Group.objects.get(name=VIEWER_GROUP)
        admin_password, viewer_password = generated_password(), generated_password()
        admin = User.objects.create_user(username=admin_username, password=admin_password,
                                         email="admin@example.invalid", is_active=True)
        admin.groups.add(admin_group)
        viewer = User.objects.create_user(username=viewer_username, password=viewer_password,
                                          email="viewer@example.invalid", is_active=True)
        viewer.groups.add(viewer_group)
        self.stdout.write(self.style.SUCCESS("PostgreSQL was recreated with the application accounts."))
        self.stdout.write(f"Admin username: {admin_username}\nAdmin password: {admin_password}")
        self.stdout.write(f"Viewer username: {viewer_username}\nViewer password: {viewer_password}")
        self.stdout.write("Both accounts must enroll Google Authenticator on first sign-in.")
