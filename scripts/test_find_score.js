"use strict";
/* 山さがし(docs/find.html)の日和スコアの実行係。
 *
 * docs/find.html は自動生成物なので、テストは**生成元の scripts/gen_find.py** に対して回す
 * (CLAUDE.md 規約6。生成物を見てしまうと、生成元を直し忘れた状態でも通ってしまう)。
 * gen_find.py の中の JS から、DOM に触らない範囲だけを目印で切り出して評価する。
 * gen_find.py は1文字も書き換えない。
 *
 *     node scripts/test_find_score.js <入力JSON> <出力JSON>
 *
 * 単体で使うものではない。python scripts/test_find_score.py から呼ばれる。
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");

// 切り出す2つの範囲。間(DOM の組み立てとイベント登録)は挟まないので飛ばす。
//   A: 代表天気(repWeather)と天気列の表示判定まで(語彙は display.js から来る)
//   B: 稜線風の補間からスコア・足切り・ランクまで
const SLICES = [
  ["代表天気", "  var CAT_ICON={", "  var elRegion=document.getElementById"],
  ["スコア本体", "  var DEGRADED_LEVEL_IDX=", "  function brkHtml("],
];

function slicePureSource() {
  const src = fs.readFileSync(path.join(ROOT, "scripts", "gen_find.py"), "utf8");
  let out = "";
  for (const [label, start, end] of SLICES) {
    for (const [what, mark] of [["開始", start], ["終了", end]]) {
      const n = src.split(mark).length - 1;
      if (n !== 1) {
        throw new Error(`gen_find.py の「${label}」の切り出し${what}の目印が ${n} 箇所あります`
          + ` (目印: ${mark.trim()})。gen_find.py の構成が変わった可能性があります`);
      }
    }
    const i = src.indexOf(start), j = src.indexOf(end);
    if (j < i) throw new Error(`gen_find.py の「${label}」で終了の目印が開始より前にあります`);
    out += src.slice(i, j) + "\n";
  }
  return out;
}

// logic.js と display.js を先に置く。find 側は
//   logic.js   … interpWind / seasonTh / blockIndex / feelsLike / RANK / LEVELS / DEGRADED_LEVELS
//   display.js … WMO / wcode / WMETA / WCAT / WSEV / SAFETY_OVERRIDE / PRECIP_CATS /
//                CAT_LABEL / TOD_ORDER / timeOfDay / timingLabel
// を使う(どちらも複製しない約束。ver 2.46β までは後者の写しが find 側にも丸ごとあった)。
const EXPOSE = ["score", "formalIndex", "ridgeAt", "repWeather",
                "rankOf", "isDangerous", "cutWind", "reasonLabel"];

function loadApi() {
  const logic = fs.readFileSync(path.join(ROOT, "logic.js"), "utf8");
  const disp = fs.readFileSync(path.join(ROOT, "display.js"), "utf8");
  const body = logic + "\n" + disp + "\n" + slicePureSource()
    + "\nreturn {" + EXPOSE.join(",") + "};";
  return new Function(body)();
}

const inPath = process.argv[2], outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error("usage: node scripts/test_find_score.js <入力JSON> <出力JSON>");
  process.exit(2);
}

const A = loadApi();
const cases = JSON.parse(fs.readFileSync(inPath, "utf8"));
const out = {};
for (const name of Object.keys(cases)) {
  if (!A[name]) { console.error(`gen_find.py に ${name}() がありません`); process.exit(2); }
  out[name] = cases[name].map(args => {
    const v = A[name].apply(null, args);
    return v === undefined ? null : v;
  });
}
fs.writeFileSync(outPath, JSON.stringify(out), "utf8");
