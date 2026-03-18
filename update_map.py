import re

with open("tracker/templates/home.html", "r", encoding="utf-8") as f:
    content = f.read()

google_js = """
  // ─── Global State Variables ───────────────────────────
  let map;
  let routePolyline = null;
  let startMarker = null;
  let endMarker = null;
  let routePoints = [];
  let totalDistanceMeters = 0;
  let lastPoint = null;
  let trackingStartTime = null;
  let durationInterval = null;
  let isTracking = false;
  let watchId = null;

  // ─── Initialize Google Map ────────────────────────────
  function initGoogleMap() {
    map = new google.maps.Map(document.getElementById('map'), {
      center: { lat: 16.7050, lng: 74.2433 }, 
      // Default center: Kolhapur, Maharashtra
      zoom: 15,
      mapTypeId: 'roadmap',
      
      // Google Maps UI options
      zoomControl: true,
      mapTypeControl: false,
      scaleControl: true,
      streetViewControl: false,
      rotateControl: false,
      fullscreenControl: true,

      // Modern Google Maps styling
      styles: [
        {
          featureType: 'poi',
          elementType: 'labels',
          stylers: [{ visibility: 'off' }]
        },
        {
          featureType: 'transit',
          elementType: 'labels',
          stylers: [{ visibility: 'off' }]
        }
      ]
    });
  }

  // ─── Start Tracking ───────────────────────────────────
  function startTracking() {
    // Full reset before new session
    routePoints = [];
    totalDistanceMeters = 0;
    lastPoint = null;

    if (routePolyline) {
      routePolyline.setMap(null);
      routePolyline = null;
    }
    if (startMarker) {
      startMarker.setMap(null);
      startMarker = null;
    }
    if (endMarker) {
      endMarker.setMap(null);
      endMarker = null;
    }

    // Remove route summary card if visible
    const card = document.getElementById('route-summary');
    if (card) card.remove();

    // Reset stats display
    updateDistanceDisplay();
    updatePointsCount(0);
    setTrackingStatus(true);
    startDurationTimer();
    isTracking = true;

    // Initialize empty polyline on Google Maps
    routePolyline = new google.maps.Polyline({
      path: [],
      geodesic: true,
      strokeColor: '#4285F4',
      strokeOpacity: 0.9,
      strokeWeight: 5,
      map: map
    });

    // Start GPS capture
    if (navigator.geolocation) {
      watchId = navigator.geolocation.watchPosition(
        onGPSSuccess,
        onGPSError,
        {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0
        }
      );
    } else {
      alert('Geolocation is not supported by this browser.');
    }
  }

  // ─── GPS Success Callback ─────────────────────────────
  async function onGPSSuccess(position) {
    if (!isTracking) return;

    const lat = position.coords.latitude;
    const lon = position.coords.longitude;
    const newPoint = { lat, lon };

    // Snap to road via backend (Google Roads API)
    const snapped = await snapPoint(newPoint);
    const sLat = snapped.lat;
    const sLon = snapped.lon;

    // Update distance
    if (lastPoint) {
      const from = new google.maps.LatLng(
        lastPoint.lat, lastPoint.lon
      );
      const to = new google.maps.LatLng(sLat, sLon);
      totalDistanceMeters += 
        google.maps.geometry.spherical.computeDistanceBetween(
          from, to
        );
      updateDistanceDisplay();
    }
    lastPoint = { lat: sLat, lon: sLon };

    // Add point to route
    routePoints.push({ lat: sLat, lon: sLon });
    updatePointsCount(routePoints.length);

    // Update polyline on map
    const path = routePolyline.getPath();
    path.push(new google.maps.LatLng(sLat, sLon));

    // Place start marker on first point
    if (routePoints.length === 1) {
      startMarker = new google.maps.Marker({
        position: { lat: sLat, lng: sLon },
        map: map,
        title: 'Start Point',
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 10,
          fillColor: '#34A853',
          fillOpacity: 1,
          strokeColor: '#ffffff',
          strokeWeight: 3
        }
      });
    }

    // Pan map to current location
    map.panTo({ lat: sLat, lng: sLon });
  }

  // ─── GPS Error Callback ───────────────────────────────
  function onGPSError(error) {
    console.error('GPS error:', error.message);
  }

  // ─── Snap Single Point to Road ────────────────────────
  async function snapPoint(point) {
    try {
      const res = await fetch('/snap_chunk/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ points: [[point.lat, point.lon]] })
      });
      if (res.status === 401) {
        window.location.href = '/login/';
        return point;
      }
      if (res.ok) {
        const data = await res.json();
        if (data.snapped && data.snapped.length > 0) {
          return { lat: data.snapped[0][0], lon: data.snapped[0][1] };
        }
      }
    } catch (e) {
      console.error('Snap error:', e);
    }
    return point; // fallback to raw point
  }

  // ─── Stop Tracking + Save Route ───────────────────────
  async function stopTracking() {
    if (!isTracking) return;
    isTracking = false;

    if (watchId) {
      navigator.geolocation.clearWatch(watchId);
      watchId = null;
    }

    setTrackingStatus(false);
    stopDurationTimer();

    if (routePoints.length === 0) {
      alert('No route data to save.');
      return;
    }

    // Place end marker
    const lastCoord = routePoints[routePoints.length - 1];
    endMarker = new google.maps.Marker({
      position: { lat: lastCoord.lat, lng: lastCoord.lon },
      map: map,
      title: 'End Point',
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 10,
        fillColor: '#EA4335',
        fillOpacity: 1,
        strokeColor: '#ffffff',
        strokeWeight: 3
      }
    });

    // Save route to backend
    await saveRoute();
  }

  // ─── Save Route to Backend ────────────────────────────
  async function saveRoute() {
    try {
      const res = await fetch('/save_route/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
        },
        // The backend expects list of lists [[lat, lon], ...]
        body: JSON.stringify({ route: routePoints.map(p => [p.lat, p.lon]) })
      });
      if (res.status === 401) {
        window.location.href = '/login/';
        return;
      }
      if (res.ok) {
        console.log('Route saved successfully');
      } else {
        const err = await res.json();
        console.error('Save failed:', err);
      }
    } catch (e) {
      console.error('Save error:', e);
    }
  }

  // ─── Load History Route on Map ────────────────────────
  function loadHistoryRoute(routeData) {
    // Clear current map
    if (routePolyline) {
      routePolyline.setMap(null);
      routePolyline = null;
    }
    if (startMarker) {
      startMarker.setMap(null);
      startMarker = null;
    }
    if (endMarker) {
      endMarker.setMap(null);
      endMarker = null;
    }

    const coords = routeData.route_points;
    if (!coords || coords.length === 0) return;

    // Draw historical route polyline
    const path = coords.map(p => ({
      lat: p[0], lng: p[1]
    }));

    routePolyline = new google.maps.Polyline({
      path: path,
      geodesic: true,
      strokeColor: '#4285F4',
      strokeOpacity: 0.9,
      strokeWeight: 5,
      map: map
    });

    // RED marker at start
    startMarker = new google.maps.Marker({
      position: { lat: coords[0][0], lng: coords[0][1] },
      map: map,
      title: 'Start Point',
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 10,
        fillColor: '#EA4335',
        fillOpacity: 1,
        strokeColor: '#ffffff',
        strokeWeight: 3
      }
    });

    // BLUE marker at end
    const last = coords[coords.length - 1];
    endMarker = new google.maps.Marker({
      position: { lat: last[0], lng: last[1] },
      map: map,
      title: 'End Point',
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 10,
        fillColor: '#4285F4',
        fillOpacity: 1,
        strokeColor: '#ffffff',
        strokeWeight: 3
      }
    });

    // Auto-fit map bounds to show full route
    const bounds = new google.maps.LatLngBounds();
    path.forEach(p => bounds.extend(p));
    map.fitBounds(bounds);

    // Show summary card
    showRouteSummaryCard(routeData);
    closeHistory();
  }
  
  // Bind buttons
  document.getElementById("startBtn").onclick = function() {
      startBtn.disabled = true;
      stopBtn.disabled = false;
      startTracking();
  };
  document.getElementById("stopBtn").onclick = function() {
      startBtn.disabled = false;
      stopBtn.disabled = true;
      stopTracking();
  };
  
  function showRouteOnMap(idx) {
      const r = historyData[idx];
      if (!r || !r.route_points) return;
      loadHistoryRoute(r);
  }
"""

