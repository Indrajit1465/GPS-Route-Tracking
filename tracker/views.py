import os
import json
import math
import logging
import threading
import functools
from django.shortcuts import render
from django.http import JsonResponse
from django.conf import settings
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django_ratelimit.decorators import ratelimit
from .models import RouteLog
import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# Module-level lock — prevents concurrent routes.json
# write collisions from multiple simultaneous users
_routes_lock = threading.Lock()

def ajax_login_required(view_func):
    """
    Returns 401 JSON for unauthenticated AJAX requests
    instead of the default 302 redirect which breaks fetch().
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'error': 'Unauthorized'}, status=401
            )
        return view_func(request, *args, **kwargs)
    return wrapper

def validate_chunk_points(points):
    """
    Used by /snap_point/ and /snap_chunk/ only.
    Enforces 100-point limit to match Google Roads API max.
    """
    if not points:
        return 'Points array is empty'
    if len(points) > 100:
        return 'Too many points (max 100 per chunk)'
    for i, point in enumerate(points):
        try:
            if not isinstance(point, dict):
                return f'Point {i} is not a valid object'
            lat = float(point.get('lat') or 0)
            lon = float(point.get('lon') or 0)
        except (TypeError, ValueError):
            return f'Point {i} has non-numeric lat/lon'
        if not (-90.0 <= lat <= 90.0):
            return f'Point {i} has invalid latitude: {lat}'
        if not (-180.0 <= lon <= 180.0):
            return f'Point {i} has invalid longitude: {lon}'
    return None

def validate_route_points(points):
    """
    Used by /save_route/ only.
    Allows up to 50,000 points for full route saves.
    """
    if not points:
        return 'Points array is empty'
    if len(points) > 50000:
        return 'Too many points (max 50,000)'
    for i, point in enumerate(points):
        try:
            if not isinstance(point, dict):
                return f'Point {i} is not a valid object'
            lat = float(point.get('lat') or 0)
            lon = float(point.get('lon') or 0)
        except (TypeError, ValueError):
            return f'Point {i} has non-numeric lat/lon'
        if not (-90.0 <= lat <= 90.0):
            return f'Point {i} has invalid latitude: {lat}'
        if not (-180.0 <= lon <= 180.0):
            return f'Point {i} has invalid longitude: {lon}'
    return None

def normalize_points(raw_points):
    """
    Normalizes route_points to always return
    {'lat': float, 'lon': float} dicts.

    Handles all known storage formats:
      Format A: {'lat': x, 'lon': y}        <- standard
      Format B: {'lat': x, 'lon': y}        <- Google Maps
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

def google_snap_to_road(points):
    """
    Snaps GPS points to nearest road using Google Roads API.
    Accepts and returns list of {'lat': float, 'lon': float}.
    Falls back to raw points on any failure.
    """
    api_key = settings.GOOGLE_MAPS_API_KEY

    # Google Roads API: pipe-separated lat,lon pairs
    path = '|'.join([
        f"{float(p['lat'])},{float(p['lon'])}"
        for p in points
    ])

    url = 'https://roads.googleapis.com/v1/snapToRoads'
    params = {
        'path': path,
        'interpolate': 'true',
        'key': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=5)

        if response.status_code == 200:
            data = response.json()
            snapped = data.get('snappedPoints', [])
            if snapped:
                return [
                    {
                        'lat': float(p['location']['latitude']),
                        'lon': float(p['location']['longitude'])
                    }
                    for p in snapped
                ]
            # Empty snappedPoints — return raw fallback
            return points

        # Non-200 response — log and fallback
        logger.error(
            f'Google Roads API error: '
            f'{response.status_code} - {response.text}'
        )
        return points

    except requests.exceptions.Timeout:
        logger.warning('Google Roads API timeout — using raw points')
        return points
    except requests.exceptions.ConnectionError:
        logger.error('Google Roads API connection error — using raw points')
        return points

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def compute_route_distance(points):
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

@ajax_login_required
@ratelimit(key='user_or_ip', rate='60/m', block=False)
def snap_point(request):
    if getattr(request, 'limited', False):
        return JsonResponse(
            {'error': 'Rate limit exceeded'}, status=429
        )
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {'error': 'Invalid JSON body'}, status=400
            )
        points = data.get('points', [])
        error = validate_chunk_points(points)
        if error:
            return JsonResponse({'error': error}, status=400)
        snapped = google_snap_to_road(points)
        return JsonResponse({'snapped': snapped})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@ajax_login_required
@ratelimit(key='user_or_ip', rate='30/m', block=False)
def snap_chunk(request):
    if getattr(request, 'limited', False):
        return JsonResponse(
            {'error': 'Rate limit exceeded'}, status=429
        )
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {'error': 'Invalid JSON body'}, status=400
            )
        points = data.get('points', [])
        error = validate_chunk_points(points)
        if error:
            return JsonResponse({'error': error}, status=400)
        snapped = google_snap_to_road(points)
        return JsonResponse({'snapped': snapped})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@ajax_login_required
