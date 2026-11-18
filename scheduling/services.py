from collections import defaultdict
from datetime import timedelta
from math import ceil
from django.db import IntegrityError
from django.utils import timezone
from psycopg.types.range import Range

from accounts.permissions import require_role, active_role, OPS
from core.services import BusinessError, commerce_transaction, code, audit, emit, idempotent
from customers.models import Customer, Pet
from .models import (
    ServicePackage,
    PackageSpecies,
    PackageResource,
    Resource,
    StaffShift,
    Booking,
    ResourceReservation,
)

BLOCKING = {"HELD", "CONFIRMED", "IN_USE", "BLOCKED"}
BOOKING_ACTIVE = {"AWAITING_PAYMENT", "CONFIRMED", "IN_SERVICE", "READY_PICKUP"}


def customer_for(user):
    return Customer.objects.get(user=user, is_active=True)


def validate_time(start, end, kind):
    if (
        not timezone.is_aware(start)
        or not timezone.is_aware(end)
        or start <= timezone.now()
        or start >= end
    ):
        raise BusinessError("Pilih jadwal mendatang dengan waktu selesai setelah waktu mulai.")
    if end - start > timedelta(days=60):
        raise BusinessError("Durasi maksimal satu Booking adalah 60 hari.")
    from core.models import StoreSettings

    store = StoreSettings.objects.filter(pk=1).first()
    hours = store.opening_hours.get(str(timezone.localtime(start).weekday())) if store else None
    if not hours:
        raise BusinessError("Toko tutup pada hari tersebut.")
    local = timezone.localtime(start)
    lo, hi = hours
    if not (lo <= local.strftime("%H:%M") < hi):
        raise BusinessError("Waktu mulai berada di luar jam operasional.")
    if kind != "BOARDING" and (
        timezone.localdate(end) != timezone.localdate(start)
        or timezone.localtime(end).strftime("%H:%M") > hi
    ):
        raise BusinessError("Layanan harus selesai dalam jam operasional.")
    if kind == "BOARDING":
        end_store_hours = store.opening_hours.get(str(timezone.localtime(end).weekday()))
        if not end_store_hours or not (
            end_store_hours[0] <= timezone.localtime(end).strftime("%H:%M") < end_store_hours[1]
        ):
            raise BusinessError("Waktu jemput harus berada dalam jam operasional.")


def expire_capacity_holds():
    # Called only under the shared commerce transaction. Payment callbacks acquire the same lock.
    now = timezone.now()
    ResourceReservation.objects.filter(status="HELD", expires_at__lte=now).update(status="EXPIRED")
    from engagement.models import Reminder

    for old in Booking.objects.select_for_update().filter(
        status="AWAITING_PAYMENT", expires_at__lte=now
    ):
        old.status = "EXPIRED"
        old.version += 1
        old.save(update_fields=["status", "version", "updated_at"])
        Reminder.objects.filter(booking=old, status="PENDING").update(status="CANCELED")


def allocate(package, booking, expires_at):
    pools = defaultdict(list)
    for entry in (
        PackageResource.objects.select_related("resource__staff_user")
        .filter(package=package, resource__is_active=True)
        .order_by("resource_id")
    ):
        pools[entry.pool].append(entry.resource)
    if not pools or "STAFF" not in pools:
        raise BusinessError("Sumber daya layanan belum dikonfigurasi. Hubungi CS.")
    period = Range(
        booking.starts_at, booking.ends_at + timedelta(minutes=package.buffer_minutes), "[)"
    )
    selected = []
    for pool, resources in sorted(pools.items()):
        chosen = None
        for candidate in resources:
            resource = Resource.objects.select_for_update().get(pk=candidate.pk)
            if resource.kind == "STAFF":
                expected_role = "DOCTOR" if booking.kind_snapshot == "VET" else "GROOMER"
                if (
                    not resource.staff_user
                    or not resource.staff_user.is_active
                    or not resource.staff_user.groups.filter(name=expected_role).exists()
                ):
                    continue
                if not StaffShift.objects.filter(
                    resource=resource,
                    is_available=True,
                    starts_at__lte=period.lower,
                    ends_at__gte=period.upper,
                ).exists():
                    continue
                if StaffShift.objects.filter(
                    resource=resource,
                    is_available=False,
                    starts_at__lt=period.upper,
                    ends_at__gt=period.lower,
                ).exists():
                    continue
            if ResourceReservation.objects.filter(
                resource=resource, status__in=BLOCKING, period__overlap=period
            ).exists():
                continue
            chosen = resource
            break
        if not chosen:
            raise BusinessError("Jadwal penuh atau staf tidak bertugas. Pilih waktu lain.")
        ResourceReservation.objects.create(
            resource=chosen,
            booking=booking,
            period=period,
            kind=pool,
            status="HELD",
            expires_at=expires_at,
        )
        selected.append(chosen)
    return selected


