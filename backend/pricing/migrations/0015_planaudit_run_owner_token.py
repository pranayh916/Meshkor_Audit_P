from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("pricing", "0014_accepted_import_hash_and_run_lease")]

    operations = [
        migrations.AddField(
            model_name="planaudit",
            name="run_owner_token",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
