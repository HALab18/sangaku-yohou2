# -*- coding: utf-8 -*-
"""index.html の MOUNTAINS 配列から docs/find.html (コンディション横断検索) を生成する。

「その日に天気の良さそうな山を、まず見つけたい」という逆引きの入口。
エリア(9地方)+ 任意で県 + 単日 を指定 → その範囲の山を Open-Meteo の気象庁モデルから
バッチ取得し、簡易スコア(晴天度を最重視)でランキング表示。行をタップすると
既存の詳細予報 (../index.html#山名/日付) が開く。

対象は今日〜6日先の7日間(FIND_DAYS)。気象庁モデルは天気・降水・稜線風・積雪を11日ぶん
配信するが、スコアの主要素である日照(sunshine_duration)だけは MSM 期間ぶんしか来ず、
4日目以降は 7:00〜15:59 が丸ごと欠測になる。そこで**日照だけ**を /v1/forecast
(ベストマッチ合成)から別名で補完し、期間を7日に延ばした。1〜3日目は気象庁モデルの
日照を優先する(基本はMSM、足りないところだけ他モデル)。補完した日照は表に * 印を付ける。

降水確率は気象庁モデルに無いので別モデルから補完するが、**表示だけで採点には使わない**。
モデルが違う値をスコアに混ぜると、スコアの意味が説明しづらくなるため。
(日照は「無ければスコアが成立しない主要素」なので、こちらは採点に使う。代わりに
 出どころが違うことを * 印と注記で開示する。)

山岳DBを更新したら再実行して同期する:
    python scripts/gen_find.py

判定ロジックについて:
  この簡易スコアは「横断検索用のふるい」であり、CLI/Web 共通の A/B/C 正式判定
  (mountain_weather.py / index.html) とは別物。正式判定には手を触れない。
"""
import json
from pathlib import Path

from gen_mountain_list import REGIONS, load_mountains

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "find.html"


def build_mountain_json(mountains):
    """[name,yomi,pref,lat,lon,elev] → [{n,pref,region,lat,lon,el}] のコンパクトJSON。"""
    pref2region = {p: name for name, prefs in REGIONS for p in prefs}
    rows = []
    for name, _yomi, pref, lat, lon, elev in mountains:
        first_pref = pref.split("・")[0]
        region = pref2region.get(first_pref)
        if region is None:
            raise SystemExit(f"地域未定義の都道府県: {first_pref} ({name})")
        rows.append({
            "n": name, "pref": pref, "reg": region,
            "lat": round(lat, 5), "lon": round(lon, 5), "el": int(elev),
        })
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>天気の良い山をさがす — PeakWeather</title>
<meta name="description" content="エリアと日付を指定すると、その日にコンディションの良さそうな山を晴天度でランキング表示。気になる山をタップするとその山頂・稜線の詳しい気象予報へ。">
<link rel="icon" type="image/png" href="../icons/favicon-32.png">
<meta name="theme-color" content="#1e2d4a">
<!-- このファイルは scripts/gen_find.py により index.html から自動生成されます。直接編集しないでください
     (直接編集すると次回の再生成で消えます。修正は必ず scripts/gen_find.py 側に入れること) -->
<script src="../gate.js?v=2026b"></script>
<!-- 登山指数 A/B/C の判定ロジック。index.html と共有する唯一の実装。
     ?v= は logic.js の PW_LOGIC_VER と同じ値にする(古い版がキャッシュに残ると
     「画面は新しいのに判定だけ旧版」という気づけない状態になる)。 -->
<script src="../logic.js?v=235"></script>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-B4FYN1EJ2S"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'G-B4FYN1EJ2S');
</script>
<style>
/* --muted: 補足文字の共通色(index.html と同じ値)。白 6.2:1 / 表の偶数行 5.5:1 /
   ページ背景 5.7:1 でいずれも WCAG AA(4.5:1) を満たす。
   以前の #8a94a8 は 3.05:1、footer の #888 は 3.27:1 で未達だった
   (順位・減点の内訳・日照の * 印は実データなので、薄すぎると読めない) */
:root{--muted:#5a6270;
  --night:#1e2d4a;--slate:#48608c;--sky:#5b87c5;--link:#2b5fa3;
  --btn:#4276b5;--bg:#f4f6f9;--line:#dee4ee;--field:#c9d2e0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:#222;
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic UI","Meiryo",system-ui,sans-serif;
  font-size:14px;line-height:1.6}

