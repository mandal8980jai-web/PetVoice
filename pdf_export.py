"""PDF export for PetFit AI. Input: a saved report dict. Output: PDF bytes."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import config

NAVY = colors.HexColor(config.COLORS["navy"])
BLUE = colors.HexColor(config.COLORS["blue"])
TEAL = colors.HexColor(config.COLORS["teal"])
BORDER = colors.HexColor(config.COLORS["border"])
LIGHT = colors.HexColor(config.COLORS["light_bg"])
DEMO = colors.HexColor(config.COLORS["demo"])

STATUS_COLORS = {"normal": TEAL, "watch": DEMO, "consult_vet": colors.HexColor("#B83232")}
FLAG_LABELS = {"vet": "Consider contacting your vet", "watch": "Keep an eye on",
               "info": "Info"}
FLAG_COLORS = {"vet": colors.HexColor("#B83232"), "watch": DEMO, "info": BLUE}


def _clean(value):
    """Escape for ReportLab and drop characters the built-in font cannot draw."""
    text = "" if value is None else str(value)
    return escape(text.encode("cp1252", "replace").decode("cp1252"))


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=NAVY,
                                fontSize=22, alignment=0, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=NAVY,
                             fontSize=13, spaceBefore=12, spaceAfter=4, keepWithNext=1),
        "body": ParagraphStyle("b", parent=base["BodyText"], textColor=NAVY,
                               fontSize=10, leading=14),
        "small": ParagraphStyle("s", parent=base["BodyText"], textColor=colors.HexColor("#5B6B82"),
                                fontSize=8.5, leading=11),
        "cell": ParagraphStyle("c", parent=base["BodyText"], textColor=NAVY,
                               fontSize=8.5, leading=11),
        "cellhead": ParagraphStyle("ch", parent=base["BodyText"], textColor=colors.white,
                                   fontSize=8.5, leading=11, fontName="Helvetica-Bold"),
    }


def _footer(demo):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5B6B82"))
        canvas.drawString(2 * cm, 1.2 * cm,
                          "PetVoice - informational report, not a veterinary diagnosis.")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
        if demo:
            canvas.setFillColor(DEMO)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(2 * cm, A4[1] - 1.1 * cm,
                              f"{config.DEMO_LABEL} - not a real animal")
        canvas.restoreState()
    return draw


def build_pdf(report):
    """Return PDF bytes for a report dict produced by agents.run_analysis."""
    st = _styles()
    pet = report.get("pet", {})
    period = report.get("period", {})
    demo = bool(pet.get("is_demo"))
    story = []

    story.append(Paragraph("PetVoice Report", st["title"]))
    details = [pet.get("name", "Unknown pet"), str(pet.get("species", "")).title()]
    if pet.get("breed"):
        details.append(pet["breed"])
    if pet.get("weight_kg"):
        details.append(f"{pet['weight_kg']} kg")
    story.append(Paragraph(_clean(" | ".join(details)), st["body"]))
    story.append(Paragraph(_clean(
        f"Period analysed: {period.get('start', '?')} to {period.get('end', '?')} "
        f"(compared with {period.get('previous_start', '?')} to "
        f"{period.get('previous_end', '?')})  |  Generated: "
        f"{report.get('generated_at', '')}"), st["small"]))
    if demo:
        story.append(Spacer(1, 4))
        story.append(Paragraph(_clean(
            f"{config.DEMO_LABEL} - this report was produced from generated "
            f"demonstration data, not a real animal."), ParagraphStyle(
                "d", parent=st["body"], textColor=DEMO)))

    status = report.get("overall_status")
    status_color = STATUS_COLORS.get(status, colors.HexColor("#6B7C93"))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f'<font color="{status_color.hexval().replace("0x", "#")}"><b>'
        f'{_clean(report.get("status_label", "Unavailable"))}</b></font>', st["h2"]))
    story.append(Paragraph(_clean(report.get("headline", "")), st["body"]))

    story.append(Paragraph("Overview", st["h2"]))
    source = ("AI-assisted (Gemini)" if report.get("overview_source") == "gemini"
              else "Rule-based")
    story.append(Paragraph(_clean(report.get("overview", "")), st["body"]))
    story.append(Paragraph(_clean(f"Overview source: {source}"), st["small"]))

    if report.get("key_findings"):
        story.append(Paragraph("Key findings", st["h2"]))
        for line in report["key_findings"]:
            story.append(Paragraph("&bull; " + _clean(line), st["body"]))

    if report.get("metrics"):
        story.append(Paragraph("Averages (latest period)", st["h2"]))
        rows = [[Paragraph(h, st["cellhead"]) for h in
                 ("Metric", "Average", "Days logged", "Compared with general guidance",
                  "General guidance range")]]
        for m in report["metrics"]:
            avg = "n/a" if m.get("average") is None else f"{m['average']} {m['unit']}"
            rows.append([Paragraph(_clean(m.get("label")), st["cell"]),
                         Paragraph(_clean(avg), st["cell"]),
                         Paragraph(_clean(m.get("days_logged")), st["cell"]),
                         Paragraph(_clean(m.get("rating_text")), st["cell"]),
                         Paragraph(_clean(m.get("range_text")), st["cell"])])
        table = Table(rows, colWidths=[2.4 * cm, 2.8 * cm, 2.2 * cm, 5 * cm, 4.6 * cm],
                      repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(table)

    if report.get("trends"):
        story.append(Paragraph("Trends (latest 7 days vs previous 7 days)", st["h2"]))
        for t in report["trends"]:
            story.append(Paragraph("&bull; " + _clean(t.get("text")), st["body"]))

    obs = report.get("observations", {})
    if obs.get("available"):
        story.append(Paragraph("Owner observations", st["h2"]))
        story.append(Paragraph(_clean(obs.get("summary")), st["body"]))
        src = "AI-assisted (Gemini)" if obs.get("source") == "gemini" else "Rule-based"
        story.append(Paragraph(_clean(f"Notes summary source: {src}"), st["small"]))

    story.append(Paragraph("Safety flags", st["h2"]))
    flags = report.get("flags", [])
    if not flags:
        story.append(Paragraph("No safety rules were triggered by the logged data "
                               "(this is not a health clearance).", st["body"]))
    for f in flags:
        level = f.get("level", "info")
        hexcolor = FLAG_COLORS.get(level, BLUE).hexval().replace("0x", "#")
        story.append(Paragraph(
            f'<font color="{hexcolor}"><b>{_clean(FLAG_LABELS.get(level, level))}:</b></font> '
            f'{_clean(f.get("message"))}', st["body"]))
        story.append(Spacer(1, 3))

    if report.get("suggestions"):
        story.append(Paragraph("General suggestions", st["h2"]))
        for line in report["suggestions"]:
            story.append(Paragraph("&bull; " + _clean(line), st["body"]))

    quality = report.get("data_quality", {})
    story.append(Paragraph("Data quality", st["h2"]))
    story.append(Paragraph(_clean(
        f"{quality.get('days_logged', 0)} of {quality.get('days_in_window', 7)} days "
        f"logged ({quality.get('completeness_pct', 0)}%). Missing days are never "
        f"filled in."), st["body"]))
    for note in quality.get("notes", []):
        story.append(Paragraph("&bull; " + _clean(note), st["small"]))
    if report.get("unavailable_sections"):
        story.append(Paragraph(_clean("Unavailable sections: " + ", ".join(
            report["unavailable_sections"])), st["small"]))
    story.append(Paragraph(_clean(
        f"Gemini calls used: {report.get('gemini_calls_used', 0)} of "
        f"{config.GEMINI_MAX_CALLS}."), st["small"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph(_clean(report.get("guidance_label", config.GUIDANCE_LABEL)),
                           st["small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Disclaimer.</b> " + _clean(
        report.get("disclaimer", config.DISCLAIMER)), st["small"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title="PetVoice Report", author=config.APP_NAME)
    decorate = _footer(demo)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()