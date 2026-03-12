from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.core.paginator import Paginator
from functools import wraps
import json
import os
import requests
import threading
import logging
import math
from .models import RouteLog
from decouple import config
from django_ratelimit.decorators import ratelimit

logger = logging.getLogger(__name__)

# ---------- CONFIG ----------
ORS_API_KEY = "invalid_key_for_testing_logger"

_routes_lock = threading.Lock()


# ---------------- HELPERS ----------------
def ajax_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"status": "error", "message": "Unauthorized"}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def validate_chunk_points(points):
    if not isinstance(points, list) or len(points) == 0:
        return False, "Points array must not be empty"
    if len(points) > 100:
        return False, "Chunk size exceeds maximum of 100 points"
    for pt in points:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return False, "Invalid point format"
        lat, lon = pt
        if not isinstance(lat, (int, float)) or not (-90.0 <= lat <= 90.0):
            return False, "Invalid latitude"
        if not isinstance(lon, (int, float)) or not (-180.0 <= lon <= 180.0):
            return False, "Invalid longitude"
    return True, ""

def validate_route_points(points):
    if not isinstance(points, list) or len(points) == 0:
        return False, "Points array must not be empty"
    if len(points) > 50000:
        return False, "Route size exceeds maximum of 50000 points"
    for pt in points:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return False, "Invalid point format"
        lat, lon = pt
        if not isinstance(lat, (int, float)) or not (-90.0 <= lat <= 90.0):
            return False, "Invalid latitude"
        if not isinstance(lon, (int, float)) or not (-180.0 <= lon <= 180.0):
            return False, "Invalid longitude"
    return True, ""


# ---------------- HOME ----------------
@login_required
def home(request):
    return render(request, "home.html")


# ---------------- SAVE ROUTE ----------------
@ajax_login_required
@ratelimit(key='user_or_ip', rate='10/m', block=False)
def save_route(request):
    if getattr(request, 'limited', False):
        return JsonResponse({"status": "error", "message": "Too Many Requests"}, status=429)

    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        route = data.get("route", [])
    except:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    is_valid, error_msg = validate_route_points(route)
    if not is_valid:
        return JsonResponse({"status": "error", "message": error_msg}, status=400)

    root = os.path.dirname(os.path.dirname(__file__))
    folder = os.path.join(root, "data")
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, "routes.json")

    # Prevents concurrent /save_route/ requests from 
    # overwriting each other's data in routes.json
    with _routes_lock:
        saved_routes = []
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    saved_routes = json.load(f)
            except:
                saved_routes = []
                
        saved_routes.append(route)
        
        with open(file_path, "w") as f:
            json.dump(saved_routes, f)

    s_lat, s_lon = route[0]
    e_lat, e_lon = route[-1]

    RouteLog.objects.create(
        user=request.user,
        start_lat=s_lat,
        start_lon=s_lon,
        end_lat=e_lat,
        end_lon=e_lon,
        route_points=route,
        total_points=len(route)
    )
    return JsonResponse({"status": "ok"})


# ---------------- SNAP CHUNK ----------------
@ajax_login_required
@ratelimit(key='user_or_ip', rate='30/m', block=False)
def snap_chunk(request):
    if getattr(request, 'limited', False):
        return JsonResponse({"status": "error", "message": "Too Many Requests"}, status=429)

    try:
        data = json.loads(request.body)
        chunk = data.get("points", [])
    except:
        return JsonResponse({"snapped": []}, status=400)

    if len(chunk) < 2:
        return JsonResponse({"snapped": chunk})

    is_valid, error_msg = validate_chunk_points(chunk)
    if not is_valid:
        return JsonResponse({"status": "error", "message": error_msg}, status=400)

    try:
        return JsonResponse({"snapped": ors_match(chunk)})
    except requests.exceptions.ConnectionError:
        return JsonResponse({"status": "error", "message": "OpenRouteService Unavailable"}, status=503)
    except:
        return JsonResponse({"snapped": chunk})


