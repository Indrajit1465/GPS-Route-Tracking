from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('tracker.urls')),
    path('', include('users.urls')),
    path('superadmin/', include('admin_panel.urls')),
]