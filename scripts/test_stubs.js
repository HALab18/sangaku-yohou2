"use strict";
/* 障害・異常系のテストで使う「身代わりの環境」。
 * scripts/test_offline.js と scripts/test_sw.js が共有する。単体では何もしない。
 *
 * 本物の時間で回すと、429 の再試行(6秒→12秒)・タイムアウト(20秒)・Service Worker の
 * 遅延しきい値(6秒)を1本ずつ試すだけで分単位かかる。それでは誰も回さなくなるので、
 * 時間そのものを差し替えて即座に進める。「タイマーが片付けられたか」も数えられるようになる。
 */

function makeClock() {
  let now = 0, seq = 0;
  const timers = new Map();
  return {
    setTimeout(fn, ms) { const id = ++seq; timers.set(id, { at: now + (ms || 0), fn }); return id; },
    clearTimeout(id) { timers.delete(id); },
    now: () => now,
    pending: () => timers.size,
    /* いちばん早いタイマーまで時間を進めて発火させる。進めるものが無ければ false */
    advance() {
      if (!timers.size) return false;
      let at = Infinity;
      for (const t of timers.values()) if (t.at < at) at = t.at;
      now = at;
      for (const [id, t] of [...timers]) if (t.at <= now) { timers.delete(id); t.fn(); }
      return true;
    },
  };
}

/* Promise が片付くまで、マイクロタスクを流しつつ仮想時計を進める。
 * 片付かないまま進めるものが尽きたら「無限に待っている」ことになるので落とす。 */
async function settle(clock, p) {
  let state = null;
  Promise.resolve(p).then(v => { state = { ok: v }; }, e => { state = { err: e }; });
  for (let i = 0; i < 5000 && !state; i++) {
    await new Promise(r => setImmediate(r));
    if (state) break;
    if (!clock.advance()) await new Promise(r => setImmediate(r));
  }
  if (!state) throw new Error("Promise が片付きませんでした (無限に待っている可能性)");
  return state;
}

/* localStorage / sessionStorage の身代わり。
 *   limit    … 合計バイト数の上限。超えると QuotaExceededError を投げる
 *   secError … アクセス自体が SecurityError を投げる端末 (Safari の全Cookieブロック) */
function makeStorage(opts) {
  const o = opts || {};
  const map = new Map();
  const guard = () => {
    if (o.secError) { const e = new Error("SecurityError"); e.name = "SecurityError"; throw e; }
  };
  const total = () => { let n = 0; for (const [k, v] of map) n += k.length + v.length; return n; };
  return {
    _map: map,
    getItem(k) { guard(); return map.has(k) ? map.get(k) : null; },
    removeItem(k) { guard(); map.delete(k); },
    setItem(k, v) {
      guard();
      v = String(v);
      const before = map.get(k);
      map.set(k, v);
      if (o.limit != null && total() > o.limit) {
        if (before === undefined) map.delete(k); else map.set(k, before);
        const e = new Error("QuotaExceededError"); e.name = "QuotaExceededError"; throw e;
      }
    },
  };
}

/* 検査の道具立て。落ちた項目を集めて最後にまとめて出す
 * (最初の1件で止めると、直すたびに回し直すことになる)。 */
function makeChecker() {
  const fails = [];
  let checks = 0;
  return {
    fails,
    count: () => checks,
    ok(cond, msg) { checks++; if (!cond) fails.push(msg); },
    eq(a, b, msg) {
      checks++;
      if (JSON.stringify(a) !== JSON.stringify(b))
        fails.push(`${msg}: ${JSON.stringify(a)} ≠ ${JSON.stringify(b)}`);
    },
    /* 結果を出して終了コードを決める */
    report(label) {
      if (fails.length) {
        console.log(`${label}: ${checks} 項目中 ${fails.length} 件が期待どおりでない\n`);
        for (const m of fails) console.log("  - " + m);
        process.exit(1);
      }
      console.log(`${label}: ${checks} 項目 ... 違反なし`);
    },
  };
}

