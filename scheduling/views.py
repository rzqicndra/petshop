import uuid
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from accounts.permissions import roles_required, verified_login, active_role, OPS
from core.services import BusinessError
from core.selectors import visible_bookings
from core.files import store_upload, upload_transaction
from core.forms import OperationForm, MedicalForm, CareLogForm
from customers.models import Customer
from care.models import (
    Visit,
    MedicalRecordVersion,
    MedicalAttachment,
    GroomingJob,
    GroomingResultFile,
    ClinicalInternalNote,
)
from boarding.models import BoardingStay, ExtensionRequest, BoardingIntakeFile, CareLog, CareLogFile
from billing.models import Invoice
from .forms import BookingForm, ExtensionForm, RescheduleForm
from . import services


@roles_required("CUSTOMER")
def new_booking(request):
    customer = Customer.objects.get(user=request.user)
    form = BookingForm(
        request.POST or None,
        request.FILES or None,
        customer=customer,
        initial={"key": str(uuid.uuid4()), "package": request.GET.get("paket")},
    )
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            contact = data.get("emergency_contact")
            emergency = (
                {
                    "name": contact.name,
                    "phone": contact.phone,
                    "relationship": contact.relationship,
                    "consent": contact.contact_consent,
                }
                if contact
                else None
            )
            upload = data.get("document") if data["package"].service.kind == "BOARDING" else None
            with upload_transaction(request.user, upload, "BOARDING_INTAKE") as file:
                booking = services.create_booking(
                    request.user,
                    data["pet"],
                    data["package"],
                    data["starts_at"],
                    data["checkout_at"],
                    data["key"],
                    notes=data["notes"],
                    emergency=emergency,
                )
                if file and booking.kind_snapshot == "BOARDING":
                    stay = BoardingStay.objects.get(booking=booking)
                    BoardingIntakeFile.objects.get_or_create(
                        stay=stay, file=file, defaults={"document_type": "HEALTH"}
                    )
            messages.success(
                request,
                (
                    "Pengajuan dikirim untuk ditinjau."
                    if booking.status == "SUBMITTED"
                    else "Booking dibuat. Selesaikan pembayaran sebelum batas waktu."
                ),
            )
            return redirect("booking_detail", pk=booking.pk)
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "scheduling/new.html",
        {"form": form, "has_pets": form.fields["pet"].queryset.exists()},
    )


@verified_login
def bookings_list(request):
    qs = visible_bookings(request.user).order_by("-starts_at")
    if request.GET.get("q"):
        qs = qs.filter(code__icontains=request.GET["q"][:80])
    from django.core.paginator import Paginator

    return render(
        request,
        "scheduling/list.html",
        {"page": Paginator(qs, 20).get_page(request.GET.get("page"))},
    )