# Block replacements:
# 1. Remove // ================= MAP ================= to // ================= COOKIE ================= (exclusive)
start_idx_map = content.find("        // ================= MAP =================")
end_idx_cookie = content.find("        // ================= COOKIE =================")

if start_idx_map != -1 and end_idx_cookie != -1:
    content = content[:start_idx_map] + google_js + "\n\n" + content[end_idx_cookie:]
else:
    print("Could not find block 1")

# 2. Remove // ================= ONLINE SAVE ================= to // ================= VIEW OFFLINE =================
start_idx_online_save = content.find("        // ================= ONLINE SAVE =================")
end_idx_view_offline = content.find("        // ================= VIEW OFFLINE =================")

if start_idx_online_save != -1 and end_idx_view_offline != -1:
    content = content[:start_idx_online_save] + content[end_idx_view_offline:]
else:
    print("Could not find block 2")

# 3. Handle showRouteOnMap inside route history section
start_idx_show_route = content.find("        function showRouteOnMap(idx) {")
if start_idx_show_route != -1:
    end_idx_show_route = content.find("        function showRouteSummaryCard(r) {", start_idx_show_route)
    if end_idx_show_route != -1:
        content = content[:start_idx_show_route] + content[end_idx_show_route:]

# 4. Remove leaflet clearHistoryRoute inside ROUTE HISTORY
start_idx_chr = content.find("        function clearHistoryRoute() {")
if start_idx_chr != -1:
    end_idx_chr = content.find("        function closeHistory() {", start_idx_chr)
    if end_idx_chr != -1:
        chr_google = '''        function clearHistoryRoute() {
            if (routePolyline) { routePolyline.setMap(null); routePolyline = null; }
            if (startMarker) { startMarker.setMap(null); startMarker = null; }
            if (endMarker) { endMarker.setMap(null); endMarker = null; }
            const card = document.getElementById('route-summary');
            if (card) card.remove();
        }
'''
        content = content[:start_idx_chr] + chr_google + content[end_idx_chr:]


with open("tracker/templates/home.html", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
