from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from accounts.permissions import require_role, active_role, OPS
from core.services import BusinessError, commerce_transaction, audit
from scheduling.models import Booking, ResourceReservation
from .models import (
    Visit,
    MedicalRecordVersion,
    ClinicalInternalNote,
    MedicalAttachment,
    GroomingJob,
    GroomingResultFile,
)


def doctor_access(actor, visit):
    require_role(actor, {"DOCTOR"})
    if visit.doctor_id != actor.pk:
        raise BusinessError("Pasien belum ditugaskan kepada dokter ini.")


def attendance_window(booking):
    from core.models import StoreSettings

    store = StoreSettings.objects.filter(pk=1).first()
    grace = store.attendance_grace_minutes if store else 15
    now = timezone.now()
    return {
        "can_arrive": now >= booking.starts_at - timedelta(minutes=30),
        "can_mark_absent": now >= booking.starts_at + timedelta(minutes=grace),
        "absence_after": booking.starts_at + timedelta(minutes=grace),
        "grace_minutes": grace,
    }


def record_attendance(actor, booking, attendance, note=""):
    require_role(actor, {"DOCTOR"})
    if attendance not in {"PRESENT", "ABSENT"}:
        raise BusinessError("Pilih Hadir atau Tidak hadir.")
    with commerce_transaction():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        visit = Visit.objects.select_for_update().get(booking=booking)
        doctor_access(actor, visit)
        if booking.status != "CONFIRMED" or visit.attendance != "PENDING":
            raise BusinessError("Kehadiran sudah diproses atau kunjungan tidak lagi terjadwal.")
        window = attendance_window(booking)
        if attendance == "PRESENT" and not window["can_arrive"]:
            raise BusinessError("Kehadiran dapat dikonfirmasi mulai 30 menit sebelum jadwal.")
        if attendance == "ABSENT":
            if not window["can_mark_absent"]:
                raise BusinessError(
                    f"Tunggu hingga {window['grace_minutes']} menit setelah jadwal mulai sebelum menandai tidak hadir."
                )
            if not note.strip() or len(note) > 1000:
                raise BusinessError("Isi catatan ketidakhadiran, maksimal 1000 karakter.")
            booking.status = "NO_SHOW"
            ResourceReservation.objects.filter(
                booking=booking, status__in={"HELD", "CONFIRMED"}
            ).update(status="RELEASED")
            from engagement.models import Reminder

            Reminder.objects.filter(booking=booking, status="PENDING").update(status="CANCELED")
        visit.attendance, visit.attendance_at, visit.attendance_note = (
            attendance,
            timezone.now(),
            note.strip()[:1000],
        )
        visit.save(update_fields=["attendance", "attendance_at", "attendance_note", "updated_at"])
        booking.version += 1
        booking.save(update_fields=["status", "version", "updated_at"])
        audit(
            actor,
            "visit.attendance_recorded",
            visit,
            after={"attendance": attendance},
            reason=visit.attendance_note,
        )
        return visit


def start_care(actor, booking):
    if booking.kind_snapshot == "VET":
        doctor_access(actor, Visit.objects.get(booking=booking))
    else:
        require_role(actor, {"GROOMER"})
        if GroomingJob.objects.get(booking=booking).groomer_id != actor.pk:
            raise BusinessError("Pekerjaan belum ditugaskan kepada Anda.")
    with commerce_transaction():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.kind_snapshot == "VET":
            visit = Visit.objects.get(booking=booking)
            doctor_access(actor, visit)
            if visit.attendance != "PRESENT":
                raise BusinessError("Konfirmasi pelanggan hadir sebelum memulai pemeriksaan.")
        elif GroomingJob.objects.get(booking=booking).groomer_id != actor.pk:
            raise BusinessError("Penugasan layanan telah berubah. Muat ulang antrean.")
        if booking.status != "CONFIRMED":
            raise BusinessError("Layanan harus sudah dibayar dan terjadwal.")
        if timezone.now() < booking.starts_at - timedelta(minutes=30):
            raise BusinessError("Layanan dapat dimulai 30 menit sebelum jadwal.")
        booking.status = "IN_SERVICE"
        booking.save()
        ResourceReservation.objects.filter(booking=booking, status="CONFIRMED").update(
            status="IN_USE"
        )
        if booking.kind_snapshot == "VET":
            Visit.objects.filter(booking=booking).update(examined_at=timezone.now())
        else:
            GroomingJob.objects.filter(booking=booking).update(started_at=timezone.now())
        audit(actor, "care.started", booking)