@verified_login
def booking_detail(request, pk):
    booking = get_object_or_404(visible_bookings(request.user), pk=pk)
    visit = Visit.objects.filter(booking=booking).first()
    job = GroomingJob.objects.filter(booking=booking).first()
    stay = BoardingStay.objects.select_related("unit", "caretaker").filter(booking=booking).first()
    is_doctor = (
        active_role(request.user) == "DOCTOR" and visit and visit.doctor_id == request.user.pk
    )
    is_groomer = (
        active_role(request.user) == "GROOMER" and job and job.groomer_id == request.user.pk
    )
    is_caretaker = (
        active_role(request.user) == "CARETAKER" and stay and stay.caretaker_id == request.user.pk
    )
    latest = (
        MedicalRecordVersion.objects.filter(visit=visit).order_by("-version_no").first()
        if is_doctor
        else None
    )
    initial_medical = (
        {
            field: getattr(latest, field)
            for field in (
                "complaint",
                "findings",
                "diagnosis",
                "treatment",
                "aftercare",
                "followup_at",
            )
        }
        if latest
        else {}
    )
    medical_form, care_form = MedicalForm(initial=initial_medical), CareLogForm()
    if request.method == "POST":
        try:
            from care import services as care
            from boarding import services as boarding

            action = request.POST.get("action")
            if action == "cancel":
                services.cancel_booking(
                    request.user, booking, request.POST.get("reason", "")[:2000]
                )
            elif action == "reschedule":
                form = RescheduleForm(request.POST)
                if not form.is_valid():
                    raise BusinessError("Pilih jadwal baru yang valid.")
                services.reschedule_booking(
                    request.user,
                    booking,
                    form.cleaned_data["starts_at"],
                    form.cleaned_data["version"],
                )
            elif action == "start":
                care.start_care(request.user, booking)
            elif action in {"medical_save", "medical_publish"} and visit:
                if not is_doctor:
                    from django.core.exceptions import PermissionDenied

                    raise PermissionDenied
                medical_form = MedicalForm(request.POST, request.FILES)
                if not medical_form.is_valid():
                    raise BusinessError("Periksa isian rekam medis dan jadwal kontrol.")
                file = (
                    store_upload(request.user, medical_form.cleaned_data["file"], "MEDICAL")
                    if medical_form.cleaned_data.get("file")
                    else None
                )
                care.save_medical(
                    request.user,
                    visit,
                    medical_form.cleaned_data,
                    publish=action == "medical_publish",
                    file=file,
                )
            elif action == "grooming_ready" and job:
                if not is_groomer:
                    from django.core.exceptions import PermissionDenied

                    raise PermissionDenied
                file = (
                    store_upload(request.user, request.FILES["file"], "GROOMING")
                    if request.FILES.get("file")
                    else None
                )
                care.grooming_ready(
                    request.user, job, request.POST.get("result_note", "")[:4000], file
                )
            elif action == "finish":
                care.finish_care(request.user, booking)
            elif action in {"intake_upload", "intake_replace"} and stay:
                document = get_object_or_404(BoardingIntakeFile, pk=request.POST.get("document"), stay=stay, is_active=True) if action == "intake_replace" else None
                boarding.replace_intake(request.user, stay, request.FILES.get("file"), document)
            elif action == "intake_verify" and stay:
                form = OperationForm(request.POST)
                if not form.is_valid():
                    raise BusinessError("Periksa tanggal berlaku dokumen.")
                document = get_object_or_404(
                    BoardingIntakeFile, pk=request.POST.get("document"), stay=stay
                )
                boarding.verify_intake(
                    request.user,
                    document,
                    form.cleaned_data["valid_until"],
                    form.cleaned_data["reason"],
                )
            elif action == "stay_approve" and stay:
                form = OperationForm(request.POST)
                if (
                    not form.is_valid()
                    or not form.cleaned_data["unit"]
                    or not form.cleaned_data["staff"]
                ):
                    raise BusinessError("Pilih unit dan petugas penitipan.")
                boarding.approve_stay(
                    request.user, stay, form.cleaned_data["unit"], form.cleaned_data["staff"]
                )
            elif action == "stay_reject" and stay:
                boarding.reject_stay(request.user, stay, request.POST.get("reason", "")[:2000])
            elif action in {"checkin", "checkout"} and stay:
                boarding.stay_transition(request.user, stay, action)
            elif action == "extend" and stay:
                form = ExtensionForm(request.POST)
                if not form.is_valid():
                    raise BusinessError("Pilih waktu jemput baru yang valid.")
                boarding.request_extension(
                    request.user, stay, form.cleaned_data["requested_checkout_at"]
                )
            elif action in {"extension_approve", "extension_reject"} and stay:
                extension = get_object_or_404(
                    ExtensionRequest, pk=request.POST.get("extension"), stay=stay
                )
                boarding.review_extension(
                    request.user,
                    extension,
                    action == "extension_approve",
                    request.POST.get("reason", "")[:2000],
                )
            elif action == "care_log" and stay:
                care_form = CareLogForm(request.POST, request.FILES)
                if not care_form.is_valid():
                    raise BusinessError("Lengkapi kondisi serta makan dan minum hewan.")
                log = boarding.add_care_log(
                    request.user,
                    stay,
                    care_form.cleaned_data["feeding"],
                    care_form.cleaned_data["condition"],
                    care_form.cleaned_data["activity"],
                )
                if care_form.cleaned_data.get("file"):
                    file = store_upload(
                        request.user, care_form.cleaned_data["file"], "BOARDING_LOG"
                    )
                    CareLogFile.objects.create(care_log=log, file=file)
            else:
                raise BusinessError("Tindakan tidak tersedia.")
            messages.success(request, "Data layanan diperbarui.")
            return redirect("booking_detail", pk=pk)
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
    records = (
        MedicalRecordVersion.objects.filter(visit=visit).order_by("-version_no")
        if visit
        else MedicalRecordVersion.objects.none()
    )
    if not is_doctor:
        records = records.filter(published_at__isnull=False)
    logs = (
        CareLog.objects.filter(stay=stay).order_by("-recorded_at")
        if stay
        else CareLog.objects.none()
    )
    if active_role(request.user) == "CUSTOMER":
        logs = logs.filter(published_at__isnull=False)
    for record in records:
        record.attachments = list(
            MedicalAttachment.objects.filter(record_version=record).select_related("file")
        )
    for log in logs:
        log.files = list(CareLogFile.objects.filter(care_log=log).select_related("file"))
    extensions = (
        list(ExtensionRequest.objects.filter(stay=stay).order_by("-created_at")) if stay else []
    )
    for extension in extensions:
        extension.invoice = Invoice.objects.filter(extension=extension).first()
    from accounts.models import User
    from boarding.models import BoardingUnit
    from engagement.models import Review

    return render(
        request,
        "scheduling/detail.html",
        {
            "booking": booking,
            "visit": visit,
            "job": job,
            "stay": stay,
            "records": records,
            "internal_notes": (
                ClinicalInternalNote.objects.filter(visit=visit).order_by("-created_at")
                if is_doctor
                else []
            ),
            "grooming_files": (
                GroomingResultFile.objects.filter(job=job).select_related("file") if job else []
            ),
            "invoice": Invoice.objects.filter(booking=booking).first(),
            "extensions": extensions,
            "intake_files": (
                BoardingIntakeFile.objects.filter(stay=stay, is_active=True).select_related("file") if stay else []
            ),
            "care_logs": logs,
            "medical_form": medical_form,
            "care_form": care_form,
            "extension_form": ExtensionForm(),
            "reschedule_form": RescheduleForm(initial={"version": booking.version}),
            "is_doctor": is_doctor,
            "is_groomer": is_groomer,
            "is_caretaker": is_caretaker,
            "can_operate": active_role(request.user) in OPS,
            "review": Review.objects.filter(booking=booking).first(),
            "units": BoardingUnit.objects.filter(is_active=True, species=booking.pet.species),
            "caretakers": User.objects.filter(is_active=True, groups__name="CARETAKER"),
        },
    )