def create_booking(
    actor,
    pet,
    package,
    starts_at,
    checkout_at=None,
    key=None,
    customer=None,
    notes="",
    emergency=None,
):
    require_role(actor, OPS | {"CUSTOMER"})
    customer = customer or customer_for(actor)
    if active_role(actor) == "CUSTOMER" and customer.user_id != actor.pk:
        raise BusinessError("Pelanggan tidak sesuai dengan akun.")
    if pet.customer_id != customer.pk or not pet.is_active:
        raise BusinessError("Hewan tidak tersedia pada profil pelanggan ini.")
    package = ServicePackage.objects.select_related("service").get(
        pk=package.pk, is_active=True, service__is_active=True
    )
    if not PackageSpecies.objects.filter(
        package=package, species=pet.species, species__is_active=True
    ).exists():
        raise BusinessError("Paket tidak sesuai dengan jenis hewan.")
    kind = package.service.kind
    if kind == "BOARDING":
        ends_at = checkout_at
        if not ends_at or ends_at - starts_at < timedelta(hours=12):
            raise BusinessError("Penitipan minimal 12 jam. Tentukan waktu jemput.")
        if not emergency or not emergency.get("phone") or not emergency.get("consent"):
            raise BusinessError("Kontak darurat dan persetujuan kontak diperlukan untuk penitipan.")
    else:
        if not package.duration_minutes or not package.price_rp or package.price_rp < 0:
            raise BusinessError("Paket layanan belum lengkap.")
        ends_at = starts_at + timedelta(minutes=package.duration_minutes)
    validate_time(starts_at, ends_at, kind)
    try:
        with commerce_transaction():
            record, created = idempotent(
                "booking",
                key,
                actor,
                {
                    "pet": pet.pk,
                    "package": package.pk,
                    "start": starts_at,
                    "end": ends_at,
                    "notes": notes,
                    "emergency": emergency,
                },
            )
            if not created and record.result_reference:
                return Booking.objects.get(pk=record.result_reference["id"])
            expire_capacity_holds()
            Pet.objects.select_for_update().get(pk=pet.pk)
            status = "SUBMITTED" if kind == "BOARDING" else "AWAITING_PAYMENT"
            expiry = None if kind == "BOARDING" else timezone.now() + timedelta(minutes=15)
            booking = Booking.objects.create(
                customer=customer,
                pet=pet,
                package=package,
                code=code("BK"),
                origin="ONLINE" if active_role(actor) == "CUSTOMER" else "WALK_IN",
                kind_snapshot=kind,
                status=status,
                starts_at=starts_at,
                ends_at=ends_at,
                price_snapshot_rp=package.price_rp or 0,
                expires_at=expiry,
                created_by=actor,
                version=1,
                policy_snapshot={"buffer_minutes": package.buffer_minutes, "notes": notes},
            )
            if kind == "BOARDING":
                from boarding.models import BoardingStay

                BoardingStay.objects.create(
                    booking=booking,
                    nightly_rate_rp=0,
                    cleaning_minutes=0,
                    emergency_snapshot=emergency,
                    intake_snapshot={"customer_notes": notes},
                )
            else:
                selected = allocate(package, booking, expiry)
                staff = next((r.staff_user for r in selected if r.kind == "STAFF"), None)
                from care.models import Visit, GroomingJob

                if kind == "VET":
                    Visit.objects.create(booking=booking, doctor=staff)
                else:
                    GroomingJob.objects.create(booking=booking, groomer=staff)
                from billing.services import issue_invoice

                issue_invoice(booking, customer, booking.price_snapshot_rp, package.name, expiry)
            audit(actor, "booking.created", booking, after={"status": booking.status, "kind": kind})
            emit(
                "booking.created", booking, {"customer_id": str(customer.pk), "code": booking.code}
            )
            record.status, record.result_reference = "DONE", {"id": str(booking.pk)}
            record.save()
            return booking
    except IntegrityError:
        raise BusinessError("Jadwal hewan atau sumber daya bentrok. Pilih jadwal lain.")


