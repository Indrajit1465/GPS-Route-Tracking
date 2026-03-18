import re

with open('tracker/templates/home.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Add Global Variables for Dual Polylines and Animations
globals_find = r"""  let isOfflineMode = false;"""
globals_replace = """  let isOfflineMode = false;
  
  // ─── PART 1.8: Real-Time Animation Variables ──
  let livePolyline = null;
  let liveRoutePoints = [];
  let markerAnimFrame = null;
  let isMarkerAnimating = false;"""
text = re.sub(globals_find, globals_replace, text)


# Update resetStats
resetStats_find = r"""  function resetStats\(\) \{.*?navLastTime         = 0;"""
resetStats_replace = """  function resetStats() {
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
    isMarkerAnimating   = false;"""
text = re.sub(resetStats_find, resetStats_replace, text, flags=re.DOTALL)


# Replace everything from PART 4 to PART 5
part45_regex = re.compile(r"// ─── PART 4: GPS \+ Tracking Functions \(FOURTH\) ──(.*?)// ─── PART 5: Start \+ Stop Tracking Functions \(FIFTH\) ──", re.DOTALL)

replacement_js = """// ─── PART 4: GPS + Tracking Functions (FOURTH) ──
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

  // ─── PART 5: Start + Stop Tracking Functions (FIFTH) ──"""

text = part45_regex.sub(replacement_js.replace('\\', '\\\\'), text)

# Insert LivePolyline instantiation in startTracking
startTracking_find = r"""    routePolyline = new google\.maps\.Polyline\(\{
      path: \[\],
      geodesic: true,
      strokeColor: '#4285F4',
      strokeOpacity: 0\.9,
      strokeWeight: 5,
      map: map
    \}\);"""

startTracking_replace = """    routePolyline = new google.maps.Polyline({
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
    });"""
text = re.sub(startTracking_find, startTracking_replace, text)

# Destroy LivePolyline in stopTracking / reset
stopTracking_find = r"""    if \(routePolyline\) \{
      routePolyline\.setMap\(null\);
      routePolyline = null;
    \}"""
stopTracking_replace = """    if (routePolyline) {
      routePolyline.setMap(null);
      routePolyline = null;
    }
    if (livePolyline) {
      livePolyline.setMap(null);
      livePolyline = null;
    }"""
text = re.sub(stopTracking_find, stopTracking_replace, text)


with open('tracker/templates/home.html', 'w', encoding='utf-8') as f:
    f.write(text)

print("Dual Polyline and Animation Scripts Inserted")
