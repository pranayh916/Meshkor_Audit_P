"""Normalize legacy groups to the two supported application roles.

Legacy Data Analyst accounts are retained as Viewer. This is the least
privileged mapping and avoids silently granting administrator capabilities.
"""
from django.db import migrations


def normalize_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    database = schema_editor.connection.alias
    admin, _ = Group.objects.using(database).get_or_create(name="Admin")
    viewer, _ = Group.objects.using(database).get_or_create(name="Viewer")

    for legacy_name, target in (("Administrator", admin),
                                ("Data Analyst", viewer),
                                ("Report Viewer", viewer)):
        legacy = Group.objects.using(database).filter(name=legacy_name).first()
        if legacy is None:
            continue
        members = list(legacy.user_set.using(database).all())
        target.user_set.add(*members)
        legacy.delete(using=database)


class Migration(migrations.Migration):
    dependencies = [
        ("pricing", "0004_adminotpdevice_recovery_code_hashes_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(normalize_roles, migrations.RunPython.noop),
    ]
