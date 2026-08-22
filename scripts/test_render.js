"use strict";
/* 描画(Web側)の実行係。index.html の run() を**そのまま**回して、出来上がった表の HTML を返す。
 *
 * これまでのテストは「DOM に触らない範囲」だけを切り出して関数単位で見ていた。表を組み立てる
 * 経路(取得 → 正規化 → 行の組み立て → 表の HTML)はまるごと未検査で、
 * **CLI と Web が同じデータから同じ表を出すか**は誰も確かめていなかった。
 *
 * ここでは本体スクリプトを丸ごと評価する。読み込み時に
 * document.getElementById(...).addEventListener(...) を何十回もするので、
 * scripts/test_stubs.js の makeDom() を document として渡す。要素は「innerHTML を覚える箱」で足りる
 * (画面の見た目ではなく、**組み立てた文字列**が CLI と一致するかを見るため)。
 *
 * 通信はしない。references/fixture_forecast.json に固定した本物の応答を、
 * リクエストの署名(パス + 並べ替えたクエリ)で引いて返す。時計も仮想に差し替えるので、
 * 「今日」が動いても結果は動かない。
 *
 *     node scripts/test_render.js <出力JSON>            … fixture を再生して表を作る
 *     node scripts/test_render.js --record <出力JSON>   … 実通信して fixture を作る(要ネット)
 *
 * 単体で使うものではない。python scripts/test_render.py から呼ばれる。
 */
const fs = require("fs");
const path = require("path");
const { makeStorage, makeDom } = require("./test_stubs");

const ROOT = path.join(__dirname, "..");
const FIXTURE = path.join(ROOT, "references", "fixture_forecast.json");

/* 本体スクリプトの切り出し。Service Worker の登録だけ外す(navigator.serviceWorker を触るため)。
 * 目印がちょうど1箇所でなければ落とす — 黙って別の範囲を評価し続けるのが一番危ないので。 */
const START = '"use strict";';
const END = "// ---- Service Worker の登録";

function sliceBody() {
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  for (const [label, mark] of [["開始", START], ["終了", END]]) {
    const n = html.split(mark).length - 1;
    if (n !== 1) {
      throw new Error(`index.html の切り出し${label}の目印「${mark}」が ${n} 箇所あります`
        + " (index.html の構成が変わった可能性があります)");
    }
  }
  return html.slice(html.indexOf(START), html.indexOf(END));
}

/* ---- リクエストの署名。CLI(Python)側と同じ規則で作ること ---- */
// 値の表記ゆれをならす。Python は 2763.0、JS は 2763 と書くので、そのままだと
// 同じリクエストが別の署名になる。カンマ区切りの並び(周辺4方位の緯度経度)にも効かせる。
function canon(v) {
  return String(v).split(",").map(tok => {
    const n = Number(tok);
    if (tok.trim() === "" || !Number.isFinite(n)) return tok;
    return Number.isInteger(n) ? String(n) : String(n);
  }).join(",");
}

function signature(url) {
  const u = new URL(url);
  const ps = [...u.searchParams.entries()]
    .map(([k, v]) => [k, canon(v)])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return u.pathname + "?" + ps.map(([k, v]) => k + "=" + v).join("&");
}

/* ---- 身代わりの環境 ---- */
function makeEnv(fixture, record) {
  const dom = makeDom();
  const ls = makeStorage({});
  const ss = makeStorage({});
  // 規約同意と認証を済ませた状態にしておく(ゲートは test_offline.js が別に見ている)
  ls.setItem("sangaku-yohou2-agreed-v1", "1");
  ls.setItem("peakweather2-auth", fixture.auth_ver);
  const captured = {};
  const fetch = async (url) => {
    const sig = signature(String(url));
    if (record) {
      const r = await globalThis.fetch(String(url));
      const json = await r.json();
      captured[sig] = json;
      return { ok: r.ok, status: r.status, json: async () => json };
    }
    if (!(sig in fixture.responses)) {
      // 黙って null を返すと「取得できたが中身が空」に化ける。落とす方が安全。
      throw new Error("fixture にこのリクエストがありません: " + sig
        + "\n  → node scripts/test_render.js --record で取り直してください");
    }
    return { ok: true, status: 200, json: async () => fixture.responses[sig] };
  };
  return { dom, ls, ss, fetch, captured };
}

