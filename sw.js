/* PeakWeather Service Worker — 圏外でもアプリが開けるようにするためだけの層。
 *
 * ここが扱うのは **画面(HTML/CSS/JS/アイコン)** だけで、気象データは一切扱わない。
 * 予報そのものの保存は index.html 側の localStorage スナップショット(pw-snap-v1)が持つ。
 * API 応答を SW でキャッシュすると「古い予報を、今取れた予報として」描いてしまい、
 * 画面上は完全に正常に見えるのに中身だけ古いという最悪の壊れ方をする。
 * 気象データの新旧は必ず利用者に見せる必要があるので、この層には入れない。
 *
 * ★ CACHE の版はリリースごとに上げる。上げないと activate の掃除が走らず、
 *   前版のシェルがキャッシュに残り続ける(ネットワーク優先なので実害は出にくいが、
 *   完全オフラインで開いたときだけ古い画面が出るという再現困難な状態になる)。 */
const CACHE = "pw-shell-2.32";

/* 初回インストール時に先読みするシェル一式。ここに載っているものだけが
 * 「一度も開いたことがなくてもオフラインで出る」。docs/ 配下を入れていないのは、
 * 全部載せると初回アクセスの通信量が数百KB増えるため(下の runtime キャッシュにより、
 * その端末で一度開いた docs ページはオフラインでも開ける)。
 *
 * gate.js は index.html からは `gate.js?v=2026b` として読まれるが、ここでは
 * クエリ無しで入れておき、照合側で ignoreSearch:true にして拾う。認証コードの
 * 年次更新で ?v= が変わってもオフライン時に前回の gate.js に当たるようにするため。 */
const SHELL = ["./", "index.html", "gate.js", "logic.js", "manifest.json",
  "icons/icon-192.png", "icons/icon-512.png",
  "icons/favicon-32.png", "icons/apple-touch-icon.png"];

/* 圏内だが極端に遅い(小屋周り・稜線の1本アンテナ)ときに待たされ続けないための上限。
 * これを過ぎたらキャッシュがある分だけ先に見せる。ネットワーク側は捨てずに走らせ、
 * 返ってきたらキャッシュを更新する(次回の表示が新しくなる)。 */
const SLOW_MS = 6000;

self.addEventListener("install", e => {
  // 1つでも 404 だと addAll 全体が失敗して以後キャッシュが空のままになるので、
  // 個別に put して失敗は握る(アイコンが1枚欠けてもシェルは成立する)。
  e.waitUntil(caches.open(CACHE).then(c =>
    Promise.all(SHELL.map(u => c.add(u).catch(() => {})))
  ).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  // 同一オリジンの GET 以外は respondWith を呼ばず、ブラウザ既定に完全に任せる。
  // 対象外になるのは Open-Meteo / 国土地理院(逆ジオコーダ・muni.js) / Google Analytics。
  // これらを触らないことが、この SW が予報の鮮度に一切関与しないことの担保になっている。
  if (req.method !== "GET") return;
  if (new URL(req.url).origin !== self.location.origin) return;
  e.respondWith(netFirst(req));
});

/* ネットワーク優先 + キャッシュ退避。
 * 「オンラインなら常に最新」を守るのが第一(GitHub Pages へ push した修正が、
 * SW のキャッシュのせいで端末に届かない状態を作らない)。 */
async function netFirst(req) {
  const cache = await caches.open(CACHE);
  // キャッシュのキーからフラグメントを落とす。このアプリの共有URLは
  // `index.html#燕岳/2026-07-19` の形で、落とさないと **開いた山と日付の組み合わせごとに**
  // index.html(200KB超)のコピーが積み上がる(実測でキーが増えるのを確認済み)。
  const key = req.url.split("#")[0];
  const cached = await cache.match(key, { ignoreSearch: true });
  const net = fetch(req).then(r => {
    // opaque(no-cors)や 206 を入れると後で壊れた応答を返すことになるので基本応答のみ
    if (r && r.ok && r.type === "basic") cache.put(key, r.clone()).catch(() => {});
    return r;
  });
  if (!cached) {
    // 退避先が無いときは通信を最後まで待つ(中途半端に諦めると初回が真っ白になる)
    return net.catch(() => new Response(
      "オフラインのため、このページはまだ表示できません。電波の届く場所で一度開いてください。",
      { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } }));
  }
  return Promise.race([
    net.catch(() => cached),
    new Promise(res => setTimeout(() => res(cached), SLOW_MS))
  ]);
}
