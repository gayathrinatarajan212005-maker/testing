from rest_framework import serializers

from . import ai
from .models import Appointment, Notification, Service, Token


class ServiceSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    live = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = ["id", "name", "provider", "provider_name", "average_minutes", "price", "active", "live"]

    def get_live(self, obj):
        return ai.new_joiner_wait(obj)


class TokenSerializer(serializers.ModelSerializer):
    display_token = serializers.ReadOnlyField()
    service_name = serializers.CharField(source="service.name", read_only=True)
    provider_name = serializers.CharField(source="service.provider.name", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    prediction = serializers.SerializerMethodField()
    predicted_wait = serializers.SerializerMethodField()   # kept for backward compatibility

    class Meta:
        model = Token
        fields = ["id", "display_token", "token_number", "service", "service_name", "provider_name",
                  "status", "priority", "priority_label", "created_at", "predicted_wait", "prediction"]

    def get_prediction(self, obj):
        return ai.predict(obj)

    def get_predicted_wait(self, obj):
        return ai.predict(obj)["minutes"]


class AppointmentSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)

    class Meta:
        model = Appointment
        fields = ["id", "service", "service_name", "slot_start", "status"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "message", "read", "created_at"]
