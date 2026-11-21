/* ちか宿のホーム画面用。ページはいつも最新を取りに行き、圏外のときだけ前に開いたページを出す */
const CACHE = 'chikayado-v1';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then(res => {
    if (res.ok && (req.mode === 'navigate' || req.url.includes('/api/my-events.json') || req.url.includes('/style.css'))) {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req)));
});
