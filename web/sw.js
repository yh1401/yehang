/* 夜航 PWA Service Worker —— 缓存优先，离线也能打开 */
const CACHE = 'yehang-v10';
const ASSETS = [
  './',
  './index.html',
  './mvp.html',
  './manifest.webmanifest',
  './audio/rain-loop.wav',
  './audio/ocean-loop.wav',
  './audio/piano-loop.wav',
  './audio/pink-loop.wav',
  // 预混音景的 120s 循环（共约 1.4 MB）——iOS 单曲试听用，值得预缓存
  './audio/sc-rainpiano-loop.m4a',
  './audio/sc-ocean-loop.m4a',
  './audio/sc-rain-loop.m4a',
  './audio/sc-pink-loop.m4a',
  // 60 分钟长文件（每份 ~10.7 MB）故意不预缓存，用到时按需缓存
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
  // 带 Range 的请求（<audio> 拖动进度 / seek 长文件）直接放行：
  // 这类响应是 206 分片，写进 Cache 会让后续播放拿到残缺文件。
  if (req.headers.has('range')) return;
  e.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req)
        .then((res) => {
          // 只缓存完整的 200 响应，跳过 206 / opaque / 错误页
          if (res.status === 200 && res.type !== 'opaque') {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => caches.match('./mvp.html'));
    })
  );
});
