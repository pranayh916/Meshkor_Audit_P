import io
import json
from pathlib import Path

from django.conf import settings

from . import data


def build_pdf(signoff: dict, codes: list[str] | None = None, user: str | None = None) -> bytes:
    """Create a PDF from the generated report payload and current Parquet metadata."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    except ImportError as exc:
        raise RuntimeError("Install the pinned ReportLab dependency to create PDF reports.") from exc

    payload_path = settings.BASE_DIR.parent / "reports" / "dashboard_data.json"
    if not payload_path.exists():
        raise data.DataMissing("dashboard_data.json not found. Run: python build_market_report.py")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    selected = set(codes or payload.get("drug_codes", []))
    summary = [r for r in payload.get("drug_summary", []) if r.get("hcpcs") in selected]

    buff = io.BytesIO()
    doc = SimpleDocTemplate(buff, pagesize=letter, rightMargin=0.55*inch, leftMargin=0.55*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch, title=payload.get("title", "Report"))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Subtle", parent=styles["BodyText"], textColor=colors.HexColor("#5B6570"),
                              fontSize=9, leading=13, alignment=TA_LEFT))
    story = [
        Paragraph(payload.get("title", "Infusion Drug Markup Audit"), styles["Title"]),
        Paragraph("DRAFT — for internal review" if payload.get("draft") else "Reviewed report", styles["Heading2"]),
        Paragraph(f"Data build: {payload.get('data_build_generated', 'unknown')} · Report generated: {payload.get('report_generated', 'unknown')}", styles["Subtle"]),
        Paragraph(f"Prepared by: {user or 'authorized user'} · Benchmark rule: {payload.get('benchmark_rule', 'unknown')}", styles["Subtle"]),
        Spacer(1, 12),
        Paragraph("Coverage and quality", styles["Heading2"]),
        Paragraph(f"{payload.get('drug_count', 0)} drugs · {payload.get('hospital_count', 0)} hospital sites · {payload.get('system_count', 0)} systems · {payload.get('headline_rows', 0)} qualifying negotiated rates", styles["BodyText"]),
        Paragraph(f"Quality records: {payload.get('quality_file_count', 0)} · Parser errors: {payload.get('quality_error_count', 0)} · Unreviewed drugs: {payload.get('drug_count', 0) - payload.get('reviewed_drug_count', 0)}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Drug comparison", styles["Heading2"]),
    ]
    table_data = [["HCPCS", "Drug", "Median markup", "Hospitals", "$ over benchmark / unit"]]
    for row in sorted(summary, key=lambda r: -(r.get("median_markup") or 0)):
        table_data.append([
            row.get("hcpcs", ""), row.get("drug_name", ""),
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
    story.extend([table, Spacer(1, 12), Paragraph("Limitations", styles["Heading2"])])
    for note in payload.get("method_notes", []):
        story.append(Paragraph("• " + note, styles["BodyText"]))
        story.append(Spacer(1, 4))
    story.extend([
        Spacer(1, 10),
        Paragraph(f"Source comparison SHA-256: {signoff.get('source_hash', '')}", styles["Subtle"]),
        Paragraph("A markup multiple compares a posted price with the Medicare ASP payment limit; it is not hospital profit or guaranteed employer savings.", styles["Subtle"]),
    ])
    doc.build(story)
    return buff.getvalue()
