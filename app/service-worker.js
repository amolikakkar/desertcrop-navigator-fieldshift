// Clean-up for phones that opened the OLD version of this site (its offline helper was called service-worker.js,
// saved copy "desertcrop-shell-v5"). Those phones check this file, pick up this version, delete the old saved copy,
// switch the old helper off and reload. The new app then loads and uses its own helper, sw.js. Added 12 Nov 2026.
// The new app never registers this file.
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) {
  event.waitUntil((async function () {
    for (const key of await caches.keys()) { await caches.delete(key); }
    await self.registration.unregister();
    for (const client of await self.clients.matchAll({ type: "window" })) { client.navigate(client.url); }
  })());
});
