"use strict";
/* 判定ロジック(Web側)の等価性テスト。
 *
 * references/logic_cases.json の入出力表どおりに logic.js の関数が動くかを確かめる。
 * 同じ表を scripts/test_logic.py が scripts/mountain_weather.py に対して回すので、
 * 両方が通れば「CLI と Web の判定は同じ入力で同じ出力を返す」ことになる
 * (CLAUDE.md 規約3 を目視ではなく機械で守るための仕掛け)。
 *
 *     node scripts/test_logic.js
 *
 * あわせて「logic.js が本当に唯一の実装になっているか」も見る:
 *   - index.html / docs/find.html の ?v= が PW_LOGIC_VER と一致すること
 *     (ずれると古い判定がキャッシュに残り、画面は新しいのに判定だけ旧版になる)
 *   - 移したはずの関数が index.html / docs/find.html に再定義されていないこと
 *     (再定義すると後勝ちで上書きされ、logic.js を直しても反映されない)
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const L = require(path.join(ROOT, "logic.js"));
const data = JSON.parse(fs.readFileSync(path.join(ROOT, "references", "logic_cases.json"), "utf8"));
const TOL = 1e-9;

const FUNCS = {
  seasonTh: L.seasonTh, blockIndex: L.blockIndex, feelsLike: L.feelsLike,
  viewScore: L.viewScore, interpWind: L.interpWind, sumOrNull: L.sumOrNull,
  lightningRisk: L.lightningRisk, eveThunder: L.eveThunder
};

// 期待値と実測の一致判定。浮動小数だけ絶対誤差 TOL を許す(それ以外は厳密一致)。
function same(a, b) {
  if (a === null || b === null || a === undefined || b === undefined) return a === b || (a == null && b == null);
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= TOL;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => same(x, b[i]));
  }
  if (typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    return ka.length === kb.length && ka.every((k, i) => k === kb[i]) && ka.every(k => same(a[k], b[k]));
  }
  return a === b;
}

const fails = [];
let total = 0;
for (const [name, fn] of Object.entries(FUNCS)) {
  const cases = data[name];
  if (!cases || !cases.length) { fails.push(`${name}: ケースが1件もありません`); continue; }
  for (const c of cases) {
    total++;
    const got = fn.apply(null, c.in);
    if (!same(c.out, got)) {
      fails.push(`${name} / ${c.name}\n`
        + `    in       = ${JSON.stringify(c.in)}\n`
        + `    expected = ${JSON.stringify(c.out)}\n`
        + `    got      = ${JSON.stringify(got === undefined ? null : got)}`);
    }
  }
}
console.log(`判定ロジック(JS): ${total - fails.length}/${total} 件一致`);
const caseFails = fails.length;   // ここまでが入出力表の不一致

// ---- logic.js が唯一の実装であることの確認 ----
const PAGES = [["index.html", /<script src="logic\.js\?v=([^"]+)"/],
               [path.join("docs", "find.html"), /<script src="\.\.\/logic\.js\?v=([^"]+)"/]];
// logic.js へ移した関数。ページ側に再定義が残っていたら、そちらが後勝ちで使われてしまう。
const MOVED = ["blockIndex", "seasonTh", "feelsLike", "viewScore", "interpWind", "sumOrNull",
               "lightningRisk", "eveThunder", "LT_LABEL"];
for (const [rel, re] of PAGES) {
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  const m = src.match(re);
  if (!m) fails.push(`${rel}: logic.js の <script src> が見つかりません`);
  else if (m[1] !== L.PW_LOGIC_VER) {
    fails.push(`${rel}: logic.js の ?v=${m[1]} が PW_LOGIC_VER=${L.PW_LOGIC_VER} と違います`
      + " (古い logic.js がキャッシュに残り、判定だけ旧版になります)");
  }
  for (const f of MOVED) {
    // 宣言の形は問わない。`function 名(` だけを見ていると
    // `const 名=(…)=>{}` / `var 名=function(…)` での再定義を素通しする
    // (どの形でも後勝ちで logic.js の実装を上書きするので、検出できないと意味が無い)。
    if (new RegExp("(?:function|const|let|var)\\s+" + f + "\\s*[=(]").test(src)) {
      fails.push(`${rel}: ${f}() が再定義されています (logic.js の実装が上書きされます)`);
    }
  }
}
console.log(`実装の一本化: ${fails.length > caseFails ? "NG" : "OK"}`);

for (const f of fails) console.log("  NG " + f);
process.exit(fails.length ? 1 : 0);
