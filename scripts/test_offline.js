"use strict";
/* 圏外・障害時のふるまいのテスト (通信層 と 端末内保存)。
 *
 *     node scripts/test_offline.js
 *
 * DEVLOG で最も重い事故が出ている領域:
 *   - meta.json だけ返ってこないと **予報全体が「取得中…」のまま固まる** (2.28β)
 *   - 補完APIの失敗で主要データごと捨てる (Promise.all → allSettled で修正済み)
 *   - localStorage 自体が SecurityError を投げる端末でフォームが無反応になる
 *   - quota 超過で残骸が索引に残る
 *
 * これらは index.html の中にあるが、**アプリ本体は1文字も書き換えない**方針なので、
 * DOM に触らない範囲だけを目印で切り出して評価する (scripts/test_display.js と同じ手口)。
 * 時間は仮想時計に差し替えるので、20秒のタイムアウトも 6秒の待ちも即座に検査できる。
 */
const fs = require("fs");
const path = require("path");
const { makeClock, settle, makeStorage, makeChecker, sliceByMarks } = require("./test_stubs");

const ROOT = path.join(__dirname, "..");

/* 切り出す範囲。DOM にもグローバルの副作用にも触らないものだけ。 */
const SLICES = [
  ["モデル比較の切り分けと系列マージ", "const CMP_MODELS=[", "const IDX={A:"],
  ["日付ユーティリティ", "const iso=d=>", "// 稜線風速の補間 interpWind"],
  ["APIアクセス", "// ---- APIアクセス (タイムアウト・リトライつき) ----", "// ---- 山名解決 ----"],
  ["応答の正規化", "const DAILY_KEYS=[", "// ---- 直近の取得結果の使い回し"],
  ["予報スナップショット", 'const SNAP_KEY="pw-snap-v1"', "// ---- 保存領域の永続化要求 ----"],
];

function slicePureSource() {
  return sliceByMarks(fs.readFileSync(path.join(ROOT, "index.html"), "utf8"), "index.html", SLICES);
}

/* ---- 切り出したコードを、身代わりの環境の中で評価する ---- */
function loadApi(env) {
  const logic = fs.readFileSync(path.join(ROOT, "logic.js"), "utf8");
  const gate = fs.readFileSync(path.join(ROOT, "gate.js"), "utf8");
  const EXPOSE = ["splitModels", "mergeSeries", "normalizeSeries", "iso", "jstToday", "addDays",
    "agoTxt", "apiJson", "apiError", "offlineErr", "modelInit", "initTxt",
    "API_TIMEOUT_MS", "META_TIMEOUT_MS", "META_KEY",
    "snapId", "snapIndex", "snapIndexSave", "snapPrune", "snapLoad", "snapSave",
    "snapKeep", "snapUnkeep", "snapEntry", "snapNameSet", "SNAP_KEY", "snapBodyKey",
    "SNAP_AUTO_MAX", "SNAP_KEEP_MAX", "DAILY_KEYS", "CMP_MODELS",
    "pwGateOk", "pwIsAgreed", "pwIsAuthed", "pwIsLocalFile", "pwLoad", "pwSave", "pwDrop",
    "pwTrack", "PW_AGREE_KEY", "PW_AUTH_KEY", "PW_AUTH_VER"];
  const body =
    "var localStorage=__env.localStorage, sessionStorage=__env.sessionStorage,"
    + " navigator=__env.navigator, fetch=__env.fetch, location=__env.location,"
    + " setTimeout=__env.setTimeout, clearTimeout=__env.clearTimeout;\n"
    + logic + "\n" + gate + "\n" + slicePureSource()
    + "\nreturn {" + EXPOSE.join(",") + "};";
  return new Function("__env", body)(env);
}

/* ---- 検査の道具立て ---- */
const C = makeChecker();
const ok = C.ok.bind(C), eq = C.eq.bind(C);

/* 応答の身代わり。Response の必要な部分だけ持つ。 */
const res = (status, json) => ({ ok: status >= 200 && status < 300, status, json: async () => json });
const HANG = () => new Promise(() => { });   // 永久に返ってこない (キャプティブポータル等)

/* fetch の記録つき身代わり。handler は (url, init, 回数) を受けて応答を返す。 */
function makeFetch(handler) {
  const calls = [];
  const f = (url, init) => {
    calls.push(String(url));
    const r = handler(String(url), init, calls.length);
    if (r === HANG) {
      // signal が abort されたら reject する = 本物の fetch と同じふるまい
      return new Promise((_, rej) => {
        const s = init && init.signal;
        if (s) s.addEventListener("abort", () => {
          const e = new Error("aborted"); e.name = "AbortError"; rej(e);
        });
      });
    }
    return Promise.resolve(r);
  };
  f.calls = calls;
  return f;
}

