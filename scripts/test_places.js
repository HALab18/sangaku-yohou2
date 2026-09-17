"use strict";
/* 保存した地点 (places.js) のテスト。
 *
 *     node scripts/test_places.js
 *
 * 見ること:
 *   - 読み出しが「自分で書いた形」を前提にしないこと。halab18.github.io は他プロジェクトと
 *     オリジンを共有し、読んだ地点名は HTML に入り、座標は API に渡る。型違い・域外・重複は捨てる
 *   - 上限(5件)で **押し出さずに断る** こと。意図して保存した地点が黙って消えるのが最悪の壊れ方
 *   - 同名は上書き、削除、localStorage が例外を投げる端末でも落ちないこと
 *   - 保存した座標が、index.html の applyHash() が読める形のハッシュになること
 *   - 読み込み側 2ページが gate.js の後に places.js を読み、関数を再定義していないこと
 */
const fs = require("fs");
const path = require("path");
const { makeStorage, makeChecker } = require("./test_stubs");

const ROOT = path.join(__dirname, "..");
const read = rel => fs.readFileSync(path.join(ROOT, rel), "utf8");

const C = makeChecker();
const ok = C.ok.bind(C), eq = C.eq.bind(C);

const EXPOSE = ["placesLoad", "placesPut", "placesRemove", "placeHashKey", "pwPlaceValid",
  "PW_PLACES_KEY", "PW_PLACES_MAX", "PW_PLACES_VER", "pwLoad", "pwSave"];

function newEnv(storage, now) {
  const env = {
    localStorage: storage || makeStorage(),
    sessionStorage: makeStorage(),
    location: { protocol: "https:" },
    Date: { now: () => (now == null ? 1000 : now) },
  };
  const body =
    "var localStorage=__env.localStorage, sessionStorage=__env.sessionStorage,"
    + " location=__env.location, Date=__env.Date;\n"
    + read("gate.js") + "\n" + read("places.js")
    + "\nreturn {" + EXPOSE.join(",") + "};";
  return { api: new Function("__env", body)(env), env };
}

const P = (n, la, lo, e) => ({ n, la: la == null ? 36.4 : la, lo: lo == null ? 137.7 : lo, e: e === undefined ? null : e });

/* 1. 保存して読み戻せる */
{
  const { api } = newEnv();
  eq(api.placesLoad(), [], "何も保存していないのに地点がある");
  eq(api.placesPut(P("入渓点", 36.4067, 137.7127, 1450)), "added", "保存の戻り値");
  eq(api.placesLoad().map(x => [x.n, x.la, x.lo, x.e]), [["入渓点", 36.4067, 137.7127, 1450]],
    "保存した地点を読み戻せない");
  eq(api.placesPut(P("  出合  ")), "added", "前後の空白つきの名前");
  eq(api.placesLoad()[1].n, "出合", "地点名の前後の空白が落ちていない");
}

/* 2. ★ 上限では押し出さずに断る */
{
  const { api } = newEnv();
  for (let i = 1; i <= api.PW_PLACES_MAX; i++) api.placesPut(P("地点" + i));
  eq(api.placesLoad().length, 5, "上限の5件まで保存できない");
  eq(api.placesPut(P("6件目")), "full", "満杯なのに 'full' を返さない");
  eq(api.placesLoad().map(x => x.n), ["地点1", "地点2", "地点3", "地点4", "地点5"],
    "満杯のときに既存の地点が押し出された/書き換わった (意図して保存した地点が黙って消える)");
  // 満杯でも同名なら上書きできる
  eq(api.placesPut(P("地点3", 35.1, 138.2, 900)), "updated", "満杯のとき同名の上書きが断られた");
  const x = api.placesLoad()[2];
  eq([x.n, x.la, x.lo, x.e], ["地点3", 35.1, 138.2, 900], "同名の上書きで座標が更新されない/位置が動いた");
  eq(api.placesLoad().length, 5, "同名の上書きで件数が増えた");
}

/* 3. 削除 */
{
  const { api, env } = newEnv();
  api.placesPut(P("A")); api.placesPut(P("B"));
  api.placesRemove("A");
  eq(api.placesLoad().map(x => x.n), ["B"], "削除できない");
  api.placesRemove("B");
  ok(env.localStorage.getItem(api.PW_PLACES_KEY) === null, "全件削除してもキーが残っている");
  api.placesRemove("存在しない");
  eq(api.placesLoad(), [], "存在しない名前の削除で壊れた");
}

