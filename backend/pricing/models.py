from django.conf import settings
from django.db import models


class SourceFile(models.Model):
    source_key = models.CharField(max_length=80, db_index=True)
    original_name = models.CharField(max_length=255, blank=True)
    relative_path = models.TextField()
    file_format = models.CharField(max_length=24, blank=True)
    source_url = models.URLField(blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.BigIntegerField(default=0)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    reporting_period = models.CharField(max_length=40, blank=True)
    effective_start = models.DateField(null=True, blank=True)
    effective_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=24, default="catalogued")
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source_key", "relative_path"]
        constraints = [
            models.UniqueConstraint(fields=["relative_path", "sha256"], name="source_path_hash_unique"),
        ]


class ProcessingJob(models.Model):
    job_type = models.CharField(max_length=60, db_index=True)
    status = models.CharField(max_length=24, default="queued", db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="processing_jobs")
    created_at = models.DateTimeField(auto_now_add=True)


class ReportRecord(models.Model):
    report_type = models.CharField(max_length=40, default="ohio_market")
    name = models.CharField(max_length=240)
    status = models.CharField(max_length=24, default="draft", db_index=True)
    output_path = models.TextField(blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    source_hash = models.CharField(max_length=64, blank=True)
    config_hash = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="approved_reports")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-generated_at"]


class DrugUnitReview(models.Model):
    STATUS_CHOICES = [("validated", "Validated"), ("rejected", "Rejected"),
                      ("unit_unresolved", "Unit unresolved")]
    hcpcs = models.CharField(max_length=5, db_index=True)
    scope_source_sha256 = models.CharField(max_length=64, db_index=True)
    billing_qty = models.DecimalField(max_digits=18, decimal_places=6)
    billing_unit = models.CharField(max_length=12)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES)
    notes = models.TextField(blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                 related_name="drug_unit_reviews")
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["hcpcs"]
        constraints = [models.UniqueConstraint(fields=["hcpcs", "scope_source_sha256"],
                                                name="drug_unit_review_scope_unique")]


class AdminOTPDevice(models.Model):
    """Authenticator-app TOTP enrollment for administrator accounts."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="admin_otp_device")
    secret = models.CharField(max_length=256)
    enabled = models.BooleanField(default=False)
    last_used_step = models.BigIntegerField(default=-1)
    recovery_code_hashes = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="audit_events")
    action = models.CharField(max_length=80, db_index=True)
    entity_type = models.CharField(max_length=80, blank=True)
    entity_id = models.CharField(max_length=120, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
