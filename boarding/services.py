from datetime import timedelta
from math import ceil
from django.db import IntegrityError
from django.utils import timezone
from psycopg.types.range import Range
from accounts.permissions import require_role, active_role, OPS
from core.services import BusinessError, commerce_transaction, audit, emit
from scheduling.models import Booking, Resource, ResourceReservation
from scheduling.services import BLOCKING, expire_capacity_holds, validate_time
from .models import BoardingStay, BoardingUnit, BoardingIntakeFile, ExtensionRequest, CareLog


def nights_between(start, end):
    return max(1, ceil((end - start).total_seconds() / 86400))


def verify_intake(actor, document, valid_until, note):
    require_role(actor, OPS)
    if not valid_until or valid_until < timezone.localdate(document.stay.booking.ends_at):
        raise BusinessError("Masa berlaku dokumen harus mencakup akhir masa inap.")
    with commerce_transaction():
        document = BoardingIntakeFile.objects.select_for_update().get(pk=document.pk)
        if not document.is_active or document.verified_at:
            raise BusinessError("Dokumen sudah diverifikasi atau telah diganti.")
        document.verified_by, document.verified_at = actor, timezone.now()
        document.valid_until, document.review_note = valid_until, note
        document.save()
        audit(actor, "boarding.intake_verified", document, after={"valid_until": str(valid_until)})


def approve_stay(actor, stay, unit, caretaker):
    require_role(actor, OPS)
    try:
        with commerce_transaction():
            expire_capacity_holds()
            stay = (
                BoardingStay.objects.select_for_update().select_related("booking").get(pk=stay.pk)
            )
            booking = Booking.objects.select_for_update().get(pk=stay.booking_id)
            if booking.status != "SUBMITTED":
                raise BusinessError("Pengajuan sudah ditinjau.")
            unit = (
                BoardingUnit.objects.select_for_update()
                .select_related("resource")
                .get(pk=unit.pk, is_active=True, resource__is_active=True)
            )
            Resource.objects.select_for_update().get(pk=unit.resource_id)
            if unit.species_id != booking.pet.species_id:
                raise BusinessError("Unit tidak sesuai jenis hewan.")
            if not caretaker.is_active or not caretaker.groups.filter(name="CARETAKER").exists():
                raise BusinessError("Pilih petugas penitipan yang aktif.")
            if not stay.emergency_snapshot.get("phone") or not stay.emergency_snapshot.get(
                "consent"
            ):
                raise BusinessError("Kontak darurat belum lengkap.")
            if not BoardingIntakeFile.objects.filter(
                stay=stay,
                is_active=True,
                verified_at__isnull=False,
                valid_until__gte=timezone.localdate(booking.ends_at),
            ).exists():
                raise BusinessError(
                    "Verifikasi dokumen kesehatan yang berlaku selama masa inap sebelum menyetujui."
                )
            if booking.starts_at <= timezone.now():
                raise BusinessError(
                    "Jadwal pengajuan sudah lewat. Buat pengajuan dengan waktu yang sesuai."
                )
            period = Range(
                booking.starts_at, booking.ends_at + timedelta(minutes=unit.cleaning_minutes), "[)"
            )
            if ResourceReservation.objects.filter(
                resource=unit.resource, status__in=BLOCKING, period__overlap=period
            ).exists():
                raise BusinessError("Unit penuh pada periode ini, termasuk waktu pembersihan.")
            expiry = timezone.now() + timedelta(minutes=30)
            ResourceReservation.objects.create(
                resource=unit.resource,
                booking=booking,
                period=period,
                kind="BOARDING",
                status="HELD",
                expires_at=expiry,
            )
            stay.unit, stay.caretaker = unit, caretaker
            stay.nightly_rate_rp, stay.cleaning_minutes = (
                unit.nightly_rate_rp,
                unit.cleaning_minutes,
            )
            stay.save()
            booking.price_snapshot_rp = (
                nights_between(booking.starts_at, booking.ends_at) * unit.nightly_rate_rp
            )
            booking.status, booking.expires_at = "AWAITING_PAYMENT", expiry
            booking.save()
            from billing.services import issue_invoice

            issue_invoice(
                booking,
                booking.customer,
                booking.price_snapshot_rp,
                f"Penitipan {booking.pet.name}",
                expiry,
            )
            audit(
                actor,
                "boarding.approved",
                stay,
                after={"unit": str(unit.pk), "total_rp": booking.price_snapshot_rp},
            )
            emit(
                "boarding.approved",
                booking,
                {"customer_id": str(booking.customer_id), "code": booking.code},
            )
    except IntegrityError:
        raise BusinessError("Unit atau jadwal hewan bertabrakan. Muat ulang ketersediaan.")


