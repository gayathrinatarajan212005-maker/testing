def shared(request):
    if not request.user.is_authenticated:
        return {"unread_count": 0, "is_provider": False}
    from .workflow import managed_services
    return {
        "unread_count": request.user.notifications.filter(read=False).count(),
        "is_provider": managed_services(request.user).exists(),
    }
