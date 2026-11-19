"""Read the same shifts, holds and facilities used when reserving an appointment."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone
from psycopg.types.range import Range

from core.models import StoreSettings
from .models import Booking, PackageResource, Resource, ResourceReservation, StaffShift

BOOK_AHEAD_DAYS = 7
STEP = timedelta(minutes=15)
MAX_MINUTES = {"VET": 60, "GROOMING": 180}
BLOCKING = {"HELD", "CONFIRMED", "IN_USE", "BLOCKED"}


def store_calendar():
    store = StoreSettings.objects.filter(pk=1).first()
    try:
        zone = (
            ZoneInfo(store.timezone or settings.TIME_ZONE)
            if store
            else ZoneInfo(settings.TIME_ZONE)
        )
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo(settings.TIME_ZONE)
    return store, zone


def opening_interval(store, day, zone):
    calendar = store.opening_hours if store and isinstance(store.opening_hours, dict) else {}
    hours = calendar.get(str(day.weekday()))
    if not isinstance(hours, (list, tuple)) or len(hours) != 2:
        return None
    try:
        start, end = [datetime.combine(day, time.fromisoformat(value), zone) for value in hours]
    except (TypeError, ValueError):
        return None
    return (start, end) if start < end else None


def overlaps(intervals, start, end):
    return any(a < end and start < b for a, b in intervals)


class AppointmentCapacity:
    """Load one time range once, including every required resource pool."""

    def __init__(self, package, pet, lower, upper, *, now, exclude=None, lock=False):
        entries = list(PackageResource.objects.filter(package=package).order_by("resource_id"))
        ids = [entry.resource_id for entry in entries]
        if lock:
            # Lock in a consistent order before reading availability at final confirmation.
            list(
                Resource.objects.select_for_update()
                .filter(pk__in=ids)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
        resources = (
            Resource.objects.filter(pk__in=ids, is_active=True)
            .select_related("staff_user")
            .prefetch_related("staff_user__groups")
        )
        role = "DOCTOR" if package.service.kind == "VET" else "GROOMER"
        candidates = {}
        for resource in resources:
            if resource.kind == "STAFF" and (
                not resource.staff_user
                or not resource.staff_user.is_active
                or not any(group.name == role for group in resource.staff_user.groups.all())
            ):
                continue
            candidates[resource.pk] = resource
        self.pools = defaultdict(list)
        for entry in entries:
            pool = self.pools[entry.pool]
            resource = candidates.get(entry.resource_id)
            if resource and (entry.pool != "STAFF" or resource.kind == "STAFF"):
                pool.append(resource)

        self.shifts = defaultdict(list)
        self.unavailable = defaultdict(list)
        for rid, yes, a, b in StaffShift.objects.filter(
            resource_id__in=ids, starts_at__lt=upper, ends_at__gt=lower
        ).values_list("resource_id", "is_available", "starts_at", "ends_at"):
            (self.shifts if yes else self.unavailable)[rid].append((a, b))
        reserved = ResourceReservation.objects.filter(
            resource_id__in=ids, status__in=BLOCKING, period__overlap=Range(lower, upper, "[)")
        ).exclude(status="HELD", expires_at__lte=now)
        visits = Booking.objects.filter(
            pet=pet,
            kind_snapshot__in=MAX_MINUTES,
            starts_at__lt=upper,
            ends_at__gt=lower,
            status__in={"HELD", "AWAITING_PAYMENT", "CONFIRMED", "IN_SERVICE", "READY_PICKUP"},
        ).exclude(status="AWAITING_PAYMENT", expires_at__lte=now)
        if exclude is not None:
            reserved = reserved.exclude(booking_id=exclude)
            visits = visits.exclude(pk=exclude)
        for rid, period in reserved.values_list("resource_id", "period"):
            self.unavailable[rid].append(
                (max(lower, period.lower or lower), min(upper, period.upper or upper))
            )
        self.pet_visits = list(visits.values_list("starts_at", "ends_at"))
        self.buffer = timedelta(minutes=package.buffer_minutes)

    def select(self, start, end):
        if "STAFF" not in self.pools or overlaps(self.pet_visits, start, end):
            return {}
        occupied_until = end + self.buffer
        selected = {}
        for pool, alternatives in self.pools.items():
            for resource in alternatives:
                if resource.kind == "STAFF" and not any(
                    a <= start and occupied_until <= b for a, b in self.shifts[resource.pk]
                ):
                    continue
                if not overlaps(self.unavailable[resource.pk], start, occupied_until):
                    selected[pool] = resource
                    break
            else:
                return {}
        return selected


def reschedule_window(booking, *, now=None, store=None):
    """Use one policy for the displayed choices and the locked booking mutation."""
    now = now or timezone.now()
    if store is None:
        store, _ = store_calendar()
    minutes = store.reschedule_notice_minutes if store else 120
    notice = timedelta(minutes=minutes)
    hours, remainder = divmod(minutes, 60)
    label = " ".join(
        part
        for part in (f"{hours} jam" if hours else "", f"{remainder} menit" if remainder else "")
        if part
    )
    cutoff = booking.starts_at - notice
    return {
        "allowed": booking.kind_snapshot in MAX_MINUTES
        and booking.status == "CONFIRMED"
        and now <= cutoff,
        "cutoff": cutoff,
        "minimum_start": now + notice,
        "notice": label,
    }


def slot_picker(package, pet, requested_day="", *, exclude=None):
    store, zone = store_calendar()
    now = timezone.now()
    today = now.astimezone(zone).date()
    days = []
    result = {"slot_days": days, "selected_day": None, "slots": [], "zone_name": zone.key}
    window = reschedule_window(exclude, now=now, store=store) if exclude else None
    if window and not window["allowed"]:
        return result
    if not package or not pet or package.service.kind not in MAX_MINUTES:
        return result
    if not (
        0 < (package.duration_minutes or 0) <= MAX_MINUTES[package.service.kind]
        and package.price_rp
    ):
        return result
    duration = timedelta(minutes=package.duration_minutes)
    lower = datetime.combine(today, time.min, zone)
    upper = lower + timedelta(days=BOOK_AHEAD_DAYS + 1, minutes=package.buffer_minutes)
    capacity = AppointmentCapacity(
        package, pet, lower, upper, now=now, exclude=exclude.pk if exclude else None
    )
    for offset in range(BOOK_AHEAD_DAYS + 1):
        day = today + timedelta(days=offset)
        hours = opening_interval(store, day, zone)
        if not hours:
            continue
        start, close = hours
        slots = []
        while start + duration <= close:
            end = start + duration
            if (
                start > now
                and (not window or start >= window["minimum_start"])
                and (not exclude or start != exclude.starts_at)
                and capacity.select(start, end)
            ):
                period_name = next(
                    label
                    for limit, label in ((12, "Pagi"), (15, "Siang"), (18, "Sore"), (24, "Malam"))
                    if start.hour < limit
                )
                slots.append(
                    {
                        "value": start.isoformat(),
                        "label": f"{start:%H:%M}–{end:%H:%M}",
                        "part": period_name,
                    }
                )
            start += STEP
        if slots:
            days.append({"date": day, "value": day.isoformat(), "slots": slots})
    if days:
        chosen = next((day for day in days if day["value"] == requested_day), days[0])
        result.update(selected_day=chosen["value"], slots=chosen["slots"])
    return result


def _available_spans(positive, negative):
    """Merge published shifts, then subtract breaks or closures."""
    spans = []
    for start, end in sorted(positive):
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    for a, b in negative:
        remaining = []
        for start, end in spans:
            if b <= start or end <= a:
                remaining.append((start, end))
            else:
                if start < a:
                    remaining.append((start, a))
                if b < end:
                    remaining.append((b, end))
        spans = remaining
    return spans


def public_timetable():
    store, zone = store_calendar()
    today = timezone.now().astimezone(zone).date()
    lower = datetime.combine(today, time.min, zone)
    upper = lower + timedelta(days=BOOK_AHEAD_DAYS + 1)
    staff = list(
        Resource.objects.filter(
            kind="STAFF",
            is_active=True,
            staff_user__is_active=True,
            staff_user__groups__name__in=["DOCTOR", "GROOMER", "CARETAKER"],
        )
        .distinct()
        .select_related("staff_user")
        .prefetch_related("staff_user__groups")
        .order_by("name", "pk")
    )
    shifts = defaultdict(list)
    breaks = defaultdict(list)
    for rid, yes, a, b in StaffShift.objects.filter(
        resource__in=staff, starts_at__lt=upper, ends_at__gt=lower
    ).values_list("resource_id", "is_available", "starts_at", "ends_at"):
        (shifts if yes else breaks)[rid].append((a, b))
    for rid, period in ResourceReservation.objects.filter(
        resource__in=staff, status="BLOCKED", period__overlap=Range(lower, upper, "[)")
    ).values_list("resource_id", "period"):
        breaks[rid].append((period.lower or lower, period.upper or upper))
    roles = {"DOCTOR": "Dokter hewan", "GROOMER": "Groomer", "CARETAKER": "Petugas penitipan"}
    roster = []
    for person in staff:
        title = " · ".join(roles[g.name] for g in person.staff_user.groups.all() if g.name in roles)
        roster.append(
            (
                person.staff_user.full_name or person.name or title,
                title,
                _available_spans(shifts[person.pk], breaks[person.pk]),
            )
        )
    days = []
    for offset in range(BOOK_AHEAD_DAYS + 1):
        day = today + timedelta(days=offset)
        hours = opening_interval(store, day, zone)
        people = []
        if hours:
            for name, title, spans in roster:
                times = []
                for a, b in spans:
                    start, end = max(a, hours[0]), min(b, hours[1])
                    if start < end:
                        times.append(f"{start.astimezone(zone):%H:%M}–{end.astimezone(zone):%H:%M}")
                if times:
                    people.append({"name": name, "role": title, "times": ", ".join(times)})
        days.append(
            {
                "day": day,
                "hours": f"{hours[0]:%H:%M}–{hours[1]:%H:%M}" if hours else "",
                "staff": people,
            }
        )
    return {
        "days": days,
        "hours_published": bool(store and store.opening_hours),
        "zone_name": zone.key,
    }
