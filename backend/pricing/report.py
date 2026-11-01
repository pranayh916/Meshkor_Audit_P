import io
import json
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings

from . import data


def build_pdf(signoff: dict, codes: list[str] | None = None, user: str | None = None,
              viewer_safe: bool = False) -> bytes:
    """Create a PDF from the generated report payload and current Parquet metadata."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, LongTable
    except ImportError as exc:
        raise RuntimeError("Install the pinned ReportLab dependency to create PDF reports.") from exc

    payload_path = settings.BASE_DIR.parent / "reports" / "dashboard_data.json"
    if not payload_path.exists():
        raise data.DataMissing("dashboard_data.json not found. Run: python build_market_report.py")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    selected = set(codes or payload.get("drug_codes", []))
    summary = [r for r in payload.get("drug_summary", []) if r.get("hcpcs") in selected]
    signoffs = signoff.get("clinical_signoffs", {})
    comparison = data.files()["comparison"]
    asp_path = data.files()["asp"]
    import duckdb

    connection = duckdb.connect()
    try:
        comparison_schema = {row[0] for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [comparison.as_posix()]).fetchall()}
        asp_rows = connection.execute(
            "SELECT hcpcs, quarter, dosage_text, payment_limit FROM read_parquet(?) "
            "WHERE hcpcs IN (SELECT unnest(?)) ORDER BY hcpcs, quarter",
            [asp_path.as_posix(), sorted(selected)]).fetchall()
        detail_fields = [name for name in (
            "hospital_label", "ccn", "npi", "setting", "payer_group", "price_type", "price",
            "gross_charge", "discounted_cash", "negotiated_percentage", "median_amount",
            "p10_amount", "p90_amount", "price_per_billing_unit", "asp_payment_limit",
            "markup_multiple", "unit_note", "status",
        ) if name in comparison_schema]
        if "hcpcs" in comparison_schema:
            predicate = "hcpcs IN (SELECT unnest(?))"
            if viewer_safe:
                predicate += (" AND coalesce(reviewed, false) AND status NOT IN "
                              "('unit_unresolved','unit_ambiguous','billing_unit_mismatch')")
            details = connection.execute(
                f"SELECT {', '.join(detail_fields)}, hcpcs FROM read_parquet(?) "
                f"WHERE {predicate} ORDER BY hcpcs, hospital_label, payer_group, setting, price_type",
                [comparison.as_posix(), sorted(selected)]).fetchall()
        else:
            details = []
    finally:
        connection.close()
    details_by_code = defaultdict(list)
    for item in details:
        details_by_code[item[-1]].append(dict(zip(detail_fields, item[:-1])))
    asp_by_code = defaultdict(list)
    for code, quarter, dosage, limit in asp_rows:
        asp_by_code[code].append((quarter, dosage, limit))

    buff = io.BytesIO()
    doc = SimpleDocTemplate(buff, pagesize=letter, rightMargin=0.55*inch, leftMargin=0.55*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch, title=payload.get("title", "Report"))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Subtle", parent=styles["BodyText"], textColor=colors.HexColor("#5B6570"),
                              fontSize=9, leading=13, alignment=TA_LEFT))
    story = [
        Paragraph(escape(payload.get("title", "Infusion Drug Markup Audit")), styles["Title"]),
        Paragraph("RELEASED" if signoff.get("signed") else "DRAFT — for internal review", styles["Heading2"]),
        Paragraph(f"Data build: {payload.get('data_build_generated', 'unknown')} · Report generated: {payload.get('report_generated', 'unknown')}", styles["Subtle"]),
        Paragraph(f"ASP quarter(s): {escape(', '.join(payload.get('benchmark_quarters') or []) or 'unavailable')} · Prepared by: {escape(user or 'authorized user')}", styles["Subtle"]),
        Paragraph(f"Independent Admin release: {escape(signoff.get('approved_by') or 'not released')} · Release date: {escape(signoff.get('approved_at') or 'not released')}", styles["Subtle"]),
        Spacer(1, 12),
        Paragraph("Coverage and quality", styles["Heading2"]),
        Paragraph(f"{payload.get('drug_count', 0)} drugs · {payload.get('hospital_count', 0)} hospital sites · {payload.get('system_count', 0)} systems · {payload.get('headline_rows', 0)} qualifying negotiated rates", styles["BodyText"]),
        Paragraph(f"Quality records: {payload.get('quality_file_count', 0)} · Parser errors: {payload.get('quality_error_count', 0)} · Clinically reviewed drugs: {payload.get('reviewed_drug_count', 0)} of {payload.get('drug_count', 0)}", styles["BodyText"]),
        Paragraph(escape(payload.get("hospital_coverage_note", "Hospital MRF coverage has not been reconciled to the Ohio acute-care universe.")), styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Drug comparison", styles["Heading2"]),
    ]
    table_data = [["HCPCS", "Drug", "Median markup", "Hospitals", "$ over benchmark / unit"]]
    for row in sorted(summary, key=lambda r: -(r.get("median_markup") or 0)):
        table_data.append([
            row.get("hcpcs", ""), escape(str(row.get("drug_name", ""))),
            f"{row['median_markup']:.2f}x" if row.get("median_markup") is not None else "—",
            str(row.get("hospital_sites", 0)),
            f"${row['median_dollars_over_benchmark_per_billing_unit']:.2f}" if row.get("median_dollars_over_benchmark_per_billing_unit") is not None else "—",
        ])
    table = Table(table_data, repeatRows=1, colWidths=[0.65*inch, 1.8*inch, 1.05*inch, 0.8*inch, 1.5*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8DEE5")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([table, Spacer(1, 12), Paragraph("Top five by estimated dollars at stake", styles["Heading2"])])
    stake_rows = [["HCPCS", "Drug", "Part B spend proxy", "Exposure proxy"]]
    for row in payload.get("top_drugs_by_dollars_at_stake", []):
        if row.get("hcpcs") in selected:
            stake_rows.append([row.get("hcpcs", ""), escape(str(row.get("drug_name", ""))),
                               f"${row['partb_spending_proxy']:,.0f}" if row.get("partb_spending_proxy") is not None else "—",
                               f"${row['estimated_dollars_at_stake_proxy']:,.0f}" if row.get("estimated_dollars_at_stake_proxy") is not None else "—"])
    story.append(Table(stake_rows, repeatRows=1, colWidths=[0.65*inch, 2.2*inch, 1.7*inch, 1.7*inch]))
    story.append(Paragraph(escape(payload.get("dollars_at_stake_definition", "")), styles["Subtle"]))
    story.extend([Spacer(1, 12), Paragraph("Clinical review sign-offs", styles["Heading2"])])
    clinical_rows = [["HCPCS", "External reviewer", "Decision", "Reviewed at"]]
    for code in sorted(selected):
        record = signoffs.get(code) or {}
        clinical_rows.append([code, escape(str(record.get("reviewer_name") or "Pending")),
                              record.get("decision", "pending clinical review"),
                              record.get("reviewed_at", "—")])
    story.append(Table(clinical_rows, repeatRows=1, colWidths=[0.7*inch, 2.5*inch, 1.2*inch, 2.0*inch]))

    story.extend([PageBreak(), Paragraph("Hospital-by-hospital rate appendix", styles["Heading1"])])
    story.append(Paragraph("Viewer exports contain released rows only. The CSV appendix download contains the same report detail in machine-readable form.", styles["Subtle"]))
    for drug in summary:
        code = drug.get("hcpcs")
        story.extend([PageBreak(), Paragraph(escape(f"{code} · {drug.get('drug_name', '')}"), styles["Heading2"])])
        reviewer = signoffs.get(code) or {}
        story.append(Paragraph(
            f"Clinical review: {escape(str(reviewer.get('decision') or 'pending clinical review'))} · "
            f"{escape(str(reviewer.get('reviewer_name') or 'No recorded reviewer'))} · "
            f"{escape(str(reviewer.get('reviewed_at') or 'No sign-off date'))}", styles["Subtle"]))
        quarters = [["ASP quarter", "CMS dosage", "ASP payment limit"]]
        quarters.extend([[q, escape(str(dose or "—")), f"${limit:,.4f}" if limit is not None else "—"]
                         for q, dose, limit in asp_by_code.get(code, [])])
        story.append(Table(quarters, repeatRows=1, colWidths=[1.2*inch, 2.4*inch, 1.8*inch]))
        headers = ["Hospital", "CCN", "NPI", "Setting", "Payer", "Rate type", "Gross / cash", "Median / P10–P90", "$/HCPCS unit", "ASP", "Markup / flags"]
        rate_rows = [headers]
        for row in details_by_code.get(code, []):
            gross_cash = f"{row.get('gross_charge') or '—'} / {row.get('discounted_cash') or '—'}"
            median_band = f"{row.get('median_amount') or '—'} / {row.get('p10_amount') or '—'}–{row.get('p90_amount') or '—'}"
            markup = row.get("markup_multiple")
            mark = f"{markup:.2f}×" if isinstance(markup, (int, float)) else "—"
            flag = str(row.get("status") or "")
            if row.get("unit_note"):
                flag = f"{flag}: {row['unit_note']}"
            rate_rows.append([
                escape(str(row.get("hospital_label") or "—")), str(row.get("ccn") or "—"),
                str(row.get("npi") or "—"), escape(str(row.get("setting") or "—")),
                escape(str(row.get("payer_group") or "—")), escape(str(row.get("price_type") or "—")),
                escape(gross_cash), escape(median_band),
                f"${row['price_per_billing_unit']:,.4f}" if row.get("price_per_billing_unit") is not None else "—",
                f"${row['asp_payment_limit']:,.4f}" if row.get("asp_payment_limit") is not None else "—",
                escape(mark + (f" · {flag}" if flag else "")),
            ])
        if len(rate_rows) == 1:
            story.append(Paragraph("No included hospital rate rows for this drug.", styles["BodyText"]))
        else:
            detailed_table = LongTable(rate_rows, repeatRows=1,
                colWidths=[1.0*inch, .42*inch, .48*inch, .48*inch, .55*inch, .58*inch,
                           .67*inch, .75*inch, .65*inch, .62*inch, .85*inch])
            detailed_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 5.4),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8DEE5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
            ]))
            story.append(detailed_table)
    story.extend([PageBreak(), Paragraph("Sources, method, and limits", styles["Heading1"])])
    source_rows = [["Source file", "Effective period", "SHA-256"]]
    for source in payload.get("source_inventory", []):
        source_rows.append([escape(str(source.get("source_file") or "—")),
                            f"{source.get('effective_start') or '—'} to {source.get('effective_end') or '—'}",
                            escape(str(source.get("source_sha256") or "—"))])
    if len(source_rows) > 1:
        story.append(LongTable(source_rows, repeatRows=1, colWidths=[2.5*inch, 1.5*inch, 2.8*inch]))
    story.append(Paragraph("Lower-cost sites are leads for further review, based only on Medicare benchmarks and hospital price files. Payer files are not included.", styles["BodyText"]))
    story.append(Paragraph("This market analysis does not estimate hospital acquisition cost. 340B discounts can lower some hospitals’ drug acquisition cost but do not determine plan payment. A site-of-care change requires a lower-cost in-network option, clinical suitability, and the treating clinician’s agreement. Some patients must receive care at a hospital for clinical reasons. This report contains no employer claims or plan-specific audit.", styles["BodyText"]))
    for note in payload.get("method_notes", []):
        story.append(Paragraph("• " + note, styles["BodyText"]))
        story.append(Spacer(1, 4))
    story.extend([
        Spacer(1, 10),
        Paragraph(f"Source comparison SHA-256: {signoff.get('source_hash', '')}", styles["Subtle"]),
    Paragraph("The CMS ASP payment limit already includes the statutory 6% add-on; this report does not add 6% again. Markup compares the hospital price per HCPCS billing unit with that limit. Unit conversion is only applied in the comparison Parquet layer; unresolved units are not assigned a price. Percentage-only rows are reported as a percentage and are not treated as a dollar rate.", styles["Subtle"]),
    Paragraph("A markup multiple compares a posted price with the Medicare ASP payment limit; it is not hospital profit or guaranteed employer savings. CSV appendix: download separately from the Reports page.", styles["Subtle"]),
    ])
    doc.build(story)
    return buff.getvalue()
