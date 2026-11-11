"""Plan-specific audit APIs, mounted under both /api/v1/ and /api/."""
from django.urls import path

from . import plan_audit_imports as imports
from . import plan_audit_reports as reports
from . import plan_audit_run as run
from . import plan_audit_setup as setup


urlpatterns = [
    path("organizations/", setup.organizations, name="plan_audit_organizations"),
    path("organizations/<int:organization_id>/status/", setup.organization_status,
         name="plan_audit_organization_status"),
    path("organizations/<int:organization_id>/users/", setup.organization_access,
         name="plan_audit_organization_user_access"),
    path("organizations/<int:organization_id>/users/<int:user_id>/",
         setup.organization_access_detail, name="plan_audit_organization_user_access_detail"),
    path("plans/", setup.plans, name="plan_audit_plans"),
    path("plans/<int:plan_id>/", setup.plan_detail, name="plan_audit_plan_detail"),
    path("plans/<int:plan_id>/network-roster/", setup.plan_network_roster,
         name="plan_audit_network_roster"),
    path("plan-audits/import-summary/", imports.import_plan_summary,
         name="plan_audit_summary_import"),
    path("plan-audits/imports/", imports.plan_summary_imports, name="plan_audit_summary_imports"),
    path("plan-audits/imports/<int:import_id>/", imports.plan_summary_import_detail,
         name="plan_audit_summary_import_detail"),
    path("plan-audits/imports/<int:import_id>/quality/", imports.plan_summary_import_quality,
         name="plan_audit_summary_import_quality"),
    path("plan-audits/create/", imports.create_plan_audit, name="plan_audit_create"),
    path("plan-audits/", imports.plan_audits, name="plan_audits"),
    path("plan-audits/<int:audit_id>/", imports.plan_audit_detail, name="plan_audit_detail"),
    path("plan-audits/<int:audit_id>/run/", run.run_audit, name="plan_audit_run"),
    path("plan-audits/<int:audit_id>/overview/", run.audit_overview, name="plan_audit_overview"),
    path("plan-audits/<int:audit_id>/results/", run.audit_results, name="plan_audit_results"),
    path("plan-audits/<int:audit_id>/historical-spending/", run.historical_spending,
         name="plan_audit_historical_spending"),
    path("plan-audits/<int:audit_id>/drug-analysis/", run.drug_analysis, name="plan_audit_drug_analysis"),
    path("plan-audits/<int:audit_id>/hospital-comparison/", run.hospital_comparison,
         name="plan_audit_hospital_comparison"),
    path("plan-audits/<int:audit_id>/asp-benchmark/", run.asp_benchmark, name="plan_audit_asp_benchmark"),
    path("plan-audits/<int:audit_id>/savings/", reports.audit_savings, name="plan_audit_savings"),
    path("plan-audits/<int:audit_id>/network-validation/", reports.audit_network_validation,
         name="plan_audit_network_validation"),
    path("plan-audits/<int:audit_id>/quality/", reports.audit_quality, name="plan_audit_quality"),
    path("plan-audits/<int:audit_id>/generate-report/", reports.generate_plan_report,
         name="plan_audit_generate_report"),
    path("plan-audits/<int:audit_id>/report/", reports.plan_report, name="plan_audit_report"),
    path("plan-audits/<int:audit_id>/export-csv/", reports.export_plan_csv,
         name="plan_audit_export_csv"),
    path("plan-audits/<int:audit_id>/review/", reports.audit_review, name="plan_audit_review"),
    path("plan-audits/<int:audit_id>/submit-review/", reports.audit_review,
         name="plan_audit_submit_review"),
    path("plan-audits/<int:audit_id>/approve/", reports.approve_plan_audit,
         name="plan_audit_approve"),
    path("plan-audits/<int:audit_id>/reject/", reports.reject_plan_audit,
         name="plan_audit_reject"),
]
