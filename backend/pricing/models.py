from django.conf import settings
from django.core.exceptions import ValidationError
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
    built_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="built_reports")
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
    clinical_reviewer_name = models.CharField(max_length=160, blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                 related_name="drug_unit_reviews")
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["hcpcs"]
        constraints = [models.UniqueConstraint(fields=["hcpcs", "scope_source_sha256"],
                                                name="drug_unit_review_scope_unique")]


class AdminOTPDevice(models.Model):
    """Encrypted authenticator-app TOTP enrollment for application accounts."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="admin_otp_device")
    secret = models.CharField(max_length=256)
    enabled = models.BooleanField(default=False)
    last_used_step = models.BigIntegerField(default=-1)
    recovery_code_hashes = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuthThrottleBucket(models.Model):
    """Database-backed authentication failure bucket shared by all workers."""
    key = models.CharField(max_length=64, unique=True)
    failure_count = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["updated_at"], name="auth_throttle_updated_ix")]


class AuthChallenge(models.Model):
    PURPOSES = [("login", "Login"), ("enroll", "Authenticator enrollment")]
    token_sha256 = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="auth_challenges")
    purpose = models.CharField(max_length=16, choices=PURPOSES)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "expires_at"], name="auth_challenge_user_ix")]


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

class PlanOrganization(models.Model):
    ORGANIZATION_TYPES = [("employer", "Employer"), ("tpa", "TPA")]
    STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]

    organization_name = models.CharField(max_length=200, unique=True)
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_TYPES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["organization_name"]

    def __str__(self):
        return self.organization_name


class Plan(models.Model):
    STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]

    organization = models.ForeignKey(PlanOrganization, on_delete=models.PROTECT, related_name="plans")
    plan_name = models.CharField(max_length=200)
    payer_reference = models.CharField(max_length=120, blank=True)
    plan_reference = models.CharField(max_length=120)
    effective_start = models.DateField(null=True, blank=True)
    effective_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["organization__organization_name", "plan_name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "plan_reference"], name="plan_org_reference_unique"),
            models.CheckConstraint(
                condition=models.Q(effective_end__isnull=True) |
                          models.Q(effective_start__isnull=True) |
                          models.Q(effective_end__gte=models.F("effective_start")),
                name="plan_effective_dates_ordered",
            ),
        ]

    def __str__(self):
        return f"{self.organization}: {self.plan_name}"


class ClaimsSummaryImport(models.Model):
    STATUSES = [("accepted", "Accepted"), ("rejected", "Rejected")]

    organization = models.ForeignKey(PlanOrganization, on_delete=models.PROTECT, related_name="summary_imports")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="summary_imports")
    source_file_name = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, db_index=True)
    schema_version = models.CharField(max_length=32)
    imported_at = models.DateTimeField(auto_now_add=True, db_index=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                    related_name="claims_summary_imports")
    import_status = models.CharField(max_length=16, choices=STATUSES, db_index=True)
    row_count = models.PositiveIntegerField(default=0)
    validation_summary = models.JSONField(default=dict, blank=True)
    source_period = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-imported_at"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "file_hash"], condition=models.Q(import_status="accepted"), name="summary_import_plan_hash_unique"),
        ]

    def __str__(self):
        return f"{self.plan.plan_name}: {self.source_file_name}"


class ClaimsSummaryRecord(models.Model):
    """Approved aggregate only. Raw claims and member identifiers are never stored here."""
    MEMBER_BANDS = [("11-50", "11-50"), ("51-100", "51-100"), ("100+", "100+")]

    summary_import = models.ForeignKey(ClaimsSummaryImport, on_delete=models.CASCADE,
                                       related_name="records")
    plan_reference = models.CharField(max_length=120)
    hcpcs_code = models.CharField(max_length=5, db_index=True)
    site_npi = models.CharField(max_length=10, db_index=True)
    quarter = models.CharField(max_length=6, db_index=True)
    service_setting = models.CharField(max_length=80, blank=True)
    total_units = models.DecimalField(max_digits=24, decimal_places=6)
    total_allowed_amount = models.DecimalField(max_digits=24, decimal_places=6)
    total_paid_amount = models.DecimalField(max_digits=24, decimal_places=6)
    member_count_band = models.CharField(max_length=8, choices=MEMBER_BANDS)
    source_period = models.CharField(max_length=64)
    extraction_timestamp = models.DateTimeField()
    schema_version = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["quarter", "hcpcs_code", "site_npi", "service_setting"]
        constraints = [
            models.UniqueConstraint(fields=["summary_import", "hcpcs_code", "site_npi", "quarter",
                                            "service_setting"], name="summary_import_group_unique"),
            models.CheckConstraint(condition=models.Q(total_units__gt=0), name="summary_units_positive"),
            models.CheckConstraint(condition=models.Q(total_allowed_amount__gte=0),
                                   name="summary_allowed_nonnegative"),
            models.CheckConstraint(condition=models.Q(total_paid_amount__gte=0),
                                   name="summary_paid_nonnegative"),
        ]
        indexes = [
            models.Index(fields=["summary_import", "quarter", "hcpcs_code"], name="summary_import_code_q_ix"),
        ]


class NetworkRosterEntry(models.Model):
    NETWORK_STATUSES = [("in_network", "In network"), ("out_of_network", "Out of network")]

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="network_roster")
    provider_npi = models.CharField(max_length=10, db_index=True)
    provider_name = models.CharField(max_length=200, blank=True)
    network_name = models.CharField(max_length=160)
    network_status = models.CharField(max_length=20, choices=NETWORK_STATUSES)
    effective_start = models.DateField()
    effective_end = models.DateField(null=True, blank=True)
    service_location = models.CharField(max_length=240, blank=True)
    source_file_name = models.CharField(max_length=255)
    source_hash = models.CharField(max_length=64)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider_npi", "effective_start"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "provider_npi", "network_name",
                                            "effective_start", "service_location"],
                                    name="network_entry_period_unique"),
            models.CheckConstraint(condition=models.Q(effective_end__isnull=True) |
                                   models.Q(effective_end__gte=models.F("effective_start")),
                                   name="network_effective_dates_ordered"),
        ]
        indexes = [models.Index(fields=["plan", "provider_npi", "network_status"],
                                name="network_plan_npi_status_ix")]


class PlanAudit(models.Model):
    STATUSES = [("draft", "Draft"), ("running", "Running"), ("completed", "Completed"),
                ("needs_review", "Needs review"), ("failed", "Failed")]

    organization = models.ForeignKey(PlanOrganization, on_delete=models.PROTECT, related_name="plan_audits")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="audits")
    summary_import = models.ForeignKey(ClaimsSummaryImport, on_delete=models.PROTECT,
                                       related_name="audits")
    audit_name = models.CharField(max_length=200)
    reporting_period = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=STATUSES, default="draft", db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                   related_name="plan_audits_created")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    report_generated_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    current_version = models.PositiveIntegerField(default=0)
    published_version = models.PositiveIntegerField(null=True, blank=True)
    run_owner_token = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "plan", "status"],
                                name="audit_org_plan_status_ix")]


class PlanAuditRun(models.Model):
    CALCULATION_STATUSES = [
        ("running", "Running"), ("completed", "Completed"),
        ("failed", "Failed"), ("legacy_unverified", "Legacy unverified"),
    ]
    PUBLICATION_STATUSES = [
        ("pending", "Pending approval"), ("published", "Published"),
        ("rejected", "Rejected"), ("revoked", "Revoked"),
        ("unverified", "Legacy unverified"), ("failed", "Calculation failed"),
    ]

    plan_audit = models.ForeignKey(PlanAudit, on_delete=models.PROTECT, related_name="runs")
    version = models.PositiveIntegerField()
    calculation_status = models.CharField(max_length=24, choices=CALCULATION_STATUSES)
    publication_status = models.CharField(max_length=16, choices=PUBLICATION_STATUSES, default="pending")
    summary_import = models.ForeignKey(ClaimsSummaryImport, on_delete=models.PROTECT,
                                      related_name="audit_runs")
    source_sha256 = models.CharField(max_length=64, blank=True)
    reference_fingerprints = models.JSONField(default=dict, blank=True)
    calculation_fingerprint = models.CharField(max_length=64, blank=True)
    result_fingerprint = models.CharField(max_length=64, blank=True)
    report_fingerprint = models.CharField(max_length=64, blank=True)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                     related_name="plan_audit_runs_initiated")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="plan_audit_runs_approved")
    review_status = models.CharField(max_length=16, default="pending")
    approved_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField()
    worker_id = models.CharField(max_length=64, blank=True, db_index=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["plan_audit", "version"],
                                                name="plan_audit_run_version_unique"),
                       models.UniqueConstraint(fields=["plan_audit"], condition=models.Q(calculation_status="running"),
                                               name="plan_audit_one_running_run_unique")]


class PlanAuditArtifact(models.Model):
    ARTIFACT_TYPES = [("pdf", "PDF report"), ("csv", "Results CSV")]

    audit_run = models.ForeignKey(PlanAuditRun, on_delete=models.PROTECT, related_name="artifacts")
    artifact_type = models.CharField(max_length=8, choices=ARTIFACT_TYPES)
    content = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["audit_run", "artifact_type"],
                                                name="plan_audit_run_artifact_unique")]


class ImmutableAuditRunQuerySet(models.QuerySet):
    """Permit result writes only while the owning calculation is running."""

    def _assert_run_is_writable(self):
        if self.exclude(audit_run__calculation_status="running").exists():
            raise ValidationError("Audit run results are immutable after calculation completes.")

    def update(self, **kwargs):
        self._assert_run_is_writable()
        return super().update(**kwargs)

    def delete(self):
        self._assert_run_is_writable()
        return super().delete()

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        if not objs:
            return super().bulk_create(objs, **kwargs)
        run_ids = {obj.audit_run_id for obj in objs}
        if (None in run_ids or not run_ids
                or PlanAuditRun.objects.filter(
                    pk__in=run_ids, calculation_status="running").count() != len(run_ids)):
            raise ValidationError("Results may only be created for an active audit run.")
        return super().bulk_create(objs, **kwargs)


class ImmutableAuditRunManager(models.Manager.from_queryset(ImmutableAuditRunQuerySet)):
    pass


class ImmutableAuditRunRow(models.Model):
    """Instance-level guard paired with the queryset guard for result snapshots."""

    objects = ImmutableAuditRunManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not PlanAuditRun.objects.filter(
                pk=self.audit_run_id, calculation_status="running").exists():
            raise ValidationError("Audit run results may only be saved while calculation is running.")
        if self.pk:
            prior_run_id = type(self)._base_manager.filter(pk=self.pk).values_list(
                "audit_run_id", flat=True).first()
            if prior_run_id and not PlanAuditRun.objects.filter(
                    pk=prior_run_id, calculation_status="running").exists():
                raise ValidationError("Completed audit run results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        prior_run_id = type(self)._base_manager.filter(pk=self.pk).values_list(
            "audit_run_id", flat=True).first() if self.pk else self.audit_run_id
        if (not PlanAuditRun.objects.filter(
                pk=self.audit_run_id, calculation_status="running").exists()
                or (prior_run_id and not PlanAuditRun.objects.filter(
                    pk=prior_run_id, calculation_status="running").exists())):
            raise ValidationError("Completed audit run results cannot be deleted.")
        return super().delete(*args, **kwargs)


class PlanAuditResult(ImmutableAuditRunRow):
    """Reproducible comparison outputs derived from approved summary and reference data."""
    plan_audit = models.ForeignKey(PlanAudit, on_delete=models.CASCADE, related_name="results")
    audit_run = models.ForeignKey(PlanAuditRun, on_delete=models.PROTECT,
                                  related_name="results")
    summary_record = models.ForeignKey(ClaimsSummaryRecord, on_delete=models.PROTECT,
                                       related_name="audit_results")
    hcpcs_code = models.CharField(max_length=5, db_index=True)
    drug_description = models.CharField(max_length=240, blank=True)
    site_npi = models.CharField(max_length=10, db_index=True)
    quarter = models.CharField(max_length=6, db_index=True)
    service_setting = models.CharField(max_length=80, blank=True)
    total_units = models.DecimalField(max_digits=24, decimal_places=6)
    total_allowed_amount = models.DecimalField(max_digits=24, decimal_places=6)
    total_paid_amount = models.DecimalField(max_digits=24, decimal_places=6)
    member_count_band = models.CharField(max_length=8, choices=ClaimsSummaryRecord.MEMBER_BANDS)
    plan_allowed_price_per_unit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    plan_paid_price_per_unit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    hospital_price_per_unit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    asp_payment_limit = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    hospital_markup_multiple = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    allowed_markup_multiple = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    paid_markup_multiple = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    plan_to_hospital_price_multiple = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    network_status = models.CharField(max_length=32, default="NETWORK_STATUS_UNKNOWN")
    data_quality_status = models.CharField(max_length=32, db_index=True)
    data_quality_notes = models.JSONField(default=list, blank=True)
    source_references = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["quarter", "hcpcs_code", "site_npi"]
        constraints = [models.UniqueConstraint(
            fields=["audit_run", "hcpcs_code", "site_npi", "quarter", "service_setting"],
            name="plan_audit_result_run_group_unique",
        )]
        indexes = [models.Index(fields=["plan_audit", "data_quality_status"],
                                name="audit_result_quality_ix")]


class SavingsOpportunity(ImmutableAuditRunRow):
    NETWORK_STATUSES = [("IN_NETWORK", "In network"), ("OUT_OF_NETWORK", "Out of network"),
                        ("NETWORK_STATUS_UNKNOWN", "Network status unknown"),
                        ("NETWORK_DATA_EXPIRED", "Network data expired")]
    VALIDATION_STATUSES = [("pending", "Pending validation"), ("validated", "Validated"),
                           ("not_actionable", "Not actionable")]

    plan_audit = models.ForeignKey(PlanAudit, on_delete=models.CASCADE, related_name="savings_opportunities")
    audit_run = models.ForeignKey(PlanAuditRun, on_delete=models.PROTECT,
                                  related_name="savings_opportunities")
    hcpcs_code = models.CharField(max_length=5, db_index=True)
    quarter = models.CharField(max_length=6)
    service_setting = models.CharField(max_length=80, blank=True)
    current_site_npi = models.CharField(max_length=10)
    alternative_site_npi = models.CharField(max_length=10)
    current_allowed_price_per_unit = models.DecimalField(max_digits=24, decimal_places=8)
    alternative_allowed_price_per_unit = models.DecimalField(max_digits=24, decimal_places=8)
    units = models.DecimalField(max_digits=24, decimal_places=6)
    potential_allowed_savings = models.DecimalField(max_digits=24, decimal_places=6)
    potential_paid_difference = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    network_status = models.CharField(max_length=32, choices=NETWORK_STATUSES)
    clinical_review_status = models.CharField(max_length=32, default="pending")
    validation_status = models.CharField(max_length=24, choices=VALIDATION_STATUSES, default="pending")
    source_references = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-potential_allowed_savings"]
        constraints = [
            models.UniqueConstraint(fields=["audit_run", "hcpcs_code", "quarter", "service_setting",
                                            "current_site_npi", "alternative_site_npi"],
                                    name="savings_run_opportunity_unique"),
            models.CheckConstraint(condition=models.Q(potential_allowed_savings__gte=0),
                                   name="savings_nonnegative"),
        ]


class AuditReview(models.Model):
    STATUSES = [("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected")]

    plan_audit = models.ForeignKey(PlanAudit, on_delete=models.CASCADE, related_name="reviews")
    audit_run = models.ForeignKey(PlanAuditRun, on_delete=models.PROTECT,
                                  related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                 related_name="plan_audit_reviews")
    review_status = models.CharField(max_length=16, choices=STATUSES, default="submitted")
    comments = models.CharField(max_length=2000, blank=True)
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-reviewed_at", "-pk"]

class PlanOrganizationAccess(models.Model):
    """Explicit organization boundary for Viewer access to client aggregates."""
    organization = models.ForeignKey(PlanOrganization, on_delete=models.CASCADE, related_name="user_access")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plan_organization_access")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                   related_name="plan_organization_access_granted")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["organization__organization_name", "user__username"]
        constraints = [models.UniqueConstraint(fields=["organization", "user"],
                                                name="plan_org_user_access_unique")]


class ClaimsExplorerDataset(models.Model):
    DATASET_IDENTIFIERS = [
        ("desynpuf_outpatient_claims_sample_1", "DE-SynPUF outpatient sample 1"),
        ("desynpuf_inpatient_claims_sample_1", "DE-SynPUF inpatient sample 1"),
        ("synthea_sample_data", "Synthea Synthetic EHR & Claims Demo"),
    ]
    CATEGORIES = [
        ("desynpuf", "CMS DE-SynPUF Synthetic Claims"),
        ("synthetic_demo", "Synthea Synthetic EHR & Claims Demo"),
    ]

    organization = models.ForeignKey(
        PlanOrganization, on_delete=models.CASCADE, related_name="claims_explorer_datasets"
    )
    dataset_identifier = models.CharField(max_length=80, choices=DATASET_IDENTIFIERS)
    category = models.CharField(max_length=40, choices=CATEGORIES, default="desynpuf")
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="claims_explorer_datasets_registered",
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.dataset_identifier == "synthea_sample_data":
            self.category = "synthetic_demo"
        elif not self.category:
            self.category = "desynpuf"
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["dataset_identifier"]
        constraints = [models.UniqueConstraint(
            fields=["organization", "dataset_identifier"],
            name="claims_explorer_org_dataset_unique",
        )]


class BrokerEvaluation(models.Model):
    """Evaluation record for Phase 1 market report by a genuine broker or TPA.

    Commercial prerequisite for Phase 4: Must document 3 genuine evaluations
    with attributable feedback or evidence before commercial pilot launch.
    """
    STATUS_CHOICES = [
        ("not_contacted", "Not contacted"),
        ("contacted", "Contacted"),
        ("meeting_scheduled", "Meeting scheduled"),
        ("report_evaluated", "Report evaluated"),
        ("feedback_received", "Feedback received"),
        ("pilot_interested", "Pilot interested"),
        ("not_interested", "Not interested"),
    ]
    VERIFIED_STATUSES = frozenset(["report_evaluated", "feedback_received", "pilot_interested"])

    organization_name = models.CharField(max_length=200, db_index=True)
    contact_reference = models.CharField(max_length=200, blank=True)
    report_version = models.CharField(max_length=120, blank=True)
    evaluation_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="not_contacted", db_index=True)
    feedback = models.TextField(blank=True)
    pilot_interest = models.BooleanField(default=False)
    next_action = models.CharField(max_length=500, blank=True)
    evidence_reference = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="broker_evaluations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def is_verified_evaluation(self) -> bool:
        """A record counts toward the 3-evaluation requirement only when there is genuine

        evaluation, attributable feedback or equivalent documented evidence.
        Scheduling a meeting or contacting does not count.
        """
        return (
            self.status in self.VERIFIED_STATUSES
            and self.evaluation_date is not None
            and bool((self.feedback or "").strip() or (self.evidence_reference or "").strip())
        )

