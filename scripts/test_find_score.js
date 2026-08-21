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
//   A: 天気コードの表と代表天気(repWeather)まで
//   B: 稜線風の補間からスコア・足切り・ランクまで
const SLICES = [
  ["天気コードの表", "  var WMO={0:", "  var elRegion=document.getElementById"],
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

// logic.js を先に置く。find 側は interpWind / seasonTh / blockIndex / feelsLike / RANK /
// LEVELS / DEGRADED_LEVELS を logic.js から使う(複製しない約束になっている)。
const EXPOSE = ["score", "formalIndex", "ridgeAt", "repWeather",
                "rankOf", "isDangerous", "cutWind", "reasonLabel"];

function loadApi() {
  const logic = fs.readFileSync(path.join(ROOT, "logic.js"), "utf8");
  const body = logic + "\n" + slicePureSource() + "\nreturn {" + EXPOSE.join(",") + "};";
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
