import io
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from accounts.permissions import verified_login, active_role
from core.selectors import visible_bookings
from core.services import audit
from .models import MedicalRecordVersion


@verified_login
def medical_pdf(request, pk):
    record = get_object_or_404(
        MedicalRecordVersion.objects.select_related("visit__booking__pet", "author"),
        pk=pk,
        published_at__isnull=False,
        visit__booking__in=visible_bookings(request.user),
    )
    booking = record.visit.booking
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=(21 * cm, 29.7 * cm),
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#24483D")
    content = [
        Paragraph("Sinau Satwa", styles["Title"]),
        Paragraph("Ringkasan pemeriksaan dan panduan perawatan", styles["Heading2"]),
    ]
    sections = [
        ("Booking", booking.code),
        ("Hewan", booking.pet.name),
        ("Dokter", record.author.full_name),
        ("Versi", record.version_no),
        ("Diterbitkan", str(record.published_at)),
        ("Keluhan", record.complaint),
        ("Temuan", record.findings),
        ("Diagnosis", record.diagnosis),
        ("Tindakan / terapi", record.treatment),
        ("Panduan perawatan", record.aftercare),
        ("Kontrol berikutnya", str(record.followup_at or "Sesuai arahan dokter")),
        ("Alasan revisi", record.revision_reason or "Versi awal"),
    ]
    if record.inpatient_recommended:
        sections.append(("Anjuran dokter", "Rawat inap"))
    for label, value in sections:
        content.extend(
            [
                Spacer(1, 0.25 * cm),
                Paragraph(escape(label), styles["Heading3"]),
                Paragraph(escape(str(value)).replace("\n", "<br/>"), styles["BodyText"]),
            ]
        )
    doc.build(content)
    buf.seek(0)
    audit(request.user, "medical.pdf_downloaded", record, after={"version": record.version_no})
    return FileResponse(
        buf,
        as_attachment=True,
        filename=f"{booking.code}-rekam-medis-v{record.version_no}.pdf",
        content_type="application/pdf",
    )
