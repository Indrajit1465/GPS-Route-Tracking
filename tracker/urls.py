from django.urls import path
from . import views

app_name = 'tracker'

urlpatterns = [
    path('', views.home, name='home'),
    path('snap_point/', views.snap_point, name='snap_point'),
    path('snap_chunk/', views.snap_chunk, name='snap_chunk'),
    path('save_route/', views.save_route, name='save_route'),
    path('route_history/', views.route_history, name='route_history'),
    path('get_road_path/', views.get_road_path, name='get_road_path'),
    path('ping/', views.ping, name='ping'),
    path('delete_route/<int:route_id>/', views.delete_route, name='delete_route'),
]