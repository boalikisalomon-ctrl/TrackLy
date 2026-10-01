// Service Worker - Présences & Pointage RH
const CACHE_NAME = 'pointage-rh-v1';

// Ressources statiques à mettre en cache (Bootstrap, fonts depuis CDN sont exclus
// car ils nécessitent CORS - on cache uniquement nos fichiers locaux)
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// ── Installation : précache des assets statiques ──────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// ── Activation : nettoyage des anciens caches ──────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch : stratégie Network-First pour les pages Flask ──────────────────────
// Les pages HTML (routes Flask) sont toujours fetched depuis le réseau.
// Les assets statiques locaux utilisent Cache-First.
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignorer les requêtes non-HTTP (chrome-extension://, etc.)
  if (!url.protocol.startsWith('http')) return;

  // Assets statiques locaux → Cache-First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        return cached || fetch(request).then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        });
      })
    );
    return;
  }

  // Pages de l'application → Network-First (données toujours fraîches)
  event.respondWith(
    fetch(request)
      .then((response) => {
        // Ne pas mettre en cache les redirections ou erreurs
        if (!response || response.status !== 200 || response.type === 'opaque') {
          return response;
        }
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        return response;
      })
      .catch(() => {
        // Fallback offline : retourner depuis le cache si dispo
        return caches.match(request).then((cached) => {
          if (cached) return cached;
          // Page d'erreur offline minimale
          return new Response(
            `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hors ligne - Pointage RH</title>
  <style>
    body { font-family: Inter, sans-serif; background: #0f172a; color: #fff;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; text-align: center; padding: 24px; }
    h1 { font-size: 1.5rem; margin-bottom: 12px; }
    p  { color: #94a3b8; margin-bottom: 24px; }
    button { background: #2563eb; color: #fff; border: none; padding: 12px 24px;
             border-radius: 8px; font-size: 1rem; cursor: pointer; }
  </style>
</head>
<body>
  <div>
    <div style="font-size:4rem">📡</div>
    <h1>Vous êtes hors ligne</h1>
    <p>Vérifiez votre connexion réseau et réessayez.</p>
    <button onclick="location.reload()">Réessayer</button>
  </div>
</body>
</html>`,
            { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
          );
        });
      })
  );
});