# ---------------- SNAP SINGLE POINT ----------------
@ajax_login_required
@ratelimit(key='user_or_ip', rate='60/m', block=False)
def snap_point(request):
    if getattr(request, 'limited', False):
        return JsonResponse({"status": "error", "message": "Too Many Requests"}, status=429)

    try:
        data = json.loads(request.body)
        lat, lon = data["point"]
    except:
        return JsonResponse({"point": None}, status=400)

    is_valid, error_msg = validate_chunk_points([[lat, lon]])
    if not is_valid:
        return JsonResponse({"status": "error", "message": error_msg}, status=400)

    url = "https://api.openrouteservice.org/v2/nearest/driving-car"

    try:
        r = requests.post(
            url,
            json={"coordinates": [[lon, lat]]},
            headers={"Authorization": ORS_API_KEY},
            timeout=6
        )

        if r.status_code != 200:
            logger.error(f"ORS non-200 response: {r.status_code} - {r.text}")
            return JsonResponse({"point": [lat, lon]})

        j = r.json()

        if not j.get("features"):
            return JsonResponse({"point": [lat, lon]})
        
        c = j["features"][0]["geometry"]["coordinates"]
        return JsonResponse({"point": [c[1], c[0]]})

    except requests.exceptions.Timeout:
        return JsonResponse({"point": [lat, lon]})
    except requests.exceptions.ConnectionError:
        return JsonResponse({"status": "error", "message": "OpenRouteService Unavailable"}, status=503)
    except:
        return JsonResponse({"point": [lat, lon]})


# ---------------- ORS MATCH ----------------
def ors_match(route):
    if len(route) < 2:
        return route

    cleaned = route[::2] if len(route) > 30 else route
    coords = [[lon, lat] for lat, lon in cleaned]

    url = "https://api.openrouteservice.org/match/v2/driving-car"

    body = {
        "coordinates": coords,
        "radiuses": [50] * len(coords)
    }

    try:
        r = requests.post(
            url,
            json=body,
            headers={"Authorization": ORS_API_KEY},
            timeout=20
        )

        if r.status_code != 200:
            logger.error(f"ORS non-200 response: {r.status_code} - {r.text}")
            return route

        data = r.json()

        if not data.get("features"):
            return route

        geom = data["features"][0]["geometry"]["coordinates"]
        snapped = [[lat, lon] for lon, lat in geom]

        return snapped if len(snapped) > 1 else route

    except requests.exceptions.Timeout:
        return route
    # ConnectionError exception falls through and caught by snap_chunk


# ---------------- GET SAVED ----------------
def get_saved_route(request):
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "data", "routes.json")

    try:
        with open(path) as f:
            data = json.load(f)
    except:
        data = []

    return JsonResponse({"snapped": data})


def haversine_dist(lat1, lon1, lat2, lon2):
    R = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(d_lon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def compute_route_distance(points):
    total = 0.0
    for i in range(1, len(points)):
        total += haversine_dist(
            points[i-1][0], points[i-1][1],
            points[i][0],   points[i][1]
        )
    return round(total)

@ajax_login_required
def route_history(request):
    routes = RouteLog.objects.filter(user=request.user).order_by("-created_at")

    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 10)
    
    paginator = Paginator(routes, limit)
    try:
        page_obj = paginator.get_page(page_number)
    except:
        page_obj = paginator.get_page(1)

    result = []
    for r in page_obj:
        local_time = timezone.localtime(r.created_at)
        
        # Calculate dynamic distance and duration proxy
        distance = compute_route_distance(r.route_points)
        duration = r.total_points * 5  # 5 seconds per pt assumption
        
        result.append({
            "id": r.id,
            "date": local_time.strftime("%d %b %Y"),
            "time": local_time.strftime("%I:%M %p"),
            "start_lat": r.start_lat,
            "start_lon": r.start_lon,
            "end_lat": r.end_lat,
            "end_lon": r.end_lon,
            "total_points": r.total_points,
            "route_points": r.route_points,
            "distance_meters": distance,
            "duration_seconds": duration,
        })

    return JsonResponse({
        "routes": result,
        "metadata": {
            "total_routes": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": page_obj.number,
            "has_next": page_obj.has_next()
        }
    })
