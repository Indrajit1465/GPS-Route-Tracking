import json
import math
from datetime import datetime, timedelta
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from tracker.models import RouteLog

# ─── Super Admin Guard Decorator ─────────────────────────
def superadmin_required(view_func):
    """
    Allows access ONLY to users where is_superuser=True.
    Returns 403 for regular users.
    Returns redirect to login for unauthenticated users.
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            return redirect('/login/')
        if not request.user.is_superuser:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden(
                'Access denied. Super Admin only.'
            )
        return view_func(request, *args, **kwargs)
    return wrapper

# ─── Haversine for distance calculation ──────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(d_lon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def compute_distance(points):
    total = 0.0
    for i in range(1, len(points)):
        try:
            total += haversine(
                float(points[i-1]['lat']),
                float(points[i-1]['lon']),
                float(points[i]['lat']),
                float(points[i]['lon'])
            )
        except (KeyError, TypeError, ValueError):
            continue
    return round(total)

def normalize_points(raw_points):
    """Normalize coordinates to {lat, lon} format."""
    normalized = []
    for p in (raw_points or []):
        try:
            if isinstance(p, dict) and 'lat' in p:
                lat = float(p['lat'])
                lon = float(p.get('lon',
                            p.get('lng',
                            p.get('longitude', 0))))
            elif isinstance(p, dict) and 'latitude' in p:
                lat = float(p['latitude'])
                lon = float(p['longitude'])
            elif isinstance(p, (list, tuple)):
                lat = float(p[0])
                lon = float(p[1])
            else:
                continue
            if (-90 <= lat <= 90) and (-180 <= lon <= 180):
                normalized.append({'lat': lat, 'lon': lon})
        except (TypeError, ValueError):
            continue
    return normalized

def format_duration(seconds):
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds//60}m {seconds%60}s'
    return f'{seconds//3600}h {(seconds%3600)//60}m'

def format_distance(meters):
    if meters < 1000:
        return f'{meters} m'
    return f'{meters/1000:.2f} km'

# ─── PLACEHOLDER: Stop Detection ─────────────────────────
def detect_stops(points):
    """
    PLACEHOLDER — Stop detection will be implemented later.
    Will analyze speed between consecutive points and
    identify locations where the user stopped for > 30s.
    Returns empty list for now.
    """
    return []

# ─── View 1: Admin Dashboard ──────────────────────────────
@superadmin_required
def admin_dashboard(request):
    """
    Main admin dashboard showing all users and
    their activity summary.
    """
    users = User.objects.filter(
        is_superuser=False
    ).order_by('-date_joined')

    user_data = []
    today     = timezone.now().date()

    for user in users:
        all_routes   = RouteLog.objects.filter(user=user)
        today_routes = all_routes.filter(
            created_at__date=today
        )

        total_distance = sum(
            compute_distance(normalize_points(r.route_points))
            for r in all_routes
        )
        today_distance = sum(
            compute_distance(normalize_points(r.route_points))
            for r in today_routes
        )

        last_route = all_routes.first()

        user_data.append({
            'user':            user,
            'total_routes':    all_routes.count(),
            'today_routes':    today_routes.count(),
            'total_distance':  format_distance(total_distance),
            'today_distance':  format_distance(today_distance),
            'last_active':     last_route.created_at
                               if last_route else None,
            'last_route_id':   last_route.id
                               if last_route else None,
        })

    context = {
        'user_data':      user_data,
        'total_users':    users.count(),
        'total_routes':   RouteLog.objects.filter(
                              user__is_superuser=False
                          ).count(),
        'today_routes':   RouteLog.objects.filter(
                              user__is_superuser=False,
                              created_at__date=today
                          ).count(),
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(
        request,
        'admin_panel/dashboard.html',
        context
    )

# ─── View 2: Single User Detail ───────────────────────────
@superadmin_required
def user_detail(request, user_id):
    """
    Detailed view for a single user showing all their
    routes, today's activity, and map visualization.
    """
    user       = get_object_or_404(
                     User,
                     id=user_id,
                     is_superuser=False
                 )
    today      = timezone.now().date()
    all_routes = RouteLog.objects.filter(
                     user=user
                 ).order_by('-created_at')

    today_routes = all_routes.filter(
        created_at__date=today
    )

    route_list = []
    for route in all_routes[:50]:  # Last 50 routes
        points   = normalize_points(route.route_points)
        distance = compute_distance(points)
        route_list.append({
            'id':          route.id,
            'date':        route.created_at.strftime(
                               '%d %b %Y'
                           ),
            'time':        route.created_at.strftime(
                               '%I:%M %p'
                           ),
            'created_at':  route.created_at.strftime(
                               '%d %b %Y, %I:%M %p'
                           ),
            'distance':    format_distance(distance),
            'distance_m':  distance,
            'duration':    format_duration(
                               route.total_points * 5
                           ),
            'total_points': route.total_points,
            'start_lat':   points[0]['lat']
                           if points else None,
            'start_lon':   points[0]['lon']
                           if points else None,
            'end_lat':     points[-1]['lat']
                           if points else None,
            'end_lon':     points[-1]['lon']
                           if points else None,
            'points':      points,
            'stops':       detect_stops(points),
            # Placeholder — will show stop count when implemented
            'stop_count':  0,
        })

    today_distance = sum(
        r['distance_m'] for r in route_list
        if r['date'] == today.strftime('%d %b %Y')
    )

    import json as json_module
    context = {
        'target_user':     user,
        'route_list':      route_list,
        'route_list_json': json_module.dumps(route_list, default=str),
        'today_routes':    today_routes.count(),
        'today_distance':  format_distance(today_distance),
        'total_routes':    all_routes.count(),
        'total_distance':  format_distance(
                               sum(r['distance_m']
                                   for r in route_list)
                           ),
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(
        request,
        'admin_panel/user_detail.html',
        context
    )

# ─── API 1: User Routes JSON ──────────────────────────────
@superadmin_required
def api_user_routes(request, user_id):
    """Returns all routes for a user as JSON for map."""
    user   = get_object_or_404(User, id=user_id)
    routes = RouteLog.objects.filter(
                 user=user
             ).order_by('-created_at')[:20]

    route_list = []
    for route in routes:
        points = normalize_points(route.route_points)
        if not points:
            continue
        route_list.append({
            'id':         route.id,
            'created_at': route.created_at.strftime(
                              '%d %b %Y, %I:%M %p'
                          ),
            'points':     points,
            'distance':   format_distance(
                              compute_distance(points)
                          ),
            'duration':   format_duration(
                              route.total_points * 5
                          ),
            'start':      points[0],
            'end':        points[-1],
            'stop_count': 0,  # Placeholder
        })

    return JsonResponse({'routes': route_list})

# ─── API 2: Today's Activity ──────────────────────────────
@superadmin_required
def api_user_today(request, user_id):
    """Returns today's routes for a specific user."""
    user  = get_object_or_404(User, id=user_id)
    today = timezone.now().date()

    routes = RouteLog.objects.filter(
                 user=user,
                 created_at__date=today
             ).order_by('-created_at')

    route_list = []
    for route in routes:
        points = normalize_points(route.route_points)
        route_list.append({
            'id':       route.id,
            'time':     route.created_at.strftime(
                            '%I:%M %p'
                        ),
            'points':   points,
            'distance': format_distance(
                            compute_distance(points)
                        ),
        })

    return JsonResponse({
        'routes':    route_list,
        'count':     len(route_list),
        'date':      today.strftime('%d %b %Y'),
    })

# ─── API 3: Global Stats ──────────────────────────────────
@superadmin_required
def api_global_stats(request):
    """Returns platform-wide statistics."""
    today = timezone.now().date()
    return JsonResponse({
        'total_users':  User.objects.filter(
                            is_superuser=False
                        ).count(),
        'total_routes': RouteLog.objects.filter(
                            user__is_superuser=False
                        ).count(),
        'today_routes': RouteLog.objects.filter(
                            user__is_superuser=False,
                            created_at__date=today
                        ).count(),
    })

# ─── API 4: Live Users ──────────────────────────────────
@superadmin_required
def api_live_users(request):
    """Placeholder for live users API"""
    return JsonResponse({'live_users': []})