def cancel_booking(actor, booking, reason):
    require_role(actor, OPS | {"CUSTOMER"})
    if not reason.strip():
        raise BusinessError("Alasan pembatalan wajib diisi.")
    with commerce_transaction():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if active_role(actor) == "CUSTOMER" and booking.customer.user_id != actor.pk:
            raise BusinessError("Booking tidak tersedia.")
        if booking.status not in {
            "SUBMITTED",
            "AWAITING_PAYMENT",
            "CONFIRMED",
            "EXPIRED",
            "NEEDS_ATTENTION",
        }:
            raise BusinessError("Booking pada tahap ini tidak dapat dibatalkan.")
        from billing.models import Invoice

        from billing.services import fully_refunded

        paid = list(Invoice.objects.filter(booking=booking, status="PAID"))
        if paid and (active_role(actor) not in OPS or not all(fully_refunded(i) for i in paid)):
            raise BusinessError(
                "Booking sudah dibayar. Pembatalan dilakukan admin setelah refund penuh selesai."
            )
        ResourceReservation.objects.filter(booking=booking, status__in=BLOCKING).update(
            status="RELEASED"
        )
        booking.status, booking.version = "CANCELED", booking.version + 1
        booking.save()
        Invoice.objects.filter(booking=booking, status="UNPAID").update(status="VOID")
        from engagement.models import Reminder

        Reminder.objects.filter(booking=booking, status="PENDING").update(status="CANCELED")
        audit(actor, "booking.canceled", booking, reason=reason)


def reschedule_booking(actor, booking, starts_at, expected_version):
    require_role(actor, OPS | {"CUSTOMER"})
    try:
        with commerce_transaction():
            booking = (
                Booking.objects.select_for_update()
                .select_related("package__service")
                .get(pk=booking.pk)
            )
            if active_role(actor) == "CUSTOMER" and booking.customer.user_id != actor.pk:
                raise BusinessError("Booking tidak tersedia.")
            if (
                booking.kind_snapshot == "BOARDING"
                or booking.status != "CONFIRMED"
                or booking.version != expected_version
            ):
                raise BusinessError(
                    "Jadwal tidak dapat diubah pada tahap ini. Muat ulang detail Booking."
                )
            ends_at = starts_at + timedelta(minutes=booking.package.duration_minutes)
            validate_time(starts_at, ends_at, booking.kind_snapshot)
            expire_capacity_holds()
            ResourceReservation.objects.filter(booking=booking, status__in=BLOCKING).update(
                status="RELEASED"
            )
            booking.starts_at, booking.ends_at, booking.version = (
                starts_at,
                ends_at,
                booking.version + 1,
            )
            booking.save()
            selected = allocate(booking.package, booking, timezone.now() + timedelta(minutes=15))
            ResourceReservation.objects.filter(booking=booking, status="HELD").update(
                status="CONFIRMED", expires_at=None
            )
            staff = next(r.staff_user for r in selected if r.kind == "STAFF")
            from care.models import Visit, GroomingJob

            Visit.objects.filter(booking=booking).update(doctor=staff)
            GroomingJob.objects.filter(booking=booking).update(groomer=staff)
            from engagement.services import sync_booking_reminders

            sync_booking_reminders(booking)
            audit(
                actor,
                "booking.rescheduled",
                booking,
                after={"start": str(starts_at), "version": booking.version},
            )
    except IntegrityError:
        raise BusinessError("Jadwal baru bentrok. Jadwal sebelumnya tetap dipertahankan.")
