
  // ─── PART 1: All Global Variable Declarations (FIRST) ──
  let map;
  let routePolyline = null;
  let startMarker   = null;
  let endMarker     = null;
  let routePoints          = [];
  let totalDistanceMeters  = 0;
  let lastPoint            = null;
  let isTracking       = false;
  let watchId          = null;
  let trackingStartTime = null;
  let durationInterval  = null;
  let movingMarker  = null;
  let lastSampleTime = 0;
  let rawSmoothingBuffer = [];
  let snapBatchBuffer = [];
  let navLastHeading = null;
  let navLastSpeed = 0;
  let navLastTime = 0;
  
  // ─── PART 1.5: Offline DB Variables ──
  let dbPromise = null;
  let isOfflineMode = false;
  
  // ─── PART 1.8: Real-Time Animation Variables ──
  let livePolyline = null;
  let liveRoutePoints = [];
  let markerAnimFrame = null;
  let isMarkerAnimating = false;
  
  // ─── PART 6: Route History Functions (Variables) ──
  let historyPolyline = null;
  let historyStartMarker = null;
  let historyEndMarker = null;
  let historyData = [];       
  let historyMeta = { current_page: 1, total_pages: 1 };


  // ─── PART 1.7: IndexedDB Initialization & Sync ──
  function initIndexedDB() {
      if (!('indexedDB' in window)) {
          console.error("This browser doesn't support IndexedDB.");
          return null;
      }
      return new Promise((resolve, reject) => {
          const request = window.indexedDB.open("GPSRouteDB", 1);
          request.onupgradeneeded = (event) => {
              console.log("IndexedDB: onupgradeneeded triggered. Creating object stores.");
              const db = event.target.result;
              if (!db.objectStoreNames.contains("offlineRoutes")) {
                  db.createObjectStore("offlineRoutes", { keyPath: "id", autoIncrement: true });
              }
              if (!db.objectStoreNames.contains("offlineChunks")) {
                  db.createObjectStore("offlineChunks", { keyPath: "id", autoIncrement: true });
              }
          };
          request.onsuccess = (event) => {
              console.log("IndexedDB: Successfully opened.");
              resolve(event.target.result);
          };
          request.onerror = (event) => {
              console.error("IndexedDB: Initialization failed.", event.target.error);
              reject(event.target.error);
          };
      });
  }

  dbPromise = initIndexedDB();

  async function bufferRouteChunk(pointsArray) {
      const db = await dbPromise;
      if (!db) return;
      return new Promise((resolve, reject) => {
          const tx = db.transaction("offlineChunks", "readwrite");
          const store = tx.objectStore("offlineChunks");
          const item = {
              timestamp: Date.now(),
              points: pointsArray
          };
          const req = store.add(item);
          req.onsuccess = () => {
              console.log("Buffered chunk offline:", pointsArray.length, "points");
              resolve();
          };
          req.onerror = (e) => reject(e.target.error);
      });
  }

  async function saveOfflineFullRoute(routeArray) {
      const db = await dbPromise;
      if (!db) return;
      return new Promise((resolve, reject) => {
          const tx = db.transaction("offlineRoutes", "readwrite");
          const store = tx.objectStore("offlineRoutes");
          const item = {
              timestamp: Date.now(),
              route: routeArray
          };
          const req = store.add(item);
          req.onsuccess = () => {
              console.log("Route saved offline:", routeArray.length, "points");
              resolve();
          };
          req.onerror = (e) => reject(e.target.error);
      });
  }

  async function syncOfflineData() {
      if (!navigator.onLine) return;
      const db = await dbPromise;
      if (!db) return;

      // Sync Chunks
      const chunkTx = db.transaction("offlineChunks", "readonly");
      const chunkStore = chunkTx.objectStore("offlineChunks");
      const chunkReq = chunkStore.getAll();
      
      chunkReq.onsuccess = async () => {
          const chunks = chunkReq.result;
          if (chunks.length > 0) console.log("Found", chunks.length, "offline chunks to sync.");
          
          for (const chunk of chunks) {
              try {
                  const csrfToken = getValidCsrfToken();
                  if (!csrfToken) continue;
                  
                  const res = await fetch('/snap_chunk/', {
                      method: 'POST',
                      headers: {
                          'Content-Type': 'application/json',
                          'X-CSRFToken': csrfToken
                      },
                      body: JSON.stringify({ points: chunk.points })
                  });
                  if (res.ok) {
                      const delTx = db.transaction("offlineChunks", "readwrite");
                      delTx.objectStore("offlineChunks").delete(chunk.id);
                  }
              } catch(e) { console.error("Chunk sync failed", e); }
          }
      };

      // Sync Full Routes
      const routeTx = db.transaction("offlineRoutes", "readonly");
      const routeStore = routeTx.objectStore("offlineRoutes");
      const routeReq = routeStore.getAll();

      routeReq.onsuccess = async () => {
          const routes = routeReq.result;
          if (routes.length > 0) console.log("Found", routes.length, "offline full routes to sync.");
          
          for (const routeObj of routes) {
              try {
                  const csrfToken = getValidCsrfToken();
                  if (!csrfToken) continue;
                  
                  const res = await fetch('/save_route/', {
                      method: 'POST',
                      headers: {
                          'Content-Type': 'application/json',
                          'X-CSRFToken': csrfToken
                      },
                      body: JSON.stringify({ route: routeObj.route })
                  });
                  if (res.ok) {
                      const delTx = db.transaction("offlineRoutes", "readwrite");
                      delTx.objectStore("offlineRoutes").delete(routeObj.id);
                  }
              } catch(e) { console.error("Route sync failed", e); }
          }
      };
  }

  // Monitor network connection for automatic sync
  window.addEventListener('online', syncOfflineData);

  // ─── PART 2: All Utility/Helper Functions (SECOND) ──
  function normalizeCoordinate(p) {
      if (!p) return null;
      let lat = 0, lng = 0;
      if (Array.isArray(p)) {
          lat = p[0]; lng = p[1];
      } else if (typeof p === 'object') {
          lat = p.lat ?? p[0];
          lng = p.lng ?? p.lon ?? p[1];
      } else if (typeof p === 'string') {
          const parts = p.split(/,|\||;/);
          if (parts.length >= 2) {
              lat = parts[0]; lng = parts[1];
          }
      }
      lat = parseFloat(lat);
      lng = parseFloat(lng);
      if (isNaN(lat) || isNaN(lng)) return null;
      return { lat, lng };
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
  }

  function getValidCsrfToken() {
      const token = getCookie('csrftoken');
      if (!token || token.length < 32) {
          console.warn("CSRF token missing or invalid length.");
      }
      return token;
  }

  function updateDistanceDisplay() {
    const el = document.getElementById('distance-display');
    if (!el) return;
    if (totalDistanceMeters < 1000) {
      el.textContent = Math.round(totalDistanceMeters) + ' m';
    } else {
      el.textContent = (totalDistanceMeters / 1000).toFixed(2) + ' km';
    }
  }

  function updatePointsCount(count) {
    const el = document.getElementById('points-count');
    if (!el) return;
    el.textContent = count;
  }

  function setTrackingStatus(active) {
    const el = document.getElementById('tracking-status');
    if (!el) return;
    if (active) {
      el.innerHTML = '<span class="status-dot live"></span> Live';
    } else {
      el.innerHTML = '<span class="status-dot idle"></span> Idle';
    }
  }

  function startDurationTimer() {
    trackingStartTime = Date.now();
    durationInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - trackingStartTime) / 1000);
      const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
      const secs = String(elapsed % 60).padStart(2, '0');
      const el = document.getElementById('trip-duration');
      if (el) el.textContent = mins + ':' + secs;
    }, 1000);
  }

  function stopDurationTimer() {
    if (durationInterval) {
      clearInterval(durationInterval);
      durationInterval = null;
    }
  }

  function resetStats() {
    totalDistanceMeters = 0;
    lastPoint           = null;
    lastSampleTime      = 0;
    rawSmoothingBuffer  = [];
    snapBatchBuffer     = [];
    navLastHeading      = null;
    navLastSpeed        = 0;
    navLastTime         = 0;
    liveRoutePoints     = [];
    if (markerAnimFrame) cancelAnimationFrame(markerAnimFrame);
    isMarkerAnimating   = false;
    updateDistanceDisplay();
    updatePointsCount(0);
    setTrackingStatus(false);
    stopDurationTimer();
    const el = document.getElementById('trip-duration');
    if (el) el.textContent = '00:00';
  }

  function formatDistance(meters) {
    if (meters < 1000) return Math.round(meters) + ' m';
    return (meters / 1000).toFixed(2) + ' km';
  }

  function formatDuration(seconds) {
    if (seconds < 60) return seconds + ' sec';
    if (seconds < 3600) {
      const mins = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return mins + ' min ' + secs + ' sec';
    }
    const hrs  = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return hrs + ' hr ' + mins + ' min';
  }

  function handleResponseAuth(res) {
    if (res.status === 401) {
      window.location.href = '/login/';
      return false;
    }
    return true;
  }
  
  function placeMarker(lat, lon, color, title, type) {
    // Validate coordinates before placing marker
    const parsedLat = parseFloat(lat);
    const parsedLon = parseFloat(lon);

    if (isNaN(parsedLat) || isNaN(parsedLon)) {
      console.error(
        'placeMarker received invalid coordinates:', 
        lat, lon
      );
      return null;
    }

    // Create colored pin element for AdvancedMarkerElement
    const pin = new google.maps.marker.PinElement({
      background: color,
      borderColor: '#ffffff',
      glyphColor: '#ffffff',
      scale: type === 'current' ? 0.9 : 1.2
    });

    const marker = new google.maps.marker.AdvancedMarkerElement({
      position: { lat: parsedLat, lng: parsedLon },
      map: map,
      title: title,
      content: pin.element
    });

    return marker;
  }

  // ─── PART 3: Google Maps Init Function (THIRD) ──
  function initGoogleMap() {
    map = new google.maps.Map(
      document.getElementById('map'), {
        center: { lat: 16.7050, lng: 74.2433 },
        zoom: 15,
        mapTypeId: 'roadmap',
        mapId: 'GPS_ROUTE_TRACKER_MAP',
        zoomControl: true,
        mapTypeControl: false,
        scaleControl: true,
        streetViewControl: false,
        rotateControl: false,
        fullscreenControl: true,
        styles: [
          {
            featureType: 'poi',
            elementType: 'labels',
            stylers: [{ visibility: 'off' }]
          }
        ]
    });
  }
  window.initMap = initGoogleMap;

  // ─── PART 4: GPS + Tracking Functions (FOURTH) ──
  // Navigation Matching Engine - Core
  function calculateConfidence(from, to, timeDeltaSeconds) {
    if (!from) return { confidence: 100, distance: 0, speed: 0, heading: 0 };
    let confidence = 100;

    const distance = google.maps.geometry.spherical.computeDistanceBetween(from, to);
    const speed = timeDeltaSeconds > 0 ? (distance / timeDeltaSeconds) : 0;
    const heading = google.maps.geometry.spherical.computeHeading(from, to);

    // 1. Speed Continuity Check (Road Lock against GPS teleporting)
    if (speed > 45) { // Faster than 160 km/h is unrealistic for tracking
       confidence -= 60;
    } else if (navLastSpeed > 0 && Math.abs(speed - navLastSpeed) > 15) {
       // Sudden delta of 54 km/h jump in a second implies a noisy drift ray
       confidence -= 30; 
    }

    // 2. Heading Continuity Check
    if (navLastHeading !== null && speed > 2) {
       let headingDiff = Math.abs(heading - navLastHeading);
       if (headingDiff > 180) headingDiff = 360 - headingDiff; // circle wrap
       
       // Strong turns without deceleration normally means jumping parallel roads erroneously
       if (headingDiff > 45 && speed > 15) confidence -= 25;
       if (headingDiff > 100) confidence -= 40;
    }

    return { confidence, distance, speed, heading };
  }

  // Smooth Marker Animation Engine
  function smoothMoveMarker(lat, lng, heading, duration = 1000) {
      if (!movingMarker) {
          updateDirectionalMarker(lat, lng, heading);
          return;
      }
      
      const startLat = movingMarker.position.lat;
      const startLng = movingMarker.position.lng;
      const startTime = performance.now();
      
      if (markerAnimFrame) cancelAnimationFrame(markerAnimFrame);
      isMarkerAnimating = true;

      function animate(time) {
          let elapsed = time - startTime;
          let progress = elapsed / duration;
          if (progress > 1) progress = 1;
          
          // Linear interpolation for coordinates
          const currentLat = startLat + (lat - startLat) * progress;
          const currentLng = startLng + (lng - startLng) * progress;
          
          updateDirectionalMarker(currentLat, currentLng, heading);
          
          if (progress < 1) {
              markerAnimFrame = requestAnimationFrame(animate);
          } else {
              isMarkerAnimating = false;
          }
      }
      markerAnimFrame = requestAnimationFrame(animate);
  }

  async function applyValidatedPoint(norm, pointTs, isFallback) {
        const to = new google.maps.LatLng(norm.lat, norm.lng);
        const from = lastPoint ? new google.maps.LatLng(lastPoint.lat, lastPoint.lng) : null;
        
        let timeDelta = 1;
        if (navLastTime > 0) {
            timeDelta = (pointTs - navLastTime) / 1000;
            if (timeDelta <= 0) timeDelta = 1; // avoid Infinity
        }

        if (from) {
          const stats = calculateConfidence(from, to, timeDelta);
          
          if (stats.confidence < 50 && !isFallback) {
             console.warn('Low confidence snapped point rejected (Road Lock active). Confidence:', stats.confidence, 'Speed:', stats.speed);
             return; 
          }

          if (stats.distance > 5) {
            totalDistanceMeters += stats.distance;
            updateDistanceDisplay();
            smoothMoveMarker(norm.lat, norm.lng, stats.heading, isFallback ? 2000 : 1000);
            navLastHeading = stats.heading;
            navLastSpeed = stats.speed;
          } else {
             // Retain old heading if we barely moved
             smoothMoveMarker(norm.lat, norm.lng, navLastHeading, 500);
          }
        } else {
          startMarker = placeMarker(norm.lat, norm.lng, '#34A853', 'Start Point', 'start');
          updateDirectionalMarker(norm.lat, norm.lng, 0);
          navLastHeading = 0;
          navLastSpeed = 0;
        }

        lastPoint = { lat: norm.lat, lng: norm.lng };
        navLastTime = pointTs;
        routePoints.push(norm);
        updatePointsCount(routePoints.length);

        const path = routePolyline.getPath();
        path.push(to);
        
        // Remove trailing live line once snap is confirmed
        if (livePolyline) livePolyline.setPath([to]);
  }

  function handleDeadReckoningFallback(rawBatch) {
      console.log('Initiating Smarter Snap / Dead Reckoning Fallback pipeline for', rawBatch.length, 'points');
      for (let i = 0; i < rawBatch.length; i++) {
         const rawNorm = normalizeCoordinate(rawBatch[i]);
         if (!rawNorm) continue;
         const pointTs = rawBatch[i].ts || Date.now();
         
         if (lastPoint && navLastHeading !== null && navLastSpeed > 2 && navLastTime > 0) {
             const from = new google.maps.LatLng(lastPoint.lat, lastPoint.lng);
             let timeDelta = (pointTs - navLastTime) / 1000;
             if (timeDelta < 0) timeDelta = 1;

             const projectedDist = navLastSpeed * Math.min(timeDelta, 5); // Cap 5s max glide
             const projectedLatLng = google.maps.geometry.spherical.computeOffset(from, projectedDist, navLastHeading);
             
             const rawLatLng = new google.maps.LatLng(rawNorm.lat, rawNorm.lng);
             const drift = google.maps.geometry.spherical.computeDistanceBetween(projectedLatLng, rawLatLng);
             
             // If raw GPS wandered far away from projection, trust the projection (Road Lock)
             if (drift < 40) {
                 const pLat = projectedLatLng.lat();
                 const pLng = projectedLatLng.lng();
                 applyValidatedPoint({lat: pLat, lng: pLng}, pointTs, true);
             } else {
                 // Genuine large turn? Accept raw as fallback
                 applyValidatedPoint(rawNorm, pointTs, true);
             }
         } else {
             applyValidatedPoint(rawNorm, pointTs, true);
         }
      }
  }

  async function processSnapBatch(pointsArray) {
    try {
      const csrfToken = getValidCsrfToken();
      if (!csrfToken) return;

      const res = await fetch('/snap_chunk/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ points: pointsArray })
      });

      if (!handleResponseAuth(res)) return;

      if (!res.ok) throw new Error('Snap API failed with ' + res.status);

      const data = await res.json();
      const snapped = data.snapped || [];
      if (snapped.length === 0) throw new Error('Empty snapped batch');

      for (let i = 0; i < snapped.length; i++) {
        const norm = normalizeCoordinate(snapped[i]);
        if (!norm || isNaN(norm.lat) || isNaN(norm.lng)) continue;
        const pointTs = pointsArray[i] ? pointsArray[i].ts : Date.now();
        await applyValidatedPoint(norm, pointTs, false);
      }
      
      // Keep last 2 points for continuous overlapping smoothing
      if (snapBatchBuffer.length === 0) {
          snapBatchBuffer = pointsArray.slice(-2);
      }
      
    } catch (e) {
      console.warn('Snap batch failed. Engaging Fallback...', e);
      handleDeadReckoningFallback(pointsArray);
      
      // Weak Signal Buffer: Automatically store unsnapped points for later sync
      bufferRouteChunk(pointsArray);
      
      if (snapBatchBuffer.length === 0) {
          snapBatchBuffer = pointsArray.slice(-2);
      }
    }
  }

  function updateDirectionalMarker(lat, lng, heading) {
    if (!movingMarker) {
        const svgHTML = `
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" style="transform: rotate(${heading || 0}deg); transition: transform 0.1s linear;">
                <path d="M16 2L30 30L16 22L2 30L16 2Z" fill="#4285F4" stroke="#ffffff" stroke-width="2"/>
            </svg>
        `;
        const iconDiv = document.createElement('div');
        iconDiv.innerHTML = svgHTML;
        
        movingMarker = new google.maps.marker.AdvancedMarkerElement({
            position: { lat, lng },
            map: map,
            title: 'Current Position',
            content: iconDiv
        });
        movingMarker.content.dataset.heading = heading || 0;
    } else {
        movingMarker.position = { lat, lng };
        if (heading !== null) {
            const svgSvg = movingMarker.content.querySelector('svg');
            if (svgSvg) {
                svgSvg.style.transform = `rotate(${heading}deg)`;
            }
            movingMarker.content.dataset.heading = heading;
        }
    }
  }

  async function onGPSSuccess(position) {
    if (!isTracking) return;

    const speed = position.coords.speed || 0;
    let sampleInterval = 8000;
    if (speed > 1.5) sampleInterval = 2000;
    if (speed > 5) sampleInterval = 1000;

    const now = Date.now();
    if (now - lastSampleTime < sampleInterval) return;
    lastSampleTime = now;

    if (position.coords.accuracy > 15) {
      console.warn('GPS drift ignored — accuracy > 15m:', position.coords.accuracy);
      return;
    }

    const rawLat = parseFloat(position.coords.latitude);
    const rawLon = parseFloat(position.coords.longitude);
    if (isNaN(rawLat) || isNaN(rawLon)) return;

    rawSmoothingBuffer.push({ lat: rawLat, lng: rawLon, ts: now });
    if (rawSmoothingBuffer.length > 3) rawSmoothingBuffer.shift();

    const avgLat = rawSmoothingBuffer.reduce((sum, p) => sum + p.lat, 0) / rawSmoothingBuffer.length;
    const avgLng = rawSmoothingBuffer.reduce((sum, p) => sum + p.lng, 0) / rawSmoothingBuffer.length;
    const avgTs = rawSmoothingBuffer[rawSmoothingBuffer.length - 1].ts;

    // 1. Instantly Draw Live Trace Frame
    const liveCoord = new google.maps.LatLng(avgLat, avgLng);
    if (!lastPoint) {
         startMarker = placeMarker(avgLat, avgLng, '#34A853', 'Start Point', 'start');
         updateDirectionalMarker(avgLat, avgLng, 0);
         lastPoint = { lat: avgLat, lng: avgLng };
         navLastTime = avgTs;
    } else {
         const path = livePolyline.getPath();
         path.push(liveCoord);
         
         const from = new google.maps.LatLng(movingMarker.position.lat, movingMarker.position.lng);
         const dist = google.maps.geometry.spherical.computeDistanceBetween(from, liveCoord);
         
         // Animate marker over incoming un-snapped points instantly
         if (dist > 2) {
             const heading = google.maps.geometry.spherical.computeHeading(from, liveCoord);
             smoothMoveMarker(avgLat, avgLng, heading, sampleInterval - 100);
             map.panTo({ lat: avgLat, lng: avgLng });
         }
    }

    // 2. Queue for Snapping
    snapBatchBuffer.push({ lat: avgLat, lng: avgLng, ts: avgTs });
    if (snapBatchBuffer.length >= 6) {   // Reduced chunk size for faster responses
      const chunk = [...snapBatchBuffer];
      snapBatchBuffer = [];
      processSnapBatch(chunk);
    }
  }

  function onGPSError(error) {
    console.error('GPS Error:', error.message);
    alert('GPS error: ' + error.message);
  }

  // ─── PART 5: Start + Stop Tracking Functions (FIFTH) ──
  function startTracking() {
    routePoints = [];
    resetStats();

    if (routePolyline) {
      routePolyline.setMap(null);
      routePolyline = null;
    }
    if (livePolyline) {
      livePolyline.setMap(null);
      livePolyline = null;
    }
    if (startMarker) {
      startMarker.map = null;
      startMarker = null;
    }
    if (endMarker) {
      endMarker.map = null;
      endMarker = null;
    }
    if (movingMarker) {
      movingMarker.map = null;
      movingMarker = null;
    }

    const card = document.getElementById('route-summary');
    if (card) card.remove();

    routePolyline = new google.maps.Polyline({
      path: [],
      geodesic: true,
      strokeColor: '#4285F4',
      strokeOpacity: 0.9,
      strokeWeight: 5,
      map: map
    });
    
    // Transparent thin dashed line indicating real-time GPS feed before snapping confirmation
    livePolyline = new google.maps.Polyline({
      path: [],
      geodesic: true,
      strokeColor: '#9CA3AF', // Gray outline
      strokeOpacity: 0.7,
      strokeWeight: 4,
      icons: [{
          icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 3 },
          offset: '0',
          repeat: '15px'
      }],
      map: map
    });

    setTrackingStatus(true);
    startDurationTimer();
    isTracking = true;

    if (!navigator.geolocation) {
      alert('Geolocation is not supported by this browser.');
      return;
    }

    watchId = navigator.geolocation.watchPosition(
      onGPSSuccess,
      onGPSError,
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0
      }
    );
  }

  async function stopTracking() {
    if (!isTracking) return;

    isTracking = false;
    setTrackingStatus(false);
    stopDurationTimer();

    if (watchId !== null) {
      navigator.geolocation.clearWatch(watchId);
      watchId = null;
    }

    if (snapBatchBuffer.length > 0) {
      await processSnapBatch([...snapBatchBuffer]);
      snapBatchBuffer = [];
    }

    if (routePoints.length === 0) {
      alert('No route points recorded.');
      return;
    }

    const last = routePoints[routePoints.length - 1];
    
    if (movingMarker) {
      movingMarker.map = null;
      movingMarker = null;
    }

    endMarker = placeMarker(
      last.lat, last.lng, '#EA4335', 'End Point', 'end'
    );

    await saveRoute();
  }

  async function saveRoute() {
    const csrfToken = getValidCsrfToken();
    if (!csrfToken) {
      alert('Security token missing. Please refresh.');
      return;
    }

    const payloadRoute = [];
    for (let i = 0; i < routePoints.length; i++) {
        const norm = normalizeCoordinate(routePoints[i]);
        if (!norm || isNaN(norm.lat) || isNaN(norm.lng)) {
            console.error('Invalid coordinate skipped at index ' + i + ':', routePoints[i]);
            continue;
        }
        payloadRoute.push(norm);
    }
    console.log("Saving route payload:", payloadRoute);

    try {
      const res = await fetch('/save_route/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ route: payloadRoute })
      });
      if (!handleResponseAuth(res)) return;
      if (res.ok) {
        console.log('Route saved successfully');
      } else {
        const err = await res.json();
        console.error('Save failed:', err);
        alert('Failed to save route. Saved locally.');
        saveOfflineFullRoute(payloadRoute);
      }
    } catch (e) {
      console.error('Save error (network):', e);
      alert('Network error. Route saved locally.');
      saveOfflineFullRoute(payloadRoute);
    }
  }

  // ─── PART 6: Route History Functions (SIXTH) ──
  function clearHistoryRoute() {
      if (routePolyline) { routePolyline.setMap(null); routePolyline = null; }
      if (startMarker) { startMarker.map = null; startMarker = null; }
      if (endMarker) { endMarker.map = null; endMarker = null; }
      const card = document.getElementById('route-summary');
      if (card) card.remove();
  }
  function closeHistory() {
      document.getElementById('historyOverlay').classList.remove('active');
  }

  async function viewHistory(page = 1) {
      const overlay = document.getElementById('historyOverlay');
      const body = document.getElementById('historyBody');

      overlay.classList.add('active');

      if (page === 1) {
          body.innerHTML = '<div class="history-empty">Loading…</div>';
          historyData = [];
      } else {
          const btn = document.getElementById('loadMoreBtn');
          if (btn) btn.innerHTML = 'Loading...';
      }

      try {
          const res = await fetch(`/route_history/?page=${page}&limit=10`);
          if (!handleResponseAuth(res)) return;

          if (!res.ok) throw new Error('fetch failed');

          const data = await res.json();
          historyData = page === 1 ? (data.routes || []) : historyData.concat(data.routes || []);
          historyMeta = data.metadata || { current_page: 1, total_pages: 1 };

          if (historyData.length === 0) {
              body.innerHTML = '<div class="history-empty">No routes recorded yet.</div>';
              return;
          }

          const groups = {};
          historyData.forEach((r, i) => {
              if (!groups[r.date]) groups[r.date] = [];
              groups[r.date].push({ ...r, _idx: i });
          });

          let html = '';
          for (const [date, routes] of Object.entries(groups)) {
              html += '<div class="history-date-group">';
              html += '<div class="history-date-label">📅 ' + date + '</div>';

              for (const r of routes) {
                  html += '<div class="history-route-card" onclick="showRouteOnMap(' + r._idx + ')">';
                  html += '  <div class="history-route-title">📍 Route — ' + date + ', ' + r.time + '</div>';
                  html += '  <div class="history-route-stats">';
                  html += '    <div class="history-stat">📏 Distance: <span>' + formatDistance(r.distance_meters || r.distance || 0) + '</span></div>';
                  html += '    <div class="history-stat">⏱ Duration: <span>' + formatDuration(r.duration_seconds || r.duration || 0) + '</span></div>';
                  html += '    <div class="history-stat">📌 Points: <span>' + (r.total_points || 0) + '</span></div>';
                  html += '  </div>';
                  html += '  <button class="btn-view-route">View on Map</button>';
                  html += '</div>';
              }

              html += '</div>';
          }

          if (historyMeta.current_page < historyMeta.total_pages) {
              html += `<div style="text-align: center; margin-top: 15px; margin-bottom: 10px;">
                          <button id="loadMoreBtn" onclick="viewHistory(${historyMeta.current_page + 1})" style="padding: 8px 16px; font-size: 0.85rem; background: rgba(127, 90, 240, 0.2); border: 1px solid rgba(127, 90, 240, 0.4); border-radius: 8px; color: #fffffe; cursor: pointer;">Load More</button>
                       </div>`;
          }

          body.innerHTML = html;

      } catch (err) {
          if (err.message && err.message.includes("Unauthorized")) return;
          body.innerHTML = '<div class="history-empty">Failed to load history.</div>';
          console.error(err);
      }
  }

  function showRouteSummaryCard(r) {
      let existing = document.getElementById('route-summary');
      if (existing) existing.remove();

      const html = `
        <div class="route-summary-card" id="route-summary">
          <div class="summary-header">
            <span class="summary-title">📍 Viewing Saved Route</span>
            <button onclick="clearHistoryRoute()" class="btn-clear-route">✕ Clear</button>
          </div>
          <div class="summary-stats">
            <div class="summary-stat">
              <span class="summary-label">Distance</span>
              <span class="summary-value" id="summary-distance">${formatDistance(r.distance_meters)}</span>
            </div>
            <div class="summary-stat">
              <span class="summary-label">Duration</span>
              <span class="summary-value" id="summary-duration">${formatDuration(r.duration_seconds)}</span>
            </div>
            <div class="summary-stat">
              <span class="summary-label">Points Logged</span>
              <span class="summary-value" id="summary-points">${r.total_points}</span>
            </div>
            <div class="summary-stat">
              <span class="summary-label">Saved On</span>
              <span class="summary-value" id="summary-date">${r.date}</span>
            </div>
          </div>
          <div class="summary-legend">
            <span class="legend-item"><span class="legend-dot red"></span> Start Point</span>
            <span class="legend-item"><span class="legend-dot blue"></span> End Point</span>
          </div>
        </div>
      `;
      document.querySelector('.map-wrapper').insertAdjacentHTML('afterend', html);
  }

  function loadHistoryRoute(routeData) {
    if (routePolyline) { routePolyline.setMap(null); routePolyline = null; }
    if (startMarker) { startMarker.map = null; startMarker = null; }
    if (endMarker) { endMarker.map = null; endMarker = null; }

    const coords = routeData.route_points;
    if (!coords || coords.length === 0) return;

    const path = coords.map(p => normalizeCoordinate(p)).filter(p => p !== null);

    routePolyline = new google.maps.Polyline({
      path: path,
      geodesic: true,
      strokeColor: '#4285F4',
      strokeOpacity: 0.9,
      strokeWeight: 5,
      map: map
    });

    startMarker = placeMarker(
      path[0].lat, path[0].lng,
      '#EA4335', 'Start Point', 'start'
    );

    const last = path[path.length - 1];
    endMarker = placeMarker(
      last.lat, last.lng,
      '#4285F4', 'End Point', 'end'
    );

    const bounds = new google.maps.LatLngBounds();
    path.forEach(p => bounds.extend(p));
    map.fitBounds(bounds);

    showRouteSummaryCard(routeData);
    closeHistory();
  }

  function showRouteOnMap(idx) {
      const r = historyData[idx];
      if (!r || !r.route_points) return;
      loadHistoryRoute(r);
  }

  async function viewOffline() {
      // Offline implementation 
      const db = await (typeof dbPromise !== 'undefined' ? dbPromise : null);
      if (!db) { alert("IndexedDB not available"); return; }
      const tx = db.transaction("offlineRoutes", "readonly");
      const store = tx.objectStore("offlineRoutes");
      const request = store.getAll();
      request.onsuccess = function () {
          const data = request.result;
          if (data.length === 0) {
              document.getElementById("offlineData").innerText = "No offline routes stored.";
              return;
          }
          let output = "";
          data.forEach((item, index) => {
              output += "Route " + (index + 1) + "\\n";
              output += "Saved at: " + new Date(item.timestamp).toLocaleString() + "\\n";
              output += "Total Points: " + item.route.length + "\\n";
              output += JSON.stringify(item.route) + "\\n\\n";
          });
          document.getElementById("offlineData").innerText = output;
      };
  }

  
  // ─── PART 7: Button onclick Bindings (LAST) ──
  document.addEventListener('DOMContentLoaded', () => {
    const startBtn = document.getElementById('start-btn');
    const stopBtn  = document.getElementById('stop-btn');

    if (startBtn) {
      startBtn.addEventListener('click', () => {
          startBtn.disabled = true;
          stopBtn.disabled = false;
          startTracking();
      });
    }
    if (stopBtn) {
      stopBtn.addEventListener('click', () => {
          startBtn.disabled = false;
          stopBtn.disabled = true;
          stopTracking();
      });
    }
  });