/* 4. 保存しない入力 */
{
  const { api } = newEnv();
  eq(api.placesPut(P("")), "invalid", "空の地点名を保存した");
  eq(api.placesPut(P("   ")), "invalid", "空白だけの地点名を保存した");
  eq(api.placesPut(P("x".repeat(41))), "invalid", "41文字の地点名を保存した");
  eq(api.placesPut(P("x".repeat(40))), "added", "40文字の地点名が保存できない");
  eq(api.placesPut(P("ハワイ", 21.3, -157.8)), "invalid",
    "日本域外の座標を保存した (/v1/jma は域外でも全球モデルの値を返す)");
  eq(api.placesPut(P("北限外", 46.6, 140)), "invalid", "北限外の座標を保存した");
  eq(api.placesPut(P("東限外", 35, 154.1)), "invalid", "東限外の座標を保存した");
  eq(api.placesPut(P("標高異常", 35, 138, 9600)), "invalid", "範囲外の標高を保存した");
  eq(api.placesPut(P("標高NaN", 35, 138, NaN)), "invalid", "NaN の標高を保存した");
  eq(api.placesPut({ n: "文字の座標", la: "35", lo: "138", e: null }), "invalid", "文字列の座標を保存した");
  eq(api.placesPut(null), "invalid", "null で落ちた/保存した");
  eq(api.placesLoad().length, 1, "保存しないはずの入力が残っている");
}

/* 5. ★ 読み出しは書かれた値を信用しない */
{
  const st = makeStorage();
  const good = { n: "良", la: 36, lo: 138, e: null, t: 1 };
  st.setItem("pw-places-v1", JSON.stringify([
    good,
    { n: "<img src=x onerror=alert(1)>", la: 36, lo: 138, e: 1, t: 1 },   // 形は正しい(表示側で esc)
    { n: 123, la: 36, lo: 138, e: null, t: 1 },
    { n: "域外", la: 10, lo: 138, e: null, t: 1 },
    { n: "座標が文字", la: "36", lo: 138, e: null, t: 1 },
    { n: "標高が文字", la: 36, lo: 138, e: "1000", t: 1 },
    { n: "時刻なし", la: 36, lo: 138, e: null },
    { n: "良", la: 35, lo: 139, e: null, t: 2 },                           // 重複
    null, "文字列", [1, 2],
  ]));
  const { api } = newEnv(st);
  eq(api.placesLoad().map(x => x.n), ["良", "<img src=x onerror=alert(1)>"],
    "不正な行を捨てていない/正しい行まで捨てた");
  const extra = makeStorage();
  extra.setItem("pw-places-v1", JSON.stringify([{ n: "余計", la: 36, lo: 138, e: null, t: 1, html: "<b>" }]));
  eq(Object.keys(newEnv(extra).api.placesLoad()[0]).sort(), ["e", "la", "lo", "n", "t"],
    "読み出しが余計なフィールドを素通しにしている");
  for (const raw of ["{", "null", "{}", "123", '"x"']) {
    const s = makeStorage(); s.setItem("pw-places-v1", raw);
    eq(newEnv(s).api.placesLoad(), [], `壊れた保存値 ${raw} で空にならない`);
  }
  const many = makeStorage();
  many.setItem("pw-places-v1", JSON.stringify(Array.from({ length: 9 }, (_, i) => ({ n: "m" + i, la: 36, lo: 138, e: null, t: 1 }))));
  eq(newEnv(many).api.placesLoad().length, 5, "上限を超えて書かれた保存値を切っていない");
}

/* 6. localStorage が例外を投げる端末でも落ちない(そのタブの間はメモリで使える) */
{
  const { api } = newEnv(makeStorage({ secError: true }));
  let threw = null;
  try {
    eq(api.placesPut(P("圏外端末")), "added", "保存できない端末で保存の戻り値が変");
    eq(api.placesLoad().map(x => x.n), ["圏外端末"], "保存できない端末で、そのタブの間も読めない");
    api.placesRemove("圏外端末");
    eq(api.placesLoad(), [], "保存できない端末で削除が効かない");
  } catch (e) { threw = e; }
  ok(!threw, `localStorage が例外を投げる端末で落ちた: ${threw && threw.message}`);
}

/* 7. 保存した座標が index.html の applyHash() で座標指定として読めること */
{
  const src = read("index.html");
  const m = src.match(/const coordM=nm\.match\((\/\^.*?\$\/)\);/);
  ok(!!m, "index.html から座標指定のハッシュの正規表現を切り出せません (コードが動いた可能性があります)");
  if (m) {
    const re = new Function("return " + m[1])();
    const { api } = newEnv();
    for (const [p, want] of [
      [P("a", 36.4067, 137.7127, null), ["36.4067", "137.7127", undefined]],
      [P("b", 36.4067, 137.7127, 2899.5), ["36.4067", "137.7127", "2899.5"]],
      [P("c", 24.5, 124, -3), ["24.5", "124", "-3"]],
    ]) {
      const key = api.placeHashKey(p);
      const g = key.match(re);
      ok(!!g, `保存した地点のハッシュ ${key} を index.html が座標指定として読めない`);
      if (g) eq([g[1], g[2], g[3]], want, `ハッシュ ${key} の読み取り結果`);
    }
  }
}

