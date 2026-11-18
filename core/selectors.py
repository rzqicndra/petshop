from django.db.models import Q
from django.http import Http404
from accounts.permissions import active_role, READ_ALL
from scheduling.models import Booking
from orders.models import Order


def visible_bookings(user):
    qs = Booking.objects.select_related("customer", "pet__species", "package__service")
    role = active_role(user)
    if role in READ_ALL:
        return qs
    if role == "CUSTOMER":
        return qs.filter(customer__user=user)
    if role == "DOCTOR":
        from care.models import Visit

        return qs.filter(pk__in=Visit.objects.filter(doctor=user).values("booking_id"))
    if role == "GROOMER":
        from care.models import GroomingJob

        return qs.filter(pk__in=GroomingJob.objects.filter(groomer=user).values("booking_id"))
    if role == "CARETAKER":
        from boarding.models import BoardingStay

        return qs.filter(pk__in=BoardingStay.objects.filter(caretaker=user).values("booking_id"))
    return qs.none()


def visible_orders(user):
    qs = Order.objects.select_related("customer", "selected_quote")
    return (
        qs
        if active_role(user) in READ_ALL
        else qs.filter(customer__user=user) if active_role(user) == "CUSTOMER" else qs.none()
    )
