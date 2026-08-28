// Historia Mission Control Service Worker (PWA Shell Only)
// Invariant: ONLY static UI shell assets are cached.
// Dynamic APIs (/api/*), credentials, and real-time telemetry are NEVER cached.

const CACHE_NAME = 'historia-mission-control-v1';
const SHELL_ASSETS = [
  '/mobile',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(SHELL_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // INVARIANT 1: Never intercept or cache API calls or mutations
  if (url.pathname.startsWith('/api') || event.request.method !== 'GET') {
    event.respondWith(fetch(event.request));
    return;
  }

  // INVARIANT 2: Static shell network-first with cache fallback
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response && response.status === 200 && response.type === 'basic') {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseClone);
        });
      }
      return response;
    }).catch(() => {
      return caches.match(event.request);
    })
  );
});