from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pricing", "0005_two_application_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportrecord",
            name="built_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="built_reports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="drugunitreview",
            name="clinical_reviewer_name",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
