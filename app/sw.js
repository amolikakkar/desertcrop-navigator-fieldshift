// Offline support. The app's own files and data.json are fetched fresh from the internet first, and the saved
// copy is used only when there is no internet. A new version takes over at once, so phones never keep showing an
// old version. Bump V on every deploy.
const V="fieldshift-v35",A=["./","index.html","manifest.webmanifest","icon-192.png","icon-512.png","data.json"];
self.addEventListener("install",e=>{self.skipWaiting();e.waitUntil(caches.open(V).then(c=>c.addAll(A)).catch(()=>{}))});
self.addEventListener("activate",e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==V).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
self.addEventListener("fetch",e=>{const r=e.request;
 if(r.method!=="GET"||new URL(r.url).origin!==location.origin)return; // NASA and font requests go straight to the internet
 const net=r.mode==="navigate"?fetch(r.url,{cache:"no-store"}):fetch(r,{cache:"no-store"});
 e.respondWith(net.then(res=>{if(res.ok){const copy=res.clone();caches.open(V).then(c=>c.put(r,copy))}return res})
  .catch(()=>caches.match(r,{ignoreSearch:true}).then(m=>m||caches.match("index.html"))))});
