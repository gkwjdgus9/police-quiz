// 내부망·오프라인판 빌드: traffic-check.html + 조문 데이터 → offline/ 폴더
// 사용법: node scripts/build-offline.mjs
// 조문 데이터는 law-data.json(자동 갱신본)이 있으면 그것을, 없으면 law-data.seed.json(임시 전사본)을 내장합니다.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';

const page = readFileSync('traffic-check.html', 'utf8');
const dataFile = existsSync('law-data.json') ? 'law-data.json' : 'law-data.seed.json';
const law = JSON.parse(readFileSync(dataFile, 'utf8'));
const version = new Date().toISOString().slice(0, 10).replace(/-/g, '') + (law.seed ? '-seed' : '');

const headExtra = `<link rel="manifest" href="manifest.webmanifest">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<link rel="apple-touch-icon" href="icon-192.png">
<link rel="icon" href="icon-192.png">`;
const inject = `<script>window.__OFFLINE__=true;window.__LAW_DATA__=${JSON.stringify(law).replace(/<\//g, '<\\/')};window.__BUILD__='${version}';</script>\n<script>`;
const swReg = `<script>
// 오프라인 캐시: https 또는 localhost에서만 서비스워커가 등록됩니다. http 내부망이나 파일로 열 때는 조용히 건너뜁니다.
if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
  window.addEventListener('load', function(){ navigator.serviceWorker.register('sw.js').catch(function(){}); });
}
</script>
</body>`;

let out = page
  .replace('<meta name="theme-color" content="#1e3a5f">', '<meta name="theme-color" content="#1e3a5f">\n' + headExtra)
  .replace('<script>\n// ───────────────────────── 12대 중과실 데이터', inject + '\n// ───────────────────────── 12대 중과실 데이터')
  .replace('</body>', swReg);
if (!out.includes('window.__OFFLINE__=true')) throw new Error('스크립트 주입 위치를 찾지 못했습니다.');
if (!out.includes('rel="manifest"')) throw new Error('head 주입 위치를 찾지 못했습니다.');

mkdirSync('offline', { recursive: true });
writeFileSync('offline/index.html', out);
writeFileSync('offline/manifest.webmanifest', JSON.stringify({
  name: '교통사고 공소권 판단 도구', short_name: '공소권 판단', lang: 'ko',
  start_url: './index.html', scope: './', display: 'standalone',
  background_color: '#f8fafc', theme_color: '#1e3a5f',
  description: '교통사고처리특례법 제3조·제4조 기준 형사처벌 대상 여부 체크리스트 (내부망·오프라인판)',
  icons: [{ src: 'icon-192.png', sizes: '192x192', type: 'image/png' }, { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' }],
}, null, 2));
writeFileSync('offline/sw.js', `// 앱 셸 캐시 (버전 ${version}). 파일이 바뀌면 버전이 바뀌어 새로 캐시됩니다.
const CACHE = 'traffic-check-${version}';
const FILES = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request).then(res => {
    if (res.ok && new URL(e.request.url).origin === location.origin) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match('./index.html'))));
});
`);
console.log(`offline/ 생성 완료 · 조문 데이터: ${dataFile} · 버전 ${version} · ${(Buffer.byteLength(out) / 1024).toFixed(0)}KB`);
