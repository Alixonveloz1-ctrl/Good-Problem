/* Service worker for the app shell only.
 *
 * API responses and generated media are never cached: a stale job state or a
 * stale credit counter would be worse than a spinner, and the media lives
 * behind signed URLs that expire. Generations keep running in Google Cloud
 * whether or not this page is open, so there is nothing to keep alive here.
 */
const SHELL = 'aaus-shell-v1'
const PRECACHE = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(PRECACHE)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET') return
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/media')) return
  if (url.origin !== self.location.origin) return

  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match('/index.html')))
    return
  }

  event.respondWith(
    caches.match(event.request).then(
      (hit) =>
        hit ||
        fetch(event.request).then((response) => {
          const copy = response.clone()
          caches.open(SHELL).then((cache) => cache.put(event.request, copy))
          return response
        }),
    ),
  )
})
