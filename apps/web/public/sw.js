/* SIGNAL service worker (PWA, §14).
 * - static assets (/_next/static, icons, manifest, fonts): cache-first
 * - pages (navigations): network-first, cached copy as offline fallback
 * - /api/*: never cached (personal data, always live)
 * Registered with ?dev=1 under `next dev`, where asset URLs are not content-hashed: assets then go network-first.
 */
const VERSION = "signal-v1";
const STATIC = `${VERSION}-static`;
const PAGES = `${VERSION}-pages`;
const DEV = new URL(self.location.href).searchParams.get("dev") === "1";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC)
      .then((c) => c.addAll(["/manifest.webmanifest", "/icon-192.png", "/icon-512.png"]))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isStatic(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    /\.(?:png|svg|ico|webp|jpg|jpeg|woff2?|webmanifest)$/.test(url.pathname)
  );
}

async function cacheFirst(req) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok && res.type === "basic") cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req);
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/api") return; // never cache the API
  if (url.pathname.startsWith("/_next/webpack-hmr") || url.pathname.includes("__nextjs")) return;
  if (isStatic(url)) {
    event.respondWith(DEV ? networkFirst(req, STATIC) : cacheFirst(req));
    return;
  }
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, PAGES));
  }
});
