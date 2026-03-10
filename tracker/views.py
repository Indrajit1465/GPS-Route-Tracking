from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
import json
import os
import requests
from .models import RouteLog


# ---------- CONFIG ----------
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjYxOGYzYzNjN2U3YjRlMDBiYmM3Y2VmNmYwYzg2YmNhIiwiaCI6Im11cm11cjY0In0="


# ---------------- HOME ----------------
@login_required
def home(request):
    return render(request, "home.html")


# ---------------- SAVE ROUTE ----------------
@csrf_exempt
def save_route(request):

    if request.method != "POST":
        return JsonResponse({"status": "error"})

    try:
        data = json.loads(request.body)
        route = data.get("route", [])
    except:
        return JsonResponse({"status": "error"})

    if len(route) < 2:
        return JsonResponse({"status": "error"})

    root = os.path.dirname(os.path.dirname(__file__))
    folder = os.path.join(root, "data")
    os.makedirs(folder, exist_ok=True)

    with open(os.path.join(folder, "routes.json"), "w") as f:
        json.dump(route, f)

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
@csrf_exempt
def snap_chunk(request):

    try:
        data = json.loads(request.body)
        chunk = data.get("points", [])
    except:
        return JsonResponse({"snapped": []})

    if len(chunk) < 2:
        return JsonResponse({"snapped": chunk})

    try:
        return JsonResponse({"snapped": ors_match(chunk)})
    except:
        return JsonResponse({"snapped": chunk})

# ---------------- SNAP SINGLE POINT ----------------
@csrf_exempt
def snap_point(request):

    try:
        data = json.loads(request.body)
        lat, lon = data["point"]
    except:
        return JsonResponse({"point": None})

    url = "https://api.openrouteservice.org/v2/nearest/driving-car"

    try:
        r = requests.post(
            url,
            json={"coordinates": [[lon, lat]]},
            headers={"Authorization": ORS_API_KEY},
            timeout=6
        )

        if r.status_code !=200:
            return JsonResponse({"point": [lat, lon]})

        j = r.json()

        if not j.get("features"):
            return JsonResponse({"point": [lat, lon]})
        
        c = j["features"][0]["geometry"]["coordinates"]
        return JsonResponse({"point": [c[1], c[0]]})

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

        if r.status_code !=200:
            return route
        

        data = r.json()

        if not data.get("features"):
            return route

        geom = data["features"][0]["geometry"]["coordinates"]

        snapped = [[lat, lon] for lon, lat in geom]

        return snapped if len(snapped) > 1 else route

    except:
        return route


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


from django.utils import timezone

# ---------------- ROUTE HISTORY ----------------
@login_required
def route_history(request):

    routes = RouteLog.objects.filter(user=request.user).order_by("-created_at")

    result = []
    for r in routes:
        local_time = timezone.localtime(r.created_at)
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
        })

    return JsonResponse({"routes": result})