function newEnv(opts) {
  const o = opts || {};
  const clock = makeClock();
  const env = {
    localStorage: o.localStorage || makeStorage(),
    sessionStorage: makeStorage(),
    navigator: { onLine: o.onLine !== false },
    location: { protocol: o.protocol || "https:" },
    fetch: o.fetch || makeFetch(() => res(200, {})),
    setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
  };
  return { env, clock, api: loadApi(env) };
}

/* ================= 通信層 ================= */
async function testApiJson() {
  // 1. 正常系: 1回で返り、タイムアウトのタイマーを残さない
  {
    const f = makeFetch(() => res(200, { hello: 1 }));
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x", { a: 1 }));
    eq(r.ok, { hello: 1 }, "正常系で応答がそのまま返らない");
    eq(f.calls.length, 1, "正常系なのに複数回リクエストしている");
    eq(clock.pending(), 0, "成功後にタイムアウトのタイマーが残っている (clearTimeout 漏れ)");
    ok(/start_date|a=1/.test(f.calls[0]), "パラメータがURLに載っていない");
  }

  // 2. 5xx は待てば直るので再試行する。最後は日本語の文面にする
  {
    const f = makeFetch(() => res(503, {}));
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x", {}));
    eq(f.calls.length, 3, "5xx が既定回数(3)まで再試行されていない");
    ok(r.err && /提供元が一時的に応答していません/.test(r.err.message),
      `5xx の文面が利用者向けになっていない: ${r.err && r.err.message}`);
    ok(r.err && !/HTTP 5/.test(r.err.message), "生の HTTP コードを利用者に出している");
  }

  // 3. 429 は無料枠を守るのが目的なので、他のエラーより長く待つ
  {
    const f = makeFetch(() => res(429, {}));
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x", {}));
    // 待ち時間そのものは仮想時計の到達時刻で見る (6000*1 + 12000*2 = 30000 が下限)
    ok(clock.now() >= 6000 + 12000, `429 の待ちが短すぎる: ${clock.now()}ms`);
    ok(r.err && /アクセスが集中しています/.test(r.err.message),
      `429 の文面が利用者向けになっていない: ${r.err && r.err.message}`);
    eq(f.calls.length, 3, "429 の再試行回数が違う");
  }
  {
    // 429 以外(5xx)の待ちは 429 より短いこと
    const f = makeFetch(() => res(503, {}));
    const { clock, api } = newEnv({ fetch: f });
    await settle(clock, api.apiJson("https://x", {}));
    ok(clock.now() < 6000 + 12000, `5xx の待ちが 429 と同じか長い: ${clock.now()}ms`);
  }

  // 4. 429/5xx 以外の 4xx は投げ直しても直らないので即中断する
  {
    const f = makeFetch(() => res(404, {}));
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x", {}));
    eq(f.calls.length, 1, "直らない 4xx を再試行している (無料枠の無駄撃ち)");
    ok(r.err instanceof Error, "4xx が Error になっていない");
  }

  // 5. 400 + reason の end_date クランプ。1回だけ縮めて、再試行回数は消費しない
  {
    const f = makeFetch((url, init, n) => n === 1
      ? res(400, { reason: "Value of 'end_date' is out of allowed range from 2026-08-01 to 2026-08-28." })
      : res(200, { clamped: true }));
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x",
      { start_date: "2026-08-01", end_date: "2026-08-30" }));
    eq(r.ok, { clamped: true }, "400+reason のクランプ再試行が成功していない");
    eq(f.calls.length, 2, "クランプ再試行の回数が違う");
    ok(/end_date=2026-08-28/.test(f.calls[1]), `end_date が縮まっていない: ${f.calls[1]}`);
    ok(!/end_date=2026-08-30/.test(f.calls[1]), "縮める前の end_date のまま投げ直している");
  }
  {
    // クランプは1回だけ。何度も 400 を返されても無限には粘らない
    const f = makeFetch(() => res(400, { reason: "Value of 'end_date' is out of allowed range from 2026-08-01 to 2026-08-28." }));
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x",
      { start_date: "2026-08-01", end_date: "2026-08-30" }));
    ok(f.calls.length <= 3, `クランプが繰り返されている: ${f.calls.length} 回`);
    ok(r.err instanceof Error, "クランプ後も 400 なのにエラーになっていない");
  }
  {
    // reason の日付が期間外なら縮めない (start より前・end より後は無視)
    const f = makeFetch(() => res(400, { reason: "Value of 'end_date' is out of allowed range from 2026-08-01 to 2026-09-30." }));
    const { clock, api } = newEnv({ fetch: f });
    await settle(clock, api.apiJson("https://x", { start_date: "2026-08-01", end_date: "2026-08-30" }));
    eq(f.calls.length, 1, "reason の日付が現在の end_date より後なのに再試行している");
  }

  // 6. 応答が永久に返ってこない = 山で最も起きる壊れ方。必ず時間で切る
  {
    const f = makeFetch(() => HANG);
    const { clock, api } = newEnv({ fetch: f });
    const r = await settle(clock, api.apiJson("https://x", {}));
    ok(r.err && /タイムアウト/.test(r.err.message),
      `無応答が時間で切れていない: ${r.err && r.err.message}`);
    ok(clock.now() >= 20000, `タイムアウトが 20 秒より早く切れている: ${clock.now()}ms`);
    eq(clock.pending(), 0, "タイムアウト後にタイマーが残っている");
  }
}

