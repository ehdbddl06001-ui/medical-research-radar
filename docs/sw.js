// 오프라인에서도 마지막 목록을 볼 수 있게 하는 서비스 워커
const CACHE = "medradar-v1";
const SHELL = ["./", "index.html", "app.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  // 데이터와 화면 파일은 네트워크 우선 → 실패하면 저장본
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok) {
        const copy = r.clone();
        const key = url.pathname.endsWith("items.json") ? new Request(url.origin + url.pathname) : e.request;
        caches.open(CACHE).then((c) => c.put(key, copy));
      }
      return r;
    }).catch(() => caches.match(url.pathname.endsWith("items.json") ? url.origin + url.pathname : e.request))
  );
});
