from datetime import time

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Avg
from django.utils import timezone


class Profile(models.Model):
    ROLE_CHOICES = [("CUSTOMER", "Customer"), ("PROVIDER", "Service Provider"), ("ADMIN", "Admin")]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="CUSTOMER")
    phone = models.CharField(max_length=20, blank=True)
    priority_eligible = models.BooleanField(
        default=False, help_text="Senior citizen / differently-abled / pregnant: may use the priority lane")

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class Provider(models.Model):
    CATEGORY_CHOICES = [
        ("HOSPITAL", "Hospital / Clinic"), ("BANK", "Bank"), ("SALON", "Salon & Spa"),
        ("REPAIR", "Repair & Home Service"), ("GOVT", "Government Office"), ("EDU", "College / Education"),
    ]
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="providers")
    name = models.CharField(max_length=140)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    area = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=250, blank=True)
    description = models.TextField(blank=True)
    open_time = models.TimeField(default=time(9, 0))
    close_time = models.TimeField(default=time(17, 0))
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name

    def is_open_now(self):
        return self.open_time <= timezone.localtime().time() <= self.close_time

    @property
    def avg_rating(self):
        value = self.reviews.aggregate(a=Avg("rating"))["a"]
        return round(value, 1) if value else None


class Service(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=250, blank=True)
    average_minutes = models.PositiveIntegerField(default=10)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.provider.name} - {self.name}"

    @property
    def active_counters(self):
        return max(1, self.counters.filter(active=True).count())


class Counter(models.Model):
    name = models.CharField(max_length=100)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="counters")
    staff = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    STATUS_CHOICES = [("BOOKED", "Booked"), ("CHECKED_IN", "Checked in"), ("COMPLETED", "Completed"),
                      ("CANCELLED", "Cancelled"), ("NO_SHOW", "No-show")]
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="appointments")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="appointments")
    slot_start = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="BOOKED")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["slot_start"]

    def __str__(self):
        return f"{self.customer.username} @ {self.slot_start:%d %b %H:%M}"


class Token(models.Model):
    STATUS_CHOICES = [("WAITING", "Waiting"), ("CALLED", "Called"), ("SERVING", "Serving"),
                      ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled"), ("NO_SHOW", "No-show")]
    PRIORITY_CHOICES = [(0, "Normal"), (1, "Appointment"), (2, "Senior / Priority"), (3, "Emergency")]

    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="tokens")
    appointment = models.OneToOneField(Appointment, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="token")
    counter = models.ForeignKey(Counter, null=True, blank=True, on_delete=models.SET_NULL, related_name="tokens")
    token_number = models.PositiveIntegerField()
    queue_date = models.DateField(default=timezone.localdate)
    priority = models.PositiveSmallIntegerField(choices=PRIORITY_CHOICES, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="WAITING")
    created_at = models.DateTimeField(default=timezone.now)
    called_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    actual_service_minutes = models.PositiveIntegerField(null=True, blank=True)
    notified_soon = models.BooleanField(default=False)

    class Meta:
        ordering = ["-priority", "created_at"]
        constraints = [models.UniqueConstraint(fields=["service", "queue_date", "token_number"],
                                               name="uniq_token_per_service_per_day")]

    @property
    def display_token(self):
        return f"{self.service.name[:2].upper()}-{self.token_number:03d}"

    def __str__(self):
        return self.display_token


class Review(models.Model):
    customer = models.ForeignKey(User, on_delete=models.CASCADE)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["customer", "provider"], name="one_review_per_provider")]


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=300)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class ServiceHistory(models.Model):
    """Every completed service is a learning sample for the adaptive predictor."""
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="history")
    minutes = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    weekday = models.PositiveSmallIntegerField(default=0)
    hour = models.PositiveSmallIntegerField(default=0)

    def save(self, *args, **kwargs):
        local = timezone.localtime(self.created_at)
        self.weekday, self.hour = local.weekday(), local.hour
        super().save(*args, **kwargs)
