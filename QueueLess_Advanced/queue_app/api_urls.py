from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register("services", api.ServiceViewSet, basename="service")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/token/", obtain_auth_token),
    path("providers/", api.providers_api),
    path("services/<int:pk>/slots/", api.slots_api),
    path("services/<int:pk>/forecast/", api.forecast_api),
    path("queues/join/", api.join_queue_api),
    path("queues/status/", api.queue_status),
    path("queues/mine/", api.my_tokens),
    path("queues/call-next/", api.call_next),
    path("queues/start/", api.start_api),
    path("queues/complete/", api.complete_token),
    path("queues/no-show/", api.no_show_api),
    path("queues/escalate/", api.escalate_api),
    path("appointments/", api.appointments_api),
    path("notifications/", api.notifications_api),
    path("staff/summary/", api.staff_summary),
]
