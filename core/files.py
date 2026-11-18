"""Private, validated uploads. Files are served only by an authorization-aware view."""

import hashlib
import io
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from core.services import BusinessError, commerce_transaction
from .models import PrivateFile

Image.MAX_IMAGE_PIXELS = 12_000_000
MAX_FILE_SIZE = 5 * 1024 * 1024


@contextmanager
def upload_transaction(actor, upload, classification):
    """Commit a new attachment and its business object together; clean the blob on rollback."""
    file = None
    try:
        with commerce_transaction():
            file = store_upload(actor, upload, classification) if upload else None
            yield file
    except Exception:
        if file:
            try:
                FileSystemStorage(location=settings.PRIVATE_ROOT).delete(file.storage_key)
            except OSError:
                pass
        raise


def store_upload(actor, upload, classification):
    if not upload or upload.size > MAX_FILE_SIZE or upload.size == 0:
        raise BusinessError("Unggah foto atau PDF dengan ukuran maksimal 5 MB.")
    raw = upload.read(MAX_FILE_SIZE + 1)
    if len(raw) > MAX_FILE_SIZE:
        raise BusinessError("Ukuran berkas melebihi 5 MB.")
    try:
        if raw.startswith(b"%PDF-"):
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 50:
                raise ValueError
            root = reader.trailer["/Root"]
            if any(k in root for k in ("/OpenAction", "/AA", "/AcroForm")):
                raise ValueError
            names = root.get("/Names", {})
            if any(k in names for k in ("/JavaScript", "/EmbeddedFiles")):
                raise ValueError
            writer = PdfWriter()
            for page in reader.pages:
                for key in ("/Annots", "/AA", "/Metadata"):
                    if key in page:
                        del page[key]
                writer.add_page(page)
            buf = io.BytesIO()
            writer.write(buf)
            data, mime, ext = buf.getvalue(), "application/pdf", ".pdf"
        else:
            source = Image.open(io.BytesIO(raw))
            source.verify()
            source = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
            if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError
            source.thumbnail((2400, 2400))
            buf = io.BytesIO()
            source.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
            data, mime, ext = buf.getvalue(), "image/jpeg", ".jpg"
    except Exception:
        raise BusinessError(
            "Berkas tidak dapat diproses. Gunakan foto JPG/PNG atau PDF biasa tanpa formulir aktif."
        )
    key = f"{timezone_folder()}/{uuid.uuid4().hex}{ext}"
    storage = FileSystemStorage(location=settings.PRIVATE_ROOT)
    from django.core.files.base import ContentFile

    saved = storage.save(key, ContentFile(data))
    try:
        return PrivateFile.objects.create(
            uploaded_by=actor,
            storage_key=saved,
            original_name=Path(upload.name).name[:220],
            mime_type=mime,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            classification=classification,
            scan_status="VALIDATED",
        )
    except Exception:
        storage.delete(saved)
        raise


def timezone_folder():
    from django.utils import timezone

    return timezone.now().strftime("%Y/%m")


def can_read_file(user, file):
    from accounts.permissions import active_role, READ_ALL
    from customers.models import Pet
    from care.models import MedicalAttachment, GroomingResultFile
    from boarding.models import BoardingIntakeFile, CareLogFile
    from delivery.models import DeliveryAssignment
    from engagement.models import ReviewFile

    role = active_role(user)
    if not user.is_authenticated or not user.email_verified_at or file.purged_at:
        return False
    attached = False
    for pet in Pet.objects.filter(photo_file=file):
        attached = True
        if pet.customer.user_id == user.pk or role in READ_ALL:
            return True
        from scheduling.models import ResourceReservation

        if ResourceReservation.objects.filter(booking__pet=pet, resource__staff_user=user).exists():
            return True
    for a in MedicalAttachment.objects.select_related(
        "record_version__visit__booking__customer"
    ).filter(file=file):
        attached = True
        v = a.record_version
        if role == "DOCTOR" and v.visit.doctor_id == user.pk:
            return True
        if v.published_at and (v.visit.booking.customer.user_id == user.pk or role in READ_ALL):
            return True
    for a in GroomingResultFile.objects.select_related("job__booking__customer").filter(file=file):
        attached = True
        if (
            a.job.booking.customer.user_id == user.pk
            or role in READ_ALL
            or (role == "GROOMER" and a.job.groomer_id == user.pk)
        ):
            return True
    for a in BoardingIntakeFile.objects.select_related("stay__booking__customer").filter(file=file):
        attached = True
        if (
            a.stay.booking.customer.user_id == user.pk
            or role in READ_ALL
            or (role == "CARETAKER" and a.stay.caretaker_id == user.pk)
        ):
            return True
    for a in CareLogFile.objects.select_related("care_log__stay__booking__customer").filter(
        file=file
    ):
        attached = True
        log = a.care_log
        if (
            role in READ_ALL
            or (role == "CARETAKER" and log.stay.caretaker_id == user.pk)
            or (log.published_at and log.stay.booking.customer.user_id == user.pk)
        ):
            return True
    for a in DeliveryAssignment.objects.select_related("shipment__order__customer").filter(
        proof_file=file
    ):
        attached = True
        if (
            role in READ_ALL
            or a.courier_user_id == user.pk
            or a.shipment.order.customer.user_id == user.pk
        ):
            return True
    for a in ReviewFile.objects.select_related("review__customer").filter(file=file):
        attached = True
        if role in READ_ALL or a.review.customer.user_id == user.pk:
            return True
    return not attached and file.uploaded_by_id == user.pk
