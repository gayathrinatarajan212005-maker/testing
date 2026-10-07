"""Business rules shared by the website and the REST API."""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import ai
from .models import Appointment, Notification, Service, ServiceHistory, Token

ACTIVE = ["WAITING", "CALLED", "SERVING"]


class QueueError(Exception):
    """A friendly, user-facing rule violation."""


def notify(user, message):
    Notification.objects.create(user=user, message=message)
    if user.email:
        send_mail("QueueLess AI update", message, None, [user.email], fail_silently=True)


def managed_services(user):
    if user.is_superuser:
        return Service.objects.select_related("provider")
    return (Service.objects.filter(Q(provider__owner=user) | Q(counters__staff=user))
            .select_related("provider").distinct())


# ---------------- tokens ----------------
@transaction.atomic
def issue_token(user, service, priority=0, appointment=None):
    if not service.active:
        raise QueueError("This service is not available.")
    if Token.objects.filter(customer=user, service=service, status__in=ACTIVE).exists():
        raise QueueError("You already have an active token for this service.")
    if appointment is None and settings.QUEUELESS_ENFORCE_HOURS and not service.provider.is_open_now():
        raise QueueError("This provider is closed right now. Book a slot instead.")
    if priority == 2 and not (hasattr(user, "profile") and user.profile.priority_eligible):
        raise QueueError("The priority lane is only for eligible customers (seniors, differently-abled, pregnant).")
    today = timezone.localdate()
    last = (Token.objects.select_for_update().filter(service=service, queue_date=today)
            .order_by("-token_number").first())
    return Token.objects.create(customer=user, service=service, token_number=last.token_number + 1 if last else 1,
                                queue_date=today, priority=max(priority, 1 if appointment else 0),
                                appointment=appointment)


@transaction.atomic
def call_next(service, counter=None):
    sweep_expired(service)
    token = (Token.objects.select_for_update().filter(service=service, status="WAITING")
             .order_by("-priority", "created_at").first())
    if not token:
        raise QueueError("No customers are waiting.")
    token.status, token.called_at, token.counter = "CALLED", timezone.now(), counter
    token.save()
    where = f" at {counter.name}" if counter else ""
    notify(token.customer, f"Your token {token.display_token} is called{where}. Please proceed now.")
    notify_progress(service)
    return token


def start_service(token):
    if token.status != "CALLED":
        raise QueueError("Call the token first.")
    token.status, token.started_at = "SERVING", timezone.now()
    token.save(update_fields=["status", "started_at"])
    return token


@transaction.atomic
def complete(token):
    if token.status not in ("CALLED", "SERVING"):
        raise QueueError("Only called or serving tokens can be completed.")
    now = timezone.now()
    token.status, token.completed_at = "COMPLETED", now
    start = token.started_at or token.called_at
    if start:
        token.actual_service_minutes = max(1, round((now - start).total_seconds() / 60))
    token.save()
    # Every completed service becomes a learning sample for the predictor.
    ServiceHistory.objects.create(service=token.service, created_at=now,
                                  minutes=token.actual_service_minutes or token.service.average_minutes)
    if token.appointment_id:
        Appointment.objects.filter(pk=token.appointment_id).update(status="COMPLETED")
    notify(token.customer, f"Thanks for using {token.service.provider.name}! Please rate your visit.")
    notify_progress(token.service)
    return token


@transaction.atomic
def mark_no_show(token, auto=False):
    if token.status not in ("WAITING", "CALLED"):
        raise QueueError("Token cannot be marked as no-show.")
    token.status, token.completed_at = "NO_SHOW", timezone.now()
    token.save(update_fields=["status", "completed_at"])
    if token.appointment_id:
        Appointment.objects.filter(pk=token.appointment_id).update(status="NO_SHOW")
    notify(token.customer, f"Token {token.display_token} was marked no-show" +
           (" (you did not arrive in time)." if auto else "."))
    notify_progress(token.service)
    return token


def escalate(token):
    if token.status != "WAITING":
        raise QueueError("Only waiting tokens can be escalated.")
    token.priority = 3
    token.save(update_fields=["priority"])
    notify(token.customer, f"{token.display_token} has been moved to the emergency lane.")
    notify_progress(token.service)
    return token


def cancel_token(token):
    if token.status != "WAITING":
        raise QueueError("Only waiting tokens can be cancelled.")
    token.status = "CANCELLED"
    token.save(update_fields=["status"])
    if token.appointment_id:
        Appointment.objects.filter(pk=token.appointment_id).update(status="CANCELLED")
    notify_progress(token.service)
    return token


def notify_progress(service):
    """'You are next' alerts, so customers can stay away from the counter until needed."""
    waiting = Token.objects.filter(service=service, status="WAITING").select_related("customer")
    for position, token in enumerate(waiting, start=1):
        if position <= 2 and not token.notified_soon:
            notify(token.customer, f"Almost your turn! {token.display_token} is #{position} in line at "
                                   f"{service.provider.name}. Please be nearby.")
            token.notified_soon = True
            token.save(update_fields=["notified_soon"])


def sweep_expired(service=None):
    """Self-healing queue: no-show if not arrived after grace time; stale bookings expire."""
    grace = timedelta(minutes=settings.QUEUELESS_NO_SHOW_GRACE_MINUTES)
    stale = Token.objects.filter(status="CALLED", called_at__lt=timezone.now() - grace)
    if service:
        stale = stale.filter(service=service)
    for token in stale:
        mark_no_show(token, auto=True)
    Appointment.objects.filter(status="BOOKED", slot_start__lt=timezone.now() - timedelta(hours=1)) \
        .update(status="NO_SHOW")


# ---------------- appointments ----------------
@transaction.atomic
def book_appointment(user, service, slot_start):
    day = timezone.localtime(slot_start).date()
    slot = next((s for s in ai.available_slots(service, day) if s["start"] == slot_start), None)
    if not slot or slot["remaining"] <= 0:
        raise QueueError("That slot is no longer available. Please pick another.")
    if Appointment.objects.filter(customer=user, status="BOOKED", slot_start__gte=timezone.now()).count() \
            >= settings.QUEUELESS_MAX_ACTIVE_BOOKINGS:
        raise QueueError("You have reached the limit of active bookings.")
    if Appointment.objects.filter(customer=user, service=service, slot_start=slot_start, status="BOOKED").exists():
        raise QueueError("You already booked this slot.")
    appt = Appointment.objects.create(customer=user, service=service, slot_start=slot_start)
    notify(user, f"Booked: {service.name} at {service.provider.name}, "
                 f"{timezone.localtime(slot_start):%a %d %b, %H:%M}.")
    return appt


def cancel_appointment(appt):
    if appt.status != "BOOKED":
        raise QueueError("Only booked appointments can be cancelled.")
    appt.status = "CANCELLED"
    appt.save(update_fields=["status"])
    return appt


@transaction.atomic
def check_in(appt):
    if appt.status != "BOOKED":
        raise QueueError("This appointment cannot be checked in.")
    if timezone.localtime(appt.slot_start).date() != timezone.localdate():
        raise QueueError("You can check in only on the day of your appointment.")
    token = issue_token(appt.customer, appt.service, priority=1, appointment=appt)
    appt.status = "CHECKED_IN"
    appt.save(update_fields=["status"])
    return token