async function testModelInit() {
  // 7. ★ 2.28β の最重要事故: meta.json だけ返ってこないと予報全体が固まっていた。
  //    ここは主要データ(20秒)より短く切れて、しかも例外を投げずに null を返すこと。
  {
    const f = makeFetch(() => HANG);
    const { clock, api } = newEnv({ fetch: f });
    ok(api.META_TIMEOUT_MS < api.API_TIMEOUT_MS,
      `発表時刻の上限(${api.META_TIMEOUT_MS}ms)が主要データ(${api.API_TIMEOUT_MS}ms)より短くない`);
    const r = await settle(clock, api.modelInit("jma_msm"));
    ok(!("err" in r), "meta.json が返らないときに例外を投げている (予報全体を巻き添えにする)");
    eq(r.ok, null, "meta.json が返らないときに null 以外を返している");
    ok(clock.now() <= api.META_TIMEOUT_MS,
      `発表時刻の取得が上限で切れていない: ${clock.now()}ms`);
    eq(clock.pending(), 0, "発表時刻の取得後にタイマーが残っている");
  }

  // 8. どんな壊れ方をしても null に倒す (補助表示なので予報を落とさない)
  for (const [label, handler] of [
    ["404", () => res(404, {})],
    ["500", () => res(500, {})],
    ["JSONが壊れている", () => ({ ok: true, status: 200, json: async () => { throw new Error("bad json"); } })],
    ["通信そのものが失敗", () => { throw new Error("network down"); }],
    ["値が数値でない", () => res(200, { last_run_initialisation_time: "2026-08-21T00:00" })],
    ["キーごと無い", () => res(200, {})],
  ]) {
    const { clock, api } = newEnv({ fetch: makeFetch(handler) });
    const r = await settle(clock, api.modelInit("jma_msm"));
    ok(!("err" in r) && r.ok === null, `発表時刻の取得(${label})が null に倒れていない`);
  }

  // 9. 正常時は Date を返し、2回目は sessionStorage のキャッシュで通信しない
  {
    const t = 1755000000;
    const f = makeFetch(() => res(200, { last_run_initialisation_time: t }));
    const { clock, api } = newEnv({ fetch: f });
    const r1 = await settle(clock, api.modelInit("jma_msm"));
    ok(r1.ok instanceof Date && r1.ok.getTime() === t * 1000, "発表時刻が Date になっていない");
    const r2 = await settle(clock, api.modelInit("jma_msm"));
    eq(f.calls.length, 1, "発表時刻のキャッシュが効かず毎回取りに行っている");
    ok(r2.ok instanceof Date, "キャッシュからの復元が Date になっていない");
  }
}

function testOfflineErr() {
  // 10. 圏外の文面は「どうすれば見られるのか」を示す。保存済みがあれば山名を挙げる
  {
    const { api } = newEnv({ onLine: false });
    const e = api.offlineErr(new Error("元の文面"));
    ok(/保存済みの予報はまだありません/.test(e.message),
      `圏外・保存なしの文面が案内になっていない: ${e.message}`);
  }
  {
    const st = makeStorage();
    const { api } = newEnv({ onLine: false, localStorage: st });
    seedSnap(api, st, ["燕岳", "槍ヶ岳"]);
    const e = api.offlineErr(new Error("元の文面"));
    ok(/燕岳/.test(e.message) && /槍ヶ岳/.test(e.message),
      `圏外の文面に保存済みの山名が出ていない: ${e.message}`);
  }
  {
    // 圏内なら握りつぶさず、元のエラーをそのまま通す
    const orig = new Error("元の文面");
    const { api } = newEnv({ onLine: true });
    ok(api.offlineErr(orig) === orig, "圏内なのにエラーを圏外の文面で塗り潰している");
  }
}

