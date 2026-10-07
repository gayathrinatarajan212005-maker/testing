from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from . import ai, workflow
from .models import Counter, Profile, Provider, Service, ServiceHistory, Token
from .workflow import QueueError


class WorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="x")
        self.provider = Provider.objects.create(owner=self.owner, name="Test Clinic", category="HOSPITAL", verified=True)
        self.service = Service.objects.create(provider=self.provider, name="Desk", average_minutes=10)
        Counter.objects.create(service=self.service, name="C1", staff=self.owner)
        self.u = [User.objects.create_user(f"u{i}", password="x") for i in range(3)]
        for i, user in enumerate(self.u):
            Profile.objects.create(user=user, priority_eligible=(i == 2))

    def test_numbering_and_duplicate_block(self):
        a = workflow.issue_token(self.u[0], self.service)
        b = workflow.issue_token(self.u[1], self.service)
        self.assertEqual((a.token_number, b.token_number), (1, 2))
        with self.assertRaises(QueueError):
            workflow.issue_token(self.u[0], self.service)

    def test_priority_lane_is_served_first_and_guarded(self):
        workflow.issue_token(self.u[0], self.service)
        with self.assertRaises(QueueError):
            workflow.issue_token(self.u[1], self.service, priority=2)   # not eligible
        workflow.issue_token(self.u[2], self.service, priority=2)
        self.assertEqual(workflow.call_next(self.service).customer, self.u[2])

    def test_predictor_learns_from_completed_services(self):
        token = workflow.issue_token(self.u[0], self.service)
        workflow.call_next(self.service)
        token.refresh_from_db()
        token.called_at = timezone.now() - timedelta(minutes=30)
        token.save()
        workflow.complete(token)
        self.assertEqual(ServiceHistory.objects.filter(service=self.service).count(), 1)
        self.assertGreater(ai.service_stats(self.service)["avg"], 25)

    def test_called_customer_who_does_not_arrive_becomes_no_show(self):
        token = workflow.issue_token(self.u[0], self.service)
        workflow.call_next(self.service)
        Token.objects.filter(pk=token.pk).update(called_at=timezone.now() - timedelta(minutes=10))
        workflow.sweep_expired(self.service)
        token.refresh_from_db()
        self.assertEqual(token.status, "NO_SHOW")

    def test_booking_capacity_and_checkin_priority(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        slot = ai.available_slots(self.service, tomorrow)[0]
        appt = workflow.book_appointment(self.u[0], self.service, slot["start"])
        with self.assertRaises(QueueError):                       # single counter => capacity 1
            workflow.book_appointment(self.u[1], self.service, slot["start"])
        with self.assertRaises(QueueError):                       # not the appointment day
            workflow.check_in(appt)
        token = workflow.issue_token(self.u[0], self.service, appointment=appt)
        self.assertEqual(token.priority, 1)
