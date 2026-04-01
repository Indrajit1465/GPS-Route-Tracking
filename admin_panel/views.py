import json
import math
from datetime import datetime, timedelta
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
import logging
from tracker.models import RouteLog

logger = logging.getLogger(__name__)

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
    """
    Normalizes route_points to always return
    {'lat': float, 'lon': float} dicts.

    Handles all known storage formats:
      Format A: {'lat': x, 'lon': y}        <- standard
      Format B: {'lat': x, 'lng': y}        <- Google Maps
      Format C: {'lat': x, 'longitude': y}  <- verbose
      Format D: {'latitude': x, 'longitude': y}
      Format E: [lat, lon]                  <- array
      Format F: {'location': {'latitude': x, 'longitude': y}}
                                            <- Roads API raw
    """
    if not raw_points:
        return []

    normalized = []

    for i, p in enumerate(raw_points):
        try:
            lat = None
            lon = None

            if isinstance(p, dict):
                # Format F: nested location object
                if 'location' in p:
                    loc = p['location']
                    lat = float(loc.get('latitude',
                                loc.get('lat', 0)))
                    lon = float(loc.get('longitude',
                                loc.get('lng',
                                loc.get('lon', 0))))

                # Format A: {'lat': x, 'lon': y}
                elif 'lat' in p and 'lon' in p:
                    lat = float(p['lat'])
                    lon = float(p['lon'])

                # Format B: {'lat': x, 'lng': y}
                elif 'lat' in p and 'lng' in p:
                    lat = float(p['lat'])
                    lon = float(p['lng'])

                # Format C: {'lat': x, 'longitude': y}
                elif 'lat' in p and 'longitude' in p:
                    lat = float(p['lat'])
                    lon = float(p['longitude'])

                # Format D: {'latitude': x, 'longitude': y}
                elif 'latitude' in p and 'longitude' in p:
                    lat = float(p['latitude'])
                    lon = float(p['longitude'])

                # Format D variant: {'latitude': x, 'lon': y}
                elif 'latitude' in p and 'lon' in p:
                    lat = float(p['latitude'])
                    lon = float(p['lon'])

                else:
                    keys = list(p.keys())
                    if len(keys) >= 2:
                        try:
                            lat = float(p[keys[0]])
                            lon = float(p[keys[1]])
                        except (ValueError, TypeError):
                            pass

            # Format E: [lat, lon] array or tuple
            elif isinstance(p, (list, tuple)):
                if len(p) >= 2:
                    lat = float(p[0])
                    lon = float(p[1])

            if lat is None or lon is None:
                continue
            if not (-90.0 <= lat <= 90.0):
                continue
            if not (-180.0 <= lon <= 180.0):
                continue
            if math.isnan(lat) or math.isnan(lon):
                continue
            if math.isinf(lat) or math.isinf(lon):
                continue

            normalized.append({
                'lat': round(lat, 7),
                'lon': round(lon, 7)
            })

        except (TypeError, ValueError,
                KeyError, IndexError) as e:
            logger.warning(
                f'normalize_points: skipping point '
                f'{i} — {e} — raw: {p}'
            )
            continue

    return normalized


