# -*- coding: utf-8 -*-
"""index.html の MOUNTAINS 配列から docs/find.html (コンディション横断検索) を生成する。

「その日に天気の良さそうな山を、まず見つけたい」という逆引きの入口。
エリア(9地方)+ 任意で県 + 単日 を指定 → その範囲の山を Open-Meteo の daily 値だけ
バッチ取得し、簡易スコア(晴天度を最重視)でランキング表示。行をタップすると
既存の詳細予報 (../index.html#山名/日付) が開く。

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
<!-- このファイルは scripts/gen_find.py により index.html から自動生成されます。直接編集しないでください -->
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
.searchcard label{display:flex;flex-direction:column;gap:5px;font-size:.82em;font-weight:600;color:#556;flex:1 1 150px}
.searchcard select,.searchcard input{font-size:16px;padding:11px 12px;border:1.5px solid var(--field);border-radius:10px;
  background:#fff;width:100%;font-family:inherit}
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
/* 山名列: 日本語CJKは基本改行させず1行で表示(word-break:keep-all)、極端に長い山名(9文字以上)だけ
   max-width を超えた時に折り返しを許容(overflow-wrap:break-word)。td共通の white-space:nowrap は
   normal に戻す(white-space:nowrap と overflow-wrap:anywhere は仕様上両立しないため)。 */
td.nm{text-align:left;white-space:normal;min-width:8em;max-width:16em;word-break:keep-all;overflow-wrap:break-word}
/* スマホで横スクロール時にどの山を見ているか分かるよう、ランク列(#)と山名列を左端に固定する
   (index.htmlの日付列 sticky-left と同じ考え方)。ランク列を固定幅にして山名列の left オフセット
   を予測可能にした。角の交差セル(th)は元々 z-index:2、tdは z-index:1 で thの下に潜る。 */
th:first-child,td.rank{width:34px;min-width:34px;max-width:34px;padding-left:6px;padding-right:6px}
th:first-child,td.rank{position:sticky;left:0}
th:nth-child(2),td.nm{position:sticky;left:34px}
td.rank,td.nm{z-index:1}
/* 偶数行の背景色が透けないよう明示 (sticky で親の背景が引き継がれないため) */
tr:nth-child(even) td.rank,tr:nth-child(even) td.nm{background:#eef1f6}
/* 山名列の右端に境界線 (横スクロール時に固定範囲の右端が視認しやすい) */
th:nth-child(2),td.nm{box-shadow:inset -1px 0 0 var(--line)}
td.nm a{color:var(--link);font-weight:700;text-decoration:none}
td.nm a:hover{text-decoration:underline}
td.nm small{display:block;color:#8a94a8;font-size:.82em;font-weight:400}
/* 天気アイコン: index.html と同じSVG(#wx-sun 等)を参照。emoji のOS依存表示ズレを回避 */
.wxico{width:1.9em;height:1.9em;display:block;margin:0 auto 2px}
.wxlbl{color:#556;font-size:.82em}
.sc{font-weight:800;font-variant-numeric:tabular-nums}
.stars{color:#e0a92b;letter-spacing:1px;font-size:.9em;display:block}
.num{font-variant-numeric:tabular-nums}
.rank{color:#8a94a8;font-variant-numeric:tabular-nums}
.sc-a{color:#1f7a34}.sc-b{color:#b26b00}.sc-c{color:#b3261e}

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
    <label>県でしぼり込み
      <select id="pref"><option value="">すべて</option></select>
    </label>
    <label>日付
      <input id="date" type="date">
    </label>
  </div>
  <button class="go" id="go">この条件でさがす</button>
  <p class="hint" id="hint"></p>
</div>

<p id="status"></p>

<div class="notice">
この一覧は<b>晴天度を最重視した「ざっくり比較用」の簡易スコア</b>です(山頂への標高補正はしていません)。
実際に登る前に、気になる山をタップして<b>正式な登山指数A/B/C・稜線の風・時間帯別</b>の詳しい予報を必ず確認してください。
</div>

<div id="results"></div>

<footer>
<a href="../index.html">← PeakWeather トップへ戻る</a> /
<a href="mountains.html">対応している山の一覧</a> /
天気データ: Open-Meteo (CC BY 4.0)
</footer>

</main>

<script>
"use strict";
(function(){
  var MOUNTAINS=__MOUNTAINS_JSON__;
  var REGION_ORDER=__REGION_ORDER__;
  var CHUNK=50;                 // 1リクエストあたりの最大地点数(負荷抑制)
  var PREF_ORDER=__PREF_ORDER__;

  var WMO={0:"快晴",1:"晴れ",2:"晴れ時々曇り",3:"曇り",45:"霧",48:"着氷性の霧",
   51:"霧雨",53:"霧雨",55:"霧雨(強)",56:"着氷性霧雨",57:"着氷性霧雨(強)",
   61:"雨(弱)",63:"雨",65:"雨(強)",66:"着氷性の雨",67:"着氷性の雨(強)",
   71:"雪(弱)",73:"雪",75:"雪(強)",77:"霧雪",80:"にわか雨",81:"にわか雨",82:"にわか雨(強)",
   85:"にわか雪",86:"にわか雪(強)",95:"雷雨",96:"雷雨(雹)",99:"雷雨(激しい雹)"};
  function wlabel(c){return c==null?"-":(WMO[c]||("code"+c))}
  // 天気列は「日照率」ベースで表示する。daily.weather_code は24hのmax値で、短時間の霧/
  // 霧雨が晴主体の日を乗っ取り「曇り なのに日照97%」のような矛盾を生むため主指標にしない。
  // 降水リスクは別列(降水確率)に任せる。日照率が取れない時だけ weather_code で代替。
  // ic は index.html と共通のSVGシンボルID(#wx-sun 等)。emojiのOS依存表示ズレを避ける。
  function dispWx(s){
    var f=s.sunFrac;
    if(f==null){
      var c=s.code,ic;
      if(c==null)ic=null;
      else if(c>=95)ic="wx-thunder";
      else if(c>=71&&c<=77||c===85||c===86)ic="wx-snow";
      else if(c>=51&&c<=67||c>=80&&c<=82)ic="wx-rain";
      else if(c===45||c===48)ic="wx-fog";
      else if(c===3)ic="wx-cloud";
      else if(c===2)ic="wx-suncloud";
      else ic="wx-sun";
      return {ic:ic,lb:wlabel(c)};
    }
    if(f>=0.80)return {ic:"wx-sun",     lb:"よく晴れ"};
    if(f>=0.55)return {ic:"wx-suncloud",lb:"晴れ"};
    if(f>=0.30)return {ic:"wx-suncloud",lb:"時々晴れ"};
    return       {ic:"wx-cloud",  lb:"曇りがち"};
  }

  var elRegion=document.getElementById("region"),elPref=document.getElementById("pref"),
      elDate=document.getElementById("date"),elGo=document.getElementById("go"),
      elHint=document.getElementById("hint"),elStatus=document.getElementById("status"),
      elResults=document.getElementById("results");

  // ---- 日付の初期値/範囲 ----
  function iso(d){return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")}
  var today=new Date();today.setHours(0,0,0,0);
  var horizon=new Date(today);horizon.setDate(horizon.getDate()+15);
  elDate.value=iso(today);elDate.min=iso(today);elDate.max=iso(horizon);

  // ---- エリア/県セレクタ ----
  REGION_ORDER.forEach(function(r){
    var c=MOUNTAINS.filter(function(m){return m.reg===r}).length;
    if(!c)return;
    var o=document.createElement("option");o.value=r;o.textContent=r+" ("+c+"座)";elRegion.appendChild(o);
  });
  function fillPrefs(){
    var r=elRegion.value;
    elPref.innerHTML='<option value="">すべて</option>';
    var counts={};
    MOUNTAINS.forEach(function(m){if(m.reg===r){var p=m.pref.split("・")[0];counts[p]=(counts[p]||0)+1}});
    PREF_ORDER.forEach(function(p){
      if(!counts[p])return;
      var o=document.createElement("option");o.value=p;o.textContent=p+" ("+counts[p]+"座)";elPref.appendChild(o);
    });
    updateHint();
  }
  function targets(){
    var r=elRegion.value,p=elPref.value;
    return MOUNTAINS.filter(function(m){
      if(m.reg!==r)return false;
      if(p&&m.pref.split("・")[0]!==p)return false;
      return true;
    });
  }
  function updateHint(){
    var n=targets().length;
    var reqs=Math.ceil(n/CHUNK);
    var msg="対象 "+n+"座";
    if(reqs>1)msg+=" / "+reqs+"回に分けて取得します。県でしぼると1回で済み負荷を抑えられます";
    else msg+=" / 1回の取得で完了します";
    elHint.textContent=msg;
  }
  elRegion.addEventListener("change",fillPrefs);
  elPref.addEventListener("change",updateHint);

  // ---- Open-Meteo (daily・単日) ----
  var DAILY="weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"+
    "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,"+
    "sunshine_duration,daylight_duration,snowfall_sum";
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
    var params={
      latitude:ms.map(function(m){return m.lat}).join(","),
      longitude:ms.map(function(m){return m.lon}).join(","),
      elevation:ms.map(function(m){return m.el}).join(","),
      daily:DAILY,timezone:"Asia/Tokyo",wind_speed_unit:"ms",
      start_date:date,end_date:date
    };
    var data=await apiJson("https://api.open-meteo.com/v1/forecast",params);
    return Array.isArray(data)?data:[data]; // 単一地点はオブジェクトで返る
  }

  // ---- 簡易スコア(0-100)。晴天度を最重視 ----
  function score(d){
    var g=function(k){return d.daily&&d.daily[k]?d.daily[k][0]:null};
    var sun=g("sunshine_duration"),day=g("daylight_duration");
    var sunFrac=(sun!=null&&day)?Math.max(0,Math.min(1,sun/day)):null;
    var code=g("weather_code"),pprob=g("precipitation_probability_max"),
        psum=g("precipitation_sum"),wmax=g("wind_speed_10m_max"),
        gust=g("wind_gusts_10m_max"),snow=g("snowfall_sum"),
        tmax=g("temperature_2m_max"),tmin=g("temperature_2m_min");
    var s=100;
    // ① 晴天度(最重要): 日照率が主。取れない時は天気コードで代替
    if(sunFrac!=null)s-=(1-sunFrac)*45;
    else if(code!=null)s-=code<=1?0:code===2?12:code===3?28:35;
    // 天気コードの悪天(雨雪雷)を軽く上乗せ
    if(code!=null){if(code>=95)s-=12;else if(code>=71&&code<=86)s-=8;else if(code>=51&&code<=82)s-=6}
    // ② 降水
    if(pprob!=null)s-=pprob/100*15;
    if(psum!=null)s-=Math.min(psum,10)/10*10;
    // ③ 風(稜線の目安。地表10m値なので相対比較用)
    if(wmax!=null)s-=Math.max(0,Math.min(1,(wmax-4)/12))*15;
    if(gust!=null)s-=Math.max(0,Math.min(1,(gust-8)/22))*5;
    // ④ 雪・寒気
    if(snow!=null&&snow>0)s-=Math.min(snow,5)/5*5;
    if(tmin!=null&&tmin<-5)s-=Math.min((-5-tmin),15)/15*5;
    return {v:Math.round(Math.max(0,Math.min(100,s))),sunFrac:sunFrac,code:code,pprob:pprob,
      wmax:wmax,tmax:tmax,tmin:tmin};
  }

  function stars(v){var n=Math.max(1,Math.round(v/20));return "★★★★★".slice(0,n)+"☆☆☆☆☆".slice(0,5-n)}
  function scClass(v){return v>=70?"sc-a":v>=45?"sc-b":"sc-c"}
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
  function pct(f){return f==null?"-":Math.round(f*100)+"%"}
  function fnum(v,u){return v==null?"-":Math.round(v)+u}

  // ---- 検索実行 ----
  function cacheKey(r,p,date){return "find:"+r+":"+p+":"+date}
  async function search(){
    var ms=targets(),date=elDate.value,r=elRegion.value,p=elPref.value;
    if(!ms.length){elStatus.textContent="対象の山がありません";return}
    elStatus.className="";elResults.innerHTML="";elGo.disabled=true;
    try{
      var key=cacheKey(r,p,date),cached=null;
      try{cached=JSON.parse(sessionStorage.getItem(key)||"null")}catch(e){}
      var rows;
      if(cached){elStatus.textContent="キャッシュから表示中…";rows=cached}
      else{
        var chunks=[];for(var i=0;i<ms.length;i+=CHUNK)chunks.push(ms.slice(i,i+CHUNK));
        rows=[];
        for(var ci=0;ci<chunks.length;ci++){
          elStatus.textContent="予報を取得中… ("+(ci+1)+"/"+chunks.length+")";
          var arr=await fetchChunk(chunks[ci],date);
          for(var j=0;j<chunks[ci].length;j++){
            var mt=chunks[ci][j],sc=arr[j]?score(arr[j]):null;
            if(sc)rows.push({mt:mt,sc:sc});
          }
        }
        rows.sort(function(a,b){return b.sc.v-a.sc.v});
        try{sessionStorage.setItem(key,JSON.stringify(rows))}catch(e){}
      }
      render(rows,date);
      elStatus.textContent=r+(p?" / "+p:"")+" の "+date+" — "+rows.length+"座を晴天度順に表示";
    }catch(e){
      elStatus.className="err";elStatus.textContent=String(e.message||e);
    }finally{elGo.disabled=false}
  }

  function render(rows,date){
    var h='<div class="tbl"><table><thead><tr>'+
      '<th>#</th><th>山名</th><th>天気</th><th>日照</th><th>気温</th><th>風</th><th>降水</th><th>スコア</th>'+
      '</tr></thead><tbody>';
    rows.forEach(function(row,i){
      var m=row.mt,s=row.sc;
      var href="../index.html#"+encodeURIComponent(m.n)+"/"+date;
      var wx=dispWx(s);
      // クリック時に「find経由」フラグをセット → 詳細ページ側で「一覧に戻る」を表示
      var oc=' onclick="sessionStorage.setItem(\'pw_from_find\',\'1\')"';
      h+='<tr>'+
        '<td class="rank">'+(i+1)+'</td>'+
        '<td class="nm"><a href="'+href+'"'+oc+'>'+esc(m.n)+'</a><small>'+esc(m.pref)+' / '+m.el+'m</small></td>'+
        '<td>'+(wx.ic?'<svg class="wxico" aria-hidden="true"><use href="#'+wx.ic+'"/></svg>':"-")+
              '<span class="wxlbl">'+esc(wx.lb)+'</span></td>'+
        '<td class="num">'+pct(s.sunFrac)+'</td>'+
        '<td class="num">'+fnum(s.tmax,"")+' / '+fnum(s.tmin,"℃")+'</td>'+
        '<td class="num">'+fnum(s.wmax,"m/s")+'</td>'+
        '<td class="num">'+(s.pprob==null?"-":s.pprob+"%")+'</td>'+
        '<td class="sc '+scClass(s.v)+'">'+s.v+'<span class="stars">'+stars(s.v)+'</span></td>'+
        '</tr>';
    });
    h+='</tbody></table></div>';
    elResults.innerHTML=h;
  }

  elGo.addEventListener("click",search);
  fillPrefs();
})();
</script>

</body>
</html>
"""


def main():
    mountains = load_mountains()
    total = len(mountains)
    mountains_json = build_mountain_json(mountains)
    region_order = json.dumps([name for name, _ in REGIONS], ensure_ascii=False)
    # 県の表示順は REGIONS の定義順(北→南)で安定させる
    pref_order = json.dumps([p for _, prefs in REGIONS for p in prefs],
                            ensure_ascii=False)

    html = (TEMPLATE
            .replace("__MOUNTAINS_JSON__", mountains_json)
            .replace("__REGION_ORDER__", region_order)
            .replace("__PREF_ORDER__", pref_order))
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"docs/find.html を生成しました (全{total}座 / 横断検索ページ)")


if __name__ == "__main__":
    main()
