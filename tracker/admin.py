from django.contrib import admin
from .models import RouteLog

admin.site.register(RouteLog)
class RouteLogAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "total_points")
    list_filter = ("created_at",)
    ordering = ("-created_at",)