def diagnose_points_format(raw_points, route_id):
    """
    Logs the detected format of route_points
    for a given route. Used for debugging only.
    """
    import logging
    logger = logging.getLogger(__name__)

    if not raw_points:
        logger.info(f'Route {route_id}: empty points')
        return

    sample = raw_points[0] if raw_points else None
    logger.info(
        f'Route {route_id}: {len(raw_points)} raw points, '
        f'sample format: {type(sample).__name__} = {sample}'
    )

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
    today     = timezone.localtime(timezone.now()).date()

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
    today      = timezone.localtime(timezone.now()).date()
    all_routes = RouteLog.objects.filter(
                     user=user
                 ).order_by('-created_at')

    today_routes = all_routes.filter(
        created_at__date=today
    )

    route_list = []
    for route in all_routes[:100]:
        points = normalize_points(route.route_points)

        # Run diagnostic for routes with 0 valid points
        if len(points) == 0:
            diagnose_points_format(
                route.route_points, route.id
            )

        distance = compute_distance(points)

        start_lat = points[0]['lat'] if points else None
        start_lon = points[0]['lon'] if points else None
        end_lat   = points[-1]['lat'] if points else None
        end_lon   = points[-1]['lon'] if points else None

        local_time = timezone.localtime(route.created_at)

        raw_count = len(route.route_points) if route.route_points else 0
        valid_count = len(points)
        pts_per_km = round(valid_count / (distance / 1000)) if distance > 100 else 0

        route_list.append({
            'id':             route.id,
            'date':           local_time.strftime('%d %b %Y'),
            'time':           local_time.strftime('%I:%M %p'),
            'created_at':     local_time.strftime(
                                  '%d %b %Y, %I:%M %p'
                              ),
            'profile':        route.profile,
            'distance':       format_distance(distance),
            'distance_m':     distance,
            'duration':       format_duration(
                                  route.total_points * 5
                              ),
            'total_points':   route.total_points,
            'raw_point_count': raw_count,
            'valid_points':   valid_count,
            'start_lat':      start_lat,
            'start_lon':      start_lon,
            'end_lat':        end_lat,
            'end_lon':        end_lon,
            'points':         points,
            'has_valid_data': valid_count >= 2,
            'stop_count':     0,
            'sampling_quality': (
                'Excellent' if pts_per_km > 40 else
                'Good'      if pts_per_km > 20 else
                'Fair'      if pts_per_km > 8  else
                'Low'       if distance > 0 else
                'No Data'
            ),
        })

    today_distance = sum(
        r['distance_m'] for r in route_list
        if r['date'] == today.strftime('%d %b %Y')
    )

    import json as json_module
    context = {
        'target_user':     user,
        'today_str':       timezone.localtime(timezone.now()).strftime('%Y-%m-%d'),
        'route_list':      route_list,
        'route_list_json': json_module.dumps(
                               route_list, default=str
                           ),
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
            'created_at': timezone.localtime(route.created_at).strftime(
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
    today = timezone.localtime(timezone.now()).date()

    routes = RouteLog.objects.filter(
                 user=user,
                 created_at__date=today
             ).order_by('-created_at')

    route_list = []
    for route in routes:
        points = normalize_points(route.route_points)
        route_list.append({
            'id':       route.id,
            'time':     timezone.localtime(route.created_at).strftime(
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
    today = timezone.localtime(timezone.now()).date()
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


# ─── Debug: Route Data Inspector ──────────────────────────
@superadmin_required
def debug_route(request, route_id):
    """
    Debug endpoint — shows raw stored data for a route.
    Use this to see exactly what format coordinates
    are stored in and why normalization may fail.
    Remove this after debugging is complete.
    """
    try:
        route = RouteLog.objects.get(id=route_id)
    except RouteLog.DoesNotExist:
        return JsonResponse(
            {'error': 'Route not found'}, status=404
        )

    raw = route.route_points or []
    sample = raw[:3] if raw else []
    normalized = normalize_points(raw)

    return JsonResponse({
        'route_id':         route_id,
        'user':             route.user.username,
        'total_points_db':  route.total_points,
        'raw_array_length': len(raw),
        'normalized_count': len(normalized),
        'first_3_raw':      sample,
        'first_3_normalized': normalized[:3],
        'raw_types':        [
            type(p).__name__ for p in sample
        ],
        'raw_keys':         [
            list(p.keys()) if isinstance(p, dict)
            else 'array' for p in sample
        ],
    })

@superadmin_required
def admin_delete_route(request, route_id):
    """
    Super admin endpoint to delete any route.
    Protected by superadmin_required decorator.
    """
    if request.method != 'DELETE':
        return JsonResponse(
            {'error': 'Method not allowed'},
            status=405
        )

    try:
        route = RouteLog.objects.get(id=route_id)
    except RouteLog.DoesNotExist:
        return JsonResponse(
            {'error': 'Route not found'},
            status=404
        )

    user_name    = route.user.username
    points_count = route.total_points

    route.delete()

    logger.info(
        f'Admin {request.user.username} deleted '
        f'route {route_id} belonging to {user_name}'
    )

    return JsonResponse({
        'status':  'deleted',
        'message': f'Route {route_id} deleted. '
                   f'Freed {points_count} points '
                   f'from {user_name}.',
        'freed_points': points_count,
    })

@superadmin_required
def api_user_graph_data(request, user_id):
    """
    Returns daily aggregated route data for a user
    filtered by date range and profile.
    Used to render the line graph in user detail.
    """
    user = get_object_or_404(
        User, id=user_id, is_superuser=False
    )

    # Read filter parameters
    date_from  = request.GET.get('from')
    date_to    = request.GET.get('to')
    profile    = request.GET.get('profile', 'all')
    metric     = request.GET.get('metric', 'distance')

    # Default: last 30 days
    today    = timezone.localtime(timezone.now()).date()
    end_date = today
    start_date = today - timezone.timedelta(days=29)

    # Parse custom date range
    try:
        if date_from:
            start_date = timezone.datetime.strptime(
                date_from, '%Y-%m-%d'
            ).date()
        if date_to:
            end_date = timezone.datetime.strptime(
                date_to, '%Y-%m-%d'
            ).date()
    except ValueError:
        return JsonResponse(
            {'error': 'Invalid date format.'
                      ' Use YYYY-MM-DD'},
            status=400
        )

    # Clamp range to max 90 days
    delta = (end_date - start_date).days
    if delta > 90:
        start_date = end_date - timezone.timedelta(
            days=90
        )
    if delta < 0:
        return JsonResponse(
            {'error': 'from date must be before to date'},
            status=400
        )

    # Build queryset
    routes = RouteLog.objects.filter(
        user=user,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).order_by('created_at')

    # Filter by profile
    allowed_profiles = [
        'walking', 'cycling', 'motorcycle', 'car'
    ]
    if profile in allowed_profiles:
        routes = routes.filter(profile=profile)

    # Aggregate by day
    from collections import defaultdict
    daily = defaultdict(lambda: {
        'distance': 0,
        'routes':   0,
        'duration': 0,
        'points':   0,
    })

    for route in routes:
        day = timezone.localtime(
            route.created_at
        ).strftime('%Y-%m-%d')

        points = normalize_points(
            route.route_points or []
        )
        dist   = compute_distance(points)

        daily[day]['distance'] += dist
        daily[day]['routes']   += 1
        daily[day]['duration'] += route.total_points * 5
        daily[day]['points']   += route.total_points

    # Fill all dates in range even if no activity
    current = start_date
    labels  = []
    values  = []

    while current <= end_date:
        day_str = current.strftime('%Y-%m-%d')
        label   = current.strftime('%d %b')
        labels.append(label)

        day_data = daily.get(day_str, {})

        if metric == 'distance':
            val = round(
                day_data.get('distance', 0) / 1000, 2
            )  # km
        elif metric == 'routes':
            val = day_data.get('routes', 0)
        elif metric == 'duration':
            val = round(
                day_data.get('duration', 0) / 60, 1
            )  # minutes
        elif metric == 'points':
            val = day_data.get('points', 0)
        else:
            val = 0

        values.append(val)
        current += timezone.timedelta(days=1)

    # Summary stats for the filtered period
    total_distance = sum(
        d['distance'] for d in daily.values()
    )
    total_routes   = sum(
        d['routes'] for d in daily.values()
    )
    total_duration = sum(
        d['duration'] for d in daily.values()
    )
    active_days    = len(
        [v for v in values if v > 0]
    )

    return JsonResponse({
        'labels':         labels,
        'values':         values,
        'metric':         metric,
        'profile':        profile,
        'date_from':      str(start_date),
        'date_to':        str(end_date),
        'summary': {
            'total_distance': format_distance(
                total_distance
            ),
            'total_routes':   total_routes,
            'total_duration': format_duration(
                total_duration
            ),
            'active_days':    active_days,
            'total_days':     (
                end_date - start_date
            ).days + 1,
        }
    })