@ratelimit(key='user_or_ip', rate='10/m', block=False)
def save_route(request):
    if getattr(request, 'limited', False):
        return JsonResponse(
            {'error': 'Rate limit exceeded'},
            status=429
        )

    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Method not allowed'},
            status=405
        )

    try:
        data   = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {'error': 'Invalid JSON body'},
            status=400
        )

    points  = data.get('points', [])
    profile = data.get('profile', 'car')

    # Validate profile
    allowed_profiles = [
        'walking', 'cycling', 'motorcycle', 'car'
    ]
    if profile not in allowed_profiles:
        profile = 'car'

    # Validate points using route validator
    error = validate_route_points(points)
    if error:
        return JsonResponse(
            {'error': error}, status=400
        )

    start = points[0]
    end   = points[-1]

    # ── STEP 1: Database write (primary) ─────────
    # This MUST succeed — it is the source of truth
    try:
        route = RouteLog.objects.create(
            user         = request.user,
            start_lat    = float(start['lat']),
            start_lon    = float(start['lon']),
            end_lat      = float(end['lat']),
            end_lon      = float(end['lon']),
            route_points = points,
            total_points = len(points),
            profile      = profile,
        )
    except Exception as db_error:
        logger.error(
            f'Database save failed: {db_error}'
        )
        return JsonResponse(
            {'error': 'Failed to save route to database'},
            status=500
        )

    # ── STEP 2: File backup (secondary) ──────────
    # Failure here does NOT affect the response
    # Route is already safely in PostgreSQL
    try:
        data_dir = os.path.join(
            str(settings.BASE_DIR), 'data'
        )
        os.makedirs(data_dir, exist_ok=True)
        backup_path = os.path.join(
            data_dir, 'routes.json'
        )

        existing = []
        with _routes_lock:
            # Rotate if file exceeds 10MB
            if os.path.exists(backup_path):
                if os.path.getsize(backup_path) > 10485760:
                    from datetime import datetime
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    rotated = os.path.join(
                        data_dir, f'routes_{ts}.json'
                    )
                    os.rename(backup_path, rotated)
                    logger.info(f'Backup rotated to {rotated}')
                    existing = []
                else:
                    try:
                        with open(backup_path, 'r') as f:
                            loaded = json.load(f)
                        if isinstance(loaded, list):
                            existing = loaded
                    except (FileNotFoundError,
                            json.JSONDecodeError):
                        existing = []

            existing.append({
                'id':          route.id,
                'user':        request.user.username,
                'points':      points,
                'total_points': len(points),
                'profile':     profile,
                'created_at':  route.created_at
                               .isoformat(),
            })

            with open(backup_path, 'w') as f:
                json.dump(existing, f, indent=2)

    except Exception as backup_error:
        # Log backup failure but do NOT return error
        # The route is already saved in PostgreSQL
        logger.warning(
            f'JSON backup failed for route '
            f'{route.id}: {backup_error}'
        )

    # ── STEP 3: Return success ────────────────────
    return JsonResponse({
        'status':   'success',
        'route_id': route.id,
        'message':  f'Route saved with '
                    f'{len(points)} points.',
    })


@ajax_login_required
def route_history(request):
    try:
        page_num = max(1, int(request.GET.get('page', 1)))
        limit = min(50, max(1, int(request.GET.get('limit', 10))))
    except (ValueError, TypeError):
        return JsonResponse(
            {'error': 'Invalid page or limit parameter'},
            status=400
        )

    routes = RouteLog.objects.filter(
        user=request.user
    ).order_by('-created_at')

    paginator    = Paginator(routes, limit)
    page_obj     = paginator.get_page(page_num)

    route_list = []
    for route in page_obj:
        points = normalize_points(route.route_points or [])
        if not points:
            continue
        distance_m = compute_route_distance(points)
        pts_per_km = round(
            len(points) / (distance_m / 1000)
        ) if distance_m > 100 else 0

        route_list.append({
            'id':               route.id,
            'created_at':       timezone.localtime(route.created_at).strftime('%d %b %Y, %I:%M %p'),
            'profile':          route.profile,
            'start_lat':        points[0]['lat'],
            'start_lon':        points[0]['lon'],
            'end_lat':          points[-1]['lat'],
            'end_lon':          points[-1]['lon'],
            'route_points':     points,
            'total_points':     len(points),
            'distance_meters':  distance_m,
            'duration_seconds': len(points) * 5,
            'points_per_km':    pts_per_km,
            'sampling_quality': (
                'Excellent' if pts_per_km > 40 else
                'Good'      if pts_per_km > 20 else
                'Fair'      if pts_per_km > 8  else
                'Low'
            )
        })

    return JsonResponse({
        'routes':       route_list,
        'total_pages':  paginator.num_pages,
        'current_page': page_num,
        'total_routes': paginator.count,
    })


