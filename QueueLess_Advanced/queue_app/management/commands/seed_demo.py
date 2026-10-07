import random
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from queue_app import ai, workflow
from queue_app.models import Counter, Profile, Provider, Review, Service, ServiceHistory, Token

HOURLY = {9: 2, 10: 4, 11: 6, 12: 4, 13: 2, 14: 3, 15: 5, 16: 2}   # typical footfall shape

CATALOG = [
    # owner, name, category, area, description, [(service, minutes, price, counters)], volume
    ("staff", "City Care Hospital", "HOSPITAL", "Downtown", "Multi-speciality hospital and diagnostics.",
     [("OPD Registration", 10, 50, 2), ("Lab Test Booking", 8, 200, 1)], 1.5),
    ("staff", "Metro Co-operative Bank", "BANK", "Central Market", "Savings, loans and cash services.",
     [("Cash & Deposit", 6, 0, 2), ("Loan Enquiry", 15, 0, 1)], 1.2),
    ("glow", "Glow Studio Salon", "SALON", "North Block", "Hair, skin and grooming.",
     [("Haircut", 30, 250, 1), ("Facial", 45, 600, 1)], 0.4),
    ("glow", "QuickFix Mobile Repair", "REPAIR", "East Street", "Same-day phone repair.",
     [("Screen Repair", 40, 1500, 1)], 0.4),
    ("admin", "Taluk e-Seva Centre", "GOVT", "Town Hall", "Certificates and civic services.",
     [("Certificate Services", 15, 0, 2)], 1.0),
]


class Command(BaseCommand):
    help = "Create demo users, providers, 4 weeks of history (so the AI has something to learn from) and a live queue"

    def user(self, name, password, role="CUSTOMER", staff=False, superuser=False, eligible=False):
        user, created = User.objects.get_or_create(username=name)
        if created:
            user.set_password(password)
            user.is_staff, user.is_superuser = staff or superuser, superuser
            user.save()
        Profile.objects.get_or_create(user=user, defaults={"role": role, "priority_eligible": eligible})
        return user

    def handle(self, *args, **kwargs):
        rng = random.Random(42)
        owners = {
            "staff": self.user("staff", "staff123", "PROVIDER", staff=True),
            "glow": self.user("glow", "glow123", "PROVIDER", staff=True),
            "admin": self.user("admin", "admin123", "ADMIN", superuser=True),
        }
        customer = self.user("customer", "customer123")
        self.user("senior", "senior123", eligible=True)
        walkins = [self.user(f"walkin{i}", "walkin123") for i in range(1, 7)]

        today = timezone.localdate()
        services = []
        for owner, name, cat, area, desc, items, volume in CATALOG:
            provider, _ = Provider.objects.get_or_create(
                name=name, defaults=dict(owner=owners[owner], category=cat, area=area, description=desc, verified=True))
            for sname, minutes, price, n_counters in items:
                svc, _ = Service.objects.get_or_create(provider=provider, name=sname,
                                                       defaults=dict(average_minutes=minutes, price=price))
                for i in range(1, n_counters + 1):
                    Counter.objects.get_or_create(service=svc, name=f"Counter {i}", defaults={"staff": owners[owner]})
                self.seed_history(svc, customer, rng, volume, today)
                services.append(svc)
            for u in rng.sample(walkins, 3):
                Review.objects.get_or_create(customer=u, provider=provider,
                                             defaults=dict(rating=rng.randint(3, 5), comment="Quick and smooth."))

        self.seed_live_queue(services, walkins, customer, today)
        self.stdout.write(self.style.SUCCESS("Demo data ready. Logins: customer/customer123, senior/senior123, "
                                             "staff/staff123, glow/glow123, admin/admin123"))

    def seed_history(self, svc, customer, rng, volume, today):
        if Token.objects.filter(service=svc, queue_date__lt=today).exists():
            return
        tz = timezone.get_current_timezone()
        tokens, history = [], []
        for back in range(28, 0, -1):
            day = today - timedelta(days=back)
            times = []
            for hour, weight in HOURLY.items():
                for _ in range(max(0, round(weight * volume * rng.uniform(0.7, 1.3) * (0.5 if day.weekday() >= 5 else 1)))):
                    times.append((hour, datetime.combine(day, time(hour, rng.randint(0, 59))), weight))
            for number, (hour, naive, weight) in enumerate(sorted(times, key=lambda x: x[1]), start=1):
                created = timezone.make_aware(naive, tz)
                rush = 1.25 if weight >= 5 else 1.0 if weight >= 3 else 0.85       # busy hours run slower
                minutes = max(2, round(svc.average_minutes * rush * rng.uniform(0.8, 1.2)))
                called = created + timedelta(minutes=5)
                done = called + timedelta(minutes=minutes)
                tokens.append(Token(customer=customer, service=svc, token_number=number, queue_date=day,
                                    status="COMPLETED", created_at=created, called_at=called, started_at=called,
                                    completed_at=done, actual_service_minutes=minutes))
                local = timezone.localtime(done)
                history.append(ServiceHistory(service=svc, minutes=minutes, created_at=done,
                                              weekday=local.weekday(), hour=local.hour))
        Token.objects.bulk_create(tokens)
        ServiceHistory.objects.bulk_create(history)

    def seed_live_queue(self, services, walkins, customer, today):
        by_name = {s.name: s for s in services}
        if not Token.objects.filter(queue_date=today, service=by_name["OPD Registration"]).exists():
            opd = by_name["OPD Registration"]
            for user in walkins[:4]:
                workflow.issue_token(user, opd)
            workflow.start_service(workflow.call_next(opd))
            workflow.issue_token(walkins[4], by_name["Cash & Deposit"])
        for offset in (0, 1):                      # one booking today, one tomorrow
            svc = by_name["OPD Registration"]
            open_slots = [s for s in ai.available_slots(svc, today + timedelta(days=offset)) if s["remaining"] > 0]
            if open_slots:
                try:
                    workflow.book_appointment(customer, svc, open_slots[len(open_slots) // 2]["start"])
                except workflow.QueueError:
                    pass