/* ================= 応答の形の正規化 ================= */
function testNormalize(api) {
  // 11. hourly.time が無い応答は、生の TypeError ではなく日本語で止める
  for (const [label, bad] of [
    ["null", null],
    ["hourly ごと無い", {}],
    ["time が配列でない", { hourly: { time: "2026-08-21T00:00" } }],
    ["time が空", { hourly: { time: [] } }],
  ]) {
    let msg = null;
    try { api.normalizeSeries(bad, ["temperature_2m"], api.DAILY_KEYS); }
    catch (e) { msg = e.message; }
    ok(msg && /気象データの形式/.test(msg), `壊れた応答(${label})が日本語で止まっていない: ${msg}`);
  }

  // 12. キーごと欠けた項目は「全時刻欠測」に正規化する (下流の欠測ハンドリングに乗せる)
  {
    const d = { hourly: { time: ["2026-08-21T00:00", "2026-08-21T01:00"] } };
    api.normalizeSeries(d, ["temperature_2m", "wind_speed_925hPa"], api.DAILY_KEYS);
    eq(d.hourly.temperature_2m, [null, null], "欠けた hourly が全時刻 null になっていない");
    eq(d.hourly.wind_speed_925hPa.length, 2, "欠けた hourly の長さが time と揃っていない");
    eq(d.daily.time, [], "daily ごと欠けたときに空の time になっていない");
    for (const k of api.DAILY_KEYS) eq(d.daily[k], [], `欠けた daily(${k}) が配列になっていない`);
  }

  // 13. 既にある値は書き換えない
  {
    const d = { hourly: { time: ["2026-08-21T00:00"], temperature_2m: [12.3] } };
    api.normalizeSeries(d, ["temperature_2m"], []);
    eq(d.hourly.temperature_2m, [12.3], "既にある値を欠測で上書きしている");
  }
}

/* ================= 系列の貼り合わせ ================= */
function testMerge(api) {
  const T = h => `2026-08-21T${String(h).padStart(2, "0")}:00`;
  // 14. 添字ではなく時刻をキーにして貼る。2本のAPIで期間がずれても対応が崩れないこと
  {
    const base = { time: [T(0), T(1), T(2), T(3)] };
    // extra は1時間ぶん先行し、末尾が短い = 添字で貼ると全部1つずれる
    const extra = { time: [T(1), T(2)], visibility: [1000, 2000] };
    api.mergeSeries(base, extra, ["visibility"]);
    eq(base.visibility, [null, 1000, 2000, null],
      "時刻ではなく添字で貼っている (2本のAPIで期間がずれると全部ずれる)");
  }
  // 15. 足りない時刻は null。0 で埋めると「降水0mm」に化ける
  {
    const base = { time: [T(0), T(1)] };
    api.mergeSeries(base, { time: [], precipitation_probability: [] }, ["precipitation_probability"]);
    eq(base.precipitation_probability, [null, null], "貼るものが無いときに 0 で埋めている");
  }
  // 16. extra のキーごと欠けても、base.time と同じ長さの列になる
  {
    const base = { time: [T(0), T(1), T(2)] };
    api.mergeSeries(base, { time: [T(0), T(1), T(2)] }, ["snow_depth"]);
    eq(base.snow_depth, [null, null, null], "extra に無いキーが time と同じ長さになっていない");
  }
  // 17. extra の値の列が time より短い場合に undefined を混ぜない
  {
    const base = { time: [T(0), T(1)] };
    api.mergeSeries(base, { time: [T(0), T(1)], cape: [100] }, ["cape"]);
    eq(base.cape, [100, null], "値の列が短いときに undefined が混ざっている");
  }
}