def decode_polyline(encoded):
    """
    Decodes a Google Maps encoded polyline string
    into a list of {'lat': float, 'lon': float} dicts.
    This is the road geometry between two points.
    """
    points  = []
    index   = 0
    lat     = 0
    lon     = 0
    length  = len(encoded)

    while index < length:
        # Decode latitude
        result = 1
        shift  = 0
        while True:
            b       = ord(encoded[index]) - 63 - 1
            index  += 1
            result += b << shift
            shift  += 5
            if b < 0x1f:
                break
        lat += (~result >> 1) if (result & 1) != 0 else (result >> 1)

        # Decode longitude
        result = 1
        shift  = 0
        while True:
            b       = ord(encoded[index]) - 63 - 1
            index  += 1
            result += b << shift
            shift  += 5
            if b < 0x1f:
                break
        lon += (~result >> 1) if (result & 1) != 0 else (result >> 1)

        points.append({
            'lat': lat  * 1e-5,
            'lon': lon  * 1e-5
        })

    return points


@ajax_login_required
def get_road_path(request):
    """
    Given origin and destination coordinates,
    returns the actual road path geometry between
    them using Google Directions API.
    This gives real road curves instead of straight lines.
    """
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Method not allowed'}, status=405
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {'error': 'Invalid JSON body'}, status=400
        )
    origin      = data.get('origin')
    destination = data.get('destination')

    if not origin or not destination:
        return JsonResponse(
            {'error': 'origin and destination required'},
            status=400
        )

    try:
        origin_lat = float(origin['lat'])
        origin_lon = float(origin['lon'])
        dest_lat   = float(destination['lat'])
        dest_lon   = float(destination['lon'])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {'error': 'Invalid coordinates'}, status=400
        )

    api_key = settings.GOOGLE_MAPS_API_KEY

    url = 'https://maps.googleapis.com/maps/api/directions/json'
    mode = data.get('mode', 'driving')
    allowed_modes = ['driving', 'walking', 'bicycling']
    if mode not in allowed_modes:
        mode = 'driving'
    
    params = {
        'origin':      f'{origin_lat},{origin_lon}',
        'destination': f'{dest_lat},{dest_lon}',
        'mode':        mode,        # ← Uses profile mode
        'key':         api_key
    }

    try:
        response = requests.get(url, params=params, timeout=5)

        if response.status_code == 200:
            data = response.json()

            if data.get('status') == 'OK':
                # Decode the polyline from Directions API
                # This contains the actual road geometry
                encoded = data['routes'][0]['overview_polyline']['points']

                decoded = decode_polyline(encoded)

                # Verify decoded points are valid
                if not decoded:
                    logger.warning(
                        f'decode_polyline returned empty for '
                        f'encoded string length {len(encoded)}'
                    )
                    # Fall back to straight line between origin/dest
                    return JsonResponse({
                        'path': [
                            {'lat': origin_lat, 'lon': origin_lon},
                            {'lat': dest_lat,   'lon': dest_lon}
                        ],
                        'source': 'fallback'
                    })

                return JsonResponse({
                    'path':   decoded,
                    'source': 'directions',
                    'count':  len(decoded)
                })

            else:
                # Directions API returned no route
                # Fall back to straight line
                logger.warning(
                    f'Directions API status: {data.get("status")}'
                )
                return JsonResponse({
                    'path': [
                        {'lat': origin_lat, 'lon': origin_lon},
                        {'lat': dest_lat,   'lon': dest_lon}
                    ]
                })

    except requests.exceptions.Timeout:
        logger.warning('Directions API timeout')
        return JsonResponse({
            'path': [
                {'lat': origin_lat, 'lon': origin_lon},
                {'lat': dest_lat,   'lon': dest_lon}
            ]
        })
    except requests.exceptions.ConnectionError:
        logger.error('Directions API connection error')
        return JsonResponse({
            'path': [
                {'lat': origin_lat, 'lon': origin_lon},
                {'lat': dest_lat,   'lon': dest_lon}
            ],  
            'source': 'fallback'
        })


@login_required
def home(request):
    return render(request, 'home.html', {
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY
    })

@ajax_login_required
def delete_route(request, route_id):
    """
    Permanently deletes a RouteLog entry.
    Only the owner of the route can delete it.
    Super admins can delete any route.
    """
    if request.method != 'DELETE':
        return JsonResponse(
            {'error': 'Method not allowed'},
            status=405
        )

    try:
        # Regular users can only delete own routes
        # Super admins can delete any route
        if request.user.is_superuser:
            route = RouteLog.objects.get(id=route_id)
        else:
            route = RouteLog.objects.get(
                id=route_id,
                user=request.user  # Ownership check
            )

    except RouteLog.DoesNotExist:
        return JsonResponse(
            {'error': 'Route not found or '
                      'you do not have permission '
                      'to delete this route'},
            status=404
        )

    # Capture info before deletion for response
    route_info = {
        'id':           route.id,
        'total_points': route.total_points,
        'created_at':   str(route.created_at),
    }

    # Permanently delete from PostgreSQL
    route.delete()

    logger.info(
        f'Route {route_id} deleted by '
        f'{request.user.username}'
    )

    return JsonResponse({
        'status':  'deleted',
        'message': f'Route {route_id} permanently '
                   f'deleted from database.',
        'route':   route_info,
    })


def ping(request):
    """
    Lightweight connectivity check endpoint.
    Returns minimal JSON. No authentication required.
    Used by frontend to verify real network connectivity.
    """
    return JsonResponse({'status': 'ok'}, status=200)