def reject_stay(actor, stay, reason):
    require_role(actor, OPS)
    if not reason.strip():
        raise BusinessError("Alasan penolakan wajib diisi.")
    with commerce_transaction():
        booking = Booking.objects.select_for_update().get(pk=stay.booking_id)
        if booking.status != "SUBMITTED":
            raise BusinessError("Pengajuan sudah ditinjau.")
        booking.status = "CANCELED"
        booking.policy_snapshot = {**booking.policy_snapshot, "rejection_reason": reason}
        booking.save()
        audit(actor, "boarding.rejected", stay, reason=reason)
        emit(
            "boarding.rejected",
            booking,
            {"customer_id": str(booking.customer_id), "code": booking.code},
        )


def request_extension(actor, stay, requested_checkout_at):
    require_role(actor, OPS | {"CUSTOMER"})
    with commerce_transaction():
        stay = BoardingStay.objects.select_for_update().select_related("booking").get(pk=stay.pk)
        booking = Booking.objects.select_for_update().get(pk=stay.booking_id)
        if active_role(actor) == "CUSTOMER" and booking.customer.user_id != actor.pk:
            raise BusinessError("Penitipan tidak tersedia.")
        if booking.status != "IN_SERVICE" or not stay.unit_id:
            raise BusinessError("Perpanjangan tersedia selama hewan masih menginap.")
        if ExtensionRequest.objects.filter(
            stay=stay, status__in={"SUBMITTED", "APPROVED_AWAITING_PAYMENT", "NEEDS_ATTENTION"}
        ).exists():
            raise BusinessError("Masih ada permintaan perpanjangan yang belum selesai.")
        if (
            requested_checkout_at <= booking.ends_at
            or requested_checkout_at - booking.starts_at > timedelta(days=60)
        ):
            raise BusinessError(
                "Waktu jemput baru harus setelah waktu sebelumnya, dengan total masa inap maksimal 60 hari."
            )
        local = timezone.localtime(requested_checkout_at)
        from core.models import StoreSettings

        store = StoreSettings.objects.get(pk=1)
        hours = store.opening_hours.get(str(local.weekday()))
        if not hours or not hours[0] <= local.strftime("%H:%M") < hours[1]:
            raise BusinessError("Pilih waktu jemput dalam jam operasional.")
        extra = nights_between(booking.starts_at, requested_checkout_at) - nights_between(
            booking.starts_at, booking.ends_at
        )
        if extra <= 0:
            raise BusinessError("Perpanjangan minimal menambah satu malam pada tarif yang berlaku.")
        extension = ExtensionRequest.objects.create(
            stay=stay,
            requested_by=actor,
            old_checkout_at=booking.ends_at,
            requested_checkout_at=requested_checkout_at,
            base_booking_version=booking.version,
            extra_nights=extra,
            extra_amount_rp=extra * stay.nightly_rate_rp,
            status="SUBMITTED",
        )
        audit(
            actor,
            "boarding.extension_requested",
            extension,
            after={"new_checkout": str(requested_checkout_at)},
        )
        return extension


