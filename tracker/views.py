import json
import math
import logging
import threading
from django.shortcuts import render
from django.http import JsonResponse
from django.conf import settings
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django_ratelimit.decorators import ratelimit
from .models import RouteLog
import requests

logger = logging.getLogger(__name__)

# Module-level lock — prevents concurrent routes.json
# write collisions from multiple simultaneous users
_routes_lock = threading.Lock()

def ajax_login_required(view_func):
    """
    Returns 401 JSON for unauthenticated AJAX requests
    instead of the default 302 redirect which breaks fetch().
    """
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
            lat = float(point.get('lat'))
            lon = float(point.get('lon'))
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
            lat = float(point.get('lat'))
            lon = float(point.get('lon'))
        except (TypeError, ValueError):
            return f'Point {i} has non-numeric lat/lon'
        if not (-90.0 <= lat <= 90.0):
            return f'Point {i} has invalid latitude: {lat}'
        if not (-180.0 <= lon <= 180.0):
            return f'Point {i} has invalid longitude: {lon}'
    return None

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
        data = json.loads(request.body)
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
        data = json.loads(request.body)
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
            {'error': 'Rate limit exceeded'}, status=429
        )
    if request.method == 'POST':
        data = json.loads(request.body)
        points = data.get('points', [])

        # Use route validator — allows up to 50,000 points
        error = validate_route_points(points)
        if error:
            return JsonResponse({'error': error}, status=400)

        start = points[0]
        end   = points[-1]

        # Save to database
        route = RouteLog.objects.create(
            user=request.user,
            start_lat=float(start['lat']),
            start_lon=float(start['lon']),
            end_lat=float(end['lat']),
            end_lon=float(end['lon']),
            route_points=points,
            total_points=len(points),
        )

        # Thread-safe JSON backup
        backup_path = 'data/routes.json'
        os.makedirs('data', exist_ok=True)
        with _routes_lock:
            try:
                with open(backup_path, 'r') as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except (FileNotFoundError, json.JSONDecodeError):
                existing = []

            existing.append({
                'id': route.id,
                'user': request.user.username,
                'points': points,
                'total_points': len(points),
                'created_at': route.created_at.isoformat(),
            })

            with open(backup_path, 'w') as f:
                json.dump(existing, f, indent=2)

        return JsonResponse({
            'status': 'success',
            'route_id': route.id
        })
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@ajax_login_required
def route_history(request):
    page_num  = int(request.GET.get('page', 1))
    limit     = int(request.GET.get('limit', 10))

    routes = RouteLog.objects.filter(
        user=request.user
    ).order_by('-created_at')

    paginator    = Paginator(routes, limit)
    page_obj     = paginator.get_page(page_num)

    def normalize_points(raw_points):
        """
        Normalizes route_points to always return
        list of {'lat': float, 'lon': float} dicts.
        """
        normalized = []
        for p in raw_points:
            try:
                if isinstance(p, dict) and 'lat' in p:
                    lat = float(p['lat'])
                    lon = float(p.get('lon', p.get('lng', p.get('longitude', 0))))
                elif isinstance(p, dict) and 'latitude' in p:
                    lat = float(p['latitude'])
                    lon = float(p['longitude'])
                elif isinstance(p, (list, tuple)) and len(p) >= 2:
                    lat = float(p[0])
                    lon = float(p[1])
                else:
                    continue

                if (-90 <= lat <= 90) and (-180 <= lon <= 180):
                    normalized.append({'lat': lat, 'lon': lon})
            except (TypeError, ValueError, KeyError):
                continue
        return normalized

    route_list = []
    for route in page_obj:
        points = normalize_points(route.route_points or [])
        if not points:
            continue
        route_list.append({
            'id':               route.id,
            'created_at':       route.created_at.strftime('%d %b %Y, %I:%M %p'),
            'start_lat':        points[0]['lat'],
            'start_lon':        points[0]['lon'],
            'end_lat':          points[-1]['lat'],
            'end_lon':          points[-1]['lon'],
            'route_points':     points,
            'total_points':     len(points),
            'distance_meters':  compute_route_distance(points),
            'duration_seconds': len(points) * 5,
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

    data        = json.loads(request.body)
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
    params = {
        'origin':      f'{origin_lat},{origin_lon}',
        'destination': f'{dest_lat},{dest_lon}',
        'mode':        'driving',
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

                # Decode the encoded polyline string
                # into list of lat/lon coordinates
                decoded = decode_polyline(encoded)
                return JsonResponse({'path': decoded})

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
        return JsonResponse(
            {'error': 'Service unavailable'}, status=503
        )


@login_required
def home(request):
    return render(request, 'home.html', {
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY
    })