def save_medical(actor, visit, data, publish=False, file=None):
    doctor_access(actor, visit)
    allowed = {
        key: data.get(key)
        for key in (
            "complaint",
            "findings",
            "diagnosis",
            "treatment",
            "aftercare",
            "followup_at",
            "revision_reason",
        )
    }
    if visit.booking.status not in {"IN_SERVICE", "READY_PICKUP", "COMPLETED"}:
        raise BusinessError("Pemeriksaan perlu dimulai terlebih dahulu.")
    if publish and any(
        not str(allowed.get(f) or "").strip()
        for f in ("complaint", "findings", "diagnosis", "treatment", "aftercare")
    ):
        raise BusinessError(
            "Keluhan, temuan, diagnosis, tindakan, dan panduan perawatan wajib lengkap sebelum terbit."
        )
    with commerce_transaction():
        current_booking = Booking.objects.select_for_update().get(pk=visit.booking_id)
        visit = Visit.objects.select_for_update().get(pk=visit.pk)
        doctor_access(actor, visit)
        if (
            current_booking.status not in {"IN_SERVICE", "READY_PICKUP", "COMPLETED"}
            or visit.attendance != "PRESENT"
        ):
            raise BusinessError("Kunjungan belum dimulai atau pelanggan tidak hadir.")
        versions = MedicalRecordVersion.objects.filter(visit=visit).order_by("-version_no")
        latest = versions.first()
        published = versions.filter(published_at__isnull=False).exists()
        if published and not str(allowed["revision_reason"] or "").strip():
            raise BusinessError("Revisi rekam medis terbit wajib mempunyai alasan.")
        if latest and not latest.published_at:
            record = latest
            for field, value in allowed.items():
                setattr(record, field, value or (None if field == "followup_at" else ""))
        else:
            record = MedicalRecordVersion(
                visit=visit,
                author=actor,
                version_no=(latest.version_no + 1 if latest else 1),
                **{k: v or (None if k == "followup_at" else "") for k, v in allowed.items()},
            )
        if "inpatient_recommended" in data:
            record.inpatient_recommended = data["inpatient_recommended"] is True
        if publish:
            if record.followup_at and record.followup_at <= timezone.now():
                raise BusinessError("Jadwal kontrol harus berada di masa mendatang.")
            versions.filter(is_current=True).update(is_current=False)
            record.published_at, record.is_current = timezone.now(), True
        record.save()
        if file:
            if file.uploaded_by_id != actor.pk:
                raise BusinessError("Lampiran tidak sesuai pengunggah.")
            MedicalAttachment.objects.create(record_version=record, file=file, kind="RESULT")
        if data.get("internal_note", "").strip():
            ClinicalInternalNote.objects.create(
                visit=visit, author=actor, content=data["internal_note"]
            )
        if publish:
            from engagement.services import sync_medical_reminder

            sync_medical_reminder(record)
            from core.services import emit

            emit(
                "medical.published",
                record,
                {"customer_id": str(visit.booking.customer_id), "code": visit.booking.code},
            )
            audit(actor, "medical.published", record, after={"version": record.version_no})
        return record


def grooming_ready(actor, job, result_note, file=None):
    require_role(actor, {"GROOMER"})
    if job.groomer_id != actor.pk or not result_note.strip():
        raise BusinessError("Isi hasil grooming untuk pekerjaan yang ditugaskan kepada Anda.")
    with commerce_transaction():
        booking = Booking.objects.select_for_update().get(pk=job.booking_id)
        if booking.status != "IN_SERVICE":
            raise BusinessError("Grooming belum dimulai atau sudah selesai.")
        job.result_note, job.ready_at = result_note, timezone.now()
        job.save()
        if file:
            GroomingResultFile.objects.create(job=job, file=file)
        booking.status = "READY_PICKUP"
        booking.save()
        audit(actor, "grooming.ready", booking)


def finish_care(actor, booking):
    require_role(actor, OPS | {"DOCTOR", "GROOMER"})
    with commerce_transaction():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.kind_snapshot == "VET":
            visit = Visit.objects.get(booking=booking)
            if active_role(actor) == "DOCTOR" and visit.doctor_id != actor.pk:
                raise BusinessError("Pasien tidak ditugaskan kepada Anda.")
            if (
                booking.status != "IN_SERVICE"
                or not MedicalRecordVersion.objects.filter(
                    visit=visit, is_current=True, published_at__isnull=False
                ).exists()
            ):
                raise BusinessError("Terbitkan hasil pemeriksaan sebelum menyelesaikan kunjungan.")
        elif booking.kind_snapshot == "GROOMING":
            job = GroomingJob.objects.get(booking=booking)
            if active_role(actor) == "GROOMER" and job.groomer_id != actor.pk:
                raise BusinessError("Pekerjaan tidak ditugaskan kepada Anda.")
            if booking.status != "READY_PICKUP":
                raise BusinessError("Grooming harus sudah siap dijemput.")
            job.completed_at = timezone.now()
            job.save()
        else:
            raise BusinessError("Gunakan proses check-out penitipan.")
        booking.status, booking.completed_at = "COMPLETED", timezone.now()
        booking.save()
        # Keep the booked buffer, releasing only at its scheduled upper bound via maintenance.
        audit(actor, "care.handover_completed", booking)
