from django.urls import path
from django.conf import settings
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('',
         views.admin_dashboard,
         name='dashboard'),
    path('user/<int:user_id>/',
         views.user_detail,
         name='user_detail'),
    path('api/user/<int:user_id>/routes/',
         views.api_user_routes,
         name='api_user_routes'),
    path('api/user/<int:user_id>/today/',
         views.api_user_today,
         name='api_user_today'),
    path('api/live/',
         views.api_live_users,
         name='api_live_users'),
    path('api/stats/',
         views.api_global_stats,
         name='api_global_stats'),
    path('delete/route/<int:route_id>/',
         views.admin_delete_route,
         name='admin_delete_route'),
    path('api/user/<int:user_id>/graph/',
         views.api_user_graph_data,
         name='api_user_graph_data'),
]

# Only expose debug endpoint in development
if settings.DEBUG:
    urlpatterns.append(
        path('debug/route/<int:route_id>/',
             views.debug_route,
             name='debug_route'),
    )
