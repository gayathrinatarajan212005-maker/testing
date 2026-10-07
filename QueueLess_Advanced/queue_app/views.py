from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import ai, workflow
from .forms import (CounterForm, JoinQueueForm, ProviderForm, RegisterForm, ReviewForm, ServiceForm)
from .models import Appointment, Counter, Profile, Provider, Review, Service, Token
from .workflow import ACTIVE, QueueError

ORDER = {"SERVING": 0, "CALLED": 1, "WAITING": 2}


def _flash(request, fn, *args, ok=None):
    """Run a workflow action; show its error or success message."""
    try:
        result = fn(*args)
    except QueueError as exc:
        messages.error(request, str(exc))
        return None
    if ok:
        messages.success(request, ok)
    return result


# ---------------- public pages ----------------
def home(request):
    ctx = {"cards": ai.provider_cards()[:3]}
    if request.user.is_authenticated:
        tokens = list(Token.objects.filter(customer=request.user, status__in=ACTIVE).select_related("service__provider"))
        for t in tokens:
            t.pred = ai.predict(t)
        ctx["tokens"] = tokens
        ctx["appointments"] = Appointment.objects.filter(
            customer=request.user, status="BOOKED", slot_start__gte=timezone.now()).select_related("service__provider")[:4]
    return render(request, "home.html", ctx)


def login_view(request):
    if request.method == "POST":
        user = authenticate(username=request.POST.get("username"), password=request.POST.get("password"))
        if user:
            login(request, user)
            return redirect(request.GET.get("next") or "home")
        messages.error(request, "Invalid username or password.")
    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("home")


def register_view(request):
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = User.objects.create_user(d["username"], d["email"], d["password"])
        Profile.objects.create(user=user, role=d["role"], priority_eligible=d["priority_eligible"])
        login(request, user)
        if d["role"] == "PROVIDER":
            messages.success(request, "Welcome! Now register your business.")
            return redirect("provider_setup")
        messages.success(request, "Account created. Find a service and skip the line!")
        return redirect("providers")
    return render(request, "register.html", {"form": form})


def providers(request):
    q, category = request.GET.get("q", "").strip(), request.GET.get("category", "")
    return render(request, "providers.html", {
        "cards": ai.provider_cards(q, category), "q": q, "category": category,
        "categories": Provider.CATEGORY_CHOICES})


def _parse_day(value):
    today = timezone.localdate()
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        return today
    return min(max(day, today), today + timedelta(days=6))


def provider_detail(request, pk):
    provider = get_object_or_404(Provider, pk=pk)
    day = _parse_day(request.GET.get("date"))
    services = [dict(service=s, live=ai.new_joiner_wait(s), forecast=ai.crowd_forecast(s),
                     best=ai.best_time(s), slots=ai.available_slots(s, day))
                for s in provider.services.filter(active=True)]
    today = timezone.localdate()
    days = [dict(iso=(today + timedelta(days=i)).isoformat(), label=(today + timedelta(days=i)).strftime("%a %d"))
            for i in range(7)]
    return render(request, "provider_detail.html", {
        "provider": provider, "services": services, "day": day, "days": days,
        "reviews": provider.reviews.select_related("customer")[:8], "review_form": ReviewForm()})


# ---------------- customer actions ----------------
@login_required
def join_queue(request):
    form = JoinQueueForm(request.POST or None, initial={"service": request.GET.get("service")})
    if request.method == "POST" and form.is_valid():
        token = _flash(request, workflow.issue_token, request.user, form.cleaned_data["service"],
                       int(form.cleaned_data["priority"]))
        if token:
            messages.success(request, f"Your token is {token.display_token}. Track it live below.")
            return redirect("token_detail", pk=token.pk)
    return render(request, "join.html", {"form": form})


@login_required
def token_detail(request, pk):
    token = get_object_or_404(Token.objects.select_related("service__provider"), pk=pk, customer=request.user)
    return render(request, "token_detail.html", {"token": token, "pred": ai.predict(token)})


@login_required
def my_activity(request):
    tokens = Token.objects.filter(customer=request.user).select_related("service__provider").order_by("-created_at")[:15]
    appts = Appointment.objects.filter(customer=request.user).select_related("service__provider").order_by("-slot_start")[:15]
    notes = list(request.user.notifications.all()[:15])
    request.user.notifications.filter(read=False).update(read=True)
    return render(request, "activity.html", {"tokens": tokens, "appointments": appts, "notes": notes})


@login_required
@require_POST
def cancel_token(request, pk):
    token = get_object_or_404(Token, pk=pk, customer=request.user)
    _flash(request, workflow.cancel_token, token, ok="Token cancelled.")
    return redirect("activity")


