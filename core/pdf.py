"""Shared, locally rendered document styling. Never fetch remote assets while exporting."""

import io
from pathlib import Path
from xml.sax.saxutils import escape
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GREEN = colors.HexColor("#214d40")
MUTED = colors.HexColor("#64726c")
LINE = colors.HexColor("#dce4df")
WIDTH = A4[0] - 84


def money(value):
    return "Rp" + f"{int(value):,}".replace(",", ".")


def local_date(value, store=None):
    if not value:
        return "-"
    try:
        zone = (
            ZoneInfo(store.timezone or settings.TIME_ZONE)
            if store
            else ZoneInfo(settings.TIME_ZONE)
        )
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo(settings.TIME_ZONE)
    return timezone.localtime(value, zone).strftime("%d %b %Y, %H:%M")


def styles():
    if "SinauSans" not in pdfmetrics.getRegisteredFontNames():
        fonts = Path(reportlab.__file__).parent / "fonts"
        pdfmetrics.registerFont(TTFont("SinauSans", str(fonts / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("SinauSansBold", str(fonts / "VeraBd.ttf")))
        pdfmetrics.registerFontFamily("SinauSans", normal="SinauSans", bold="SinauSansBold")
    body = ParagraphStyle(
        "Body",
        fontName="SinauSans",
        fontSize=9,
        leading=14,
        textColor=GREEN,
        spaceAfter=6,
        splitLongWords=True,
    )
    return {
        "body": body,
        "muted": ParagraphStyle("Muted", parent=body, textColor=MUTED, fontSize=8, leading=12),
        "title": ParagraphStyle(
            "Title", parent=body, fontName="SinauSansBold", fontSize=22, leading=29, spaceAfter=8
        ),
        "section": ParagraphStyle(
            "Section",
            parent=body,
            fontName="SinauSansBold",
            fontSize=11,
            leading=16,
            spaceBefore=13,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "white": ParagraphStyle(
            "White",
            parent=body,
            textColor=colors.white,
            fontName="SinauSansBold",
            fontSize=8,
            spaceAfter=0,
        ),
        "right": ParagraphStyle("Right", parent=body, alignment=2),
        "amount": ParagraphStyle(
            "Amount",
            parent=body,
            fontName="SinauSansBold",
            fontSize=16,
            leading=21,
            alignment=2,
            spaceAfter=0,
        ),
    }


def text(value, style):
    return Paragraph(escape(str(value or "-")).replace("\n", "<br/>"), style)


def metadata(rows, theme):
    table = LongTable(
        [[text(k, theme["muted"]), text(v, theme["body"])] for k, v in rows],
        colWidths=[120, WIDTH - 120],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ]
        )
    )
    return table


def document(content, store, title, *, footer="Dokumen diterbitkan secara elektronik."):
    styles()
    stream = io.BytesIO()
    brand = store.business_name if store and store.business_name else "Sinau Satwa"
    logo_path = None
    logo = store.logo_file if store and store.logo_file_id else None
    if (
        logo
        and logo.classification == "SITE_PUBLIC"
        and logo.mime_type == "image/jpeg"
        and logo.scan_status == "VALIDATED"
        and not logo.purged_at
    ):
        candidate = (settings.PRIVATE_ROOT / logo.storage_key).resolve()
        if candidate.is_relative_to(settings.PRIVATE_ROOT.resolve()) and candidate.is_file():
            logo_path = candidate

    def page(canvas, doc):
        canvas.saveState()
        x = 42
        if logo_path:
            canvas.drawImage(
                str(logo_path),
                x,
                A4[1] - 77,
                width=36,
                height=36,
                preserveAspectRatio=True,
                mask="auto",
            )
            x += 47
        canvas.setFillColor(GREEN)
        canvas.setFont("SinauSansBold", 13)
        canvas.drawString(x, A4[1] - 48, brand[:45])
        canvas.setFillColor(MUTED)
        canvas.setFont("SinauSans", 8)
        canvas.drawString(x, A4[1] - 64, (store.tagline if store else "")[:90])
        canvas.setStrokeColor(GREEN)
        canvas.setLineWidth(1.4)
        canvas.line(42, A4[1] - 82, A4[0] - 42, A4[1] - 82)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(42, 43, A4[0] - 42, 43)
        canvas.setFont("SinauSans", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(42, 29, footer[:105])
        canvas.drawRightString(A4[0] - 42, 29, f"Halaman {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=100,
        bottomMargin=62,
        title=title,
        author=brand,
    )
    doc.build(content, onFirstPage=page, onLaterPages=page)
    stream.seek(0)
    return stream
