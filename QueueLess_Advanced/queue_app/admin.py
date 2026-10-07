from django.contrib import admin

from .models import (Appointment, Counter, Notification, Profile, Provider, Review, Service,
                     ServiceHistory, Token)


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "area", "owner", "verified")
    list_filter = ("category", "verified")
    search_fields = ("name", "area")
    actions = ["verify"]

    @admin.action(description="Mark selected providers as verified")
    def verify(self, request, queryset):
        queryset.update(verified=True)


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ("id", "service", "token_number", "queue_date", "priority", "status", "customer")
    list_filter = ("status", "priority", "queue_date")


admin.site.register([Profile, Service, Counter, Appointment, Review, Notification, ServiceHistory])
