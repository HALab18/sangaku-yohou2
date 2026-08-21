"use strict";
/* Service Worker (sw.js) のふるまいのテスト。
 *
 *     node scripts/test_sw.js
 *
 * この層の壊れ方は **オンラインでは表面化しない** ので、実機で気づくのがとても難しい:
 *   - API 応答をキャッシュしてしまうと「古い予報を、いま取れた予報として」描く。
 *     画面上は完全に正常に見える = 気づけない誤表示 (CLAUDE.md 規約9)
 *   - CACHE の版を上げ忘れると、完全オフラインで開いたときだけ古い画面が出る
 *   - フラグメントを落とし忘れると、山と日付の組み合わせごとに index.html(200KB超)が積み上がる
 *
 * sw.js は Service Worker のグローバル(self / caches / Response)を前提にしているので、
 * その身代わりを組んでから評価する。sw.js は1文字も書き換えない。
 */
const fs = require("fs");
const path = require("path");
const { makeClock, settle, makeChecker } = require("./test_stubs");

const ROOT = path.join(__dirname, "..");
const SW_SRC = fs.readFileSync(path.join(ROOT, "sw.js"), "utf8");
const ORIGIN = "https://halab18.github.io";
const BASE = ORIGIN + "/sangaku-yohou2/";

const C = makeChecker();
const ok = C.ok.bind(C), eq = C.eq.bind(C);

/* ---- 応答の身代わり ----
 * type は本物の fetch が付けるもの: basic=同一オリジン / opaque=no-cors / cors=別オリジン */
function mkRes(opts) {
  const o = Object.assign({ status: 200, type: "basic", body: "" }, opts || {});
  return {
    ok: o.status >= 200 && o.status < 300, status: o.status, type: o.type, body: o.body,
    headers: o.headers || {},
    clone() { return mkRes(o); },
  };
}
const HANG = { __hang: true };

