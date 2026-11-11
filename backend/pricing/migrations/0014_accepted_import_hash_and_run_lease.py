from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("pricing", "0013_auththrottlebucket_authchallenge")]

    operations = [
        migrations.RemoveConstraint(
            model_name="claimssummaryimport",
            name="summary_import_plan_hash_unique",
        ),
        migrations.AddConstraint(
            model_name="claimssummaryimport",
            constraint=models.UniqueConstraint(
                fields=("plan", "file_hash"), condition=models.Q(import_status="accepted"),
                name="summary_import_plan_hash_unique",
            ),
        ),
        migrations.AddField(
            model_name="planauditrun", name="worker_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="planauditrun", name="heartbeat_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="planauditrun",
            constraint=models.UniqueConstraint(
                fields=("plan_audit",), condition=models.Q(calculation_status="running"),
                name="plan_audit_one_running_run_unique",
            ),
        ),
    ]