def review_extension(actor, extension, approve, reason=""):
    require_role(actor, OPS)
    if not approve and not reason.strip():
        raise BusinessError("Tuliskan alasan penolakan agar pelanggan dapat memahami keputusan.")
    try:
        with commerce_transaction():
            expire_capacity_holds()
            extension = (
                ExtensionRequest.objects.select_for_update(of=("self",))
                .select_related("stay__unit__resource")
                .get(pk=extension.pk)
            )
            stay = extension.stay
            booking = Booking.objects.select_for_update().get(pk=stay.booking_id)
            if extension.status == "NEEDS_ATTENTION" and not approve:
                from billing.models import Invoice
                from billing.services import fully_refunded

                invoice = Invoice.objects.filter(extension=extension, status="PAID").first()
                if not invoice or not fully_refunded(invoice):
                    raise BusinessError(
                        "Selesaikan refund penuh tagihan tambahan sebelum menutup pengajuan bermasalah."
                    )
                ResourceReservation.objects.filter(extension=extension, status="HELD").update(
                    status="RELEASED"
                )
            elif extension.status != "SUBMITTED":
                raise BusinessError("Permintaan sudah ditinjau.")
            extension.reviewed_by, extension.reviewed_at, extension.review_reason = (
                actor,
                timezone.now(),
                reason,
            )
            if not approve:
                extension.status = "REJECTED"
                extension.save()
                audit(actor, "boarding.extension_rejected", extension, reason=reason)
                return extension
            if (
                booking.status != "IN_SERVICE"
                or extension.base_booking_version != booking.version
                or extension.old_checkout_at != booking.ends_at
            ):
                raise BusinessError("Jadwal berubah. Tinjau ulang dengan pengajuan baru.")
            if not BoardingIntakeFile.objects.filter(
                stay=stay,
                is_active=True,
                verified_at__isnull=False,
                valid_until__gte=timezone.localdate(extension.requested_checkout_at),
            ).exists():
                raise BusinessError("Dokumen kesehatan perlu berlaku hingga waktu jemput baru.")
            Resource.objects.select_for_update().get(pk=stay.unit.resource_id)
            period = Range(
                booking.ends_at + timedelta(minutes=stay.cleaning_minutes),
                extension.requested_checkout_at + timedelta(minutes=stay.cleaning_minutes),
                "[)",
            )
            if ResourceReservation.objects.filter(
                resource=stay.unit.resource, status__in=BLOCKING, period__overlap=period
            ).exists():
                raise BusinessError(
                    "Unit sudah terpakai pada periode tambahan. Tolak dengan alasan atau hubungi pelanggan."
                )
            expiry = min(timezone.now() + timedelta(minutes=30), booking.ends_at)
            if expiry <= timezone.now():
                raise BusinessError(
                    "Waktu jemput awal sudah lewat. Perlu penanganan langsung admin."
                )
            ResourceReservation.objects.create(
                resource=stay.unit.resource,
                booking=booking,
                extension=extension,
                period=period,
                kind="EXTENSION",
                status="HELD",
                expires_at=expiry,
            )
            extension.status, extension.payment_expires_at = "APPROVED_AWAITING_PAYMENT", expiry
            extension.save()
            from billing.models import Invoice
            from billing.services import issue_invoice

            parent = Invoice.objects.get(booking=booking, stage="INITIAL")
            issue_invoice(
                extension,
                booking.customer,
                extension.extra_amount_rp,
                f"Tambahan {extension.extra_nights} malam",
                expiry,
                parent=parent,
            )
            audit(
                actor,
                "boarding.extension_approved",
                extension,
                after={"extra_amount_rp": extension.extra_amount_rp},
            )
            return extension
    except IntegrityError:
        raise BusinessError("Kapasitas berubah. Muat ulang dan tinjau permintaan lagi.")


def activate_extension(extension):
    """Called under the commerce lock only after verified funds were recorded."""
    extension = (
        ExtensionRequest.objects.select_for_update(of=("self",))
        .select_related("stay__unit")
        .get(pk=extension.pk)
    )
    if extension.status == "ACTIVE":
        return True
    booking = Booking.objects.select_for_update().get(pk=extension.stay.booking_id)
    hold = (
        ResourceReservation.objects.select_for_update()
        .filter(extension=extension, status="HELD")
        .first()
    )
    if (
        extension.status != "APPROVED_AWAITING_PAYMENT"
        or not hold
        or hold.expires_at <= timezone.now()
        or booking.version != extension.base_booking_version
        or booking.status != "IN_SERVICE"
        or booking.ends_at != extension.old_checkout_at
    ):
        ResourceReservation.objects.filter(extension=extension, status="HELD").update(
            status="RELEASED"
        )
        extension.status = "NEEDS_ATTENTION"
        extension.save()
        return False
    original = ResourceReservation.objects.select_for_update().get(
        booking=booking,
        extension__isnull=True,
        resource=extension.stay.unit.resource,
        status="IN_USE",
    )
    hold.status = "RELEASED"  # Release the adjacent segment before expanding the original range.
    hold.save(update_fields=["status", "updated_at"])
    original.period = Range(
        original.period.lower,
        extension.requested_checkout_at + timedelta(minutes=extension.stay.cleaning_minutes),
        "[)",
    )
    original.save(update_fields=["period", "updated_at"])
    booking.ends_at, booking.version = extension.requested_checkout_at, booking.version + 1
    booking.price_snapshot_rp += extension.extra_amount_rp
    booking.save()
    extension.status, extension.activated_at = "ACTIVE", timezone.now()
    extension.save()
    from engagement.services import sync_booking_reminders

    sync_booking_reminders(booking)
    audit(None, "boarding.extension_activated", extension, after={"checkout": str(booking.ends_at)})
    return True