/* ファイルから目印で範囲を切り出す。アプリ本体を書き換えずにテストするための仕掛け。
 * 目印がちょうど1箇所でなければ落とす — 構成が変わったのに黙って別の範囲を
 * 評価し続けるのが、このやり方でいちばん危ない壊れ方なので。 */
function sliceByMarks(src, file, slices) {
  let out = "";
  for (const [label, start, end] of slices) {
    for (const [what, mark] of [["開始", start], ["終了", end]]) {
      const n = src.split(mark).length - 1;
      if (n !== 1) {
        throw new Error(`${file} の「${label}」の切り出し${what}の目印が ${n} 箇所あります`
          + ` (目印: ${mark})。${file} の構成が変わった可能性があります`);
      }
    }
    const i = src.indexOf(start), j = src.indexOf(end);
    if (j < i) throw new Error(`${file} の「${label}」で終了の目印が開始より前にあります`);
    out += src.slice(i, j) + "\n";
  }
  return out;
}

/* DOM の身代わり。index.html の本体スクリプトは読み込み時に
 * document.getElementById(...).addEventListener(...) を何十回もするので、これが無いと
 * 描画の関数を1つ呼ぶことすらできない。
 *
 * ★ 本物の DOM を真似るためのものではない。**画面を組み立てる文字列**が CLI と一致するかを
 *   見るのが目的なので、要素は「innerHTML を覚えるだけの箱」で足りる。
 *   要素どうしの親子関係も、CSS も、レイアウトも持たない(持たせると、この身代わり自体が
 *   正しいかを検査する羽目になる)。querySelectorAll は必ず空配列を返す。
 * ★ 触られたのに用意していないメソッドがあれば、黙って undefined を返さずに落とす。
 *   静かに素通りすると「描けたつもりで空の表」を検査してしまう。 */
function makeDom() {
  const nodes = new Map();
  const make = (id) => {
    const el = {
      id, innerHTML: "", textContent: "", value: "", hidden: false, checked: false,
      dataset: {}, style: {}, options: [], children: [], tabIndex: -1,
      classList: {
        _s: new Set(),
        add(...c) { c.forEach(x => this._s.add(x)) },
        remove(...c) { c.forEach(x => this._s.delete(x)) },
        toggle(c, on) { if (on === undefined) on = !this._s.has(c); on ? this._s.add(c) : this._s.delete(c); return on },
        contains(c) { return this._s.has(c) },
      },
      addEventListener() { }, removeEventListener() { }, focus() { }, blur() { }, click() { },
      scrollIntoView() { }, appendChild(c) { el.children.push(c); return c },
      setAttribute(k, v) { el.dataset["attr_" + k] = String(v) },
      getAttribute(k) { const v = el.dataset["attr_" + k]; return v === undefined ? null : v },
      removeAttribute(k) { delete el.dataset["attr_" + k] },
      toggleAttribute() { }, hasAttribute() { return false },
      closest() { return null }, matches() { return false },
      // 親を持たせるのは `inp.closest("label")||inp.parentElement` のような書き方のため。
      // 実際の入れ子は再現しない(共通の箱を1つ返すだけ)。
      get parentElement() { return get("__parent__") }, get parentNode() { return get("__parent__") },
      querySelector() { return null }, querySelectorAll() { return [] },
      getBoundingClientRect() { return { x: 0, y: 0, width: 0, height: 0, top: 0, left: 0 } },
      get firstChild() { return el.children[0] || null },
      get scrollWidth() { return 0 }, get clientWidth() { return 0 },
    };
    return el;
  };
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, make(id));
    return nodes.get(id);
  };
  const document = {
    getElementById: (id) => get(id),
    querySelector: (sel) => get("sel:" + sel),
    querySelectorAll: () => [],
    createElement: (tag) => make("new:" + tag),
    addEventListener() { }, removeEventListener() { },
    documentElement: get("html"), body: get("body"), head: get("head"),
    readyState: "complete", get activeElement() { return null },
  };
  return { document, nodes, el: get };
}

module.exports = { makeClock, settle, makeStorage, makeChecker, sliceByMarks, makeDom };
