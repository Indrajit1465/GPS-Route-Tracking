from django.contrib import admin
from django.urls import path, include # include also new 
from tracker.views import (
    home,
    save_route,
    get_saved_route,
    snap_chunk,
    snap_point,
    route_history,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home),
    path('save_route/', save_route),
    path('get_saved_route/', get_saved_route),
    path('snap_chunk/', snap_chunk),
    path('snap_point/', snap_point),
    path('route_history/', route_history),
    path('', include('tracker.urls')), # new one
    path('', include('users.urls')), # new one 
]