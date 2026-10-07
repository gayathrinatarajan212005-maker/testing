from django.contrib import admin
from django.urls import include, path

from queue_app import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("queue_app.api_urls")),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("", views.home, name="home"),
    path("providers/", views.providers, name="providers"),
    path("providers/<int:pk>/", views.provider_detail, name="provider_detail"),
    path("providers/<int:pk>/review/", views.review, name="review"),
    path("join/", views.join_queue, name="join_queue"),
    path("tokens/<int:pk>/", views.token_detail, name="token_detail"),
    path("tokens/<int:pk>/cancel/", views.cancel_token, name="cancel_token"),
    path("services/<int:pk>/book/", views.book_slot, name="book_slot"),
    path("appointments/<int:pk>/cancel/", views.cancel_appointment, name="cancel_appointment"),
    path("appointments/<int:pk>/check-in/", views.check_in, name="check_in"),
    path("activity/", views.my_activity, name="activity"),
    path("provider/setup/", views.provider_setup, name="provider_setup"),
    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path("staff/token/<int:pk>/<str:action>/", views.staff_action, name="staff_action"),
    path("staff/service/<int:service_id>/call-next/", views.staff_call_next, name="staff_call_next"),
    path("staff/service/add/", views.add_service, name="add_service"),
    path("staff/counter/add/", views.add_counter, name="add_counter"),
    path("staff/counter/<int:pk>/toggle/", views.toggle_counter, name="toggle_counter"),
]