function testSplitModels(api) {
  const T = ["2026-08-21T00:00"];
  // 18. 接尾辞を外して素のキーに戻す (そのまま ridgeWind / blockIndex に渡せること)
  {
    const cd = {
      hourly: {
        time: T,
        temperature_2m_jma_seamless: [20], temperature_2m_ecmwf_ifs025: [21],
        temperature_2m_gfs_seamless: [22], wind_speed_925hPa_ecmwf_ifs025: [8],
      }
    };
    const s = api.splitModels(cd);
    eq(s.jma_seamless.temperature_2m, [20], "気象庁メンバーの接尾辞が外れていない");
    eq(s.ecmwf_ifs025.temperature_2m, [21], "ECMWF の接尾辞が外れていない");
    eq(s.gfs_seamless.temperature_2m, [22], "GFS の接尾辞が外れていない");
    eq(s.ecmwf_ifs025.wind_speed_925hPa, [8], "気圧面の接尾辞が外れていない");
    eq(s.ecmwf_ifs025.time, T, "time が引き継がれていない");
    ok(!("temperature_2m_jma_seamless" in s.ecmwf_ifs025),
      "別モデルのキーが混ざっている (接尾辞の付け外しを間違えている)");
  }
  // 19. 形が違えば null。ここで例外を投げると確度だけでなく予報表ごと落ちる
  for (const [label, cd] of [["null", null], ["hourly 無し", {}],
  ["time が配列でない", { hourly: {} }]]) {
    eq(api.splitModels(cd), null, `モデル比較の応答(${label})が null に倒れていない`);
  }
  // 20. モデルを1つだけ指定したときは接尾辞が付かない。素のキーで拾い直せること
  {
    const s = api.splitModels({ hourly: { time: T, temperature_2m: [20] } });
    eq(s.ecmwf_ifs025.temperature_2m, [20], "接尾辞の無い応答を拾えていない");
  }
}

/* ================= 端末内保存 (スナップショット) ================= */
const MT = (name, extra) => Object.assign(
  { name, pref: "長野県", lat: 36.4, lon: 137.7, elev: 2763 }, extra || {});

function payloadFor(api, lastDay) {
  const day = lastDay || api.iso(api.addDays(api.jstToday(), 3));
  return {
    data: {
      hourly: { time: [day + "T00:00", day + "T01:00"], temperature_2m: [10, 11] },
      daily: { time: [day], weather_code: [1] },
    },
    fetchedAt: Date.now(),
  };
}

function seedSnap(api, st, names) {
  for (const n of names) api.snapSave(MT(n), payloadFor(api));
}