@login_required
@require_POST
def book_slot(request, pk):
    service = get_object_or_404(Service, pk=pk, active=True)
    try:
        start = datetime.fromisoformat(request.POST.get("slot", ""))
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
    except ValueError:
        messages.error(request, "Invalid slot.")
        return redirect("provider_detail", pk=service.provider_id)
    if _flash(request, workflow.book_appointment, request.user, service, start,
              ok="Slot booked! Check in on the day to get a priority token."):
        return redirect("activity")
    return redirect("provider_detail", pk=service.provider_id)


@login_required
@require_POST
def cancel_appointment(request, pk):
    _flash(request, workflow.cancel_appointment, get_object_or_404(Appointment, pk=pk, customer=request.user),
           ok="Appointment cancelled.")
    return redirect("activity")


@login_required
@require_POST
def check_in(request, pk):
    token = _flash(request, workflow.check_in, get_object_or_404(Appointment, pk=pk, customer=request.user))
    return redirect("token_detail", pk=token.pk) if token else redirect("activity")


@login_required
@require_POST
def review(request, pk):
    provider = get_object_or_404(Provider, pk=pk)
    form = ReviewForm(request.POST)
    if form.is_valid():
        Review.objects.update_or_create(customer=request.user, provider=provider, defaults=form.cleaned_data)
        messages.success(request, "Thanks for your review!")
    else:
        messages.error(request, "Rating must be between 1 and 5.")
    return redirect("provider_detail", pk=pk)


# ---------------- provider side ----------------
@login_required
def provider_setup(request):
    form = ProviderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        provider = form.save(commit=False)
        provider.owner = request.user
        provider.save()
        Profile.objects.update_or_create(user=request.user, defaults={"role": "PROVIDER"})
        messages.success(request, "Business registered. Add services and counters below.")
        return redirect("staff_dashboard")
    return render(request, "provider_setup.html", {"form": form})


@login_required
def staff_dashboard(request):
    services = workflow.managed_services(request.user)
    if not services.exists():
        messages.info(request, "Register your business to use the provider dashboard.")
        return redirect("provider_setup")
    workflow.sweep_expired()
    blocks = []
    for s in services:
        rows = [dict(t=t, pred=ai.predict(t), risk=round(ai.no_show_risk(t.customer) * 100))
                for t in Token.objects.filter(service=s, status__in=ACTIVE).select_related("customer", "counter")]
        rows.sort(key=lambda r: (ORDER[r["t"].status], -r["t"].priority, r["t"].created_at))
        blocks.append(dict(service=s, rows=rows, counters=s.counters.all(), summary=ai.daily_summary(s),
                           advice=ai.staffing_advice(s), forecast=ai.crowd_forecast(s),
                           booked_today=Appointment.objects.filter(service=s, status="BOOKED",
                                                                  slot_start__date=timezone.localdate()).count()))
    return render(request, "staff.html", {
        "blocks": blocks, "service_form": ServiceForm(owner=request.user),
        "counter_form": CounterForm(services=services)})


def _owned_token(request, pk):
    token = get_object_or_404(Token.objects.select_related("service__provider"), pk=pk)
    if not workflow.managed_services(request.user).filter(pk=token.service_id).exists():
        raise PermissionError
    return token


@login_required
@require_POST
def staff_action(request, pk, action):
    try:
        token = _owned_token(request, pk)
    except PermissionError:
        messages.error(request, "You do not manage that service.")
        return redirect("staff_dashboard")
    actions = {"start": workflow.start_service, "complete": workflow.complete,
               "no_show": workflow.mark_no_show, "escalate": workflow.escalate}
    if action in actions:
        _flash(request, actions[action], token)
    return redirect("staff_dashboard")


@login_required
@require_POST
def staff_call_next(request, service_id):
    service = get_object_or_404(workflow.managed_services(request.user), pk=service_id)
    counter = Counter.objects.filter(pk=request.POST.get("counter") or 0, service=service).first()
    token = _flash(request, workflow.call_next, service, counter)
    if token:
        messages.success(request, f"Called {token.display_token}.")
    return redirect("staff_dashboard")


@login_required
@require_POST
def add_service(request):
    form = ServiceForm(request.POST, owner=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "Service added.")
    else:
        messages.error(request, "Could not add service. Check the details.")
    return redirect("staff_dashboard")


@login_required
@require_POST
def add_counter(request):
    form = CounterForm(request.POST, services=workflow.managed_services(request.user))
    if form.is_valid():
        counter = form.save(commit=False)
        counter.staff = request.user
        counter.save()
        messages.success(request, "Counter added.")
    return redirect("staff_dashboard")


@login_required
@require_POST
def toggle_counter(request, pk):
    counter = get_object_or_404(Counter, pk=pk, service__in=workflow.managed_services(request.user))
    counter.active = not counter.active
    counter.save(update_fields=["active"])
    return redirect("staff_dashboard")