header{background:var(--night);color:#fff;text-align:center;padding:30px 20px 0;position:relative}
header .back{position:absolute;left:14px;top:12px;color:#c9d3e5;font-size:.82em;text-decoration:none}
header .back:hover{color:#fff}
header h1{margin:0;font-size:1.45em;font-weight:800;letter-spacing:.04em}
header .sub{margin:8px 0 0;font-size:.85em;color:#c9d3e5}
.ridge{display:block;width:100%;height:44px;margin-top:18px}

main{max-width:860px;margin:0 auto;padding:18px 14px 8px}

.searchcard{background:#fff;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 12px rgba(30,45,74,.10)}
.searchcard .row{display:flex;flex-wrap:wrap;gap:12px}
/* min-width:0 は flex 子要素のデフォルト(auto)を無効にして親幅を尊重させる */
.searchcard label{display:flex;flex-direction:column;gap:5px;font-size:.82em;font-weight:600;color:#556;flex:1 1 150px;min-width:0}
.searchcard select,.searchcard input{font-size:16px;padding:11px 12px;border:1.5px solid var(--field);border-radius:10px;
  background:#fff;width:100%;max-width:100%;min-width:0;font-family:inherit}
.searchcard select:focus,.searchcard input:focus{outline:2px solid var(--night);outline-offset:1px}
.searchcard .go{margin-top:12px;width:100%;background:var(--btn);color:#fff;border:0;border-radius:10px;
  padding:13px;font-size:1.02em;font-weight:700;font-family:inherit;cursor:pointer}
.searchcard .go:hover{background:#3768a3}
.searchcard .go:disabled{background:#9fb2cd;cursor:default}
.hint{margin:10px 0 0;font-size:.8em;color:#5b6b8a}

#status{margin:14px 0 0;font-size:.9em;font-weight:600;min-height:1.2em}
#status.err{color:#b3261e}

.notice{background:#edf2f9;border-left:5px solid var(--slate);color:#44506b;padding:10px 12px;
  border-radius:0 6px 6px 0;margin:16px 0;font-size:.86em}
.notice a{color:var(--link)}

/* .tbl 自身をスクロールコンテナ(max-height + overflow)にして、内部の th{position:sticky} が
   ページ縦スクロールではなく .tbl 内スクロールで効くようにする(index.htmlと同じ方式)。
   overflow-x:auto だけだと position:sticky はページ全体に対しては効かない。 */
.tbl{max-height:75vh;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;margin:10px 0 4px}
/* 横スクロールの手がかり(index.html と同じ方式)。実測(375px)でこの表は 509px あり、
   稜線風・降水確率・降水量が画面外に出る。手がかりが無いとそもそも横に送られない。
   ★ 背景グラデーション方式は使えない: td が不透明(#fff / 偶数行)なのでセルに隠れる。
     mask で描画結果ごとフェードさせる。sticky(ヘッダ行・左2列)は壊れないことを実測で確認済み。 */
.tbl.xscroll{-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 28px),transparent);
  mask-image:linear-gradient(to right,#000 calc(100% - 28px),transparent)}
.tbl.xscroll.at-end{-webkit-mask-image:none;mask-image:none}
table{border-collapse:collapse;width:100%}
/* ヘッダはページ縦スクロール時に画面上端に固定し、どの列を見ているか分かるようにする(index.htmlと同じ挙動) */
th{background:var(--slate);color:#fff;padding:6px 8px;font-weight:600;font-size:.86em;white-space:nowrap;position:sticky;top:0;z-index:2}
td{padding:8px;border-bottom:1px solid var(--line);text-align:center;background:#fff;white-space:nowrap}
/* 数値だけの列(日照・気温・稜線風・降水確率・降水量)は右揃え+tabular-numsで桁を揃える。
   見出し(th)も同じ寄せにして、値と見出しがずれないようにする。 */
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:nth-child(even) td{background:#eef1f6}
/* 山名列: max-width を超える極端に長い山名(カムイエクウチカウシヤマ 等)は改行を許容する。
   word-break:keep-all を外し、overflow-wrap:anywhere で任意位置で折り返せるようにする。
   短い山名は max-width に収まるため改行されない。td共通の white-space:nowrap は normal に戻す。 */
td.nm{text-align:left;white-space:normal;min-width:6em;max-width:11em;overflow-wrap:anywhere;line-break:anywhere}
/* 山名セル内の右端にスコアを配置(山名の脇に常に見える)。山名が2行になっても位置がブレないよう
   align-items:flex-start にして「常に1行目の高さの右上」に固定する。 */
td.nm .nmrow{display:flex;justify-content:space-between;align-items:flex-start;gap:6px}
td.nm .scb{font-weight:800;font-size:1.05em;font-variant-numeric:tabular-nums;flex-shrink:0;line-height:1.2}
/* スコアの色は A/B/C ランクに合わせて色分け (find-score.html の閾値と一致):
   A(70-100)=緑 / B(45-69)=橙 / C(0-44)=赤。視認性重視で濃いめの色を選ぶ。 */
/* 正式指数 A/B/C のバッジ。index.html の .b-a/.b-b/.b-c と同じ配色にして、
   詳細ページと同じ意味の値だと分かるようにする。 */
.abc{display:inline-block;min-width:1.5em;text-align:center;border-radius:4px;
     padding:1px 4px;font-weight:800;font-size:.9em}
.abc-a{background:#d8efe1;color:#1c5b3f}
.abc-b{background:#fdeec9;color:#7b5e00}
.abc-c{background:#f9d9cf;color:#a03415}
.abcr{display:block;font-size:.72em;color:#a03415;font-weight:700;margin-top:2px;white-space:nowrap}
/* 一覧の初期表示を上位FIND_HEAD件に畳む開閉ボタン(index.htmlのwk-toggleと同じ考え方) */
.find-more[hidden]{display:none}
.find-toggle{width:100%;padding:9px;font-size:.92em;font-weight:600;border-radius:10px;
  margin:2px 0 14px;background:#fff;color:var(--link);border:1.5px solid var(--line)}
.find-toggle:hover{background:#eef2f8}
.find-toggle::after{content:"▾";margin-left:6px;display:inline-block;transition:transform .15s}
.find-toggle[aria-expanded="true"]::after{transform:rotate(180deg)}
td.nm .scb.rank-a{color:#1f7a34}
td.nm .scb.rank-b{color:#b26b00}
td.nm .scb.rank-c{color:#b3261e}
/* スマホで横スクロール時にどの山を見ているか分かるよう、ランク列(#)と山名列を左端に固定する
   (index.htmlの日付列 sticky-left と同じ考え方)。ランク列を固定幅にして山名列の left オフセット
   を予測可能にした。角の交差セル(th)は元々 z-index:2、tdは z-index:1 で thの下に潜る。 */
th:first-child,td.rank{width:34px;min-width:34px;max-width:34px;padding-left:6px;padding-right:6px}
th:first-child,td.rank{position:sticky;left:0}
th:nth-child(2),td.nm{position:sticky;left:34px}
td.rank,td.nm{z-index:1}
/* sticky-left の角セル(th)は sticky-top の他ヘッダ(z-index:2)より前面に置き、
   横スクロール時に天気以降の列ヘッダが山名/ランク列の下に潜るようにする(index.htmlと同方式)。 */
th:first-child,th:nth-child(2){z-index:3}
/* 偶数行の背景色が透けないよう明示 (sticky で親の背景が引き継がれないため) */
tr:nth-child(even) td.rank,tr:nth-child(even) td.nm{background:#eef1f6}
/* 指数Cの行は背景色で警告する(スコア順位に関わらず要注意〜不適であることに気づけるように)。
   td個別に背景を敷く tr:nth-child(even) td / sticky列の背景指定と同じ specificity になるよう
   td.rank/td.nm も明示し、上記2つのルールより後方に置くことで確実に上書きする */
tr.row-c td{background:#fbe0da}
tr.row-c td.rank,tr.row-c td.nm{background:#fbe0da}
/* 山名列の右端に境界線 (横スクロール時に固定範囲の右端が視認しやすい) */
th:nth-child(2),td.nm{box-shadow:inset -1px 0 0 var(--line)}
td.nm a{color:var(--link);font-weight:700;text-decoration:none}
td.nm a:hover{text-decoration:underline}
td.nm small{display:block;color:var(--muted);font-size:.82em;font-weight:400}
/* スコアの減点内訳。スコアの数字だけでは「何で引かれたか」が分からず、隣の列を突き合わせる
   必要があった。県・標高の行より一段弱い色にして、山名の読み取りを邪魔しないようにする。 */
td.nm small.brk{color:#a2708a;font-size:.78em;letter-spacing:.02em}
/* 行全体をクリック可能に(index.htmlの見通し表の行ジャンプと挙動を統一)。
   tr自体にはtabindexを付けない: 山名の<a>が既にキーボードでフォーカスできる本物のリンクで、
   行にも付けると同じ行でTab停止が2回になってしまう(マウス/タッチだけの利便性強化)。
   sticky列(td.rank/td.nm)は個別の背景色指定があるため明示的に上書きする */
tr[data-href]{cursor:pointer}
tr[data-href]:hover td,tr[data-href]:hover td.rank,tr[data-href]:hover td.nm{background:#dde6f2}
/* 結果ブロックの見出しと注記 (メイン表 / 足切り表を分ける) */
h3.results-h{margin:18px 0 4px;font-size:1em;color:var(--night);font-weight:700}
h3.results-h.caution{color:#b26b00}
h3.results-h .rcount{color:#556;font-weight:500;font-size:.9em;margin-left:6px}
.rnote{margin:4px 0 0;font-size:.82em;color:#5b6b8a}
.rnote.caution{color:#b26b00;background:#fff8e6;border-left:4px solid #b26b00;padding:6px 10px;border-radius:0 4px 4px 0}
.rnote a{color:var(--link)}
/* 表の下に置く「各列の意味」凡例。ユーザーが「気温が2つあるが説明がない」等で
   迷わないよう、列ごとの意味と単位・対象時間帯を短い1行で列挙する。
   ★ 既定で畳む。実測(375px)でこの凡例は 631px あり、表(509px)より背が高かった。
     毎回読むものではないので、開きたい人だけ開く形にする(index.html の「表の見方」と同じ)。 */
.legend{background:#fff;border:1px solid var(--line);border-radius:8px;margin:14px 0 6px;font-size:.85em;color:#44506b}
.legend>summary{cursor:pointer;padding:10px 14px;font-size:.95em;color:var(--night);
  font-weight:700;user-select:none}
.legend .tbody{padding:0 14px 12px}
.legend dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:4px 10px}
.legend dt{font-weight:700;color:var(--night);white-space:nowrap}
.legend dd{margin:0}
.legend .rk{display:inline-block;padding:1px 7px;border-radius:10px;font-weight:700;font-size:.85em;margin-right:4px}
.legend .rk-a{background:#d8efe1;color:#1c5b3f}
.legend .rk-b{background:#fdeec9;color:#7b5e00}
.legend .rk-c{background:#f9d9cf;color:#a03415}
/* 足切り表: 見出し帯をオレンジ系にして通常表と視覚的に差別化 */
.tbl.caution table th{background:#b26b00}
td.reason{color:#b26b00;font-weight:700;font-size:.85em;white-space:nowrap;text-align:left}
/* 天気アイコン: index.html と同じSVG(#wx-sun 等)を参照。emoji のOS依存表示ズレを回避 */
.wxico{width:1.9em;height:1.9em;display:block;margin:0 auto 2px}
.wxlbl{color:#556;font-size:.82em}
/* 代表天気から降格した短時間の降水の注記 (index.html の .wxnote と同趣旨。表幅が狭いので一段小さく) */
.wxnote{display:block;font-size:.72em;color:var(--muted);margin-top:2px;line-height:1.25}
/* 日照が気象庁モデル外(別モデルで補完)であることの印。数値の読み取りを邪魔しない小さな * にする */
td.num .altm{color:var(--muted);font-weight:700;margin-left:1px}
.num{font-variant-numeric:tabular-nums}
.rank{color:var(--muted);font-variant-numeric:tabular-nums}

footer{color:var(--muted);font-size:.82em;margin-top:26px;border-top:1px solid var(--line);padding-top:10px;padding-bottom:16px}
footer a{color:var(--link)}

#totop{position:fixed;right:16px;bottom:max(16px,env(safe-area-inset-bottom));z-index:30;
  opacity:0;transform:translateX(100%);transition:all .2s;pointer-events:none;
  background:rgba(220,234,249,.5);color:var(--night);border:0;border-radius:100px;
  padding:10px;cursor:pointer;font-weight:600;font-size:.82em}
#totop.show{opacity:1;transform:none;pointer-events:auto}
#totop:hover{background:rgba(220,234,249,.7)}
#totop .mk{width:20px;height:14px;display:block;margin:0 auto}

@media(min-width:700px){
  header h1{font-size:1.7em}
  main{padding:24px 24px 12px}
}
</style>
</head>
<body>

<!-- 天気アイコン(index.html と共通のSVGシンボル)。晴=橙/雲=灰/雨=青/雪=水色/雷=橙 -->
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <symbol id="wx-sun" viewBox="0 0 24 24" fill="none" stroke="#f5a623" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="4.2" fill="#f5a623" stroke="none"/>
    <path d="M12 2v2.6M12 19.4V22M2 12h2.6M19.4 12H22M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M19.4 4.6l-1.8 1.8M6.4 17.6l-1.8 1.8"/>
  </symbol>
  <symbol id="wx-cloud" viewBox="0 0 24 24" fill="none" stroke="#8b93a3" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M7.5 18.5h8.6a3.9 3.9 0 0 0 .4-7.78 5.6 5.6 0 0 0-10.75-1.35A3.85 3.85 0 0 0 7.5 18.5Z"/>
  </symbol>
  <symbol id="wx-suncloud" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="8" cy="8.5" r="3" fill="#f5a623" stroke="none"/>
    <path d="M8 2.6v1.8M8 12.6v1.8M2.4 8.5h1.8M11.8 8.5h1.8M4.1 4.6l1.3 1.3M10.6 11.1l1.3 1.3M11.9 4.6l-1.3 1.3M5.4 11.1l-1.3 1.3" stroke="#f5a623"/>
    <path d="M11.5 20.5h7.7a3.5 3.5 0 0 0 .36-6.98 5 5 0 0 0-9.6-1.2A3.45 3.45 0 0 0 11.5 20.5Z" stroke="#8b93a3"/>
  </symbol>
  <symbol id="wx-fog" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M7.3 13.5h8.6a3.9 3.9 0 0 0 .4-7.78A5.6 5.6 0 0 0 5.55 4.37 3.85 3.85 0 0 0 7.3 13.5Z" stroke="#8b93a3"/>
    <path d="M5 18h9M8 21.3h8" stroke="#aab2c0"/>
  </symbol>
  <symbol id="wx-rain" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M7.3 14.5h8.6a3.9 3.9 0 0 0 .4-7.78A5.6 5.6 0 0 0 5.55 5.37 3.85 3.85 0 0 0 7.3 14.5Z" stroke="#8b93a3"/>
    <path d="M8.5 17.5 7 21M12.5 17.5 11 21M16.5 17.5 15 21" stroke="#3f83d6"/>
  </symbol>
  <symbol id="wx-snow" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M7.3 14.5h8.6a3.9 3.9 0 0 0 .4-7.78A5.6 5.6 0 0 0 5.55 5.37 3.85 3.85 0 0 0 7.3 14.5Z" stroke="#8b93a3"/>
    <g fill="#4aa5e0" stroke="none"><circle cx="8.5" cy="18.6" r="1.05"/><circle cx="12" cy="20.4" r="1.05"/><circle cx="15.5" cy="18.6" r="1.05"/></g>
  </symbol>
  <symbol id="wx-thunder" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M7.3 13.5h8.6a3.9 3.9 0 0 0 .4-7.78A5.6 5.6 0 0 0 5.55 4.37 3.85 3.85 0 0 0 7.3 13.5Z" stroke="#8b93a3"/>
    <path d="M12.5 15.5 9.5 20h3l-1 3" stroke="#f5a623"/>
  </symbol>
  <symbol id="mkico" viewBox="0 0 76 52">
    <path d="M4 48 L28 8 L40 27 L50 14 L72 48 Z" fill="none" stroke="currentColor" stroke-width="7" stroke-linejoin="round"/>
    <path d="M21.5 19 L28 8 L34.5 19 L31.2 15.6 L28 19.6 L24.8 15.6 Z" fill="currentColor"/>
    <path d="M45.8 20.5 L50 14 L54.2 20.5 L52 18.2 L50 20.8 L48 18.2 Z" fill="currentColor"/>
  </symbol>
</svg>

<header>
  <a class="back" href="../index.html">← トップへ戻る</a>
  <h1>天気の良い山をさがす</h1>
  <p class="sub">エリアと日付から、その日コンディションの良さそうな山をさがします</p>
  <svg class="ridge" viewBox="0 0 750 44" preserveAspectRatio="none" aria-hidden="true">
    <path d="M0 44 L0 30 L95 12 L185 26 L290 5 L395 24 L500 9 L610 27 L695 15 L750 24 L750 44 Z" fill="#f4f6f9"/>
  </svg>
</header>

<main>

<!-- autocomplete="off" は必須。付けないとブラウザがリロード/復帰のたびに前回の選択を
     こちらの初期化より後に復元してきて、「新しく開いたら初期状態」という方針が崩れる
     (実測: Chrome。都道府県だけ前回の県が残り、検索ボタンは無効のままで表示が食い違う)。 -->
<div class="searchcard">
  <div class="row">
    <label>エリア
      <select id="region" autocomplete="off"></select>
    </label>
    <label>都道府県
      <select id="pref" autocomplete="off"><option value="">すべて</option></select>
    </label>
    <label>日付
      <select id="date" autocomplete="off"></select>
    </label>
    <label>標高
      <select id="elev" autocomplete="off">
        <option value="">すべて</option>
        <option value="-1000">〜1000m</option>
        <option value="1000-2000">1000〜2000m</option>
        <option value="2000-2500">2000〜2500m</option>
        <option value="2500-">2500m〜</option>
      </select>
    </label>
  </div>
  <button class="go" id="go">この条件でさがす</button>
  <p class="hint" id="hint"></p>
</div>

<p id="status"></p>

<div class="notice">
この一覧は<b>晴天度を最重視した「ざっくり比較用」の簡易スコア</b>です
(<a href="find-score.html">スコアの計算方法</a>)。
実際に登る前に、気になる山をタップして<b>正式な登山指数A/B/C・稜線の風・時間帯別</b>の詳しい予報を必ず確認してください。
</div>

<div id="results"></div>

<footer>
<a href="../index.html">← PeakWeather トップへ戻る</a> /
<a href="mountains.html">対応している山の一覧</a>
</footer>

</main>

<!-- 「上に戻る」は <main> の外に置く。gate.js の pwGuardPage() は未認証時に main.innerHTML を
     案内文で丸ごと差し替えるため、中に入れておくとボタンが消え、下の初期化 IIFE が
     null 参照で毎回落ちる(未認証・file:// 直開き・gate.js が404 の fail-closed すべてで発生)。
     position:fixed なので main の外でも見た目は変わらない。 -->
<button id="totop" type="button" aria-label="ページ上部へ戻る"><svg class="mk" aria-hidden="true"><use href="#mkico"/></svg></button>

<script>
"use strict";
(function(){
  // 規約同意・認証コードが済んでいなければ、ここで打ち切って案内に差し替える。
  // このページは Open-Meteo を最大50地点×N回まとめて叩くため、
  // 未認証のまま素通しにすると認証ゲートが守っている無料利用枠が最も削られる。
  // 以降のセレクタ生成・検索・前回条件の自動復元は一切実行しない。
  //
  // gate.js 自体が読めなかった場合(404・通信断・ブロッカー)も素通しさせない。
  // ここで止めないと、検索カードのHTMLだけが残って「認証なしで開けた」ように見えてしまう。
  // 認証定数は複製せず「判定できない = 通さない」で倒す(定数の置き場は gate.js のみ)。
  // 判定ロジック(logic.js)が読めていない場合も同じ扱いにする。正式指数もスコアも
  // 計算できないので、無言で「指数の列だけ空の表」を出させない。
  if(typeof pwGuardPage!=="function"||typeof blockIndex!=="function"){
    document.querySelector("main").innerHTML=
      '<div style="max-width:560px;margin:26px auto;padding:22px 18px;background:#fff;'+
      'border:1px solid #dee4ee;border-radius:12px;text-align:center;line-height:1.8">'+
      '<p style="margin:0 0 12px;color:#44506b">ページの読み込みに失敗しました。'+
      'お手数ですが、トップページから開き直してください。</p>'+
      '<a href="../index.html" style="display:inline-block;padding:12px 26px;background:#4276b5;'+
      'color:#fff;border-radius:10px;font-weight:700;text-decoration:none">PeakWeather トップページへ</a></div>';
    return;
  }
  if(!pwGuardPage())return;

  var MOUNTAINS=__MOUNTAINS_JSON__;
  var REGION_ORDER=__REGION_ORDER__;
  var CHUNK=50;                 // 1リクエストあたりの最大地点数(負荷抑制)
  // 日付の選択肢の日数。気象庁モデル(MSM 0〜4日 / GSM 5〜11日)は天気コード・降水・雲量・
  // 気圧面風を11日ぶん配信するが、日照(sunshine_duration)だけは MSM 期間ぶんしか来ない。
  // 4日目以降の日照は /v1/forecast(ベストマッチ)から別名で補完している(SUPP_KEYS)。
  // ・期間を伸ばすときは補完側の配信期間も必ず実測で確認すること。このAPIは期間を超過しても
  //   エラーを返さず黙って null を並べるため、日数はコード側で制限するしかない。
  // ・FIND_DAYS <= index.html の JMA_DAYS(10) は不変条件。山名リンク先は
  //   ../index.html#山名/日付 なので、超えると本体の予報範囲外の日付を渡すことになる。
  var FIND_DAYS=7;
  var PREF_ORDER=__PREF_ORDER__;
  var PREF2REGION=__PREF2REGION__;  // 県名→地方名。県境またぎ(m.pref が「岩手県・宮城県・秋田県」等)を各県で扱うため
  // 山の所属県リスト。県境をまたぐ山は各県に属するものとして数え・絞り込む(例: 栗駒山→岩手/宮城/秋田)
  function prefsOf(m){return m.pref.split("・");}

  var WMO={0:"快晴",1:"晴れ",2:"晴れ時々曇り",3:"曇り",45:"霧",48:"着氷性の霧",
   51:"霧雨",53:"霧雨",55:"霧雨(強)",56:"着氷性霧雨",57:"着氷性霧雨(強)",
   61:"雨(弱)",63:"雨",65:"雨(強)",66:"着氷性の雨",67:"着氷性の雨(強)",
   71:"雪(弱)",73:"雪",75:"雪(強)",77:"霧雪",80:"にわか雨",81:"にわか雨",82:"にわか雨(強)",
   85:"にわか雪",86:"にわか雪(強)",95:"雷雨",96:"雷雨(雹)",99:"雷雨(激しい雹)"};
  function wlabel(c){return c==null?"-":(WMO[c]||("code"+c))}

  // ---- 代表天気モデル (index.html の WMETA / SAFETY_OVERRIDE と同一の値) ----
  // 7:00〜15:59の weather_code を単純な max で潰すと、9時間中1時間の霧雨が6時間の快晴を乗っ取り
  // 「雨アイコンなのに日照100%」という不整合が出る。index.html の summarizeDailyWeather と同じ
  // 「カテゴリ別の時間数で多数決 / 強い悪天だけは1時間でも昇格」で代表を決める。
  // 値を変えるときは index.html:WMETA と scripts/mountain_weather.py:WMETA も必ず揃えること。
  var WMETA={0:["clear",0],1:["clear",1],2:["partly",2],3:["cloudy",3],
   45:["fog",4],48:["fog",4],51:["drizzle",5],53:["drizzle",5],55:["drizzle",6],
   56:["drizzle",6],57:["drizzle",6],
   61:["rain",7],63:["rain",8],65:["rain",9],66:["rain",9],67:["rain",9],
   71:["snow",7],73:["snow",8],75:["snow",10],77:["snow",7],
   80:["showers",7],81:["showers",8],82:["showers",10],85:["snowshowers",9],86:["snowshowers",10],
   95:["thunder",11],96:["thunder",12],99:["thunder",12]};
  function wcat(c){return WMETA[c]?WMETA[c][0]:"unknown"}
  function wsev(c){return WMETA[c]?WMETA[c][1]:0}
  // 窓内に1時間でもあれば無条件で代表に昇格する悪天(安全側)。多数決で潰させない。
  var SAFETY_OVERRIDE={65:1,66:1,67:1,75:1,82:1,85:1,86:1,95:1,96:1,99:1};
  var PRECIP_CATS={fog:1,drizzle:1,rain:1,showers:1,snow:1,snowshowers:1,thunder:1};
  var CAT_LABEL={fog:"霧",drizzle:"霧雨",rain:"雨",showers:"にわか雨",
   snow:"雪",snowshowers:"にわか雪",thunder:"雷雨"};
  var CAT_ICON={fog:"wx-fog",drizzle:"wx-rain",rain:"wx-rain",showers:"wx-rain",
   snow:"wx-snow",snowshowers:"wx-snow",thunder:"wx-thunder"};
  // 代表が降水系になった日に「晴れていた時間帯」を添えるための表示名。
  // clear/partly はどちらも「晴れ」にまとめる (index.html の WBASE と同じ畳み方)。
  var FAIR_LABEL={clear:"晴れ",partly:"晴れ",cloudy:"曇り"};
  // 注記の時間帯表現。find の窓は 7:00〜15:59 なので実際に出るのは 朝/昼前/昼過ぎ/夕方 の4つ。
  var TOD_ORDER=["明け方","朝","昼前","昼過ぎ","夕方"];
  function timeOfDay(h){return h<=6?"明け方":h<=9?"朝":h<=11?"昼前":h<=14?"昼過ぎ":"夕方"}
  function timingLabel(hours){
    var seen={},labels=[],i,l;
    for(i=0;i<hours.length;i++){l=timeOfDay(hours[i]);if(!seen[l]){seen[l]=1;labels.push(l)}}
    labels.sort(function(a,b){return TOD_ORDER.indexOf(a)-TOD_ORDER.indexOf(b)});
    if(labels.length>=4)return "日中";
    if(labels.length>=2)return labels[0]+"〜"+labels[labels.length-1];
    return labels[0];
  }
  // win=[{hour,code}] (7:00〜15:59) → {code,cat,hours,notes,fair}。窓が空なら null。
  // notes: 代表にならなかった降水の注記 [{h:開始時,t:"昼過ぎに霧雨"}] を時刻順に。
  // fair : 代表が降水系のとき、最も長かった晴れ/曇りの注記 {h,t}。それ以外は null。
  //        「雷雨マークなのに日照88%」という隣の日照列との食い違いを防ぐために添える。
  //        表示するかは dispWx が決める (霧雨の降水量裏取りで降格した場合は不要なため)。
  function repWeather(win){
    if(!win.length)return null;
    var catHours={},i,cat;
    for(i=0;i<win.length;i++){
      cat=wcat(win[i].code);
      if(!catHours[cat])catHours[cat]=[];
      catHours[cat].push(win[i].hour);
    }
    function note(hours,text){return {h:Math.min.apply(null,hours),t:text}}
    // 代表コードが決まったら、注記を組み立てて返す
    function finish(code){
      var rc=wcat(code),notes=[],fair=null,c2;
      // 代表以外の降水カテゴリを注記に降格
      for(c2 in catHours){
        if(c2===rc||!PRECIP_CATS[c2])continue;
        notes.push(note(catHours[c2],timingLabel(catHours[c2])+"に"+CAT_LABEL[c2]));
      }
      notes.sort(function(a,b){return a.h-b.h});
      // 代表が降水系なら、最も長かった晴れ/曇りも拾っておく(1時間だけなら雑音なので出さない)
      if(PRECIP_CATS[rc]){
        var byLabel={},fl;
        for(c2 in catHours){
          fl=FAIR_LABEL[c2]; if(!fl)continue;
          byLabel[fl]=(byLabel[fl]||[]).concat(catHours[c2]);
        }
        var bestL=null,bestH=null;
        for(fl in byLabel)if(!bestH||byLabel[fl].length>bestH.length){bestL=fl;bestH=byLabel[fl]}
        if(bestH&&bestH.length>=2)fair=note(bestH,timingLabel(bestH)+"は"+bestL);
      }
      return {code:code,cat:rc,hours:catHours[rc]||[],notes:notes,fair:fair};
    }
    // 第1層: 安全オーバーライド(強雨・大雪・雷などは1時間でも代表に昇格。最重症を採る)
    var ov=null;
    for(i=0;i<win.length;i++){
      if(!SAFETY_OVERRIDE[win[i].code])continue;
      if(!ov||wsev(win[i].code)>wsev(ov))ov=win[i].code;
    }
    if(ov!=null)return finish(ov);
    // 第2層: カテゴリ別の時間数で多数決(同数なら最大重症度が高い方)
    var repCat=null,repCount=-1,repSev=-1;
    for(cat in catHours){
      var cnt=catHours[cat].length,sev=-1;
      for(i=0;i<win.length;i++)if(wcat(win[i].code)===cat&&wsev(win[i].code)>sev)sev=wsev(win[i].code);
      if(cnt>repCount||(cnt===repCount&&sev>repSev)){repCat=cat;repCount=cnt;repSev=sev}
    }
    // 代表カテゴリの中で最頻のコード(同数なら重症度が高い方)を代表コードに
    var codeCount={},k;
    for(i=0;i<win.length;i++){
      if(wcat(win[i].code)!==repCat)continue;
      codeCount[win[i].code]=(codeCount[win[i].code]||0)+1;
    }
    var repCode=null,best=-1,bestSev=-1;
    for(k in codeCount){
      var cd=+k,cc=codeCount[k],sv=wsev(cd);
      if(cc>best||(cc===best&&sv>bestSev)){repCode=cd;best=cc;bestSev=sv}
    }
    return finish(repCode);
  }

  // 天気列は 7:00〜15:59 の予報を「代表天気(多数決) → 日照率」の順で判定する。
  //   1) repWeather() の代表が降水系(雷雨/雪/雨/にわか雨/霧雨/霧)なら、そのアイコンで明示する。
  //      → 「雨が降る予報の日が『曇りがち』としか表示されない」誤解を防ぐ。
  //      強い雨・雪・雷は1時間でもあれば代表になる(SAFETY_OVERRIDE)ので取りこぼさない。
  //   2) 代表が降水系でなければ日照率で「よく晴れ〜曇りがち」を判定。
  //      代表になれなかった短時間の降水は nt(注記)に残して表に併記する。
  //   3) 日照率も weather_code もない場合は "-"。
  // 対象時間帯は score() 側の agg() と一致する 7:00〜15:59。
  // なお score() の悪天上乗せ減点は従来どおり「窓内の最悪コード」基準(安全側)で、ここの表示判定とは別。
  // 注記の配列 [{h,t}] を時刻順に並べて文字列配列にする
  function noteTexts(arr){
    var a=arr.slice().sort(function(x,y){return x.h-y.h}),out=[],i;
    for(i=0;i<a.length;i++)out.push(a[i].t);
    return out;
  }
  function dispWx(s){
    var rep=s.wxRep, f=s.sunFrac, notes=(rep&&rep.notes)||[];
    // 1) 代表が降水系ならそれを優先表示
    if(rep&&rep.code!=null){
      var cat=rep.cat;
      // 霧雨だけは「コードは出るが実質降っていない」ケースがあるので降水量で裏取りする
      var drizzleDry=(cat==="drizzle"&&!(s.psum!=null&&s.psum>=0.1));
      if(PRECIP_CATS[cat]&&!drizzleDry)
        // 「晴れていた時間帯」の注記はここでだけ添える(下の日照率ラベルなら文言が重複するため)
        return {ic:CAT_ICON[cat], lb:CAT_LABEL[cat],
                nt:noteTexts(rep.fair?notes.concat([rep.fair]):notes)};
      // 裏取りで降格した霧雨も注記には残す
      if(drizzleDry&&rep.hours.length)
        notes=notes.concat([{h:Math.min.apply(null,rep.hours),
                             t:timingLabel(rep.hours)+"に"+CAT_LABEL[cat]}]);
    }
    var nt=noteTexts(notes);
    // 2) 日照率ベース
    if(f!=null){
      if(f>=0.80)return {ic:"wx-sun",     lb:"よく晴れ", nt:nt};
      if(f>=0.55)return {ic:"wx-suncloud",lb:"晴れ",     nt:nt};
      if(f>=0.30)return {ic:"wx-suncloud",lb:"時々晴れ", nt:nt};
      return       {ic:"wx-cloud",  lb:"曇りがち", nt:nt};
    }
    // 3) 日照率フォールバック: 代表コードのみで大分類
    var c=(rep&&rep.code!=null)?rep.code:s.code;
    if(c==null)return {ic:null,lb:"-",nt:nt};
    if(c===45||c===48)return {ic:"wx-fog",     lb:"霧",          nt:nt};
    if(c===3)         return {ic:"wx-cloud",   lb:"曇り",        nt:nt};
    if(c===2)         return {ic:"wx-suncloud",lb:"晴れ時々曇り", nt:nt};
    return             {ic:"wx-sun",     lb:wlabel(c),     nt:nt};
  }

  var elRegion=document.getElementById("region"),elPref=document.getElementById("pref"),
      elDate=document.getElementById("date"),elElev=document.getElementById("elev"),
      elGo=document.getElementById("go"),
      elHint=document.getElementById("hint"),elStatus=document.getElementById("status"),
      elResults=document.getElementById("results");

  // 取得時刻・発表時刻は JST 固定で出す。表の日付が JST 基準なので、端末ローカル時刻で
  // 出すと海外や時計ずれの端末で「表の日付」と「時刻」が別基準になって読み解けなくなる
  // (index.html の JST_YMD / JST_HM / JST_MD と同一)。
  var JST_YMD=new Intl.DateTimeFormat("en-CA",
    {timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"});
  var JST_HM=new Intl.DateTimeFormat("en-GB",
    {timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",hour12:false});
  // en-GB は dd/mm なので、日本式の MM/DD になるよう YMD から組む
  var JST_MD={format:function(d){return JST_YMD.format(d).slice(5).replace("-","/")}};

  // ---- 日付の選択肢 (今日〜FIND_DAYS-1 日先・曜日つき) ----
  // 以前は3日だった。スコアの主要素である日照(sunshine_duration)を気象庁モデルが
  // MSM 期間ぶんしか配信せず、4日目以降が丸ごと欠測になるためだったが、
  // 日照だけを /v1/forecast(ベストマッチ)から補完する形にして7日に延ばした。
  // 降水・稜線風・天気コード・積雪は7日間まるごと気象庁モデルのまま(基本はMSM/GSM、
  // 足りないところだけ他モデル)。日数の変更は FIND_DAYS 一箇所で行うこと。
  // index.html と同じ方式: <select> に「07/25(土) 今日」形式の option を並べる。
  // input[type=date] だと iOS/PCで曜日が出ない・実装差でカードから溢れるなどの問題が
  // あったため、明示的に「日付+曜日」を全部option文言に埋め込む方式に統一。
  //
  // 4日目以降には「参考」を付ける。この範囲は (1)日照が別モデル由来 (2)稜線風が GSM の
  // 気圧面欠落ぶんだけ粗い (3)予報自体の誤差が大きい、と性質が変わるため。
  // 日照の * 印は検索した後にしか見えないので、精度の性格は日付そのものに出しておく。
  var WJA="日月火水木金土";
  function iso(d){return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")}
  function md(d){return String(d.getMonth()+1).padStart(2,"0")+"/"+String(d.getDate()).padStart(2,"0")}
  // 「今日」は必ず日本時間で決める。端末ローカルの日付で作ると TZ が JST でない端末で
  // 1日ずれ、選んだ日と API に投げる date、および山名リンク先(../index.html#山名/日付)の
  // 日付がまとめてずれる (index.html の jstToday と同一。3系統を同時に直すこと)
  var JST_YMD=new Intl.DateTimeFormat("en-CA",
    {timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"});
  function jstToday(){
    var p=JST_YMD.format(new Date()).split("-");
    return new Date(+p[0],+p[1]-1,+p[2]);
  }
  (function(){
    var today=jstToday();
    for(var i=0;i<FIND_DAYS;i++){
      var d=new Date(today);d.setDate(d.getDate()+i);
      var o=document.createElement("option");
      o.value=iso(d);
      o.textContent=md(d)+"("+WJA[d.getDay()]+")"+
        (i===0?" 今日":i===1?" 明日":i>=3?" 参考":"");
      elDate.appendChild(o);
    }
  })();

  // ---- エリア/県セレクタ ----
  REGION_ORDER.forEach(function(r){
    // 県境またぎの山は、所属するいずれかの県がこの地方に含まれれば1座として数える
    var c=MOUNTAINS.filter(function(m){return prefsOf(m).some(function(p){return PREF2REGION[p]===r})}).length;
    if(!c)return;
    var o=document.createElement("option");o.value=r;o.textContent=r+" ("+c+"座)";elRegion.appendChild(o);
  });
  // デフォルトのエリアは東北にする (山域が広くバランスよく散らばっており、初見のユーザーが
  // 「まず何か動かして結果を見る」ための入口として適切)。東北が未定義の場合は先頭のまま。
  if(Array.prototype.some.call(elRegion.options,function(o){return o.value==="東北"})){
    elRegion.value="東北";
  }
  // 北海道は都道府県=1(北海道)なので県絞り込み不要。それ以外は県まで選ばないと検索させない
  // (Open-Meteo 側の負荷軽減が目的)。
  var NO_PREF_REGIONS={"北海道":true};
  function fillPrefs(){
    var r=elRegion.value;
    // デフォルトの「すべて」ラベルを状況で切り替える。
    // 「県を選択してください」だと 375px 幅の <select> (テキスト領域126px) に収まらず
    // 末尾が見切れるため、ラベル(都道府県)で分かる分は削って「選択してください」(101px)にする。
    var placeholder=r&&!NO_PREF_REGIONS[r]?"選択してください":"すべて";
    elPref.innerHTML='<option value="">'+placeholder+'</option>';
    var counts={};
    // 県境またぎの山は所属する各県でそれぞれ1座として数える(この地方に属する県のみ)
    MOUNTAINS.forEach(function(m){prefsOf(m).forEach(function(p){if(PREF2REGION[p]===r)counts[p]=(counts[p]||0)+1})});
    PREF_ORDER.forEach(function(p){
      if(!counts[p])return;
      var o=document.createElement("option");o.value=p;o.textContent=p+" ("+counts[p]+"座)";elPref.appendChild(o);
    });
    updateHint();
  }
  // 標高帯。未選択("")なら判定を素通りする = 従来どおり全部が対象。
  // 上限は「未満」で切る(2000m ちょうどの山は 2000〜2500m 側に入る)。
  var ELEV_BANDS={"-1000":[0,1000],"1000-2000":[1000,2000],"2000-2500":[2000,2500],"2500-":[2500,1e9]};
  var ELEV_LABEL={"-1000":"〜1000m","1000-2000":"1000〜2000m","2000-2500":"2000〜2500m","2500-":"2500m〜"};
  function inElevBand(m,e){
    if(!e)return true;
    var b=ELEV_BANDS[e];
    if(!b)return true;   // 未知の値(旧キャッシュ・手改変)は絞り込まない側に倒す
    return m.el>=b[0]&&m.el<b[1];
  }
  // 絞り込みは fetch の手前(ここ)で行う。描画後に間引く形にすると、標高帯を変えるたびに
  // 対象外の山まで Open-Meteo に問い合わせることになり、認証ゲートで守っている無料枠を削る。
  function targets(){
    var r=elRegion.value,p=elPref.value,e=elElev.value;
    return MOUNTAINS.filter(function(m){
      if(!inElevBand(m,e))return false;
      var prefs=prefsOf(m);
      // 県が選択されていれば、その県を含む山を対象にする(県境またぎは各県で拾える)
      if(p)return prefs.indexOf(p)!==-1;
      // 県未選択(北海道など)は、いずれかの県がこの地方に属する山を対象にする
      return prefs.some(function(pp){return PREF2REGION[pp]===r});
    });
  }
  function needsPrefSelection(){
    var r=elRegion.value,p=elPref.value;
    return r && !NO_PREF_REGIONS[r] && !p;
  }
  function updateHint(){
    var r=elRegion.value;
    if(needsPrefSelection()){
      elHint.textContent="Open-Meteoの負荷軽減のため、都道府県を選択してから検索してください(北海道を除く)";
      elGo.disabled=true;
      return;
    }
    elGo.disabled=false;
    var n=targets().length;
    var reqs=Math.ceil(n/CHUNK);
    var msg="対象 "+n+"座";
    if(reqs>1)msg+=" / "+reqs+"回に分けて取得します";
    else msg+=" / 1回の取得で完了します";
    // 標高帯を絞ると対象0座になりうる(エリア・県だけでは起きなかった)。押しても
    // 「対象の山がありません」で終わるので、押させる前に理由の分かる文言で止める。
    if(!n){
      elHint.textContent="この条件に該当する山がありません（標高の条件をゆるめてください）";
      elGo.disabled=true;
      return;
    }
    elHint.textContent=msg;
  }
  elRegion.addEventListener("change",fillPrefs);
  elPref.addEventListener("change",updateHint);
  elElev.addEventListener("change",updateHint);

  // ---- 稜線風速の補間・判定のしきい値 ----
  // interpWind と定数 (LEVELS / SURFACE_WIND_M / DEGRADED_LEVELS / WINTER_TMAX / WINTER_TMIN /
  // WET_HYPO_* / FEELS_* / RANK) は logic.js にある。index.html と共有する唯一の実装なので、
  // ここに複製しないこと(片方だけ直すと詳細ページと山さがしで判定がズレる)。
  // 900/800hPa を別モデルで埋めてはいけない理由も logic.js のコメントに書いてある。
  // 900hPa・800hPa は MSM 期間にしか配信されない(GSM 期間はこの2面が丸ごと欠測)。この2面が
  // 両方欠測の時刻は内挿点が減り、稜線風が実測で北ア級-1.2m/s程度弱く出る(埋め合わせは却下済み。
  // 上のコメント参照)。degraded として持ち回り、score()/formalIndex() の表示側で `*` を出す。
  // 面の番号は logic.js の DEGRADED_LEVELS から引く(900/800 をここに書き写さない。
  // 書き写すと logic.js 側を変えたときに find だけ古い面を見続ける)。
  var DEGRADED_LEVEL_IDX=LEVELS.reduce(function(a,L,li){
    if(DEGRADED_LEVELS.indexOf(L[0])>=0)a.push(li);return a},[]);
  // i時刻の稜線風速+degraded。lvArrs=LEVELS と同じ並びの風速配列、w10=地上10m風の配列。
  // 気圧面が1つも無い時刻は null(判定不能)。ここで地上10m風だけの pts を interpWind に渡すと
  // 最下点の生値(=地上風)が返り、稜線20m/s相当の日が地上4m/sとして通ってしまう。すると
  // score() の欠測ガード(ridgeWmax!=null)もすり抜け、最大の減点③(-32)が消えて不当に上位へ出る。
  // 「データが無い→好条件」は安全と逆方向なので、欠測は欠測のまま出す。
  // (index.html の ridgeWind / mountain_weather.py の ridge_wind と同じ扱い。)
  function ridgeAt(lvArrs,w10,i,elev){
    var pts=[], lv=0, s10=w10?w10[i]:null;
    // 地上10m風を内挿の最下点に置く(SURFACE_WIND_M のコメント参照)
    if(s10!=null)pts.push([SURFACE_WIND_M,s10]);
    for(var li=0;li<LEVELS.length;li++){
      var a=lvArrs[li], v=a?a[i]:null;
      if(v!=null){pts.push([LEVELS[li][1],v]);lv++}
    }
    if(!lv)return null;
    var degraded=DEGRADED_LEVEL_IDX.every(function(li){
      var a=lvArrs[li];return !a||a[i]==null});
    return{v:interpWind(pts,elev),degraded:degraded};
  }
  // 対象時間帯: 7:00〜15:59 (hour 7〜15 の 9時間、登山コアタイム)
  function inRange(t){var h=parseInt(t.slice(11,13),10);return h>=7&&h<=15}
  var WIN_HOURS=9;              // 上の対象時間帯の時間数 (日照率の分母・被覆判定に使う)

  // ---- Open-Meteo 気象庁モデル (daily は積雪のみ、hourly で7:00〜15:59集計) ----
  var JMA_URL="https://api.open-meteo.com/v1/jma";
  var FC_URL="https://api.open-meteo.com/v1/forecast";
  var DAILY="snowfall_sum";
  var HOURLY="weather_code,temperature_2m,relative_humidity_2m,precipitation,"+
    "sunshine_duration,wind_speed_925hPa,wind_speed_900hPa,wind_speed_850hPa,"+
    "wind_speed_800hPa,wind_speed_700hPa,wind_speed_600hPa,wind_speed_10m";
  // /v1/forecast(ベストマッチ合成)から補う変数。
  //   precipitation_probability : 気象庁モデルに存在しない(投げても400にならず全nullで返る)。
  //                               find では「表に出す参考値」だけの扱いで、減点には一切使わない
  //                               (降水量-30に一本化したまま)。
  //   sunshine_duration         : 気象庁モデルは MSM 期間(おおむね1〜3日目)しか配信しない。
  //                               4日目以降を埋めるために取る。こちらは採点に使う(主要素のため)。
  // ※ このリクエストに models= を付けないこと。付けるとレスポンスのキーが
  //   sunshine_duration_best_match のように接尾辞つきになり、mergeSeries はエラーを出さないまま
  //   全 null を貼る。「例外が出ないから取れている」が成り立たない壊れ方をする。
  var SUPP_HOURLY="precipitation_probability,sunshine_duration";
  // base(気象庁モデル)側に貼り付けるときのキー名。日照は別名にする ─ 同名で貼ると
  // 1〜3日目の MSM の日照をベストマッチの値で上書きしてしまう(基本はMSM、の方針に反する)。
  var SUPP_KEYS=["precipitation_probability","sunshine_supp"];
  // extra の系列を base の time 軸に「時刻をキーにして」貼り直す(index.html の mergeSeries と同じ)。
  // 2本のAPIで時系列が食い違いうるので添字が揃っている前提を置かない。
  // 足りない時刻は null で埋めるため、下流は必ず base.time と同じ長さの列を得る。
  function mergeSeries(base,extra,keys){
    var pos={},et=(extra&&extra.time)||[],i;
    for(i=0;i<et.length;i++)pos[et[i]]=i;
    keys.forEach(function(k){
      var src=(extra&&extra[k])||[];
      base[k]=base.time.map(function(t){
        return (t in pos)&&pos[t]<src.length?src[pos[t]]:null;
      });
    });
  }
  // fetch は既定でタイムアウトしない。レスポンスが来ないまま Promise が pending だと
  // 「予報を取得中… (1/2)」のままボタンが無効で固まる。必ず時間で切る
  // (index.html の apiJson と同じ方針。CLI は urlopen(timeout=30) で同じ保護をしている)。
  var API_TIMEOUT_MS=20000;
  // 例外を利用者向けの日本語メッセージに変換する。生の "HTTP 429" は次の行動に繋がらない。
  function apiError(e){
    if(e&&e.name==="AbortError")
      return new Error("気象データの取得がタイムアウトしました。電波の良い場所で再度お試しください");
    if(e&&e.status===429)
      return new Error("アクセスが集中しています。数分おいてから再度お試しください");
    if(e&&e.status>=500)
      return new Error("気象データの提供元が一時的に応答していません。時間をおいて再度お試しください");
    return new Error("気象データを取得できませんでした。通信状況をご確認のうえ再度お試しください");
  }
  async function apiJson(url,params,retries){
    retries=retries||3;var lastErr;
    for(var a=1;a<=retries;a++){
      var ac=new AbortController();
      var timer=setTimeout(function(){ac.abort()},API_TIMEOUT_MS);
      try{
        var r=await fetch(url+"?"+new URLSearchParams(params),{signal:ac.signal});
        if(!r.ok){
          // 429(混雑)と 5xx(提供元の一時障害)は待てば直るので再試行する。
          // それ以外の 4xx はリクエスト側の問題で、投げ直しても直らないので即中断。
          if(r.status!==429&&r.status<500)
            throw Object.assign(new Error("HTTP "+r.status),{fatal:true,status:r.status});
          throw Object.assign(new Error("HTTP "+r.status),{status:r.status});
        }
        return await r.json();
      }catch(e){
        lastErr=e;
        if(e.fatal||a===retries)break;
        // 429 は無料利用枠を守るのが目的なので、他のエラーより長く待ってから再試行する
        await new Promise(function(res){setTimeout(res,(e.status===429?6000:1200)*a)});
      }finally{clearTimeout(timer)}
    }
    throw apiError(lastErr);
  }
  // ---- 予報の発表時刻(モデル初期時刻) ----
  // Open-Meteo が公開しているモデルのメタ情報。last_run_initialisation_time(Unix秒)が
  // そのモデルの初期時刻 = 予報の「発表」時刻。
  // ★ レスポンスの generationtime_ms は「サーバの処理時間」であって発表時刻ではない。
  //   名前が紛らわしいので取り違えないこと(値は数msで、予報の新しさとは無関係)。
  // このページは結果を sessionStorage に最大30分キャッシュして復元もするので、
  // 「いつ取得した値か」「いつ発表された予報か」が画面から分からないと、古い順位表を
  // 最新と誤解したまま山を選ぶことになる(CACHE_TTL_MS のコメントと同じ問題意識)。
  // index.html の modelInit / initTxt と同一ロジック。
  var META_MODELS=[["jma_msm","MSM"],["jma_gsm","GSM"]];
  var META_TTL_MS=10*60*1000;   // 10分。MSM の更新間隔3時間に対して十分細かく、
                                // かつ検索のたびにリクエストが増えない(無料枠を守るのが優先)
  async function modelInit(model){
    var k="pwmeta1:"+model, c=null;
    try{c=JSON.parse(pwSLoad(k)||"null")}catch(e){}
    if(c&&typeof c.t==="number"&&(Date.now()-c.t)<=META_TTL_MS)
      return typeof c.v==="number"?new Date(c.v*1000):null;
    // 発表時刻は補助表示。ここで落として一覧が出なくなるのは本末転倒なので、
    // 失敗は必ず握りつぶして null を返す(注記からこの項目が消えるだけにする)
    try{
      var r=await fetch("https://api.open-meteo.com/data/"+model+"/static/meta.json");
      if(!r.ok)return null;
      var j=await r.json(), v=j.last_run_initialisation_time;
      if(typeof v!=="number")return null;
      try{pwSSave(k,JSON.stringify({t:Date.now(),v:v}))}catch(e){}
      return new Date(v*1000);
    }catch(e){return null}
  }
  // 「MSM 08/10 18:00 ／ GSM 08/10 15:00」の形。取れたモデルだけ並べ、1つも無ければ ""。
  // find は FIND_DAYS=7 で MSM 期間と GSM 期間の両方にまたがるので、両方を出す
  async function initTxt(){
    var parts=[];
    for(var i=0;i<META_MODELS.length;i++){
      var d=await modelInit(META_MODELS[i][0]);
      if(d)parts.push(META_MODELS[i][1]+" "+JST_MD.format(d)+" "+JST_HM.format(d));
    }
    return parts.join(" ／ ");
  }
  // 補完APIの hourly を「base に貼るときのキー名」に組み替える。
  // sunshine_duration は気象庁モデル側にも同名で存在するため、ここで sunshine_supp に改名して
  // 別列として持つ。score() は気象庁モデルの日照を優先し、無い日だけこちらを使う。
  function suppRenamed(h){
    h=h||{};
    return {time:h.time||[],
            precipitation_probability:h.precipitation_probability||[],
            sunshine_supp:h.sunshine_duration||[]};
  }
  async function fetchChunk(ms,date){
    var lat=ms.map(function(m){return m.lat}).join(","),
        lon=ms.map(function(m){return m.lon}).join(","),
        el =ms.map(function(m){return m.el }).join(",");
    // 基本は気象庁モデル。降水確率と(MSM期間外の)日照だけ別モデルから補完する。
    // 2本を並行に投げ、地点ごとに時刻キーで貼り合わせる。
    //
    // Promise.all だと補完側が落ちただけで 50座ぶんの検索が丸ごと失敗する。天気・降水・
    // 稜線風・気温という主要素は気象庁モデル側に揃っているので、補完だけ諦めて先へ進む。
    // 日照が無い日は score() が weather_code による粗い代替評価に落ち、render() が
    // 「◯座は日照データが取得できず…」の注記を自動で出すので、精度低下は開示される。
    var res=await Promise.allSettled([
      apiJson(JMA_URL,{latitude:lat,longitude:lon,elevation:el,
        daily:DAILY,hourly:HOURLY,timezone:"Asia/Tokyo",wind_speed_unit:"ms",
        start_date:date,end_date:date}),
      apiJson(FC_URL,{latitude:lat,longitude:lon,elevation:el,
        hourly:SUPP_HOURLY,timezone:"Asia/Tokyo",
        start_date:date,end_date:date})
    ]);
    if(res[0].status==="rejected")throw res[0].reason;   // 主要データの失敗だけが致命
    var b0=res[0].value, s0=res[1].status==="fulfilled"?res[1].value:[];
    var base=Array.isArray(b0)?b0:[b0]; // 単一地点はオブジェクトで返る
    var sup =Array.isArray(s0)?s0:[s0];
    // 同じ座標列を送っているので地点の並びは一致する
    for(var i=0;i<base.length;i++){
      // hourly ごと欠けた地点は score() 側で主要素が全欠測となり null が返る = 一覧から外れる
      if(!base[i]||!base[i].hourly||!base[i].hourly.time)continue;
      mergeSeries(base[i].hourly,suppRenamed(sup[i]&&sup[i].hourly),SUPP_KEYS);
    }
    return base;
  }

  // ---- 安全性優先スコア(0-100)。稜線風と降水を最重視、対象時間帯 7:00〜15:59 ----
  // 重み: ①晴天度-28 / ②降水量-30 / ③稜線風-32 / ④雪寒気-10  (合計-100)
  function score(d, mt){
    var hr=d.hourly, times=(hr&&hr.time)||[], N=times.length;
    // 7:00〜15:59 の hourly 値を集計するヘルパ
    function agg(key, mode){
      var arr=hr&&hr[key]; if(!arr)return null;
      var vs=[], sum=0;
      for(var i=0;i<N;i++){
        if(!inRange(times[i]))continue;
        var v=arr[i]; if(v==null)continue;
        vs.push(v); sum+=v;
      }
      if(!vs.length)return null;
      if(mode==="sum")return sum;
      if(mode==="max")return Math.max.apply(null,vs);
      if(mode==="min")return Math.min.apply(null,vs);
      if(mode==="count")return vs.length;
      return null;
    }
    // 夏冬モードの判定にだけ使う気温。窓は行動時間帯 5〜16時で、表に出す tmax/tmin の窓
    // (7:00〜15:59)とは別物なので分けている。ここを 7-15 で代用してはいけない:
    // 詳細ページの正式判定(mountain_weather.py の mode_temps / index.html の modeTemps)は
    // 5〜16時で冬モードを決めており、窓がずれると 5-6時だけ冷える日に find だけ夏モードのまま
    // A を出し、開いた先の正式判定は B/C という食い違いが出る(凡例は「同じ正式な登山指数」と
    // 説明している)。ACT_HOURS=(5,16) は両端を含む。
    function actTemp(mode){
      var arr=hr&&hr.temperature_2m; if(!arr)return null;
      var vs=[];
      for(var i=0;i<N;i++){
        var h2=parseInt(times[i].slice(11,13),10);
        if(h2<5||h2>16)continue;
        var v=arr[i]; if(v==null)continue;
        vs.push(v);
      }
      if(!vs.length)return null;
      return mode==="max"?Math.max.apply(null,vs):Math.min.apply(null,vs);
    }
    // 日照は「窓の9時間ぶんが全部そろっている時だけ」採用する。部分欠測のまま合計すると、
    // 例えば3時間ぶんしか来ていない日が「日照率33%」に見え、実際より悪く採点してしまう
    // (MSM→GSM の切れ目に当たる日で起こりうる。切れ目の位置はモデルラン時刻で動く)。
    // そろっていなければ null を返し、呼び出し側で次の系列にフォールバックさせる。
    function sunOf(key){
      var n=agg(key,"count");
      return (n!=null&&n>=WIN_HOURS)?agg(key,"sum"):null;
    }
    // 稜線風速: 各時刻ごとに「値のある気圧面」から山頂標高の風速を補間し、その max をとる。
    // 面の取捨を時刻ごとにやるのは、MSM→GSM の切替で配信される面が変わるため(interpWind 参照)。
    var ridgeWmax=null, ridgeDegraded=false;
    var lvArrs=LEVELS.map(function(L){return hr&&hr["wind_speed_"+L[0]+"hPa"]});
    var w10=hr&&hr["wind_speed_10m"];
    var mv=0, hasW=false;
    for(var i=0;i<N;i++){
      if(!inRange(times[i]))continue;
      var w=ridgeAt(lvArrs,w10,i,mt.el);
      if(w==null)continue;
      // hasW は「値が1つでもあったか」なので if の外。1行に並べると条件付きに見えるので分ける
      if(w.v>mv){mv=w.v;ridgeDegraded=w.degraded}
      hasW=true;
    }
    if(hasW)ridgeWmax=mv;
    // 日照率: 7:00〜15:59 の sunshine_duration 合計 / (9h × 3600s)
    // 基本は気象庁モデル(MSM)の日照。MSM 期間を外れた日(おおむね4日目以降)は気象庁モデルが
    // 日照を配信しないので、/v1/forecast(ベストマッチ)から補完した sunshine_supp を使い、
    // sunAlt=true を立てて「別モデル由来」であることを表示側に伝える。
    var sunJma=sunOf("sunshine_duration");
    var sunSum=sunJma, sunAlt=false;
    if(sunSum==null){sunSum=sunOf("sunshine_supp");if(sunSum!=null)sunAlt=true}
    var sunFrac=sunSum==null?null:Math.max(0,Math.min(1,sunSum/(WIN_HOURS*3600)));
    // 天気コードの worst(max)。スコアの悪天上乗せ減点(安全側)にのみ使う。
    // 表示用の代表天気は下の repWeather() が別に決める(max だと短時間の霧雨に乗っ取られるため)。
    var code=agg("weather_code","max");
    // 表示用: 7:00〜15:59の (時刻, code) 列から代表天気を多数決で決める
    var win=[];
    for(var wi=0;wi<N;wi++){
      if(!inRange(times[wi]))continue;
      var wc=hr&&hr.weather_code?hr.weather_code[wi]:null;
      if(wc==null)continue;
      win.push({hour:parseInt(times[wi].slice(11,13),10),code:wc});
    }
    var wxRep=repWeather(win);
    var psum=agg("precipitation","sum");
    // 降水確率は「表に出す参考値」だけ。下の減点計算では一切使わない
    var pprob=agg("precipitation_probability","max");
    var tmin=agg("temperature_2m","min");
    var tmax=agg("temperature_2m","max");
    var snow=d.daily&&d.daily.snowfall_sum?d.daily.snowfall_sum[0]:null;
    // 主要素が1つも取れていない山はスコアを出さない(呼び出し側が一覧から外す)。
    // 減点方式なので、引く材料が無いと 100点=ランクA になり最上位に出てしまう。
    // 「データが無い」が「最高のコンディション」に化けるのは安全と逆方向。
    // 判定材料は必ず「気象庁モデルから取れたもの」で数える(sunFrac ではなく sunJma)。
    // sunFrac で数えると、気象庁モデルが全滅した地点でも補完日照だけで非nullになってこの
    // ガードをすり抜け、天気・気温・稜線風・降水がすべて「-」の行が①だけの減点=80点前後の
    // ランクAとして最上位付近に出てしまう。
    if(sunJma==null&&code==null&&psum==null&&ridgeWmax==null)return null;
    // 夏冬モード。月ベースを基本に、行動時間帯の山頂気温が低ければ冬側へ倒す。
    // これを入れないと、冬・快晴・稜線風12m/s が「80点=ランクA」で最上位に出るのに、
    // 詳細ページの正式判定では C(冬モードは12m/sでC)になる ── 入口が安全と逆を向く。
    var mon=parseInt((times[0]||"").slice(5,7),10)||1;
    var th=seasonTh(mon, actTemp("max"), actTemp("min"));
    var winter=th.mode!=="夏山";
    var s=100;
    // 減点は控えながら引く(内訳を表に出すため)。★ 引く順序と式は変えないこと。
    // まとめて計算してから一度に引くと浮動小数の丸めが変わり、最後の Math.round が
    // 境界でずれてスコアが1点動く日が出る。あくまで「引いた値を記録する」だけにする。
    var dSun=0,dPre=0,dWind=0,dCold=0;
    // ① 晴天度 (最大 -28)
    if(sunFrac!=null){dSun=(1-sunFrac)*28;s-=dSun}
    else if(code!=null){dSun=code<=1?0:code===2?8:code===3?18:22;s-=dSun}
    // 天気コードの悪天(雨雪雷)を軽く上乗せ
    if(code!=null){var dBad=code>=95?8:(code>=71&&code<=86)?5:(code>=51&&code<=82)?4:0;
      dSun+=dBad;s-=dBad}
    // ② 降水量 (最大 -30) - 行動可否に効くのは実際に降る量。
    // 以前は「確率-10 / 量-20」だったが、気象庁モデルに降水確率が無いため量に一本化した。
    // 降水確率(pprob)は表には出すが、ここには足さない(スコアの意味を変えないため)
    if(psum!=null){dPre=Math.min(psum,10)/10*30;s-=dPre}
    // ③ 稜線風 (最大 -32)
    // 夏: 6m/s以下=0、18m/s以上=最大 / 冬: 4m/s以下=0、12m/s以上=最大。
    // 冬は同じ風速でも危険度が段違いに上がるため、正式判定の閾値(8/12m/s)に合わせて前倒しする。
    if(ridgeWmax!=null){
      var w0=winter?4:6, wSpan=winter?8:12;
      dWind=Math.max(0,Math.min(1,(ridgeWmax-w0)/wSpan))*32;
      s-=dWind;
    }
    // ④ 雪・寒気 (最大 -10)
    if(snow!=null&&snow>0){var dS=Math.min(snow,5)/5*5;dCold+=dS;s-=dS}
    if(tmin!=null&&tmin<-5){var dT=Math.min((-5-tmin),15)/15*5;dCold+=dT;s-=dT}
    return {v:Math.round(Math.max(0,Math.min(100,s))),sunFrac:sunFrac,sunAlt:sunAlt,
      code:code,wxRep:wxRep,winter:winter,abc:formalIndex(d,mt,th),
      psum:psum,pprob:pprob,ridgeWmax:ridgeWmax,ridgeDegraded:ridgeDegraded,tmax:tmax,tmin:tmin,
      brk:{sun:dSun,pre:dPre,wind:dWind,cold:dCold}};
  }
  // 詳細ページと同じ「正式な登山指数 A/B/C」を各行に併記するために計算する。
  // スコア(相対比較のふるい)とは別物なので、両方を並べて食い違いに気づけるようにする。
  // 行動時間帯 5〜16時を3時間ブロックに割り、最悪値を採る(index.html の日別指数と同じ)。
  // ★ find は視程を取得しないため D4(視界不良)は判定できない。主判定+D1+D2 までを出す。
  function formalIndex(d,mt,th){
    var hr=d.hourly, times=(hr&&hr.time)||[], N=times.length;
    var lvArrs=LEVELS.map(function(L){return hr&&hr["wind_speed_"+L[0]+"hPa"]});
    var w10=hr&&hr["wind_speed_10m"];
    function windAt(i){var w=ridgeAt(lvArrs,w10,i,mt.el);return w?w.v:null}
    var worst=null, worstReason="";
    for(var sh=3;sh<18;sh+=3){
      // 材料は安全側に寄せる(風=最大 / 降水=合計 / 気温=最小 / 湿度=最大)。
      // index.html の blkVerdict と同じ集計。ここを変えると詳細ページと食い違う。
      var ws=null, pr=null, tmn=null, rhx=null;
      for(var i=0;i<N;i++){
        var h2=parseInt(times[i].slice(11,13),10);
        if(h2<5||h2>16||Math.floor(h2/3)*3!==sh)continue;
        var w=windAt(i); if(w!=null&&(ws==null||w>ws))ws=w;
        var p=hr.precipitation?hr.precipitation[i]:null;
        if(p!=null)pr=(pr==null?0:pr)+p;
        var t=hr.temperature_2m?hr.temperature_2m[i]:null;
        if(t!=null&&(tmn==null||t<tmn))tmn=t;
        // 湿度は最大値(最も熱が逃げにくい = 安全側)
        var rv=hr.relative_humidity_2m?hr.relative_humidity_2m[i]:null;
        if(rv!=null&&(rhx==null||rv>rhx))rhx=rv;
      }
      // 視程に null を渡すので D4(視界不良)は自動でスキップされる。
      // find は視程を取得しないため、主判定 + D1 + D2 までを出す。
      var r=blockIndex(ws,pr,th,tmn,feelsLike(tmn,ws,rhx),null);
      if(r[0]==null)continue;   // そのブロックは判定材料なし
      if(worst==null||RANK[r[0]]>RANK[worst]){worst=r[0];worstReason=r[1]}
    }
    return worst==null?null:{v:worst,reason:worstReason};
  }
  // 安全性の足切り: 稜線風速(夏18/冬12 m/s以上) または 降水量 >=10mm で別表送り。
  // 冬の12m/sは正式判定でC(登山不適)なので、一覧の本表に残してはいけない。
  function cutWind(s){return s.winter?12:18}
  function isDangerous(s){
    return (s.ridgeWmax!=null&&s.ridgeWmax>=cutWind(s))||(s.psum!=null&&s.psum>=10);
  }
  // 足切り理由のラベル (足切り表の「理由」列に表示)
  function reasonLabel(s){
    var parts=[];
    if(s.ridgeWmax!=null&&s.ridgeWmax>=cutWind(s))parts.push("稜線風 "+Math.round(s.ridgeWmax)+"m/s");
    if(s.psum!=null&&s.psum>=10)parts.push("降水量 "+Math.round(s.psum)+"mm");
    return parts.join(" / ");
  }

  // ' も落とす(index.html の esc と同一。属性を ' で囲む行を将来書いた時の保険)
  function esc(s){return String(s).replace(/[&<>"']/g,function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
  function pct(f){return f==null?"-":Math.round(f*100)+"%"}
  function fnum(v,u){return v==null?"-":Math.round(v)+u}
  // 降水量は「小雨(0.1〜0.9mm)」を丸めて 0mm と表示してしまうと誤解を招くため、小数1桁で表示する
  function pmm(v){if(v==null)return "-";if(v<0.05)return "0.0mm";return v.toFixed(1)+"mm"}
  // スコアの A/B/C ランク色分け (find-score.html の閾値と一致: A>=70 / B>=45 / C<45)
  function rankOf(v){return v>=70?"a":v>=45?"b":"c"}
  // スコアの減点内訳。数字だけでは「何で引かれた山なのか」が分からず、日照・降水・風の列を
  // 突き合わせないと読めなかった。減点の大きい順に並べ、0.5点未満は省く。
  // ★ 「100 − 合計」の形にはしないこと。score は最後に 0〜100 へクランプしているので、
  //   減点合計が100を超える日は表示スコアと一致しない(内訳の方が正しく、表示が下げ止まる)。
  function brkHtml(b,v){
    if(!b)return"";
    var items=[["日照",b.sun],["降水",b.pre],["風",b.wind],["雪寒",b.cold]]
      .filter(function(x){return x[1]>=0.5})
      .sort(function(x,y){return y[1]-x[1]});
    // 0.5点未満だけで構成される日は項目が1つも残らない。ここで「減点なし」と言い切ると
    // スコアが99なのに減点なし、という食い違いになるので、満点かどうかで文言を分ける
    if(!items.length)return'<small class="brk">'+(v>=100?"減点なし":"減点1点未満")+'</small>';
    return'<small class="brk">'+items.map(function(x){return x[0]+"-"+Math.round(x[1])}).join(" / ")+'</small>';
  }

  // ---- 検索実行 ----
  // キー接頭辞の数字は保存形式のバージョン。sc の中身を変えたら必ず上げる
  // (find2: 代表天気 wxRep を追加 / find3: wxRep.notes を [{h,t}] 形式にし fair を追加
  //  / find4: 降水の配点を 確率-10・量-20 に変更しスコア値の意味が変わった
  //  / find5: 取得元を気象庁モデルに変更・対象を3日に短縮・降水を量-30に一本化
  //  / find6: 降水確率を別モデルから取り直し、表示専用フィールド pprob として復活
  //  / find7: 対象を3日→7日に拡張。気象庁モデルの日照が届かない日は別モデルで補完し、
  //           その旨を sunAlt で持つ。日照は窓9時間そろっている時だけ採用に変更。
  //           稜線風を「値のある気圧面から時刻ごとに補間」に変更(GSM は 900/800hPa を
  //           配信せず、従来の決め打ちだと4日目以降の稜線風が丸ごと欠測になっていた)
  //  / find8: キャッシュを {t:取得時刻, rows:…} 形式にし TTL を導入
  //  / find9: 稜線風の減点・足切りを夏冬で分け、正式指数 abc を併記
  //  / find10: 体感温度を風冷指数から Apparent Temperature へ(相対湿度を追加取得)
  //  / find11: 夏冬モードの判定窓を詳細ページと同じ行動時間帯 5〜17時に統一(従来は 7〜15時で、
  //            5-6時だけ冷える日に find だけ夏モードのままAを出していた)。あわせて、気圧面が
  //            1つも無い時刻の稜線風を地上10m風で代用せず欠測に倒した(スコアが変わる))
  //  / find12: 稜線風に ridgeDegraded(900hPa/800hPa両欠測)を追加し、GSM期間の稜線風セルに
  //            `*` を出すようにした(sc の形が変わる)
  //  / find13: 夏冬モードの判定窓・正式指数の判定窓を行動時間帯5〜17時→5〜16時に変更
  //            (winter判定・稜線風の減点・abc がこの窓に依存するためスコアが変わりうる)
  //  / find14: sc に減点内訳 brk を追加(sc の形が変わる)。あわせてキーに標高帯を足した
  //            (標高帯で対象座数が変わるため、同じエリア・県・日付でも別の結果になる)
  //  / find15: 正式指数の理由(sc.abc.reason)に主判定「風」「降水」を追加(sc の中身が変わる)。
  //            A/B/C の値自体は変わらないが、旧キャッシュだと理由だけ空のまま復元される
  // 上げ忘れると旧キャッシュがそのまま復元され、天気列だけ古い表示になる。
  function cacheKey(r,p,e,date){return "find15:"+r+":"+p+":"+e+":"+date}
  // 直近の検索条件を保存するキー。ページを再訪した時にセレクタと結果を復元する用途
  // (bfcache が効かない iOS 直リンク等のフォールバック。詳細は末尾の restoreLastSearch)。
  var LAST_KEY="find15:last";
  // 旧世代のキャッシュキー掃除。バージョンを上げても古い接頭辞のキーが sessionStorage に
  // 残り続け、quota に達するとキャッシュが黙って無効化される(認証ゲートが守っている
  // 無料枠と逆方向に働く)。既知の旧接頭辞を明示的に消す(localStorageの列挙APIには依存しない)。
  // 次にバージョンを上げる時は、いま現行の接頭辞("find15")をこの配列に追記すること
  // (この配列には「もう使わない世代」だけを並べる。現行を入れると自分のキャッシュを消す)。
  var OLD_FIND_PREFIXES=["find2","find3","find4","find5","find6","find7","find8","find9","find10","find11","find12","find13","find14"];
  function cleanupOldCache(){
    try{
      var ks=[];for(var i=0;i<sessionStorage.length;i++)ks.push(sessionStorage.key(i));
      ks.forEach(function(k){
        if(OLD_FIND_PREFIXES.some(function(pfx){return k===pfx+":last"||k.indexOf(pfx+":")===0})){
          pwSDrop(k);
        }
      });
    }catch(e){} // sessionStorage 列挙が使えない環境では何もしない(実害なし)
  }
  // キャッシュの有効期限。キーは「エリア:県:対象日」だけで時刻成分を持たないので、
  // TTL が無いと同一セッション中は永久に最初の取得結果が返る。気象庁モデルは1日に複数回
  // 更新されるため、タブを開きっぱなしにした利用者へ朝6時の予報を夜18時に「最新」として
  // 出すことになり、ランキング・スコア・足切り判定がまるごと古いまま提示される。
  // 予報が更新されないことに気づく手がかりが利用者側に無いので、必ず時間で切る。
  var CACHE_TTL_MS=30*60*1000;   // 30分
  async function search(fromRestore){
    if(needsPrefSelection()){elStatus.textContent="都道府県を選択してから検索してください";return}
    var ms=targets(),date=elDate.value,r=elRegion.value,p=elPref.value,e=elElev.value;
    if(!ms.length){elStatus.textContent="対象の山がありません";return}
    elStatus.className="";elResults.innerHTML="";elGo.disabled=true;
    try{
      var key=cacheKey(r,p,e,date),cached=null;
      try{cached=JSON.parse(pwSLoad(key)||"null")}catch(e){}
      // 期限切れ・旧形式(rows が直接入った配列)は使わない。取り直す方が安全側。
      if(cached&&(!cached.t||!cached.rows||(Date.now()-cached.t)>CACHE_TTL_MS))cached=null;
      var rows,gotAt;
      if(cached){
        elStatus.textContent=fromRestore?"前回の検索結果を復元しました":"キャッシュから表示中…";
        rows=cached.rows;
        // 取得時刻は「キャッシュに入れた時刻」。Date.now() にしてはいけない。
        // 復元したのに「たった今取得」と出ると、最大30分前の順位表を最新と誤解させる
        gotAt=cached.t;
      }
      else{
        var chunks=[];for(var i=0;i<ms.length;i+=CHUNK)chunks.push(ms.slice(i,i+CHUNK));
        rows=[];
        for(var ci=0;ci<chunks.length;ci++){
          elStatus.textContent="予報を取得中… ("+(ci+1)+"/"+chunks.length+")";
          var arr=await fetchChunk(chunks[ci],date);
          for(var j=0;j<chunks[ci].length;j++){
            var mt=chunks[ci][j],sc=arr[j]?score(arr[j],mt):null;
            if(sc)rows.push({mt:mt,sc:sc});
          }
        }
        rows.sort(function(a,b){return b.sc.v-a.sc.v});
        gotAt=Date.now();
        pwSSave(key,JSON.stringify({t:gotAt,rows:rows}));
      }
      // 復元用に「最後の検索条件」を保存 (実際の rows は cacheKey 側に既に入っている)
      pwSSave(LAST_KEY,JSON.stringify({r:r,p:p,e:e,date:date}));
      // 発表時刻。失敗しても "" が返るだけで一覧の表示には影響しない
      var initAll=await initTxt();
      render(rows,date,gotAt,initAll);
      // 結果表示位置までスクロール(表示データが見やすい位置に移動)
      elResults.scrollIntoView({behavior:"smooth",block:"start"});
      // 足切り分離した内訳をステータスに出す
      var safeN=rows.filter(function(x){return !isDangerous(x.sc)}).length;
      var cautionN=rows.length-safeN;
      elStatus.textContent=r+(p?" / "+p:"")+(e?" / "+ELEV_LABEL[e]:"")+" の "+date+" — 登れそう "+safeN+"座"+
        (cautionN?" / 要慎重 "+cautionN+"座":"");
      // アクセス解析: 前回条件の自動復元(fromRestore)は利用者の検索操作ではないので数えない
      if(!fromRestore)pwTrack("find_search",{pw_region:r,pw_result:"success"});
    }catch(e){
      elStatus.className="err";elStatus.textContent=String(e.message||e);
      if(!fromRestore)pwTrack("find_search",{pw_region:r,pw_result:"error"});
    }finally{elGo.disabled=false}
  }

  // 表 1行分の HTML (メイン/足切り共通、caution=true で「理由」列を出す)
  // more=先頭FIND_HEAD件より後ろの行か、open=表示開始時点で展開済みか(「もっと見る」用)
  function rowHtml(row,i,date,caution,more,open){
    var m=row.mt,s=row.sc;
    var href="../index.html#"+encodeURIComponent(m.n)+"/"+date;
    var wx=dispWx(s);
    var reason=caution?'<td class="reason">⚠ '+esc(reasonLabel(s))+'</td>':'';
    // 指数Cはスコア順位に関わらず要注意〜不適であることに気づけるよう行全体を警告色にする
    var cls=[];if(s.abc&&s.abc.v==="C")cls.push("row-c");if(more)cls.push("find-more");
    var clsAttr=cls.length?' class="'+cls.join(" ")+'"':'';
    var hiddenAttr=(more&&!open)?' hidden':'';
    // 行のどこを押しても詳細予報へ飛べるようにする(見通し表の行ジャンプと挙動を統一)。
    // href は既に encodeURIComponent 済みなので data-href にそのまま埋めて安全
    return '<tr'+clsAttr+hiddenAttr+' data-href="'+href+'">'+
      '<td class="rank">'+(i+1)+'</td>'+
      '<td class="nm">'+
        '<div class="nmrow">'+
          '<a href="'+href+'">'+esc(m.n)+'</a>'+
          '<span class="scb rank-'+rankOf(s.v)+'">'+s.v+'</span>'+
        '</div>'+
        '<small>'+esc(m.pref)+' / '+m.el+'m</small>'+
        brkHtml(s.brk,s.v)+
      '</td>'+
      reason+
      // 正式指数。スコア(相対比較のふるい)と食い違う日に気づけるよう並べて出す
      '<td>'+(s.abc?'<span class="abc abc-'+s.abc.v.toLowerCase()+'">'+s.abc.v+'</span>'
             +(s.abc.reason?'<span class="abcr">'+esc(s.abc.reason)+'</span>':""):"-")+'</td>'+
      '<td>'+(wx.ic?'<svg class="wxico" aria-hidden="true"><use href="#'+wx.ic+'"/></svg>':"-")+
            '<span class="wxlbl">'+esc(wx.lb)+'</span>'+
            (wx.nt&&wx.nt.length?'<span class="wxnote">'+esc(wx.nt.join(" / "))+'</span>':"")+'</td>'+
      '<td class="num">'+pct(s.sunFrac)+
        (s.sunAlt?'<span class="altm" title="別の予報モデルで補完した日照">*</span>':"")+'</td>'+
      '<td class="num">'+fnum(s.tmax,"")+' / '+fnum(s.tmin,"℃")+'</td>'+
      '<td class="num">'+fnum(s.ridgeWmax,"m/s")+
        (s.ridgeDegraded?'<span class="altm" title="900hPa/800hPaのデータが無く、やや弱めに出ている可能性があります">*</span>':"")+'</td>'+
      '<td class="num">'+(s.pprob==null?"-":Math.round(s.pprob)+"%")+'</td>'+
      '<td class="num">'+pmm(s.psum)+'</td>'+
      '</tr>';
  }

  // 既定は先頭FIND_HEAD件だけ出し、残りは hidden で畳む(スマホで表が長くなりすぎるため)。
  // index.html の週間見通し表(WK_HEAD/wk-toggle)と同じ考え方
  var FIND_HEAD=10;

  /* 表が横にはみ出していること(=横スクロールできること)を右端のフェードで示す。
   * 実測(375px幅)でこの表は 509px あり、表示できるのは 347px。稜線風・降水確率・降水量が
   * 画面外に出る。手がかりが無いとそもそも横に送られないので、初見では列が無いのと同じになる。
   * 右端まで送ったら .at-end でフェードを消す(最後の列が薄いまま残らないように)。
   * index.html の markScrollables() と同じ実装。 */
  var xsResizeBound=false;
  function markScrollables(root){
    function upd(t){
      var over=t.scrollWidth-t.clientWidth>2;   // 端数での誤検出を避けるため 2px の余裕を見る
      t.classList.toggle("xscroll",over);
      t.classList.toggle("at-end",over&&t.scrollLeft>=t.scrollWidth-t.clientWidth-2);
    }
    function all(){Array.prototype.forEach.call(root.querySelectorAll(".tbl"),upd)}
    Array.prototype.forEach.call(root.querySelectorAll(".tbl"),function(t){
      upd(t);
      if(t.dataset.xs)return;
      t.dataset.xs="1";
      t.addEventListener("scroll",function(){upd(t)},{passive:true});
    });
    if(!xsResizeBound){xsResizeBound=true;addEventListener("resize",all,{passive:true})}
    return all;
  }

  function tableHtml(rows,date,caution){
    var tblId="tbl-"+(caution?"caution":"safe");
    var open=rows.length<=FIND_HEAD;
    var head='<tr><th>#</th><th>山名 / スコア</th>'+
      (caution?'<th>理由</th>':'')+
      '<th>指数</th>'+
      '<th>天気</th><th class="num">日照</th><th class="num">気温</th><th class="num">稜線風</th>'+
      '<th class="num">降水確率</th><th class="num">降水量</th></tr>';
    var body='';
    rows.forEach(function(row,i){body+=rowHtml(row,i,date,caution,i>=FIND_HEAD,open)});
    var html='<div class="tbl'+(caution?' caution':'')+'" id="'+tblId+'"><table><thead>'+head+
      '</thead><tbody>'+body+'</tbody></table></div>';
    if(rows.length>FIND_HEAD)
      html+='<button type="button" class="find-toggle" aria-controls="'+tblId+'" aria-expanded="'+open+'">'+
        (open?"折りたたむ":"残り"+(rows.length-FIND_HEAD)+"件を表示")+'</button>';
    return html;
  }

  // 表の下に置く「各列の意味」凡例。対象時間帯(朝7時〜夕方3時)・単位・重要ポイントを簡潔に説明
  var LEGEND_HTML=(
    '<details class="legend"><summary>表の見方</summary>'+
    '<div class="tbody"><dl>'+
    '<dt>スコア</dt><dd>0〜100 の登山適性スコア。'+
      '<span class="rk rk-a">A</span>70〜100 '+
      '<span class="rk rk-b">B</span>45〜69 '+
      '<span class="rk rk-c">C</span>0〜44 '+
      '(<a href="find-score.html">計算の詳細</a>)</dd>'+
    '<dt>減点の内訳</dt><dd>山名の下の小さい文字は、100点から何で引かれたかの内訳です'+
      '(減点の大きい順。日照・降水・風・雪寒の4項目、1点未満は省略)。'+
      'スコアは0〜100に収めるため、内訳の合計が100を超える日はスコアが0で下げ止まります。</dd>'+
    // スコアは相対比較の「ふるい」、指数は行動可否の「正式判定」。別物なので両方出し、
    // 食い違い(スコアは高いが指数はC 等)にその場で気づけるようにする。
    '<dt>指数</dt><dd>個別の山のページと同じ<b>正式な登山指数</b>'+
      '<span class="abc abc-a">A</span>登山適 '+
      '<span class="abc abc-b">B</span>要注意 '+
      '<span class="abc abc-c">C</span>登山不適。'+
      '行動時間帯5〜16時を3時間ごとに判定した最悪値です。'+
      'スコアは「相対的に天気の良い山を探すためのふるい」、指数は「行動できるかの判定」で別物です。'+
      '<b>この一覧では視程を取得していないため、視界不良による判定だけは含まれません</b>。'+
      '実際に登る前に必ず個別ページでご確認ください</dd>'+
    '<dt>天気</dt><dd>朝7時〜夕方3時の天気。最も続く天気を表示。危険な天気は1時間でも優先します</dd>'+
    '<dt>日照</dt><dd>朝7時〜夕方3時の晴れ時間の割合 (%)。<b>*</b>印は別モデルからの補完</dd>'+
    '<dt>気温</dt><dd>朝7時〜夕方3時の最高気温／最低気温（℃）。山頂の標高で計算済み</dd>'+
    '<dt>稜線風</dt><dd>山頂付近の稜線風速の朝7時〜夕方3時最大値（m/s）。'+
      'スコアの減点も足切りも<b>夏と冬で基準が変わります</b>'+
      '(足切り: 夏18m/s・冬12m/s以上)。冬は同じ風速でも危険度が大きく上がるためです</dd>'+
    '<dt>降水確率</dt><dd>朝7時〜夕方3時の降水確率の最大値 (%)。参考表示のみです</dd>'+
    '<dt>降水量</dt><dd>朝7時〜夕方3時の合計降水量（mm）。スコアに直接影響します</dd>'+
    '</dl></div></details>');

  // gotAt = この順位表を取得した時刻(キャッシュ復元時はキャッシュに入れた時刻)
  // initAll = 発表時刻の文字列("" なら取得できなかったので出さない)
  function render(rows,date,gotAt,initAll){
    var safe=[],caution=[];
    rows.forEach(function(x){(isDangerous(x.sc)?caution:safe).push(x)});
    var h='';
    // ① メイン表: 登れそうな山 (該当ゼロなら「見つかりませんでした」表示)
    if(safe.length){
      h+='<h3 class="results-h">登れそうな山 <span class="rcount">('+safe.length+'座)</span></h3>';
      h+=tableHtml(safe,date,false);
    }else{
      h+='<h3 class="results-h">登れそうな山は見つかりませんでした</h3>'+
         '<p class="rnote">この日は選択エリアの全山が下記の安全性足切りに該当しました。日を変えてお試しください。</p>';
    }
    // ② 足切り表: 該当ゼロなら表示しない
    if(caution.length){
      h+='<h3 class="results-h caution">⚠ 慎重に判断が必要 <span class="rcount">('+caution.length+'座)</span></h3>';
      // 風の閾値は cutWind と同じく夏冬で変わり、しかも夏冬は山ごとに決まる(同じ日でも標高で
      // 分かれる)ので、1つの数字には決められない。両方を書く。18m/s 固定のままだと、冬に
      // 13m/s で別表送りになった行を見た人が「18m/s 未満なのになぜ」と読めなくなる
      h+='<p class="rnote caution">稜線風速 18m/s 以上(冬・残雪期は 12m/s 以上)、'+
         'または 7:00〜15:59 の降水量 10mm 以上。'+
         '登山に不適格の可能性が高いため、参考として下位に表示しています。</p>';
      h+=tableHtml(caution,date,true);
    }
    h+='<p class="rnote">※ スコアは <b>登山コアタイム 7:00〜15:59</b> の気象値で算定しています。'+
       '<a href="find-score.html">計算方法の詳細</a></p>';
    // いつ取得した値か・いつ発表された予報かを明記する。この一覧は結果を最大30分
    // sessionStorage にキャッシュして復元もするため、これが無いと古い順位表を最新と
    // 誤解したまま山を選ぶことになる(CACHE_TTL_MS のコメントと同じ問題意識)。
    if(gotAt||initAll){
      h+='<p class="rnote">データ: 気象庁モデル / 出典: Open-Meteo'+
        (gotAt?' / 取得 '+JST_MD.format(new Date(gotAt))+' '+JST_HM.format(new Date(gotAt)):'')+
        (initAll?' / <b>発表(初期時刻) '+initAll+'</b>':'')+
        (gotAt||initAll?' JST':'')+'</p>';
    }
    // 日照の出どころが気象庁モデルでない日は、表の下に1回だけ明記する。
    // 行ごとの * だけだと「何の印か」が分からないため。
    var altN=rows.filter(function(x){return x.sc.sunAlt}).length;
    if(altN){
      h+='<p class="rnote">※ 日照の <b>*</b> 印'+(altN<rows.length?"が付いた山":"")+
         'は、この日が<b>気象庁モデルの日照の配信範囲外</b>のため、日照だけ'+
         '<b>別の予報モデル(ベストマッチ合成)</b>の値で補完しています。'+
         '天気・降水量・稜線風・積雪は気象庁モデルのままです'+
         '(<a href="find-score.html">計算方法</a>)。</p>';
    }
    // 稜線風が900hPa/800hPa欠測(粗いモデル=GSM の期間)でやや弱めに出ている山も、表の下に1回だけ明記する。
    var degN=rows.filter(function(x){return x.sc.ridgeDegraded}).length;
    if(degN){
      h+='<p class="rnote">※ 稜線風の <b>*</b> 印'+(degN<rows.length?"が付いた山":"")+
         'は、この時間帯が<b>900hPa/800hPaのデータが無い期間</b>(GSM期間)のため、'+
         '稜線風がやや弱めに出ている可能性があります(実測でおおむね-1.2m/s程度)。'+
         '強めに見積もって判断してください。</p>';
    }
    // 日照そのものが取れなかった山は、天気コードによる粗い代替評価になっている。
    // 黙って精度が落ちると気づけないので、これも表に出す。
    var noSunN=rows.filter(function(x){return x.sc.sunFrac==null}).length;
    if(noSunN){
      h+='<p class="rnote caution">※ '+noSunN+'座は日照データが取得できず、'+
         '天気コードによる簡易評価になっています(スコアの根拠が薄くなります)。</p>';
    }
    // 表下部に「各列の意味」凡例。気温が2つある/天気の判定基準など、初見でも列の意味が
    // 分かるようにする。1回だけ表示(メイン表と足切り表のどちらか(または両方)が出た時)。
    h+=LEGEND_HTML;
    elResults.innerHTML=h;
    markScrollables(elResults);
  }

  elGo.addEventListener("click",function(){search(false)});

  // 山名リンクを押したとき、遷移先(index.html)に「この一覧から来た」ことを1回だけ伝える。
  // index.html 側は読んだ直後に削除するので、その回の詳細予報にだけ「一覧に戻る」が出る。
  // 行ごとの onclick 属性ではなく委譲リスナー1本にして、生成HTMLを軽く保つ。
  // 山名リンク自体はブラウザの既定遷移に任せ、行の他の部分(ランク・指数・天気・気温など)を
  // 押した場合だけ JS で同じ遷移先(tr[data-href])へ移動する(index.htmlの見通し表の
  // 行ジャンプと操作性を統一)。
  elResults.addEventListener("click",function(e){
    var toggleBtn=e.target.closest?e.target.closest(".find-toggle"):null;
    if(toggleBtn){
      var open=toggleBtn.getAttribute("aria-expanded")!=="true";
      var tbl=document.getElementById(toggleBtn.getAttribute("aria-controls"));
      var more=tbl.querySelectorAll("tr.find-more");
      more.forEach(function(tr){tr.hidden=!open});
      toggleBtn.setAttribute("aria-expanded",open);
      toggleBtn.textContent=open?"折りたたむ":"残り"+more.length+"件を表示";
      // 行が増えると長い山名で表幅が変わるので、横スクロールの手がかりを測り直す
      markScrollables(elResults);
      return;
    }
    var a=e.target.closest?e.target.closest("td.nm a"):null;
    if(a){pwSSave("pw_entry","find");return}
    var tr=e.target.closest?e.target.closest("tr[data-href]"):null;
    if(!tr)return;
    pwSSave("pw_entry","find");
    location.href=tr.dataset.href;
  });

  // ---- 復元してよいのは「一覧から開いた詳細予報」から戻ってきた時だけ ----
  // 前回の検索条件・結果を復元するのは、この一覧から個別予報(index.html)へ進んで帰ってきた
  // 時に限る。「← 天気で山さがしの一覧に戻る」ボタンでもブラウザの戻るでも同じように戻す。
  // 一方、トップの「天気の良い山をさがす」から開いた時・直リンク・リロードでは、毎回
  // 初期状態(最上部・東北・都道府県未選択・結果なし)から始める。「新しく探しに来たのに
  // 前回の一覧が途中から出ている」状態を避けるため。
  //
  // 判別は index.html が立てる sessionStorage マーカーで行う(referrer では bfcache 復帰と
  // 区別できない)。マーカーは詳細予報を一覧から開いた時に立ち、トップの「天気の良い山を
  // さがす」を押した時に消える。ここでは1回で消費する。
  function takeBackFlag(){
    if(pwSLoad("pw_find_back")){
      pwSDrop("pw_find_back");
      return true;
    }
    return false;
  }

  // bfcache から復帰したページを初期状態に戻す (通常ロードは元から初期状態なので不要)。
  //
  // DOM を書き換えて戻すのではなく、素直に再ロードする。復帰したページではブラウザが
  // <select> の選択状態をこちらの初期化より後に復元しにきて、都道府県だけ前回の県が
  // 残る(=検索ボタンは無効のままで表示が食い違う)のを実測したため。setTimeout で
  // 上書きし返すのはタイミング勝負になり当てにできない。
  // 再ロードしても復元マーカーは無いので restoreLastSearch() は走らず、Open-Meteo も
  // 叩かない(検索は「この条件でさがす」を押した時だけ)。日付の選択肢も組み直される。
  function resetToInitial(){
    location.reload();
  }

  // ---- 直近の検索条件を自動復元 ----
  // 詳細予報から戻ってきたが bfcache が効かず新規ロードされたケース (iOS 直リンク等)。
  // 前回の検索条件を sessionStorage から読んでセレクタを復元し、対応する cacheKey に
  // ヒットすれば自動で render() まで進める。Open-Meteo は叩かない(キャッシュヒット時)。
  function restoreLastSearch(){
    var last;
    try{last=JSON.parse(pwSLoad(LAST_KEY)||"null")}catch(e){}
    if(!last||!last.r||!last.date)return;
    // 保存されたエリアが今の選択肢に無ければ復元しない(初期状態のまま手動検索を待つ)
    if(!Array.prototype.some.call(elRegion.options,function(o){return o.value===last.r}))return;
    elRegion.value=last.r;
    fillPrefs();
    if(last.p){
      if(Array.prototype.some.call(elPref.options,function(o){return o.value===last.p})){
        elPref.value=last.p;
      }
    }
    // 標高帯も復元する。ここを飛ばすと、詳細予報から戻ったときだけ「セレクタはすべて」なのに
    // 一覧は絞り込まれた結果、という食い違いが出る(下の cacheKey も last.e で引くため)
    if(last.e&&Array.prototype.some.call(elElev.options,function(o){return o.value===last.e})){
      elElev.value=last.e;
    }
    if(Array.prototype.some.call(elDate.options,function(o){return o.value===last.date})){
      elDate.value=last.date;
    }else{
      // 日付が期限切れ (選択できる期間を外れた) 場合は復元スキップ (キャッシュヒットしない)
      return;
    }
    updateHint();
    // cacheKey にヒットする場合だけ自動描画。ヒットしない場合はセレクタだけ復元して手動検索を待つ。
    // キャッシュが TTL 切れなら search() 側が取り直す(一覧は同じ条件で復元されるが中身は最新)。
    // 「戻ったら古い予報が出ていた」より「戻ったら少し待って最新が出た」の方が安全側。
    var key=cacheKey(last.r,last.p||"",last.e||"",last.date);
    if(pwSLoad(key))search(true);
  }

  cleanupOldCache();
  fillPrefs();
  if(takeBackFlag()){
    restoreLastSearch();
  }else{
    // 新規に開いた / ブラウザ戻りで再ロードされた → 初期状態のまま、ページ最上部を見せる。
    // リロード時はブラウザがスクロール位置をこちらの初期化より後に復元しにくるので、
    // load 後にもう一度最上部へ戻す。ついでにセレクタも初期値へ倒し直す(こちらは
    // <select autocomplete="off"> で止まっているはずの選択状態復元に対する保険)
    // (history.scrollRestoration は触らない。manual にすると「一覧に戻る」で bfcache 復帰
    //  した時のスクロール位置まで戻らなくなる実装があり、維持したい挙動を壊すため)。
    window.scrollTo(0,0);
    addEventListener("load",function(){requestAnimationFrame(function(){
      window.scrollTo(0,0);
      if(elPref.selectedIndex!==0||elDate.selectedIndex!==0||elElev.selectedIndex!==0||
         (elRegion.value!=="東北"&&Array.prototype.some.call(elRegion.options,function(o){return o.value==="東北"}))){
        elRegion.value="東北";
        elDate.selectedIndex=0;
        elElev.selectedIndex=0;   // 標高帯も「すべて」へ戻す(新規に開いた時は毎回初期状態)
        fillPrefs();            // 都道府県を placeholder に戻す(updateHint も走る)
        elPref.selectedIndex=0;
      }
    })});
  }

  // bfcache から復帰したケース (ブラウザの戻る/進む、および「一覧に戻る」の history.back())。
  // このときスクリプトは再実行されないので、ここで同じ振り分けをする。
  addEventListener("pageshow",function(e){
    if(!e.persisted)return;   // 通常ロードは上の初期化で処理済み
    if(takeBackFlag())return; // 詳細予報から戻ってきた → 条件・結果・スクロール位置をそのまま維持
    resetToInitial();
  });
})();

// ---- 上に戻るボタン (ヒーロー相当の高さを過ぎたら表示。戻り先はページ上部) ----
(function(){
  const btn=document.getElementById("totop");
  if(!btn)return; // 多重防御(ボタンは <main> の外にあるが、消えていても落とさない)
  btn.addEventListener("click",()=>window.scrollTo({top:0,behavior:"smooth"}));
  let tick=false;
  addEventListener("scroll",()=>{
    if(tick)return;tick=true;
    requestAnimationFrame(()=>{btn.classList.toggle("show",scrollY>innerHeight*.8);tick=false});
  });
})();
</script>

</body>
</html>
"""


def build_html():
    """docs/find.html の中身を組み立てて返す(ファイルには書かない)。

    check_mountains.py の「生成物ドリフト検査」がこれを呼び、docs/find.html と
    突き合わせる。生成物を直接編集して再生成で消える事故を検出するため。
    """
    mountains = load_mountains()
    mountains_json = build_mountain_json(mountains)
    region_order = json.dumps([name for name, _ in REGIONS], ensure_ascii=False)
    # 県の表示順は REGIONS の定義順(北→南)で安定させる
    pref_order = json.dumps([p for _, prefs in REGIONS for p in prefs],
                            ensure_ascii=False)
    # 県名→地方名。県境またぎの山を各県・各地方で扱うためクライアントに渡す
    pref2region = json.dumps({p: name for name, prefs in REGIONS for p in prefs},
                             ensure_ascii=False)

    return (TEMPLATE
            .replace("__MOUNTAINS_JSON__", mountains_json)
            .replace("__REGION_ORDER__", region_order)
            .replace("__PREF_ORDER__", pref_order)
            .replace("__PREF2REGION__", pref2region))


def main():
    html = build_html()
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"docs/find.html を生成しました (全{len(load_mountains())}座 / 横断検索ページ)")


if __name__ == "__main__":
    main()
