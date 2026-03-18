# GPS Route Tracker - Product Specification Document (PRD)

## 1. Product Overview
The GPS Route Tracker is a web-based, mobile-responsive application designed for real-time geolocation tracking, road-snapped route visualization, and historical trip management. Built with a Django backend and a vanilla JavaScript frontend integrated with the native Google Maps ecosystem, the project delivers a high-accuracy navigation experience. 

The application solves common GPS tracking issues—such as signal drift, jagged map lines, and network instability—by implementing advanced motion filtering, a dual-layer rendering system, and offline data caching.

## 2. Target Audience
* Users who need reliable, high-precision personal GPS tracking on mobile devices.
* Drivers or cyclists tracking distance for work, fitness, or general travel logs.
* Organizations requiring an embeddable, lightweight fleet tracking layer.

## 3. Core Features

### 3.1. User Authentication
* **Account Creation**: Secure user registration.
* **Tokenless AJAX Authentication**: Login, logout, and credential management strictly handled via Django session authentication and CSRF protection explicitly adapted for dynamic AJAX workflows without full-page reloads.

### 3.2. Real-Time Navigation & Tracking
* **Hardware Interfacing**: Hooks into the browser's `navigator.geolocation` API requesting high-accuracy coordinates dynamically.
* **Kalman-Style Motion Filter**: Cleans noisy raw GPS signals by filtering points with poor accuracy profiles and discarding micro-movements (under 3 meters) to eliminate "drifting" while standing still.
* **Directional Arrow Marker**: Features an SVG-based dynamic navigation marker that rotates dynamically matching the user's geographical movement heading.

### 3.3. Dual-Layer Polyline Rendering (Zero-Lag UI)
* **Layer 1 (LivePolyline)**: Immediately draws thin, semi-transparent paths across raw, filtered GPS ping coordinates. This provides the user with zero-lag visual feedback of their movement.
* **Layer 2 (SnappedPolyline)**: Behind the scenes, the app dynamically requests Google Directions API road geometry based on geographic anchor thresholds (~25 meters). It draws a solid, highly accurate route molded directly to realistic road curves, effectively replacing the raw live line automatically.

### 3.4. Offline Resilience
* **IndexedDB Local Storage**: If the user enters a tunnel or drops cellular connectivity, active driving points are automatically cached locally within the browser.
* **Auto-Syncing Engine**: Once a network connection is securely re-established, the offline buffer synchronizes seamlessly with the Django backend.

### 3.5. Route History Pipeline
* **Batch Endpoint Save**: Submits captured coordinates to the database asynchronously to prevent data loss.
* **History Dashboard**: Features server-side pagination to fetch past trips cleanly.
* **Map Playback**: Routes dynamically compute Haversine distances, playback total session duration, and map distinct red/green start and end vectors onto the interactive map UI when invoked.

## 4. Technical Architecture

### 4.1. Tech Stack
* **Backend Module**: Python 3.x, Django 5.x+
* **Frontend Module**: HTML5, custom CSS3, Vanilla ECMAScript 6 (JS)
* **Database**: SQLite / PostgreSQL (Django ORM mapping)
* **Third-Party APIs**: Google Maps JavaScript API (Advanced Markers), Google Directions API (`/maps/api/directions/json`)

### 4.2. API Endpoints Reference
| Endpoint | Method | Role |
| :--- | :--- | :--- |
| `/login/` | POST/GET | Django auth handshakes |
| `/snap_chunk/` | POST | Validates maximum chunk inputs before road snapping logic |
| `/get_road_path/` | POST | Proxies Google Directions geometry logic returning encrypted polylines decoded to dictionary coordinates |
| `/save_route/` | POST | Finalizes and commits route arrays alongside timestamp/distance metadata |
| `/route_history/` | GET | Paginated retrieval of prior trips targeting the authenticated `request.user` |

## 5. Non-Functional Requirements (NFR)

* **Scalability & Security**: Implements `django-ratelimit` protecting `/save_route/` and API endpoints via IP/User blocks to prevent spam flooding.
* **Responsive UI/UX**: Designed cross-platform with distinct viewport structures. Desktop features centered 1400px maximum boundaries; Mobile features native OS-like full-screen scaling fixed at 65-80vh ratios.
* **Accessibility**: Fully integrates `prefers-reduced-motion` respecting OS animation standards for elements like pulse indicators.
* **Environment Governance**: Hardcoded credentials stripped, dynamically utilizing `python-decouple` reading from root `.env` dictionaries for scaling to CI/CD pipelines.