function loadApp(env, nowMs) {
  const read = (f) => fs.readFileSync(path.join(ROOT, f), "utf8");
  // 時刻を固定する。Date を丸ごと差し替えると Intl の書式まで壊れるので、
  // 引数なしの new Date() と Date.now() だけを基準時刻に寄せる。
  const header = `
    var document=__env.dom.document, localStorage=__env.ls, sessionStorage=__env.ss,
        fetch=__env.fetch, location={hash:"",href:"http://localhost/index.html",origin:"http://localhost"},
        navigator={onLine:true,language:"ja"},
        history={state:null,replaceState:function(){},pushState:function(){}},
        matchMedia=function(){return{matches:false,addEventListener:function(){}}},
        requestAnimationFrame=function(f){return 0},
        addEventListener=function(){}, removeEventListener=function(){},
        innerWidth=1280, innerHeight=900, scrollY=0, scrollTo=function(){},
        gtag=function(){}, dataLayer=[],
        __NOW=${nowMs}, __RealDate=__env.RealDate;
    // 引数なしの new Date() と Date.now() だけを基準時刻に寄せる。
    // ★ 本物のコンストラクタは __env から受け取る。ここで var __RealDate=Date と書くと
    //   巻き上げで「自分自身」を掴んで無限再帰する(実際に踏んだ)。
    var Date=function(){ if(arguments.length===0) return new __RealDate(__NOW);
      return new (Function.prototype.bind.apply(__RealDate,[null].concat([].slice.call(arguments)))); };
    Date.now=function(){return __NOW};
    Date.UTC=__RealDate.UTC; Date.parse=__RealDate.parse;
    Date.prototype=__RealDate.prototype;
  `;
  const body = header + read("logic.js") + "\n" + read("display.js") + "\n"
    + read("gate.js") + "\n" + sliceBody()
    + "\nreturn {run:run, resolveLocal:resolveLocal, jstToday:jstToday, iso:iso, dom:__env.dom};";
  return new Function("__env", body)(Object.assign({ RealDate: Date }, env));
}

/* ---- 実行 ---- */
async function main() {
  const args = process.argv.slice(2);
  const record = args[0] === "--record";
  const outPath = record ? args[1] : args[0];
  if (!outPath) {
    console.error("usage: node scripts/test_render.js [--record] <出力JSON>");
    process.exit(2);
  }
  const fixture = record
    ? { name: process.env.PW_FIXTURE_NAME || "燕岳", now: Date.now(), auth_ver: readAuthVer(), responses: {} }
    : JSON.parse(fs.readFileSync(FIXTURE, "utf8"));

  const env = makeEnv(fixture, record);
  const app = loadApp(env, fixture.now);
  const hits = app.resolveLocal(fixture.name);
  if (hits.length !== 1) throw new Error(`山名 ${fixture.name} が1件に定まりません (${hits.length}件)`);
  const m = hits[0];
  await app.run({ name: m[0], pref: m[2], lat: m[3], lon: m[4], elev: m[5] }, {});

  const out = env.dom.el("out").innerHTML;
  if (!out || out.length < 500) throw new Error("表が組み立てられていません (out.innerHTML が空同然)");
  if (record) {
    fixture.responses = env.captured;
    fs.writeFileSync(FIXTURE, JSON.stringify(fixture), "utf8");
    console.error(`fixture を書きました: ${Object.keys(env.captured).length} 応答`);
  }
  fs.writeFileSync(outPath, JSON.stringify({ html: out }), "utf8");
}

function readAuthVer() {
  const m = fs.readFileSync(path.join(ROOT, "gate.js"), "utf8").match(/PW_AUTH_VER\s*=\s*"([^"]+)"/);
  if (!m) throw new Error("gate.js から PW_AUTH_VER を読めません");
  return m[1];
}

main().catch(e => { console.error(e.stack || String(e)); process.exit(1); });
