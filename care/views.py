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
    from core.models import StoreSettings
    from core.pdf import styles, text, metadata, document, local_date
    from reportlab.platypus import Spacer

    store = StoreSettings.objects.select_related("logo_file").filter(pk=1).first()
    theme = styles()
    content = [
        text("Ringkasan pemeriksaan", theme["title"]),
        text("Hasil konsultasi dan panduan perawatan", theme["muted"]),
        Spacer(1, 8),
    ]
    content.append(
        metadata(
            [
                ("Nomor booking", booking.code),
                ("Hewan", f"{booking.pet.name} - {booking.pet.species.name}"),
                ("Pemilik", booking.customer.name),
                ("Dokter pemeriksa", record.author.full_name),
                (
                    "Tanggal pemeriksaan",
                    local_date(record.visit.examined_at or booking.starts_at, store),
                ),
                ("Diterbitkan", local_date(record.published_at, store)),
                ("Versi dokumen", str(record.version_no)),
            ],
            theme,
        )
    )
    sections = [
        ("Keluhan", record.complaint),
        ("Hasil pemeriksaan", record.findings),
        ("Diagnosis", record.diagnosis),
        ("Tindakan dan terapi", record.treatment),
        ("Perawatan di rumah", record.aftercare),
        (
            "Kontrol berikutnya",
            (
                local_date(record.followup_at, store)
                if record.followup_at
                else "Sesuai arahan dokter."
            ),
        ),
    ]
    if record.inpatient_recommended:
        sections.append(
            (
                "Anjuran tindak lanjut",
                "Dokter merekomendasikan rawat inap. Hubungi tim perawatan untuk pengaturan lebih lanjut.",
            )
        )
    if record.revision_reason:
        sections.append(("Catatan revisi", record.revision_reason))
    for label, value in sections:
        content += [text(label, theme["section"]), text(value, theme["body"])]
    buf = document(
        content,
        store,
        f"Ringkasan pemeriksaan {booking.code}",
        footer="Dokumen perawatan privat. Simpan dan bagikan hanya kepada pihak yang berkepentingan.",
    )
    audit(request.user, "medical.pdf_downloaded", record, after={"version": record.version_no})
    return FileResponse(
        buf,
        as_attachment=True,
        filename=f"{booking.code}-rekam-medis-v{record.version_no}.pdf",
        content_type="application/pdf",
    )
