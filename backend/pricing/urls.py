from django.urls import path

from . import auth_views, views

urlpatterns = [
    path("auth/csrf", auth_views.csrf, name="legacy_v0_authentication_csrf_token"),
    path("auth/login", auth_views.login_view, name="legacy_v0_authentication_sign_in"),
    path("auth/refresh", auth_views.refresh_access, name="legacy_v0_authentication_token_refresh"),
    path("auth/logout", auth_views.logout_view, name="legacy_v0_authentication_sign_out"),
    path("auth/me", auth_views.me, name="legacy_v0_authentication_current_user"),
    path("signoff", auth_views.signoff, name="legacy_v0_report_sign_off"),
    path("meta", views.meta, name="legacy_v0_dashboard_metadata"),
    path("drugs", views.drugs, name="legacy_v0_medicare_part_b_drug_catalog"),
    path("drugs/<str:hcpcs>", views.drug_detail, name="legacy_v0_medicare_part_b_drug_detail"),
    path("hospitals", views.hospitals, name="legacy_v0_hospital_catalog"),
    path("hospitals/<str:hospital_key>", views.hospital_detail, name="legacy_v0_hospital_detail"),
    path("rates", views.rates, name="legacy_v0_hospital_drug_price_comparisons"),
    path("rates.csv", views.rates_csv, name="legacy_v0_price_comparisons_csv_export"),
    path("rates.xlsx", views.rates_xlsx, name="legacy_v0_price_comparisons_excel_export"),
    path("report.pdf", views.report_pdf, name="legacy_v0_market_analysis_pdf_report"),
    path("quality", views.quality, name="legacy_v0_hospital_file_quality"),
]
