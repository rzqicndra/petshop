"""Present the configured weekly hours in the shop's own time zone."""

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

from scheduling.availability import opening_interval

DAY_NAMES = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


def opening_summary(store):
    if not store or not isinstance(store.opening_hours, dict) or not store.opening_hours:
        return {"published": False}
    try:
        zone = ZoneInfo(store.timezone or settings.TIME_ZONE)
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo(settings.TIME_ZONE)
    now = timezone.now().astimezone(zone)
    today = now.date()
    hours = opening_interval(store, today, zone)
    is_open = bool(hours and hours[0] <= now < hours[1])
    following = ""
    for offset in range(8):
        day = today + timedelta(days=offset)
        interval = opening_interval(store, day, zone)
        if interval and interval[0] > now:
            name = (
                "hari ini" if offset == 0 else "besok" if offset == 1 else DAY_NAMES[day.weekday()]
            )
            following = f"Buka {name} pukul {interval[0]:%H:%M}"
            break
    monday = today - timedelta(days=today.weekday())
    week = []
    for index, name in enumerate(DAY_NAMES):
        interval = opening_interval(store, monday + timedelta(days=index), zone)
        week.append(
            {
                "name": name,
                "hours": f"{interval[0]:%H:%M}–{interval[1]:%H:%M}" if interval else "Tutup",
                "today": index == today.weekday(),
            }
        )
    return {
        "published": True,
        "is_open": is_open,
        "today_hours": f"{hours[0]:%H:%M}–{hours[1]:%H:%M}" if hours else "Hari ini tutup",
        "next_opening": following,
        "zone": {"Asia/Jakarta": "WIB", "Asia/Makassar": "WITA", "Asia/Jayapura": "WIT"}.get(
            zone.key, zone.key
        ),
        "week": week,
    }
