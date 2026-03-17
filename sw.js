/**
 * StudyAI – Service Worker
 * Strategie:
 *   Statische Assets  → Cache-First (sofortiger Load, kein Netz nötig)
 *   API-Calls         → Network-First (frische Daten, Fallback auf Cache)
 *   Externe Fonts     → Network-First mit Cache-Fallback
 */

"use strict";

const CACHE_VERSION = "20260310"; // Wird bei Updates manuell oder per Build-Script erhöht
const STATIC_CACHE = `studyai-static-${CACHE_VERSION}`;
const DATA_CACHE   = `studyai-data-${CACHE_VERSION}`;

// Assets die beim Install sofort gecacht werden
const PRECACHE_ASSETS = [
  "/",
  "/index.html",
  "/app.js",
  "/styles.css",
  "/icons/icon.svg",
  "/icons/icon-maskable.svg",
  "/manifest.json",
];

// ── Install: Pre-Cache statische Assets ──────────────────────────────────────
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(PRECACHE_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: Alte Cache-Versionen aufräumen ──────────────────────────────────
self.addEventListener("activate", (e) => {
  const CURRENT_CACHES = [STATIC_CACHE, DATA_CACHE];
  e.waitUntil(
    caches.keys()
      .then(keys =>
        Promise.all(
          keys.filter(k => !CURRENT_CACHES.includes(k)).map(k => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch: Request abfangen ───────────────────────────────────────────────────
self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);

  // Nur GET cachen
  if (request.method !== "GET") return;

  // API-Calls: Network-First, erfolgreich geladene Sessions cachen
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(networkFirstApi(request));
    return;
  }

  // Kritische Auth-Bibliotheken (Firebase SDK, DOMPurify) NIEMALS cachen –
  // SW-Caching würde nach Reload opaque/503-Responses liefern und Auth brechen.
  const PASSTHROUGH_HOSTS = [
    "www.gstatic.com",          // Firebase SDK
    "apis.google.com",          // Google Auth APIs
    "securetoken.googleapis.com",
    "identitytoolkit.googleapis.com",
    "accounts.google.com",
    "cdnjs.cloudflare.com",     // DOMPurify
  ];
  if (PASSTHROUGH_HOSTS.some(h => url.hostname === h || url.hostname.endsWith("." + h))) {
    // Gar nicht intercepten → Browser/OS-Cache + Netzwerk entscheidet
    return;
  }

  // Google Fonts & weitere externe CDNs: Network-First mit Cache-Fallback
  if (url.origin !== self.location.origin) {
    e.respondWith(networkFirstExternal(request));
    return;
  }

  // Alle anderen lokalen Dateien: Cache-First
  e.respondWith(cacheFirst(request));
});

// ── Strategien ────────────────────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Wenn komplett offline und nicht gecacht – leere Antwort
    return new Response("Offline – Seite nicht verfügbar", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}

async function networkFirstApi(request) {
  try {
    const response = await fetch(request);
    // Erfolgreiche Session-Daten für Offline-Zugriff cachen
    if (response.ok) {
      const url = new URL(request.url);
      const isSessionRead = url.pathname.match(/^\/api\/sessions\/[^/]+$/) && request.method === "GET";
      const isSessionList = url.pathname === "/api/sessions";
      if (isSessionRead || isSessionList) {
        const cache = await caches.open(DATA_CACHE);
        cache.put(request, response.clone());
      }
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(
      JSON.stringify({ error: "Offline – keine Verbindung zum Server" }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }
}

async function networkFirstExternal(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response("", { status: 503 });
  }
}

// ── Background Sync: Offline-Queue nachsenden ────────────────────────────────
self.addEventListener("sync", (e) => {
  if (e.tag === "studyai-sync-sessions") {
    e.waitUntil(notifyClientsToSync());
  }
});

async function notifyClientsToSync() {
  const clients = await self.clients.matchAll({ includeUncontrolled: true });
  clients.forEach(client => client.postMessage({ type: "SW_SYNC_SESSIONS" }));
}

// ── Message Handler (von app.js) ─────────────────────────────────────────────
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "LOGOUT") {
    // API-Cache löschen bei Logout (Datenschutz)
    caches.delete(DATA_CACHE).then(() => {
      console.log("[SW] API-Cache nach Logout geleert");
    });
  }
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
  if (event.data?.type === "CACHE_VERSION") {
    // Neue Version verfügbar – Clients benachrichtigen
    self.clients.matchAll().then(clients =>
      clients.forEach(c => c.postMessage({ type: "SW_UPDATE_AVAILABLE" }))
    );
  }
});
