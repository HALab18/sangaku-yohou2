# -*- coding: utf-8 -*-
"""index.html の MOUNTAINS 配列から docs/find.html (コンディション横断検索) を生成する。

「その日に天気の良さそうな山を、まず見つけたい」という逆引きの入口。
エリア(9地方)+ 任意で県 + 単日 を指定 → その範囲の山を Open-Meteo の気象庁モデルから
バッチ取得し、簡易スコア(晴天度を最重視)でランキング表示。行をタップすると
既存の詳細予報 (../index.html#山名/日付) が開く。

対象は今日〜2日先の3日間。気象庁モデルはスコアの主要素である日照(sunshine_duration)を
MSM 期間ぶんしか配信せず、4日目以降は 7:00〜15:59 が丸ごと欠測になるため。
別の予報モデルを組み合わせて期間を延ばすかは検討中(判断材料は DEVLOG 参照)。

降水確率は気象庁モデルに無いので別モデルから補完するが、**表示だけで採点には使わない**。
モデルが違う値をスコアに混ぜると、スコアの意味が説明しづらくなるため。

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
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>天気の良い山をさがす — PeakWeather</title>
<meta name="description" content="エリアと日付を指定すると、その日にコンディションの良さそうな山を晴天度でランキング表示。気になる山をタップするとその山頂・稜線の詳しい気象予報へ。">
<link rel="icon" type="image/png" href="../icons/favicon-32.png">
<meta name="theme-color" content="#1e2d4a">
<!-- このファイルは scripts/gen_find.py により index.html から自動生成されます。直接編集しないでください
     (直接編集すると次回の再生成で消えます。修正は必ず scripts/gen_find.py 側に入れること) -->
<script src="../gate.js"></script>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-B4FYN1EJ2S"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'G-B4FYN1EJ2S');
</script>
<style>
:root{--night:#1e2d4a;--slate:#48608c;--sky:#5b87c5;--link:#2b5fa3;
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
table{border-collapse:collapse;width:100%}
/* ヘッダはページ縦スクロール時に画面上端に固定し、どの列を見ているか分かるようにする(index.htmlと同じ挙動) */
th{background:var(--slate);color:#fff;padding:6px 8px;font-weight:600;font-size:.86em;white-space:nowrap;position:sticky;top:0;z-index:2}
td{padding:8px;border-bottom:1px solid var(--line);text-align:center;background:#fff;white-space:nowrap}
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
/* 山名列の右端に境界線 (横スクロール時に固定範囲の右端が視認しやすい) */
th:nth-child(2),td.nm{box-shadow:inset -1px 0 0 var(--line)}
td.nm a{color:var(--link);font-weight:700;text-decoration:none}
td.nm a:hover{text-decoration:underline}
td.nm small{display:block;color:#8a94a8;font-size:.82em;font-weight:400}
/* 結果ブロックの見出しと注記 (メイン表 / 足切り表を分ける) */
h3.results-h{margin:18px 0 4px;font-size:1em;color:var(--night);font-weight:700}
h3.results-h.caution{color:#b26b00}
h3.results-h .rcount{color:#556;font-weight:500;font-size:.9em;margin-left:6px}
.rnote{margin:4px 0 0;font-size:.82em;color:#5b6b8a}
.rnote.caution{color:#b26b00;background:#fff8e6;border-left:4px solid #b26b00;padding:6px 10px;border-radius:0 4px 4px 0}
.rnote a{color:var(--link)}
/* 表の下に置く「各列の意味」凡例。ユーザーが「気温が2つあるが説明がない」等で
   迷わないよう、列ごとの意味と単位・対象時間帯を短い1行で列挙する。 */
.legend{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:14px 0 6px;font-size:.85em;color:#44506b}
.legend h4{margin:0 0 6px;font-size:.95em;color:var(--night);font-weight:700}
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
.wxnote{display:block;font-size:.72em;color:#6b7280;margin-top:2px;line-height:1.25}
.num{font-variant-numeric:tabular-nums}
.rank{color:#8a94a8;font-variant-numeric:tabular-nums}

footer{color:#888;font-size:.82em;margin-top:26px;border-top:1px solid var(--line);padding-top:10px;padding-bottom:16px}
footer a{color:var(--link)}

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

<div class="searchcard">
  <div class="row">
    <label>エリア
      <select id="region"></select>
    </label>
    <label>都道府県
      <select id="pref"><option value="">すべて</option></select>
    </label>
    <label>日付
      <select id="date"></select>
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

<div class="notice">
📅 対象は<b>今日〜2日先の3日間</b>です。天気の正確性を担保するため、日本域に最適化された
<b>気象庁モデル（MSM・約5kmメッシュ）</b>が採点に必要なデータ（とくに日照）を配信する範囲に
合わせて期間を絞りました。以前は14日間表示していましたが、後半は精度が「傾向」の域を出ず、
山を選び分ける用途には向かなかったためです。
今後、別の予報モデルと組み合わせて期間を延ばすかは<b>検討中</b>です。
</div>

<div id="results"></div>

<footer>
<a href="../index.html">← PeakWeather トップへ戻る</a> /
<a href="mountains.html">対応している山の一覧</a> /
天気データ: Open-Meteo (CC BY 4.0) / 気象庁モデル (MSM)
</footer>

</main>

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
  if(typeof pwGuardPage!=="function"){
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
      elDate=document.getElementById("date"),elGo=document.getElementById("go"),
      elHint=document.getElementById("hint"),elStatus=document.getElementById("status"),
      elResults=document.getElementById("results");

  // ---- 日付の選択肢 (今日〜2日先の3個・曜日つき) ----
  // 3日なのは気象庁モデル(MSM)の都合。スコアの主要素である日照(sunshine_duration)は
  // MSM 期間ぶんしか配信されず、4日目以降は 7:00〜15:59 が丸ごと欠測になる。
  // 「日照ぬきの薄いスコア」を出すより、確実に採点できる範囲に絞る方針。
  // 別モデルの併用で期間を延ばすかは検討中。延ばすならまず日照の代替をどう作るかから。
  // index.html と同じ方式: <select> に「07/25(土) 今日」形式の option を並べる。
  // input[type=date] だと iOS/PCで曜日が出ない・実装差でカードから溢れるなどの問題が
  // あったため、明示的に「日付+曜日」を全部option文言に埋め込む方式に統一。
  var WJA="日月火水木金土";
  function iso(d){return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")}
  function md(d){return String(d.getMonth()+1).padStart(2,"0")+"/"+String(d.getDate()).padStart(2,"0")}
  (function(){
    var today=new Date();today.setHours(0,0,0,0);
    for(var i=0;i<3;i++){
      var d=new Date(today);d.setDate(d.getDate()+i);
      var o=document.createElement("option");
      o.value=iso(d);
      o.textContent=md(d)+"("+WJA[d.getDay()]+")"+(i===0?" 今日":i===1?" 明日":"");
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
  function targets(){
    var r=elRegion.value,p=elPref.value;
    return MOUNTAINS.filter(function(m){
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
    elHint.textContent=msg;
  }
  elRegion.addEventListener("change",fillPrefs);
  elPref.addEventListener("change",updateHint);

  // ---- 稜線風速の補間 (index.html / mountain_weather.py と同一ロジック) ----
  // 山頂標高を挟む上下2気圧面の風速を線形補間して「稜線風速」を推定する。
  // LEVELS[i]=[気圧面hPa, 標準高度m]。 500m台の里山から3800m級までを 6面でカバー。
  var LEVELS=[[925,760],[900,990],[850,1460],[800,1950],[700,3010],[600,4200]];
  function bracket(elev){
    for(var i=0;i<LEVELS.length-1;i++){
      var lo=LEVELS[i], hi=LEVELS[i+1];
      if(elev>=lo[1]&&elev<=hi[1])return {lo:lo,hi:hi,t:(elev-lo[1])/(hi[1]-lo[1])};
    }
    return elev<LEVELS[0][1]
      ? {lo:LEVELS[0],hi:LEVELS[0],t:0}
      : {lo:LEVELS[LEVELS.length-1],hi:LEVELS[LEVELS.length-1],t:0};
  }
  // 対象時間帯: 7:00〜15:59 (hour 7〜15 の 9時間、登山コアタイム)
  function inRange(t){var h=parseInt(t.slice(11,13),10);return h>=7&&h<=15}

  // ---- Open-Meteo 気象庁モデル (daily は積雪のみ、hourly で7:00〜15:59集計) ----
  // 降水確率は気象庁モデルに存在しない(投げても 400 にならず全 null で返る)ため、
  // 本体(index.html)と同じく別モデルから補完する。ただし find では
  // 「表に出す参考値」だけの扱いで、スコアの減点には一切使わない(降水量-30に一本化したまま)。
  var JMA_URL="https://api.open-meteo.com/v1/jma";
  var FC_URL="https://api.open-meteo.com/v1/forecast";
  var DAILY="snowfall_sum";
  var HOURLY="weather_code,temperature_2m,precipitation,"+
    "sunshine_duration,wind_speed_925hPa,wind_speed_900hPa,wind_speed_850hPa,"+
    "wind_speed_800hPa,wind_speed_700hPa,wind_speed_600hPa";
  var SUPP_HOURLY="precipitation_probability";
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
  async function apiJson(url,params,retries){
    retries=retries||3;var lastErr;
    for(var a=1;a<=retries;a++){
      try{
        var r=await fetch(url+"?"+new URLSearchParams(params));
        if(!r.ok){if(r.status<500)throw Object.assign(new Error("HTTP "+r.status),{fatal:true});throw new Error("HTTP "+r.status)}
        return await r.json();
      }catch(e){lastErr=e;if(e.fatal||a===retries)break;await new Promise(function(res){setTimeout(res,1200*a)})}
    }
    throw new Error("API呼び出しに失敗しました: "+(lastErr&&lastErr.message||lastErr));
  }
  async function fetchChunk(ms,date){
    var lat=ms.map(function(m){return m.lat}).join(","),
        lon=ms.map(function(m){return m.lon}).join(","),
        el =ms.map(function(m){return m.el }).join(",");
    // 基本は気象庁モデル。降水確率だけ別モデルから補完する(1変数だけの軽いリクエスト)。
    // 2本を並行に投げ、地点ごとに時刻キーで貼り合わせる。
    var res=await Promise.all([
      apiJson(JMA_URL,{latitude:lat,longitude:lon,elevation:el,
        daily:DAILY,hourly:HOURLY,timezone:"Asia/Tokyo",wind_speed_unit:"ms",
        start_date:date,end_date:date}),
      apiJson(FC_URL,{latitude:lat,longitude:lon,elevation:el,
        hourly:SUPP_HOURLY,timezone:"Asia/Tokyo",
        start_date:date,end_date:date})
    ]);
    var base=Array.isArray(res[0])?res[0]:[res[0]]; // 単一地点はオブジェクトで返る
    var sup =Array.isArray(res[1])?res[1]:[res[1]];
    // 同じ座標列を送っているので地点の並びは一致する
    for(var i=0;i<base.length;i++)
      mergeSeries(base[i].hourly,(sup[i]&&sup[i].hourly)||{},[SUPP_HOURLY]);
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
      return null;
    }
    // 稜線風速: 山頂標高を挟む2気圧面を bracket() で選び、各時刻を線形補間して max
    var bra=bracket(mt.el), ridgeWmax=null;
    var loArr=hr&&hr["wind_speed_"+bra.lo[0]+"hPa"];
    var hiArr=hr&&hr["wind_speed_"+bra.hi[0]+"hPa"];
    if(loArr&&hiArr){
      var mv=0, has=false;
      for(var i=0;i<N;i++){
        if(!inRange(times[i]))continue;
        var lo=loArr[i], hi=hiArr[i];
        if(lo==null||hi==null)continue;
        var v=lo*(1-bra.t)+hi*bra.t;
        if(v>mv)mv=v; has=true;
      }
      if(has)ridgeWmax=mv;
    }
    // 日照率: 7:00〜15:59 の sunshine_duration 合計 / (9h × 3600s)
    var sunSum=agg("sunshine_duration","sum");
    var sunFrac=sunSum==null?null:Math.max(0,Math.min(1,sunSum/(9*3600)));
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
    if(sunFrac==null&&code==null&&psum==null&&ridgeWmax==null)return null;
    var s=100;
    // ① 晴天度 (最大 -28)
    if(sunFrac!=null)s-=(1-sunFrac)*28;
    else if(code!=null)s-=code<=1?0:code===2?8:code===3?18:22;
    // 天気コードの悪天(雨雪雷)を軽く上乗せ
    if(code!=null){if(code>=95)s-=8;else if(code>=71&&code<=86)s-=5;else if(code>=51&&code<=82)s-=4}
    // ② 降水量 (最大 -30) - 行動可否に効くのは実際に降る量。
    // 以前は「確率-10 / 量-20」だったが、気象庁モデルに降水確率が無いため量に一本化した。
    // 降水確率(pprob)は表には出すが、ここには足さない(スコアの意味を変えないため)
    if(psum!=null)s-=Math.min(psum,10)/10*30;
    // ③ 稜線風 (最大 -32) - 6m/s以下=0、18m/s以上=最大
    if(ridgeWmax!=null)s-=Math.max(0,Math.min(1,(ridgeWmax-6)/12))*32;
    // ④ 雪・寒気 (最大 -10)
    if(snow!=null&&snow>0)s-=Math.min(snow,5)/5*5;
    if(tmin!=null&&tmin<-5)s-=Math.min((-5-tmin),15)/15*5;
    return {v:Math.round(Math.max(0,Math.min(100,s))),sunFrac:sunFrac,code:code,wxRep:wxRep,
      psum:psum,pprob:pprob,ridgeWmax:ridgeWmax,tmax:tmax,tmin:tmin};
  }
  // 安全性の足切り: 稜線風速 >=18m/s または 降水量 >=10mm のいずれかで別表送り
  function isDangerous(s){
    return (s.ridgeWmax!=null&&s.ridgeWmax>=18)||(s.psum!=null&&s.psum>=10);
  }
  // 足切り理由のラベル (足切り表の「理由」列に表示)
  function reasonLabel(s){
    var parts=[];
    if(s.ridgeWmax!=null&&s.ridgeWmax>=18)parts.push("稜線風 "+Math.round(s.ridgeWmax)+"m/s");
    if(s.psum!=null&&s.psum>=10)parts.push("降水量 "+Math.round(s.psum)+"mm");
    return parts.join(" / ");
  }

  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
  function pct(f){return f==null?"-":Math.round(f*100)+"%"}
  function fnum(v,u){return v==null?"-":Math.round(v)+u}
  // 降水量は「小雨(0.1〜0.9mm)」を丸めて 0mm と表示してしまうと誤解を招くため、小数1桁で表示する
  function pmm(v){if(v==null)return "-";if(v<0.05)return "0.0mm";return v.toFixed(1)+"mm"}
  // スコアの A/B/C ランク色分け (find-score.html の閾値と一致: A>=70 / B>=45 / C<45)
  function rankOf(v){return v>=70?"a":v>=45?"b":"c"}

  // ---- 検索実行 ----
  // キー接頭辞の数字は保存形式のバージョン。sc の中身を変えたら必ず上げる
  // (find2: 代表天気 wxRep を追加 / find3: wxRep.notes を [{h,t}] 形式にし fair を追加
  //  / find4: 降水の配点を 確率-10・量-20 に変更しスコア値の意味が変わった
  //  / find5: 取得元を気象庁モデルに変更・対象を3日に短縮・降水を量-30に一本化
  //  / find6: 降水確率を別モデルから取り直し、表示専用フィールド pprob として復活)。
  // 上げ忘れると旧キャッシュがそのまま復元され、天気列だけ古い表示になる。
  function cacheKey(r,p,date){return "find6:"+r+":"+p+":"+date}
  // 直近の検索条件を保存するキー。ページを再訪した時にセレクタと結果を復元する用途
  // (bfcache が効かない iOS 直リンク等のフォールバック。詳細は末尾の restoreLastSearch)。
  var LAST_KEY="find6:last";
  async function search(fromRestore){
    if(needsPrefSelection()){elStatus.textContent="都道府県を選択してから検索してください";return}
    var ms=targets(),date=elDate.value,r=elRegion.value,p=elPref.value;
    if(!ms.length){elStatus.textContent="対象の山がありません";return}
    elStatus.className="";elResults.innerHTML="";elGo.disabled=true;
    try{
      var key=cacheKey(r,p,date),cached=null;
      try{cached=JSON.parse(sessionStorage.getItem(key)||"null")}catch(e){}
      var rows;
      if(cached){elStatus.textContent=fromRestore?"前回の検索結果を復元しました":"キャッシュから表示中…";rows=cached}
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
        try{sessionStorage.setItem(key,JSON.stringify(rows))}catch(e){}
      }
      // 復元用に「最後の検索条件」を保存 (実際の rows は cacheKey 側に既に入っている)
      try{sessionStorage.setItem(LAST_KEY,JSON.stringify({r:r,p:p,date:date}))}catch(e){}
      render(rows,date);
      // 足切り分離した内訳をステータスに出す
      var safeN=rows.filter(function(x){return !isDangerous(x.sc)}).length;
      var cautionN=rows.length-safeN;
      elStatus.textContent=r+(p?" / "+p:"")+" の "+date+" — 登れそう "+safeN+"座"+
        (cautionN?" / 要慎重 "+cautionN+"座":"");
      // アクセス解析: 前回条件の自動復元(fromRestore)は利用者の検索操作ではないので数えない
      if(!fromRestore)pwTrack("find_search",{pw_region:r,pw_result:"success"});
    }catch(e){
      elStatus.className="err";elStatus.textContent=String(e.message||e);
      if(!fromRestore)pwTrack("find_search",{pw_region:r,pw_result:"error"});
    }finally{elGo.disabled=false}
  }

  // 表 1行分の HTML (メイン/足切り共通、caution=true で「理由」列を出す)
  function rowHtml(row,i,date,caution){
    var m=row.mt,s=row.sc;
    var href="../index.html#"+encodeURIComponent(m.n)+"/"+date;
    var wx=dispWx(s);
    var reason=caution?'<td class="reason">⚠ '+esc(reasonLabel(s))+'</td>':'';
    return '<tr>'+
      '<td class="rank">'+(i+1)+'</td>'+
      '<td class="nm">'+
        '<div class="nmrow">'+
          '<a href="'+href+'">'+esc(m.n)+'</a>'+
          '<span class="scb rank-'+rankOf(s.v)+'">'+s.v+'</span>'+
        '</div>'+
        '<small>'+esc(m.pref)+' / '+m.el+'m</small>'+
      '</td>'+
      reason+
      '<td>'+(wx.ic?'<svg class="wxico" aria-hidden="true"><use href="#'+wx.ic+'"/></svg>':"-")+
            '<span class="wxlbl">'+esc(wx.lb)+'</span>'+
            (wx.nt&&wx.nt.length?'<span class="wxnote">'+esc(wx.nt.join(" / "))+'</span>':"")+'</td>'+
      '<td class="num">'+pct(s.sunFrac)+'</td>'+
      '<td class="num">'+fnum(s.tmax,"")+' / '+fnum(s.tmin,"℃")+'</td>'+
      '<td class="num">'+fnum(s.ridgeWmax,"m/s")+'</td>'+
      '<td class="num">'+(s.pprob==null?"-":Math.round(s.pprob)+"%")+'</td>'+
      '<td class="num">'+pmm(s.psum)+'</td>'+
      '</tr>';
  }

  function tableHtml(rows,date,caution){
    var head='<tr><th>#</th><th>山名 / スコア</th>'+
      (caution?'<th>理由</th>':'')+
      '<th>天気</th><th>日照</th><th>気温</th><th>稜線風</th><th>降水確率</th><th>降水量</th></tr>';
    var body='';
    rows.forEach(function(row,i){body+=rowHtml(row,i,date,caution)});
    return '<div class="tbl'+(caution?' caution':'')+'"><table><thead>'+head+
      '</thead><tbody>'+body+'</tbody></table></div>';
  }

  // 表の下に置く「各列の意味」凡例 (対象時間帯・単位・スコア色分けの説明つき)
  var LEGEND_HTML=(
    '<div class="legend"><h4>表の見方</h4>'+
    '<dl>'+
    '<dt>スコア</dt><dd>0〜100 の総合コンディション値 (大きいほど良い)。'+
      '<span class="rk rk-a">A</span>70〜100 '+
      '<span class="rk rk-b">B</span>45〜69 '+
      '<span class="rk rk-c">C</span>0〜44 '+
      '色は山名脇のスコアに反映(<a href="find-score.html">計算方法</a>)</dd>'+
    '<dt>天気</dt><dd>7:00〜15:59 の代表天気。<b>最も長い時間を占めた天気</b>を採用し、'+
      '強い雨・雪・雷は1時間でも含まれれば優先して表示。降水が代表でない日は日照率で'+
      '「よく晴れ・晴れ・時々晴れ・曇りがち」を判定。代表とならなかった天気は下段へ小さく併記する'+
      '(晴れが代表なら「昼過ぎに霧雨」、雨・雪・雷が代表なら「朝〜昼過ぎは晴れ」など。'+
      '<a href="find-score.html">判定の手順</a>)</dd>'+
    '<dt>日照</dt><dd>7:00〜15:59 のうち日照が見込まれる時間の割合 (0〜100%)</dd>'+
    '<dt>気温</dt><dd>7:00〜15:59 の <b>最高 / 最低</b> 気温 (℃)。'+
      '山頂標高で標高補正済み (Open-Meteo の elevation パラメータ経由。乾燥断熱減率 約0.65℃/100m)</dd>'+
    '<dt>稜線風</dt><dd>山頂標高で推定した稜線風速の 7:00〜15:59 最大値 (m/s)。'+
      '地表10mではなく気圧面から線形補間した値</dd>'+
    '<dt>降水確率</dt><dd>7:00〜15:59 の1時間ごとの降水確率の最大値 (%)。'+
      '<b>参考表示のみでスコアには影響しません</b>。気象庁モデルは降水確率を配信していないため、'+
      'この列だけ別の予報モデルから取得しています(隣の降水量とは出どころが違います)</dd>'+
    '<dt>降水量</dt><dd>7:00〜15:59 の降水量の合計 (mm)。'+
      'スコアと足切り(⚠ 慎重に判断が必要)に直接影響する</dd>'+
    '</dl></div>');

  function render(rows,date){
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
      h+='<p class="rnote caution">稜線風速 18m/s 以上、または 7:00〜15:59 の降水量 10mm 以上。'+
         '登山に不適格の可能性が高いため、参考として下位に表示しています。</p>';
      h+=tableHtml(caution,date,true);
    }
    h+='<p class="rnote">※ スコアは <b>登山コアタイム 7:00〜15:59</b> の気象値で算定しています。'+
       '<a href="find-score.html">計算方法の詳細</a></p>';
    // 表下部に「各列の意味」凡例。気温が2つある/天気の判定基準など、初見でも列の意味が
    // 分かるようにする。1回だけ表示(メイン表と足切り表のどちらか(または両方)が出た時)。
    h+=LEGEND_HTML;
    elResults.innerHTML=h;
  }

  elGo.addEventListener("click",function(){search(false)});

  // 山名リンクを押したとき、遷移先(index.html)に「この一覧から来た」ことを1回だけ伝える。
  // index.html 側は読んだ直後に削除するので、その回の詳細予報にだけ「一覧に戻る」が出る。
  // 行ごとの onclick 属性ではなく委譲リスナー1本にして、生成HTMLを軽く保つ。
  elResults.addEventListener("click",function(e){
    var a=e.target.closest?e.target.closest("td.nm a"):null;
    if(a)try{sessionStorage.setItem("pw_entry","find")}catch(err){}
  });

  // ---- 直近の検索条件を自動復元 ----
  // find.html を再訪した時 (bfcache が効かず新規ロードされたケース)、前回の検索条件を
  // sessionStorage から読んでセレクタを復元し、対応する cacheKey にヒットすれば
  // 自動で render() まで進める。Open-Meteo は叩かない(キャッシュヒット時)。
  // 個別予報 (index.html) から「一覧に戻る」した時、条件と結果が復元される導線として機能。
  function restoreLastSearch(){
    var last;
    try{last=JSON.parse(sessionStorage.getItem(LAST_KEY)||"null")}catch(e){}
    if(!last||!last.r||!last.date)return;
    // 東北など初期値を東北から書き換えた場合のみ発動 (無条件だと初回訪問でも動いてしまう)
    if(!Array.prototype.some.call(elRegion.options,function(o){return o.value===last.r}))return;
    elRegion.value=last.r;
    fillPrefs();
    if(last.p){
      if(Array.prototype.some.call(elPref.options,function(o){return o.value===last.p})){
        elPref.value=last.p;
      }
    }
    if(Array.prototype.some.call(elDate.options,function(o){return o.value===last.date})){
      elDate.value=last.date;
    }else{
      // 日付が期限切れ (3日ウインドウを外れた) 場合は復元スキップ (キャッシュヒットしない)
      return;
    }
    updateHint();
    // cacheKey にヒットする場合だけ自動描画。ヒットしない場合はセレクタだけ復元して手動検索を待つ。
    var key=cacheKey(last.r,last.p||"",last.date);
    var hit=null;try{hit=sessionStorage.getItem(key)}catch(e){}
    if(hit)search(true);
  }

  fillPrefs();
  restoreLastSearch();
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
