"use strict";
/* 判定ロジック(Web側)を乱数ケース表で回す実行係。
 *
 * 入力表は scripts/test_logic_fuzz.py が作って渡す(生成を両言語に書くと、生成側がズレた
 * ときに「同じ入力で比べている」前提そのものが崩れるため、生成は Python 側の1箇所だけ)。
 * このスクリプトは受け取った引数どおりに logic.js を呼び、結果を JSON で書き出すだけ。
 *
 *     node scripts/test_logic_fuzz.js <入力JSON> <出力JSON>
 *
 * 単体で使うものではない。python scripts/test_logic_fuzz.py から呼ばれる。
 */
const fs = require("fs");
const path = require("path");

const L = require(path.join(__dirname, "..", "logic.js"));

const FUNCS = {
  seasonTh: L.seasonTh, blockIndex: L.blockIndex, feelsLike: L.feelsLike,
  viewScore: L.viewScore, interpWind: L.interpWind, sumOrNull: L.sumOrNull,
  lightningRisk: L.lightningRisk, eveThunder: L.eveThunder, modelAgree: L.modelAgree
};

const inPath = process.argv[2], outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error("usage: node scripts/test_logic_fuzz.js <入力JSON> <出力JSON>");
  process.exit(2);
}

const cases = JSON.parse(fs.readFileSync(inPath, "utf8"));
const out = {};
for (const name of Object.keys(cases)) {
  const fn = FUNCS[name];
  if (!fn) { console.error(`logic.js に ${name}() がありません`); process.exit(2); }
  // undefined は JSON に載らず「キーごと消える」ので、null に寄せてから積む
  // (Python 側は「値が無い」を None として比較するため、消えると欠測と区別できなくなる)
  out[name] = cases[name].map(args => {
    const v = fn.apply(null, args);
    return v === undefined ? null : v;
  });
}
fs.writeFileSync(outPath, JSON.stringify(out), "utf8");
