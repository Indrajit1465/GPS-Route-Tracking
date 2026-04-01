# GPS Route Tracker - Product Specification Document (PRD)

## 1. Product Overview
GPS Route Tracker is a robust Django-based web application designed to capture, process, and display live GPS route data from client devices. The application features a dual-layer tracking system which instantly displays raw coordinates to user interfaces while silently processing accurate, road-snapped routes in the background via the Google Roads API. A comprehensive super administrator dashboard allows system managers to analyze global usage metrics and view granular user routes.

## 2. Core Features

### 2.1 Live GPS Tracking
- **High-Frequency GPS Watch:** High-accuracy geolocation watch active at regular intervals.
- **Adaptive Sampling:** Adjusts polling interval based on the current speed of the user (e.g., 8s when stationary, 1s when driving).
- **Kalman-style Motion Filter:** Automatically removes GPS jitter by calculating device residual trust against historical speed constraints.
- **Impossible-Jump Rejection:** Guards against catastrophic GPS misreporting.

### 2.2 Dual-Layer Rendering
- **Layer 1 (Immediate UI):** Draws raw/filtered coordinates as a lightweight polyline without waiting for external API responses.
- **Layer 2 (Road Geometry):** Asynchronously batches points to the `Google Roads API` over intervals of ~25m to snap paths to genuine road networks. Replaces straight cuts.

### 2.3 Automatic Travel-Mode Profiling
- Dynamically shifts routing configurations parameters via realtime speed calculations.
- Detects the optimal profile limit and UI visualization for:
  - **Walking** (< 2.5 m/s)
  - **Cycling** (2.5 - 8.0 m/s)
  - **Motorcycle** (8.0 - 15.0 m/s)
  - **Car** (> 15.0 m/s)
- **Manual override** support through the responsive Travel Mode menu.

### 2.4 Offline-First Synchronization
- Constant ping endpoint monitoring verifies actual WAN internet stability vs standard network statuses.
- In-memory `IndexedDB` implementation continuously buffers successfully recorded route points.
- Automatically pushes local arrays to the server synchronously when back online.

### 2.5 Route History & Assessment
- Aggregates recorded path details highlighting active durations, geographic starts/ends.
- Determines overall GPS transmission consistency using a `points_per_km` evaluation rating (`Excellent`, `Good`, `Fair`, `Low`).
- Permits interactive map review of historical logs.

### 2.6 Dedicated Super Admin Panel
- Restricted routing and authorization for global managers.
- Dashboard analytics rendering entire application KPIs (Total Distance, Active Users).
- Detailed user introspection isolating granular route data matching UTC-localized server records against timezone adjustments. 

## 3. Technology Stack
- **Backend Infrastructure:** Python 3.x, Django
- **Core Database:** SQLite (Development) / Supported PostgreSQL
- **Frontend Interactivity:** HTML5, CSS3 Variables, Vanilla JavaScript (ES6+), IndexedDB API
- **External Dependencies:** Google Maps JavaScript API (Display), Google Roads API (Snapping)

## 4. Architecture Specifications
- **Client Processing:** Uses `requestAnimationFrame` for high performance Marker DOM sliding in place of generic laggy translation.
- **API Snapping Worker:** Executes asynchronously out of sequence with the main `onGPSSuccess` pipeline.

## 5. Security & Rate Limiting
- **SuperAdmin Guard Mechanism:** Decorator enforcing tight boundary permission limits.
- **CSRF Tokens:** All backend push streams (snapped geometry fetching & route persistence) pass standard Django protection frameworks.
- **API Limitations:** `@ratelimit` deployed upon heavy endpoints preserving Google's cloud computing constraints. 