def stay_transition(actor, stay, action):
    require_role(actor, OPS | {"CARETAKER"})
    with commerce_transaction():
        stay = BoardingStay.objects.select_for_update().get(pk=stay.pk)
        booking = Booking.objects.select_for_update().get(pk=stay.booking_id)
        if active_role(actor) == "CARETAKER" and stay.caretaker_id != actor.pk:
            raise BusinessError("Penitipan belum ditugaskan kepada Anda.")
        now = timezone.now()
        if action == "checkin" and booking.status == "CONFIRMED":
            if not BoardingIntakeFile.objects.filter(
                stay=stay,
                is_active=True,
                verified_at__isnull=False,
                valid_until__gte=timezone.localdate(booking.ends_at),
            ).exists():
                raise BusinessError(
                    "Dokumen kesehatan terbaru perlu diverifikasi sebelum check-in."
                )
            if now < booking.starts_at - timedelta(minutes=30) or now >= booking.ends_at:
                raise BusinessError(
                    "Check-in tersedia mulai 30 menit sebelum jadwal, selama masa inap belum berakhir."
                )
            stay.checked_in_at, booking.status = now, "IN_SERVICE"
            ResourceReservation.objects.filter(booking=booking, status="CONFIRMED").update(
                status="IN_USE"
            )
        elif action == "checkout" and booking.status == "IN_SERVICE":
            if ExtensionRequest.objects.filter(
                stay=stay, status__in={"SUBMITTED", "APPROVED_AWAITING_PAYMENT", "NEEDS_ATTENTION"}
            ).exists():
                raise BusinessError("Selesaikan permintaan perpanjangan terlebih dahulu.")
            stay.checked_out_at, booking.completed_at, booking.status = now, now, "COMPLETED"
            # Keep the room blocked through the actual cleaning time; release only when the worker sees the upper bound.
            for reservation in ResourceReservation.objects.filter(
                booking=booking, extension__isnull=True, status="IN_USE"
            ):
                reservation.period = Range(
                    reservation.period.lower,
                    max(reservation.period.upper, now + timedelta(minutes=stay.cleaning_minutes)),
                    "[)",
                )
                reservation.save()
        else:
            raise BusinessError("Perubahan status penitipan tidak sesuai tahap saat ini.")
        stay.save()
        booking.save()
        from engagement.services import sync_booking_reminders

        sync_booking_reminders(booking)
        audit(actor, f"boarding.{action}", stay)


def add_care_log(actor, stay, feeding, condition, activity, publish=True):
    require_role(actor, OPS | {"CARETAKER"})
    with commerce_transaction():
        stay = BoardingStay.objects.select_for_update().get(pk=stay.pk)
        Booking.objects.select_for_update().get(pk=stay.booking_id)
        if active_role(actor) == "CARETAKER" and stay.caretaker_id != actor.pk:
            raise BusinessError("Penitipan belum ditugaskan kepada Anda.")
        if stay.booking.status != "IN_SERVICE" or not feeding.strip() or not condition.strip():
            raise BusinessError("Isi kondisi dan makan untuk hewan yang sedang menginap.")
        return CareLog.objects.create(
            stay=stay,
            author=actor,
            recorded_at=timezone.now(),
            feeding=feeding,
            condition=condition,
            activity=activity,
            published_at=timezone.now() if publish else None,
        )


def replace_intake(actor, stay, upload, document=None):
    from core.files import upload_transaction

    require_role(actor, OPS | {"CUSTOMER"})
    if active_role(actor) == "CUSTOMER" and stay.booking.customer.user_id != actor.pk:
        raise BusinessError("Dokumen ini bukan milik akun Anda.")
    if not upload:
        raise BusinessError("Pilih dokumen kesehatan terlebih dahulu.")
    with upload_transaction(actor, upload, "BOARDING_INTAKE") as file:
        # Upload and metadata are rolled back together on any validation failure.
        booking = Booking.objects.select_for_update().get(pk=stay.booking_id)
        if booking.status not in {"SUBMITTED", "HELD", "CONFIRMED", "IN_SERVICE"}:
            raise BusinessError("Dokumen tidak dapat diubah setelah layanan ditutup.")
        if document:
            document = BoardingIntakeFile.objects.select_for_update().get(
                pk=document.pk, stay=stay, is_active=True
            )
            document.is_active = False
            document.save(update_fields=["is_active", "updated_at"])
        revised = BoardingIntakeFile.objects.create(stay=stay, file=file, document_type="HEALTH")
        audit(
            actor,
            "boarding.intake_replaced" if document else "boarding.intake_uploaded",
            revised,
            after={"previous_document": str(document.pk) if document else None},
        )
        return revised
