from django.contrib import admin
from django.urls import path, include
from django.http import FileResponse, Http404
from django.conf import settings
import os

def serve_sw(request):
    """
    Serves the Service Worker file from root URL /sw.js
    Service workers must be served from the root scope
    to control the entire app — /static/sw.js would only
    control requests under /static/ which is useless.
    """
    sw_path = os.path.join(
        str(settings.BASE_DIR),
        'tracker',
        'static',
        'sw.js'
    )

    if not os.path.exists(sw_path):
        raise Http404(
            'sw.js not found at: ' + sw_path
        )

    response = FileResponse(
        open(sw_path, 'rb'),
        content_type='application/javascript'
    )
    # Service workers require this header
    response['Service-Worker-Allowed'] = '/'
    # Cache for 1 hour
    response['Cache-Control'] = (
        'public, max-age=3600'
    )
    return response

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sw.js', serve_sw),            # ← Service Worker
    path('', include('tracker.urls')),
    path('', include('users.urls')),
    path('superadmin/', include('admin_panel.urls')),
]