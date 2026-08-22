"use strict";
/* 表示まわり(Web側)の実行係。display.js の関数をそのまま呼ぶ。
 *
 * 天気の文言・「濡れ注意」の印・雨雪判別・積雪や視程の表記は、CLI(mountain_weather.py)と
 * display.js に**同じものが2重に書かれている**。言語が違う以上この1組は消せないので、
 * 片方だけ直したときに落ちるよう、機械で突き合わせる。実際に「表示間隔を1時間に
 * 変えると濡れ注意の印が消える」という壊れ方をした前例がある。
 *
 * ver 2.46β までは index.html のインライン script から**目印で切り出して**評価していた。
 * display.js に出したのでその仕掛けは要らなくなった(切り出しは、index.html のどこに
 * コードを書けるかという制約も生んでいた)。
 *
 *     node scripts/test_display.js <入力JSON> <出力JSON>
 *
 * 単体で使うものではない。python scripts/test_display.py から呼ばれる。
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");

// display.js は logic.js の定数(WET_HYPO_WIND_B など)を参照するので、先に読ませる。
// require ではなくまとめて評価するのは、display.js がブラウザ用の素のスクリプトで、
// logic.js の値をグローバルとして受け取る前提だから。module を渡してやると
// display.js 末尾の module.exports が発火するので、公開する名前の一覧は display.js 側に1つだけ置ける。
function loadApi() {
  const logic = fs.readFileSync(path.join(ROOT, "logic.js"), "utf8");
  const disp = fs.readFileSync(path.join(ROOT, "display.js"), "utf8");
  return new Function("module", logic + "\n" + disp + "\nreturn module.exports;")({ exports: {} });
}

// ---- display.js が唯一の置き場であることの確認 ----
// (書き方は scripts/test_logic.js の logic.js 版と同じ。ズレたら両方直すこと)
function checkPages(D) {
  // ★ find 側は生成物(docs/find.html)ではなく**生成元**を見る(CLAUDE.md 規約6)。
  //   生成物を見ると、gen_find.py を直し忘れた状態でも通ってしまう。
  //   生成物が生成元と一致していることは check_mountains.py の [4/8] が別に見ている。
  const PAGES = [["index.html", /<script src="display\.js\?v=([^"]+)"/],
                 [path.join("scripts", "gen_find.py"), /<script src="\.\.\/display\.js\?v=([^"]+)"/]];
  // display.js へ移したもの。ページ側に再定義が残っていたら、そちらが後勝ちで使われる。
  const MOVED = ["timingLabel", "addPrecipNotes", "summarizeDailyWeather", "dayWeatherPhrase",
                 "singleCodePhrase", "wetWarn", "precipPhase", "snowCell", "visTxt",
                 "WMETA", "SAFETY_OVERRIDE", "PRECIP_CATS", "CAT_LABEL", "TOD_ORDER", "timeOfDay"];
  const fails = [];
  for (const [rel, re] of PAGES) {
    const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
    const m = src.match(re);
    if (!m) { fails.push(`${rel}: display.js の <script src> が見つかりません`); continue; }
    if (m[1] !== D.PW_DISPLAY_VER) {
      fails.push(`${rel}: display.js の ?v=${m[1]} が PW_DISPLAY_VER=${D.PW_DISPLAY_VER} と違います`
        + " (古い display.js がキャッシュに残り、文言だけ旧版になります)");
    }
    for (const n of MOVED) {
      if (new RegExp("(?:function|const|let|var)\\s+" + n + "\\s*[=({]").test(src)) {
        fails.push(`${rel}: ${n} が再定義されています (display.js の実装が上書きされます)`);
      }
    }
  }
  return fails;
}

// CLI は markdown なのでアイコンを持たない。比較できるよう、フレーズを文字列の列に落とす
// (「晴れ」「のち」「曇り」)。アイコンの有無は CLI/Web で違って当然の部分。
function phraseText(ph) {
  if (!ph) return null;
  return ph.map(s => (s.conn !== undefined ? s.conn : s.label));
}

const CALL = {
  timingLabel: (A, a) => A.timingLabel(a[0]),
  wetWarn: (A, a) => A.wetWarn(a[0], a[1], a[2]),
  precipPhase: (A, a) => A.precipPhase(a[0], a[1]),
  snowCell: (A, a) => A.snowCell(a[0], a[1]),
  visTxt: (A, a) => A.visTxt(a[0]),
  singleCodePhrase: (A, a) => phraseText(A.singleCodePhrase(a[0])),
  dayWeatherPhrase: (A, a) => phraseText(A.dayWeatherPhrase(a[0])),
  // Python は {日付: {...}} の辞書、JS は配列。どちらも時刻順なので列に揃える
  summarizeDailyWeather: (A, a) => A.summarizeDailyWeather(a[0], a[1])
    .map(d => [d.date, d.code, d.notes, phraseText(d.phrase)]),
};

const inPath = process.argv[2], outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error("usage: node scripts/test_display.js <入力JSON> <出力JSON>");
  process.exit(2);
}

const A = loadApi();
const pageFails = checkPages(A);
if (pageFails.length) {
  for (const m of pageFails) console.error("  NG " + m);
  process.exit(2);
}
const cases = JSON.parse(fs.readFileSync(inPath, "utf8"));
const out = {};
for (const name of Object.keys(cases)) {
  const call = CALL[name];
  if (!call) { console.error(`${name} の呼び出し方が定義されていません`); process.exit(2); }
  out[name] = cases[name].map(args => {
    const v = call(A, args);
    return v === undefined ? null : v;
  });
}
fs.writeFileSync(outPath, JSON.stringify(out), "utf8");
