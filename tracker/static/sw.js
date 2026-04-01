// Service Worker — GPS Route Tracker
const CACHE_NAME = 'gps-tracker-v1';

// Cache essential files for offline loading
const CACHE_URLS = [
  '/',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(CACHE_URLS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME)
            .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // Only cache GET requests
  if (event.request.method !== 'GET') return;

  // Never cache API endpoints
  const url = event.request.url;
  if (url.includes('/snap_') ||
      url.includes('/save_route') ||
      url.includes('/route_history') ||
      url.includes('/get_road_path')) {
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() =>
      caches.match(event.request)
    )
  );
});