/* 8. 読み込み側: gate.js の後に places.js を読む / ?v= が版と一致 / 関数を再定義しない */
{
  const { api } = newEnv();
  for (const rel of ["index.html", "docs/point.html"]) {
    const s = read(rel);
    const g = s.search(/<script src="[^"]*gate\.js\?v=/), p = s.search(/<script src="[^"]*places\.js\?v=/);
    ok(p >= 0, `${rel}: places.js を読み込んでいない`);
    ok(g >= 0 && p > g, `${rel}: places.js が gate.js より前に読まれている (pwLoad が未定義になる)`);
    const v = (s.match(/places\.js\?v=([^"]+)"/) || [])[1];
    eq(v, api.PW_PLACES_VER, `${rel}: places.js?v= が PW_PLACES_VER と違う (旧版がキャッシュに残る)`);
    for (const fn of ["placesLoad", "placesPut", "placesRemove", "placeHashKey", "pwPlaceValid"]) {
      ok(!new RegExp(`function\\s+${fn}\\s*\\(|(const|let|var)\\s+${fn}\\s*=`).test(s),
        `${rel}: ${fn} を再定義している (後勝ちで places.js の修正が反映されない)`);
    }
    ok(!/pw-places-v1/.test(s), `${rel}: 保存キーを直接書いている (places.js を通すこと)`);
  }
  // 位置情報を黙って残す経路を作らない: point.html の保存は「保存する」チェックの内側だけ
  const pt = read("docs/point.html");
  const calls = pt.split("placesPut(").length - 1;
  eq(calls, 1, "docs/point.html の placesPut 呼び出しの数");
  ok(/if\(PLACES_OK&&document\.getElementById\("keep"\)\.checked\)\{[\s\S]{0,400}placesPut\(/.test(pt),
    "docs/point.html の保存が「この地点を保存する」のチェックの内側にない (位置情報を黙って残す)");
  ok(!/placesPut\(/.test(read("index.html")), "index.html から地点を保存している (保存は座標指定ページで明示的に行う)");
  // 候補欄の📴印。行を組み立てる式より後で saved を宣言すると、候補欄を開くたびに
  // ReferenceError で候補が一切出なくなる(2.51β の作業中に実機で起きた。DOM を持たない
  // テストでは描画を通せないので、宣言と使用の順序だけを見る)
  {
    const ix = read("index.html");
    const decl = ix.indexOf("const saved="), use = ix.indexOf('saved.has("p:"+p.n)');
    ok(decl >= 0 && use >= 0, "index.html の候補欄から保存地点の📴印の判定が見つかりません (コードが動いた可能性があります)");
    ok(decl < use, "index.html の候補欄で saved を使ってから宣言している (候補欄が ReferenceError で開かない)");
  }
}

/* 9. 候補欄から選んだ地点が、山名欄にも入って検索し直せること
      (DOM を持たないテストなので、置き場所と順序だけを見る) */
{
  const ix = read("index.html");
  ok(/if\(place\)\{\s*\n\s*document\.getElementById\("mname"\)\.value=customLabel;/.test(ix),
    "index.html: 保存した地点のときに山名欄へ地点名を入れていない (どの地点を見ているか分からない)");
  // 保存していない座標指定("指定地点（松本市）")を欄に入れると、そのまま押したとき
  // 地名検索に流れて失敗する。名前を入れるのは place のときだけ
  ok(!/const name=customLabel\|\|[\s\S]{0,200}getElementById\("mname"\)\.value=name/.test(ix),
    "index.html: 保存していない座標指定でも山名欄に名前を入れている");
  const db = ix.indexOf("let hits=resolveLocal(name)"),
        pl = ix.indexOf("if(p)return placeGo(p);"),
        geo = ix.indexOf("内蔵DBに無いため地名検索中…");
  ok(pl >= 0, "index.html: 山名欄に地点名が入ったまま送信されたときの分岐が無い"
    + " (候補から選んだあと日付を変えて押すと「見つかりません」になる)");
  ok(db >= 0 && geo >= 0 && db < pl && pl < geo,
    "index.html: 保存した地点の分岐が内蔵DB照合の前、または地名検索の後にある"
    + " (同名の山が地点に食われる/圏外で地名検索に流れる)");
}

/* 10. 候補を選んだ瞬間には検索しない(開始日・表示間隔を選べなくなる)。
      行の選択は入力欄に入れるだけで、実行は送信側の分岐に任せる */
{
  const ix = read("index.html");
  const a = ix.indexOf("function activate(el){"), b = ix.indexOf("// 消去ボタン: 空にして候補欄を");
  ok(a >= 0 && b > a, "index.html: 候補行の選択処理(activate)を切り出せません (コードが動いた可能性があります)");
  if (a >= 0 && b > a) {
    ok(!/placeGo\(/.test(ix.slice(a, b)),
      "index.html: 候補行を選んだ時点で予報を開いている (開始日・表示間隔を選ぶ前に走る)");
  }
}

C.report("保存した地点 (places.js)");
