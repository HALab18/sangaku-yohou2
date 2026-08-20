"use strict";
/* 表示まわり(Web側)の実行係。index.html を書き換えずに、中の関数だけを取り出して呼ぶ。
 *
 * 天気の文言・「濡れ注意」の印・雨雪判別・積雪表示は、CLI(mountain_weather.py)と
 * index.html に**同じものが2重に書かれている**。判定ロジック(logic.js)と違って
 * 一本化されていないので、片方だけ直すと静かにズレる。実際に「表示間隔を1時間に
 * 変えると濡れ注意の印が消える」という壊れ方をした前例がある。
 *
 * これらは index.html のインライン script の中にあり、Node から普通には読めない。
 * かといってページ全体を評価すると document を触る行で落ちる。そこで
 * **DOM に触らない範囲だけを目印で切り出して**関数として評価する。
 * index.html は1文字も変えない(アプリ側の版上げもリリースも要らない)。
 *
 *     node scripts/test_display.js <入力JSON> <出力JSON>
 *
 * 単体で使うものではない。python scripts/test_display.py から呼ばれる。
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");

// 切り出す範囲の目印。ここから下は DOM に触らない定数と純粋な関数だけが並んでいる。
// 目印が見つからない/複数ある場合はコードが動いた合図なので、黙って通さず止める
// (空振りしたまま「一致しました」と言うと、この仕掛け自体が嘘になる)。
const START = "const WET_PRECIP=";
const END = "// ---- APIアクセス";

function slicePureSource() {
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  for (const [label, mark] of [["開始", START], ["終了", END]]) {
    const n = html.split(mark).length - 1;
    if (n !== 1) {
      throw new Error(`index.html の切り出し${label}の目印「${mark}」が ${n} 箇所あります`
        + " (index.html の構成が変わった可能性があります。目印を updates してください)");
    }
  }
  return html.slice(html.indexOf(START), html.indexOf(END));
}

// logic.js を先に置くのは、切り出した側が WET_HYPO_WIND_B のような
// logic.js 側の定数を参照するため(module.exports の行は typeof で素通りする)。
const EXPOSE = ["timingLabel", "addPrecipNotes", "summarizeDailyWeather", "dayWeatherPhrase",
                "singleCodePhrase", "wetWarn", "precipPhase", "snowCell", "visTxt"];

function loadApi() {
  const logic = fs.readFileSync(path.join(ROOT, "logic.js"), "utf8");
  const body = logic + "\n" + slicePureSource()
    + "\nreturn {" + EXPOSE.join(",") + "};";
  return new Function(body)();
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
