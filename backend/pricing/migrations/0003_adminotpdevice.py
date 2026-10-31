# Generated for administrator authenticator-app OTP enrollment.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pricing", "0002_drugunitreview"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminOTPDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("secret", models.CharField(max_length=64)),
                ("enabled", models.BooleanField(default=False)),
                ("last_used_step", models.BigIntegerField(default=-1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                               related_name="admin_otp_device",
                                               to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
