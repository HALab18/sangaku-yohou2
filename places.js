"use strict";
/* PeakWeather 保存した地点 (座標指定の名前付き保存)
 *
 * 沢登りの入渓点・幕営地など「山名が無い場所」を、名前を付けて端末内に残す。
 * 入山の数日前から何度も見る使い方で、毎回座標を貼り直さずに済むようにするためのもの。
 *
 * 読み書きするのは docs/point.html (保存・削除) と index.html (候補欄から呼び出し)。
 * **キー名・上限・検証はこのファイルだけに置く**。2ページに写すと、片方だけ上限や
 * 検証を変えて「保存できたのに候補欄に出ない」形で食い違う。
 *
 * ★ 位置情報は原則として端末内にも残さない (recentAdd()・snapId() の除外は変えない)。
 *   ここは **利用者が「この地点を保存する」を選んだときだけ** 書く opt-in の枠で、
 *   利用規約 第6条にもその範囲で書いてある。黙って書く経路を足さないこと。
 *
 * 読み書きは gate.js の pwLoad/pwSave/pwDrop を通す (アクセス自体が例外を投げる端末がある)。
 * よって gate.js より後に読み込むこと。ES5 の範囲に留める (check_syntax.py が見る)。
 *
 * 保存形を変えるときはキーの v を上げること。PW_PLACES_VER を変えたら、読み込み側
 * (index.html・docs/point.html) の ?v= も同時に上げる (一致は check_consistency.py が見る)。 */

var PW_PLACES_VER = "251";
var PW_PLACES_KEY = "pw-places-v1",
    PW_PLACES_MAX = 5,
    PW_PLACES_NAME_MAX = 40;
/* 日本域。index.html の JP_LAT/JP_LON・docs/point.html の入力検証と同じ値にすること
 * (一致は check_consistency.py が見る)。域外の座標でも /v1/jma は 200 で全球モデルの値を返す */
var PW_PLACES_LAT = [20, 46.5], PW_PLACES_LON = [122, 154];

function pwPlaceValid(x) {
  return !!x && typeof x === "object"
    && typeof x.n === "string" && x.n.length > 0 && x.n.length <= PW_PLACES_NAME_MAX
    && typeof x.la === "number" && x.la >= PW_PLACES_LAT[0] && x.la <= PW_PLACES_LAT[1]
    && typeof x.lo === "number" && x.lo >= PW_PLACES_LON[0] && x.lo <= PW_PLACES_LON[1]
    && (x.e === null || (typeof x.e === "number" && x.e >= -500 && x.e <= 9500))
    && typeof x.t === "number" && isFinite(x.t);
}

/* 読み出し。全フィールドの型と範囲を見る。halab18.github.io は他プロジェクトと
 * オリジンを共有するうえ、ここで読んだ値は地点名として HTML に入り、座標は API に渡る。
 * 「自分で書いた形のはず」を前提にしない。不正な行は捨て、上限を超えたぶんも切る。 */
function placesLoad() {
  var a;
  try { a = JSON.parse(pwLoad(PW_PLACES_KEY) || "[]"); } catch (e) { return []; }
  if (!Array.isArray(a)) return [];
  var out = [], seen = {};
  for (var i = 0; i < a.length && out.length < PW_PLACES_MAX; i++) {
    var x = a[i];
    if (!pwPlaceValid(x) || seen["#" + x.n]) continue;
    seen["#" + x.n] = true;
    out.push({ n: x.n, la: x.la, lo: x.lo, e: x.e, t: x.t });
  }
  return out;
}

function placesSave(a) {
  if (a.length) pwSave(PW_PLACES_KEY, JSON.stringify(a)); else pwDrop(PW_PLACES_KEY);
}

/* 保存。戻り値: "added" / "updated" / "full" / "invalid"
 * 同じ名前は上書きする (並び順は保つ)。新しい名前で満杯なら **保存しない**。
 * 意図して残した地点を、黙って押し出して消すことはしない。 */
function placesPut(p) {
  var name = p && typeof p.n === "string" ? p.n.trim() : "";
  var rec = { n: name, la: p && p.la, lo: p && p.lo,
              e: p && p.e != null ? p.e : null, t: Date.now() };
  if (!pwPlaceValid(rec)) return "invalid";
  var a = placesLoad();
  for (var i = 0; i < a.length; i++) {
    if (a[i].n === name) { a[i] = rec; placesSave(a); return "updated"; }
  }
  if (a.length >= PW_PLACES_MAX) return "full";
  a.push(rec);
  placesSave(a);
  return "added";
}

function placesRemove(name) {
  var a = placesLoad(), b = [];
  for (var i = 0; i < a.length; i++) if (a[i].n !== name) b.push(a[i]);
  placesSave(b);
}

/* 予報ページ(index.html)へ渡すハッシュの座標部分。"緯度,経度" または "緯度,経度,標高"。
 * index.html の applyHash() が読む形と同じにすること */
function placeHashKey(p) {
  return p.la + "," + p.lo + (p.e != null ? "," + p.e : "");
}