/* ---- Cache Storage の身代わり ---- */
function makeCaches() {
  const stores = new Map();
  const mk = () => {
    const m = new Map();
    const api = {
      _map: m,
      async match(key, opt) {
        if (m.has(key)) return m.get(key);
        if (opt && opt.ignoreSearch) {
          const bare = String(key).split("?")[0];
          for (const [k, v] of m) if (String(k).split("?")[0] === bare) return v;
        }
        return undefined;
      },
      /* 本物の Cache API は 206(部分応答)の保存を仕様で禁じており、put が TypeError で
       * 拒否する。sw.js 側の `r.ok` は 206 を弾かない(206 も ok=true)ので、ここは
       * ブラウザ側の拒否と sw.js の .catch() で倒れている。身代わりも同じ挙動にする。 */
      async put(key, res) {
        if (res && res.status === 206) throw new TypeError("Cache API は 206 を保存できない");
        m.set(String(key), res);
      },
      /* addAll は1つでも失敗すると全体が拒否される(だから sw.js は個別 add にしてある) */
      async addAll(urls) { for (const u of urls) await api.add(u); },
      async add(url) {
        const r = await api._fetch(BASE + String(url).replace(/^\.\//, ""));
        if (!r || !r.ok) throw new Error("add failed: " + url);
        m.set(BASE + String(url).replace(/^\.\//, ""), r);
      },
    };
    return api;
  };
  return {
    _stores: stores,
    async open(name) { if (!stores.has(name)) stores.set(name, mk()); return stores.get(name); },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
  };
}

/* ---- sw.js を身代わりの環境で読み込み、登録されたイベントハンドラを取り出す ---- */
function loadSW(opts) {
  const o = opts || {};
  const clock = makeClock();
  const listeners = {};
  const calls = [];
  const fetchImpl = o.fetch || (() => mkRes({}));
  const fetchStub = (req) => {
    const url = typeof req === "string" ? req : req.url;
    calls.push(url);
    const r = fetchImpl(url, calls.length);
    if (r === HANG) return new Promise(() => { });
    if (r instanceof Error) return Promise.reject(r);
    return Promise.resolve(r);
  };
  const cachesStub = makeCaches();
  const self_ = {
    location: { origin: ORIGIN },
    addEventListener(type, fn) { listeners[type] = fn; },
    skipWaiting() { self_._skipWaiting = true; },
    clients: { claim() { self_._claim = true; return Promise.resolve(); } },
  };
  const body = "var self=__e.self, caches=__e.caches, fetch=__e.fetch, URL=__e.URL,"
    + " Response=__e.Response, setTimeout=__e.setTimeout, clearTimeout=__e.clearTimeout;\n"
    + SW_SRC + "\nreturn {CACHE:CACHE, SHELL:SHELL, SLOW_MS:SLOW_MS, netFirst:netFirst};";
  const mod = new Function("__e", body)({
    self: self_, caches: cachesStub, fetch: fetchStub, URL,
    Response: function (body2, init) {
      return mkRes({ status: (init && init.status) || 200, body: body2, headers: (init && init.headers) || {} });
    },
    setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
  });
  // cache.add() はテスト側の fetch を使う
  const openOrig = cachesStub.open.bind(cachesStub);
  cachesStub.open = async n => { const c = await openOrig(n); c._fetch = fetchStub; return c; };
  return { mod, self: self_, caches: cachesStub, clock, calls, listeners };
}

/* イベントの身代わり。waitUntil / respondWith に渡された Promise を掴んでおく */
function mkEvent(request) {
  const e = { request, _wait: null, _resp: null };
  e.waitUntil = p => { e._wait = p; };
  e.respondWith = p => { e._resp = p; };
  return e;
}
const mkReq = (url, method) => ({ url, method: method || "GET" });

/* ================= install ================= */
async function testInstall() {
  // 1. シェルのうち1つが 404 でも、残りはキャッシュに入ること。
  //    addAll だと1つの失敗で全体が失敗し、以後キャッシュが空のままになる
  const sw = loadSW({ fetch: url => /icon-512/.test(url) ? mkRes({ status: 404 }) : mkRes({}) });
  const e = mkEvent();
  sw.listeners.install(e);
  const r = await settle(sw.clock, e._wait);
  ok(!("err" in r), `シェルの1つが 404 だと install 全体が失敗する: ${r.err && r.err.message}`);
  const c = await sw.caches.open(sw.mod.CACHE);
  eq(c._map.size, sw.mod.SHELL.length - 1,
    "404 だった1件以外がキャッシュに入っていない (addAll になっている可能性)");
  ok(sw.self._skipWaiting === true, "install で skipWaiting していない (更新が次回起動まで効かない)");
}

/* ================= activate ================= */
async function testActivate() {
  // 2. 前の版のキャッシュを掃除し、現行だけ残すこと
  const sw = loadSW();
  await sw.caches.open("pw-shell-2.40");
  await sw.caches.open("pw-shell-2.41");
  await sw.caches.open(sw.mod.CACHE);
  const e = mkEvent();
  sw.listeners.activate(e);
  await settle(sw.clock, e._wait);
  eq(await sw.caches.keys(), [sw.mod.CACHE], "前の版のキャッシュが掃除されていない");
  ok(sw.self._claim === true, "activate で clients.claim() していない");
}

/* ================= fetch イベントの適用範囲 ================= */
function testScope() {
  // 3. ★ 規約9の中核。気象データの通信には一切関与しないこと。
  //    ここに手を出すと「古い予報を、いま取れた予報として」描く = 画面上は正常に見える誤表示
  const outside = [
    ["Open-Meteo(気象庁モデル)", "https://api.open-meteo.com/v1/jma?latitude=36.4"],
    ["Open-Meteo(補完)", "https://api.open-meteo.com/v1/forecast?latitude=36.4"],
    ["Open-Meteo(発表時刻)", "https://api.open-meteo.com/data/jma_msm/static/meta.json"],
    ["Open-Meteo(ジオコーダ)", "https://geocoding-api.open-meteo.com/v1/search?name=%E7%87%95%E5%B2%B3"],
    ["国土地理院(逆ジオ)", "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat=36.4"],
    ["国土地理院(muni.js)", "https://maps.gsi.go.jp/js/muni.js"],
    ["Google Analytics", "https://www.googletagmanager.com/gtag/js?id=G-XXXX"],
  ];
  for (const [label, url] of outside) {
    const sw = loadSW();
    const e = mkEvent(mkReq(url));
    sw.listeners.fetch(e);
    ok(e._resp === null, `${label} を Service Worker が横取りしている (予報の鮮度に関与してしまう)`);
  }
  // 4. 同一オリジンでも GET 以外は触らない
  {
    const sw = loadSW();
    const e = mkEvent(mkReq(BASE + "index.html", "POST"));
    sw.listeners.fetch(e);
    ok(e._resp === null, "POST を横取りしている");
  }
  // 5. 同一オリジンの GET は受け持つ (圏外でアプリが開けることの担保)
  {
    const sw = loadSW();
    const e = mkEvent(mkReq(BASE + "index.html"));
    sw.listeners.fetch(e);
    ok(e._resp !== null, "同一オリジンの GET を受け持っていない (圏外で開けなくなる)");
  }
  // 6. シェルの一覧に API の URL が紛れ込んでいないこと (先読みの経路からも入らない)
  {
    const sw = loadSW();
    for (const u of sw.mod.SHELL)
      ok(!/^https?:|open-meteo|gsi\.go\.jp|googletagmanager/.test(u),
        `先読みするシェルに外部/APIのURLが入っている: ${u}`);
  }
}

/* ================= netFirst ================= */
async function testNetFirst() {
  const URL_INDEX = BASE + "index.html";

  // 7. オンラインなら常に最新。キャッシュがあってもネットワークの応答を返す
  {
    const sw = loadSW({ fetch: () => mkRes({ body: "新" }) });
    const c = await sw.caches.open(sw.mod.CACHE);
    c._map.set(URL_INDEX, mkRes({ body: "古" }));
    const r = await settle(sw.clock, sw.mod.netFirst(mkReq(URL_INDEX)));
    eq(r.ok.body, "新", "キャッシュがあるとネットワークの応答を返していない (push した修正が届かない)");
    eq((await c.match(URL_INDEX)).body, "新", "キャッシュが更新されていない");
  }

  // 8. ★ フラグメントを落としてからキャッシュする。
  //    落とさないと **開いた山と日付の組み合わせごとに** index.html のコピーが積み上がる
  {
    const sw = loadSW({ fetch: () => mkRes({ body: "本体" }) });
    const c = await sw.caches.open(sw.mod.CACHE);
    for (const h of ["#燕岳/2026-07-19", "#槍ヶ岳/2026-07-20", "#gps/2026-07-21", ""])
      await settle(sw.clock, sw.mod.netFirst(mkReq(URL_INDEX + h)));
    eq(c._map.size, 1, `フラグメントごとにキャッシュが増えている: ${[...c._map.keys()]}`);
    eq([...c._map.keys()], [URL_INDEX], "キャッシュのキーからフラグメントが落ちていない");
  }

  // 9. 失敗した応答・別オリジンの応答をキャッシュに入れない
  //    (入れると、後で「壊れた応答」を正常なものとして返すことになる)
  for (const [label, r] of [
    ["404", mkRes({ status: 404 })],
    ["500", mkRes({ status: 500 })],
    ["opaque(no-cors)", mkRes({ type: "opaque", status: 0 })],
    // 206 は sw.js の r.ok を通ってしまうが、Cache API 側が拒否し .catch() で握られる。
    // 「結果としてキャッシュに入らず、例外も漏れない」ことをここで固定する
    ["206(部分応答)", mkRes({ status: 206 })],
    ["cors(別オリジン)", mkRes({ type: "cors" })],
  ]) {
    const sw = loadSW({ fetch: () => r });
    const c = await sw.caches.open(sw.mod.CACHE);
    await settle(sw.clock, sw.mod.netFirst(mkReq(URL_INDEX)));
    eq(c._map.size, 0, `${label} の応答をキャッシュに入れている`);
  }

  // 10. 圏外で、退避先も無いとき。真っ白ではなく日本語で理由と次の行動を出す
  {
    const sw = loadSW({ fetch: () => new Error("network down") });
    const r = await settle(sw.clock, sw.mod.netFirst(mkReq(URL_INDEX)));
    eq(r.ok.status, 503, "オフラインの代替応答が 503 になっていない");
    ok(/電波の届く場所で一度開いて/.test(r.ok.body),
      `オフラインの代替応答が案内になっていない: ${r.ok.body}`);
    ok(/charset=utf-8/i.test(String(r.ok.headers["Content-Type"] || "")),
      "オフラインの代替応答に charset が無い (日本語が化ける)");
  }

  // 11. 圏外だが退避先がある = 圏外でもアプリが開ける、というこの層の存在意義
  {
    const sw = loadSW({ fetch: () => new Error("network down") });
    const c = await sw.caches.open(sw.mod.CACHE);
    c._map.set(URL_INDEX, mkRes({ body: "退避" }));
    const r = await settle(sw.clock, sw.mod.netFirst(mkReq(URL_INDEX)));
    eq(r.ok.body, "退避", "圏外でキャッシュから返せていない");
  }

  // 12. 退避先が無いときは通信を最後まで待つ (中途半端に諦めると初回が真っ白になる)
  {
    const sw = loadSW({ fetch: () => HANG });
    const r = await settle(sw.clock, Promise.race([
      sw.mod.netFirst(mkReq(URL_INDEX)).then(() => "返った"),
      new Promise(res => sw.clock.setTimeout(() => res("待ち続けた"), sw.mod.SLOW_MS * 5)),
    ]));
    eq(r.ok, "待ち続けた", "退避先が無いのに途中で諦めている (初回アクセスが真っ白になる)");
  }

  // 13. 極端に遅い回線(小屋周り・稜線の1本アンテナ)。退避先があるなら待たせ続けない
  {
    let resolveNet;
    const sw = loadSW({ fetch: () => new Promise(r => { resolveNet = () => r(mkRes({ body: "遅れて到着" })); }) });
    const c = await sw.caches.open(sw.mod.CACHE);
    c._map.set(URL_INDEX, mkRes({ body: "退避" }));
    const r = await settle(sw.clock, sw.mod.netFirst(mkReq(URL_INDEX)));
    eq(r.ok.body, "退避", "遅い回線でキャッシュを先に見せていない");
    ok(sw.clock.now() <= sw.mod.SLOW_MS, `待ちが上限(${sw.mod.SLOW_MS}ms)を超えている: ${sw.clock.now()}ms`);
    // ネットワーク側は捨てずに走らせ、返ってきたらキャッシュを更新する(次回の表示が新しくなる)
    resolveNet();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));
    eq((await c.match(URL_INDEX)).body, "遅れて到着",
      "遅れて届いた応答でキャッシュが更新されていない (いつまでも古い画面のまま)");
  }

  // 14. gate.js は ?v= 付きで読まれるが、先読みはクエリ無し。
  //     認証コードの年次更新で ?v= が変わってもオフラインで前回のものに当たること
  {
    const sw = loadSW({ fetch: () => new Error("network down") });
    const c = await sw.caches.open(sw.mod.CACHE);
    c._map.set(BASE + "gate.js", mkRes({ body: "gate" }));
    const r = await settle(sw.clock, sw.mod.netFirst(mkReq(BASE + "gate.js?v=2027a")));
    eq(r.ok.body, "gate", "?v= が変わるとオフラインで gate.js に当たらない (認証画面が出せなくなる)");
  }
}

/* ================= 版の管理 ================= */
function testVersion() {
  // 15. CACHE の版はリリースごとに上げる。上げ忘れると完全オフラインでのみ古い画面が出る。
  //     index.html のフッター表記との突き合わせは check_consistency.py が見ているので、
  //     ここでは「版が固定文字列で1つだけ定義されている」ことだけ確かめる
  const n = SW_SRC.split(/const CACHE\s*=/).length - 1;
  eq(n, 1, "sw.js の CACHE が1箇所で定義されていない");
  const m = SW_SRC.match(/const CACHE\s*=\s*"([^"]+)"/);
  ok(m && /^pw-shell-\d+\.\d+$/.test(m[1]), `CACHE の版の書き方が想定と違う: ${m && m[1]}`);
}

/* ================= 実行 ================= */
(async () => {
  await testInstall();
  await testActivate();
  testScope();
  await testNetFirst();
  testVersion();
  C.report("Service Worker のふるまい");
})().catch(e => { console.error(e); process.exit(2); });
