/* 夜航 PWA Service Worker —— 缓存优先，离线也能打开 */
const CACHE = 'yehang-v7';
const ASSETS = [
  './',
  './index.html',
  './mvp.html',
  './manifest.webmanifest',
  './audio/rain-loop.wav',
  './audio/ocean-loop.wav',
  './audio/piano-loop.wav',
  './audio/pink-loop.wav',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png',
  './favicon-64.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // 逐个缓存：单个资源失败（如音频未部署）不拖垮整次安装
      .then((c) => Promise.all(ASSETS.map((u) => c.add(u).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (new URL(req.url).origin !== self.location.origin) return;
  e.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match('./mvp.html'));
    })
  );
});
