"""Database-aware adaptive intelligence built on engine.py."""
from collections import Counter as Tally, defaultdict
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from . import engine
from .models import Appointment, Provider, ServiceHistory, Token

RANK = {"Low": 0, "Medium": 1, "High": 2}


# ---------- 1. learning the real service speed ----------
def service_stats(service, hour=None):
    hour = timezone.localtime().hour if hour is None else hour
    rows = list(ServiceHistory.objects.filter(service=service).order_by("-created_at")[:80])
    rows.reverse()
    return engine.estimate_service_time([r.minutes for r in rows], [r.hour for r in rows],
                                        hour, service.average_minutes)


def _counts(service, token=None):
    waiting = Token.objects.filter(service=service, status="WAITING")
    in_service = Token.objects.filter(service=service, status__in=["CALLED", "SERVING"])
    if token is not None:  # only people who will be served BEFORE this token
        waiting = waiting.filter(Q(priority__gt=token.priority) |
                                 Q(priority=token.priority, created_at__lt=token.created_at))
        in_service = in_service.exclude(pk=token.pk)
    return waiting.count(), in_service.count()


# ---------- 2. explainable wait prediction ----------
def predict(token):
    service, stats = token.service, service_stats(token.service)
    counters = service.active_counters
    if token.status in ("CALLED", "SERVING"):
        return dict(minutes=0, low=0, high=0, position=0, ahead=0, counters=counters,
                    avg_service=round(stats["avg"], 1), confidence=engine.confidence_label(stats["samples"]),
                    samples=stats["samples"], explanation=["You are being served / called now."])
    ahead, in_service = _counts(service, token)
    w = engine.wait_estimate(ahead, in_service, counters, stats["avg"], stats["sd"])
    why = [f"{ahead} customer(s) are ahead of you" + (" (priority lanes are served first)." if token.priority == 0 else "."),
           f"Learned average service time is {stats['avg']:.1f} min from {stats['samples']} recent services.",
           f"{counters} counter(s) are working in parallel, so the wait is divided across them."]
    if abs(stats["factor"] - 1) > 0.05:
        why.append(f"This hour is usually {'slower' if stats['factor'] > 1 else 'faster'} "
                   f"(x{stats['factor']:.2f}), so the estimate was adjusted.")
    return dict(minutes=w["minutes"], low=w["low"], high=w["high"], position=ahead + 1, ahead=ahead,
                counters=counters, avg_service=round(stats["avg"], 1),
                confidence=engine.confidence_label(stats["samples"]), samples=stats["samples"],
                explanation=why)


def new_joiner_wait(service):
    """Live status for a customer who joined right now (used on provider cards)."""
    stats = service_stats(service)
    waiting, in_service = _counts(service)
    w = engine.wait_estimate(waiting, in_service, service.active_counters, stats["avg"], stats["sd"])
    return dict(minutes=w["minutes"], waiting=waiting, in_service=in_service, counters=service.active_counters)


# ---------- 3. crowd forecasting ----------
def crowd_forecast(service, weekday=None):
    now = timezone.localtime()
    weekday = now.weekday() if weekday is None else weekday
    counts, days = defaultdict(int), set()
    since = now - timedelta(days=56)
    for created in Token.objects.filter(service=service, created_at__gte=since).values_list("created_at", flat=True):
        local = timezone.localtime(created)
        if local.weekday() == weekday:
            counts[local.hour] += 1
            days.add(local.date())
    n = max(1, len(days))
    p = service.provider
    hours = list(range(p.open_time.hour, max(p.close_time.hour, p.open_time.hour + 1)))
    values = [counts[h] / n for h in hours]
    levels = engine.crowd_levels(values)
    top = max(values) or 1
    return [dict(hour=h, label=f"{h:02d}:00", expected=round(v, 1), level=lv,
                 pct=max(8, int(v / top * 100)), now=(h == now.hour and weekday == now.weekday()))
            for h, v, lv in zip(hours, values, levels)]


def best_time(service):
    forecast = crowd_forecast(service)
    hour = timezone.localtime().hour
    future = [x for x in forecast if x["hour"] >= hour] or forecast
    return min(future, key=lambda x: (x["expected"], x["hour"]))


def crowd_now(service):
    hour = timezone.localtime().hour
    return next((x["level"] for x in crowd_forecast(service) if x["hour"] == hour), "Low")


# ---------- 4. smart slot booking ----------
def slot_length(service):
    return max(10, int(round(service.average_minutes / 5.0)) * 5)


def available_slots(service, day):
    tz = timezone.get_current_timezone()
    p, length = service.provider, slot_length(service)
    start = timezone.make_aware(datetime.combine(day, p.open_time), tz)
    end = timezone.make_aware(datetime.combine(day, p.close_time), tz)
    booked = Tally(a.slot_start for a in Appointment.objects.filter(
        service=service, status__in=["BOOKED", "CHECKED_IN"], slot_start__gte=start, slot_start__lt=end))
    capacity = service.active_counters
    levels = {x["hour"]: x["level"] for x in crowd_forecast(service, day.weekday())}
    slots, cur, now = [], start, timezone.now()
    while cur + timedelta(minutes=length) <= end:
        if cur > now:
            local = timezone.localtime(cur)
            slots.append(dict(start=cur, iso=cur.isoformat(), label=local.strftime("%H:%M"),
                              remaining=capacity - booked.get(cur, 0), level=levels.get(local.hour, "Low")))
        cur += timedelta(minutes=length)
    open_slots = [s for s in slots if s["remaining"] > 0]
    if open_slots:   # recommend the least crowded free slot
        min(open_slots, key=lambda s: (RANK[s["level"]], s["start"]))["recommended"] = True
    return slots


# ---------- 5. customer reliability ----------
def no_show_risk(user):
    ns = Token.objects.filter(customer=user, status="NO_SHOW").count()
    done = Token.objects.filter(customer=user, status="COMPLETED").count()
    ghost = Appointment.objects.filter(customer=user, status="NO_SHOW", token__isnull=True).count()
    return engine.no_show_risk(ns + ghost, done + ns + ghost)


# ---------- 6. proactive staffing advice ----------
def staffing_advice(service):
    stats, live = service_stats(service), new_joiner_wait(service)
    tips = engine.staffing_advice(live["minutes"], live["waiting"], service.active_counters,
                                  service.counters.count(), stats["slow"], stats["recent_avg"], stats["older_avg"])
    return [dict(level=lv, text=t) for lv, t in tips]


def daily_summary(service):
    today = timezone.localdate()
    qs = Token.objects.filter(service=service, queue_date=today)
    done = qs.filter(status="COMPLETED")
    mins = [t.actual_service_minutes for t in done if t.actual_service_minutes]
    return dict(total=qs.count(), served=done.count(), no_shows=qs.filter(status="NO_SHOW").count(),
                avg=round(sum(mins) / len(mins), 1) if mins else None)


# ---------- 7. smart provider ranking ----------
def provider_cards(q="", category=""):
    qs = Provider.objects.filter(services__active=True)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(area__icontains=q) | Q(services__name__icontains=q))
    if category:
        qs = qs.filter(category=category)
    cards = []
    for p in qs.distinct():
        rows = [(s, new_joiner_wait(s)) for s in p.services.filter(active=True)]
        best_wait = min(w["minutes"] for _, w in rows)
        rating = p.avg_rating
        cards.append(dict(provider=p, services=rows, best_wait=best_wait, rating=rating,
                          score=round((rating or 3.5) * 20 - best_wait)))
    cards.sort(key=lambda c: -c["score"])
    return cards
