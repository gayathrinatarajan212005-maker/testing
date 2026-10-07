from datetime import datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import ai, workflow
from .models import Appointment, Counter, Service, Token
from .serializers import AppointmentSerializer, NotificationSerializer, ServiceSerializer, TokenSerializer
from .workflow import ACTIVE, QueueError


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Service.objects.filter(active=True).select_related("provider")
    serializer_class = ServiceSerializer


def _run(fn, *args, serializer=TokenSerializer, code=status.HTTP_200_OK):
    try:
        return Response(serializer(fn(*args)).data, status=code)
    except QueueError as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
@permission_classes([AllowAny])
def providers_api(request):
    cards = ai.provider_cards(request.query_params.get("q", ""), request.query_params.get("category", ""))
    return Response([{
        "id": c["provider"].id, "name": c["provider"].name, "category": c["provider"].category,
        "area": c["provider"].area, "rating": c["rating"], "best_wait": c["best_wait"], "smart_score": c["score"],
        "services": [{"id": s.id, "name": s.name, "price": str(s.price), **w} for s, w in c["services"]],
    } for c in cards])


@api_view(["GET"])
@permission_classes([AllowAny])
def slots_api(request, pk):
    service = get_object_or_404(Service, pk=pk, active=True)
    try:
        day = datetime.strptime(request.query_params.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        day = timezone.localdate()
    return Response([{k: v for k, v in s.items() if k != "start"} for s in ai.available_slots(service, day)])


@api_view(["GET"])
@permission_classes([AllowAny])
def forecast_api(request, pk):
    service = get_object_or_404(Service, pk=pk, active=True)
    return Response({"forecast": ai.crowd_forecast(service), "best_time": ai.best_time(service)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def join_queue_api(request):
    service = Service.objects.filter(pk=request.data.get("service_id"), active=True).first()
    if not service:
        return Response({"error": "Invalid service"}, status=400)
    return _run(workflow.issue_token, request.user, service, int(request.data.get("priority", 0) or 0),
                code=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def queue_status(request):
    workflow.sweep_expired()
    token = Token.objects.filter(pk=request.query_params.get("token_id") or 0, customer=request.user).first()
    if not token:
        return Response({"error": "Token not found"}, status=404)
    return Response(TokenSerializer(token).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_tokens(request):
    qs = Token.objects.filter(customer=request.user, status__in=ACTIVE)
    return Response(TokenSerializer(qs, many=True).data)


def _staff_token(request):
    token = Token.objects.filter(pk=request.data.get("token_id")).first()
    if not token or not workflow.managed_services(request.user).filter(pk=token.service_id).exists():
        return None
    return token


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def call_next(request):
    service = workflow.managed_services(request.user).filter(pk=request.data.get("service_id") or 0).first()
    if not service:
        return Response({"error": "You do not manage that service"}, status=403)
    counter = Counter.objects.filter(pk=request.data.get("counter_id") or 0, service=service).first()
    return _run(workflow.call_next, service, counter)


def _token_action(fn):
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def view(request):
        token = _staff_token(request)
        if not token:
            return Response({"error": "Token not found or not yours to manage"}, status=403)
        return _run(fn, token)
    view.__name__ = fn.__name__ + "_api"
    return view


start_api = _token_action(workflow.start_service)
complete_token = _token_action(workflow.complete)
no_show_api = _token_action(workflow.mark_no_show)
escalate_api = _token_action(workflow.escalate)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def appointments_api(request):
    if request.method == "GET":
        qs = Appointment.objects.filter(customer=request.user).select_related("service")
        return Response(AppointmentSerializer(qs, many=True).data)
    service = Service.objects.filter(pk=request.data.get("service_id"), active=True).first()
    try:
        start = datetime.fromisoformat(request.data.get("slot", ""))
    except ValueError:
        return Response({"error": "slot must be an ISO datetime from /services/<id>/slots/"}, status=400)
    if not service:
        return Response({"error": "Invalid service"}, status=400)
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    return _run(workflow.book_appointment, request.user, service, start,
                serializer=AppointmentSerializer, code=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_api(request):
    return Response(NotificationSerializer(request.user.notifications.all()[:30], many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_summary(request):
    return Response([{"service": s.name, "provider": s.provider.name, **ai.daily_summary(s),
                      "advice": ai.staffing_advice(s)} for s in workflow.managed_services(request.user)])