function testSnapshot() {
  // 21. 保存 → 読み出しの往復
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    ok(api.snapSave(MT("燕岳"), payloadFor(api)) === true, "スナップショットの保存に失敗した");
    const o = api.snapLoad("n:燕岳");
    ok(o && o.mt.name === "燕岳", "保存した予報を読み出せない");
    eq(api.snapIndex().map(x => x.n), ["燕岳"], "索引に載っていない");
  }

  // 22. GPS現在地・座標指定は保存しない (居場所を端末内にも残さない)
  {
    const { api } = newEnv();
    eq(api.snapId(MT("現在地", { here: true })), null, "GPS現在地を保存対象にしている");
    eq(api.snapId(MT("地点", { coord: true })), null, "座標指定を保存対象にしている");
    eq(api.snapId(null), null, "山が無いのに保存対象にしている");
  }

  // 23. 自動枠は3座。古いものから押し出される
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    seedSnap(api, st, ["A", "B", "C", "D"]);
    const idx = api.snapIndex();
    eq(idx.map(x => x.n), ["D", "C", "B"], "自動枠の上限または並び(新しい順)が違う");
    eq(api.snapLoad("n:A"), null, "押し出された本体が消えていない (領域を食い続ける)");
  }

  // 24. 固定した山は自動枠の計算から外れ、何座検索しても押し出されない
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    seedSnap(api, st, ["A"]);
    api.snapKeep("n:A");
    seedSnap(api, st, ["B", "C", "D", "E"]);
    const names = api.snapIndex().map(x => x.n);
    ok(names.includes("A"), `固定した山が押し出された: ${names}`);
    ok(api.snapLoad("n:A"), "固定した山の本体が消えている");
  }

  // 25. 再検索しても固定は外れない
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    seedSnap(api, st, ["A"]);
    api.snapKeep("n:A");
    api.snapSave(MT("A"), payloadFor(api));
    ok(api.snapEntry("n:A").keep === true, "再検索で固定が外れている");
  }

  // 26. 上限まで固定した状態でさらに押したとき、**押した山が残る**こと。
  //     先頭へ移す前に上限で切ると、いま押した山が最古扱いで真っ先に外れ、
  //     「押しても何も起きない」ように見える(履歴のピン留めに同じ注意書きがある罠)
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    // 固定が上限まで埋まっていて、押す相手が**それより古い**状態を作る。
    // (新しい側を押すと、並べ替えが無くても上限の切り方で残ってしまい差が出ない)
    const future = api.iso(api.addDays(api.jstToday(), 3));
    api.snapIndexSave([
      { id: "n:C", n: "C", p: "", t: 3, l: future, keep: true },
      { id: "n:B", n: "B", p: "", t: 2, l: future, keep: true },
      { id: "n:A", n: "A", p: "", t: 1, l: future, keep: true },
      { id: "n:X", n: "X", p: "", t: 0, l: future },
    ]);
    const released = api.snapKeep("n:X");
    ok(api.snapEntry("n:X") && api.snapEntry("n:X").keep === true,
      "固定が上限のときに、いま押した山が固定されていない (押しても何も起きないように見える)");
    eq(api.snapIndex().filter(x => x.keep === true).length, api.SNAP_KEEP_MAX,
      "固定の数が上限を超えている");
    eq(released, ["A"], "入れ替えで外れた山の名前が返っていない (画面で説明できない)");
  }

  // 27. 固定が溢れたら**消さずに**自動枠へ戻す (押した操作を黙って無効にしない・データも捨てない)
  {
    const { api } = newEnv();
    const a = [1, 2, 3, 4].map(i => ({ id: "n:" + i, n: String(i), p: "", t: 1, l: "2999-01-01", keep: true }));
    const out = api.snapPrune(a);
    eq(out.filter(x => x.keep === true).length, api.SNAP_KEEP_MAX, "固定の上限が効いていない");
    eq(out.length, 4, "固定から溢れた分が消えている (自動枠へ戻していない)");
  }

  // 28. 期限切れ(最終日が今日より前)は索引からも本体からも消す
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    const past = api.iso(api.addDays(api.jstToday(), -1));
    api.snapSave(MT("古い山"), payloadFor(api, past));
    eq(api.snapIndex().length, 0, "期限切れのスナップショットが索引に残っている");
    eq(api.snapLoad("n:古い山"), null, "期限切れの本体が消えていない");
    eq(st.getItem(api.snapBodyKey("n:古い山")), null, "期限切れの本体が localStorage に残っている");
  }

  // 29. quota 超過: 固定していない最古を1件落として1回だけやり直す
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    seedSnap(api, st, ["古", "新"]);
    const used = [...st._map].reduce((n, [k, v]) => n + k.length + v.length, 0);
    // いま入っている量 +1件ぶんは入らない大きさに絞る
    st._map.set("__limit__", "");
    const st2 = makeStorage({ limit: Math.floor(used * 1.4) });
    for (const [k, v] of st._map) if (k !== "__limit__") st2._map.set(k, v);
    const e2 = newEnv({ localStorage: st2 });
    // 索引の型検査を通すため、同じ内容で作り直した環境で保存する
    const r = e2.api.snapSave(MT("追加"), payloadFor(e2.api));
    ok(r === true, "quota 超過のときに古い1件を落として保存し直せていない");
    ok(e2.api.snapLoad("n:追加"), "保存し直した本体が読み出せない");
    eq(e2.api.snapLoad("n:古"), null, "落とす相手が最古になっていない");
  }

  // 30. どうやっても入らないときは false を返し、**残骸を索引にも領域にも残さない**。
  //     前回ぶんの本体が残ったまま索引から消えると、誰も参照しない塊が領域を食い続ける
  {
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    api.snapSave(MT("燕岳"), payloadFor(api));
    const used = [...st._map].reduce((n, [k, v]) => n + k.length + v.length, 0);
    // 同じ山を、いまの領域には収まらない大きさで保存し直す
    const st2 = makeStorage({ limit: Math.floor(used * 1.2) });
    for (const [k, v] of st._map) st2._map.set(k, v);
    const e2 = newEnv({ localStorage: st2 });
    const big = payloadFor(e2.api);
    big.data.hourly.temperature_2m = new Array(5000).fill(12.3456789);
    const r = e2.api.snapSave(MT("燕岳"), big);
    eq(r, false, "保存できないのに成功を返している (「保存しました」と案内してしまう)");
    eq(e2.api.snapIndex().filter(x => x.id === "n:燕岳").length, 0,
      "保存に失敗した山が索引に残っている (圏外で開くと空の表になる)");
    eq(st2.getItem(e2.api.snapBodyKey("n:燕岳")), null,
      "索引から外したのに本体が残っている (誰も参照しない塊が領域を食い続ける)");
  }
  {
    // 索引すら書けない極端な場合でも、成功を返さないこと
    const st = makeStorage({ limit: 50 });
    const { api } = newEnv({ localStorage: st });
    eq(api.snapSave(MT("入らない山"), payloadFor(api)), false,
      "領域が全く無いのに保存成功を返している");
    eq(st.getItem(api.snapBodyKey("n:入らない山")), null, "半端な本体が残っている");
  }

  // 31. ★ localStorage に触るだけで例外になる端末 (Safari の全Cookieブロック)。
  //     ここで throw が漏れると、呼び出し元のスクリプトがその行で丸ごと死ぬ = 画面が無反応になる
  {
    const st = makeStorage({ secError: true });
    const { api } = newEnv({ localStorage: st });
    let threw = null;
    try {
      eq(api.snapIndex(), [], "アクセス不能な端末で索引が空になっていない");
      eq(api.snapLoad("n:燕岳"), null, "アクセス不能な端末で読み出しが null になっていない");
      eq(api.snapSave(MT("燕岳"), payloadFor(api)), false, "アクセス不能な端末で保存が false になっていない");
      api.snapUnkeep("n:燕岳");
      eq(api.snapKeep("n:燕岳"), null, "アクセス不能な端末で固定が null になっていない");
      eq([...api.snapNameSet()], [], "アクセス不能な端末で保存済み一覧が空になっていない");
    } catch (e) { threw = e; }
    ok(!threw, `localStorage が例外を投げる端末でスクリプトが死ぬ: ${threw && threw.message}`);
  }

  // 32. 汚染データ。同じオリジンを他プロジェクトと共有するので「自分が書いた形」を前提にできない。
  //     索引の値は山名として画面にも出るため、型を通らないものは全て捨てること
  {
    const bad = [
      null, 42, "文字列", [],
      { id: "n:x" },                                                   // 足りない
      { id: 1, n: "数値のid", p: "", t: 1, l: "2999-01-01" },
      { id: "n:x", n: 1, p: "", t: 1, l: "2999-01-01" },
      { id: "n:x", n: "x", p: "", t: "1", l: "2999-01-01" },
      { id: "n:x", n: "x", p: "", t: 1, l: 20990101 },
      { id: "n:x", n: "x", p: "", t: Date.now() + 9e9, l: "2999-01-01" },  // 未来の保存時刻
      { id: "n:x", n: "<img src=x onerror=alert(1)>", p: "", t: 1, l: "2999-01-01", keep: "yes" },
    ];
    const st = makeStorage();
    st.setItem("pw-snap-v1", JSON.stringify(bad));
    const { api } = newEnv({ localStorage: st });
    const live = api.snapIndex();
    eq(live.filter(x => x.keep !== undefined && x.keep !== true).length, 0,
      "keep が true 以外の値のまま索引に残っている");
    for (const x of live) {
      ok(typeof x.id === "string" && typeof x.n === "string" && typeof x.t === "number"
        && typeof x.l === "string", `型検査を通っていない索引が残っている: ${JSON.stringify(x)}`);
      ok(x.t <= Date.now(), "未来の保存時刻を持つ索引が残っている");
    }
  }
  {
    // 索引そのものが JSON でない・配列でない
    for (const junk of ["{", "null", '{"a":1}', '"文字列"', "123"]) {
      const st = makeStorage();
      st.setItem("pw-snap-v1", junk);
      const { api } = newEnv({ localStorage: st });
      eq(api.snapIndex(), [], `索引が壊れている(${junk})ときに空にならない`);
    }
  }
  {
    // 本体が壊れている場合。ここを通すと下流が生の TypeError になる
    const st = makeStorage();
    const { api } = newEnv({ localStorage: st });
    api.snapSave(MT("燕岳"), payloadFor(api));
    const key = api.snapBodyKey("n:燕岳");
    for (const junk of [
      "{", "null", "[]",
      JSON.stringify({ t: 1 }),
      JSON.stringify({ t: 1, mt: { name: "燕岳", pref: "", lat: 1, lon: 1, elev: 1 } }),
      JSON.stringify({ t: 1, mt: { name: "燕岳", pref: "", lat: NaN, lon: 1, elev: 1 }, data: { hourly: { time: ["x"] }, daily: { time: [] } } }),
      JSON.stringify({ t: 1, mt: { name: "燕岳", pref: "", lat: 1, lon: 1, elev: 1 }, data: { hourly: { time: [] }, daily: { time: [] } } }),
      JSON.stringify({ t: 1, mt: { name: "燕岳", pref: "", lat: 1, lon: 1, elev: 1 }, data: { hourly: { time: [123] }, daily: { time: [] } } }),
      JSON.stringify({ t: 1, mt: { name: "燕岳", pref: "", lat: 1, lon: 1, elev: 1 }, data: { hourly: { time: ["x"] } } }),
    ]) {
      st.setItem(key, junk);
      eq(api.snapLoad("n:燕岳"), null, `壊れた本体(${junk.slice(0, 40)})を読み出してしまっている`);
    }
  }
}

/* ================= ゲート (gate.js) ================= */
function testGate() {
  const agreedAuthed = api => { api.pwSave(api.PW_AGREE_KEY, "1"); api.pwSave(api.PW_AUTH_KEY, api.PW_AUTH_VER); };

  // 34. 同意・認証がそろって初めて通す
  {
    const { api } = newEnv();
    ok(api.pwGateOk() === false, "何も入力していないのにゲートが開いている");
    api.pwSave(api.PW_AGREE_KEY, "1");
    ok(api.pwGateOk() === false, "認証コード無しでゲートが開いている");
    api.pwDrop(api.PW_AGREE_KEY);
    api.pwSave(api.PW_AUTH_KEY, api.PW_AUTH_VER);
    ok(api.pwGateOk() === false, "規約に同意していないのにゲートが開いている");
    agreedAuthed(api);
    ok(api.pwGateOk() === true, "同意・認証が済んでいるのにゲートが開かない");
  }

  // 35. 認証の版が変われば再入力を求める(年次ローテーション)
  {
    const { api } = newEnv();
    api.pwSave(api.PW_AGREE_KEY, "1");
    api.pwSave(api.PW_AUTH_KEY, "2000a");
    ok(api.pwIsAuthed() === false, "古い版の認証済み印で通してしまっている");
  }

  // 36. ★ fail-closed。ダウンロードして直接開いた場合は、同意・認証が済んでいても常に閉じる
  {
    const { api } = newEnv({ protocol: "file:" });
    agreedAuthed(api);
    ok(api.pwIsLocalFile() === true, "file:// を判定できていない");
    ok(api.pwGateOk() === false,
      "ファイルを直接開いた状態でゲートが開いている (無料枠を守る仕組みが素通りする)");
  }
  {
    // ローカル確認(python -m http.server)は http: なので対象外
    const { api } = newEnv({ protocol: "http:" });
    agreedAuthed(api);
    ok(api.pwGateOk() === true, "http:// のローカル確認までブロックしている");
  }

  // 37. localStorage が例外を投げる端末でも、そのタブの間は使えること。
  //     ここで throw が漏れると index.html は冒頭で死に、フォームが無反応になる
  {
    const { api } = newEnv({ localStorage: makeStorage({ secError: true }) });
    let threw = null;
    try {
      agreedAuthed(api);
      ok(api.pwGateOk() === true, "保存できない端末で、入力してもゲートが開かない");
      api.pwDrop(api.PW_AGREE_KEY);
      ok(api.pwGateOk() === false, "保存できない端末で同意の取り消しが効かない");
    } catch (e) { threw = e; }
    ok(!threw, `localStorage が例外を投げる端末でゲートが死ぬ: ${threw && threw.message}`);
  }

  // 38. 計測の失敗がアプリの動作を壊さないこと(広告ブロッカー・gtag の読み込み前)
  {
    const { api } = newEnv();
    let threw = null;
    try { api.pwTrack("search", { a: 1 }); } catch (e) { threw = e; }
    ok(!threw, `gtag が無い状態で計測がスクリプトを止める: ${threw && threw.message}`);
  }
}

/* ================= 表示の小物 ================= */
function testAgo(api) {
  // 33. 圏外で何日も同じ画面を見ている状態に気づけるようにするための表示
  eq(api.agoTxt(-1), "", "負の経過時間が空文字になっていない");
  eq(api.agoTxt(0), "約1分前", "0ms の表記が違う");
  eq(api.agoTxt(59 * 60 * 1000), "約59分前", "59分の表記が違う");
  eq(api.agoTxt(3 * 3600 * 1000), "約3時間前", "3時間の表記が違う");
  eq(api.agoTxt(50 * 3600 * 1000), "約2日前", "2日の表記が違う");
  ok(/日前/.test(api.agoTxt(30 * 24 * 3600 * 1000)), "何日も経った予報が「日前」で出ていない");
}

/* ================= 実行 ================= */
(async () => {
  const { api } = newEnv();
  await testApiJson();
  await testModelInit();
  testOfflineErr();
  testNormalize(api);
  testMerge(api);
  testSplitModels(api);
  testSnapshot();
  testGate();
  testAgo(api);

  C.report("圏外・障害時のふるまい(通信・保存)");
})().catch(e => { console.error(e); process.exit(2); });
