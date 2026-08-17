"use strict";
/* PeakWeather 判定ロジック — 登山指数 A/B/C とその材料を計算する関数の唯一の置き場。
 *
 * index.html(詳細予報) と docs/find.html(山さがし) の両方がこのファイルを読む。
 * かつては同じ判定が2本のJSで書かれており(index.html の blockIndex と find の formalIndex)、
 * 片方だけ直すと静かにズレる状態だった。ここに1本化したので、**判定を変えるときに触るのは
 * このファイルと scripts/mountain_weather.py の2箇所だけ**になる(CLAUDE.md 規約3)。
 *
 * ★ scripts/mountain_weather.py(CLI) と同一ロジックであることは
 *   references/logic_cases.json の入出力表で機械的に検証している。
 *   式やしきい値を変えたら、必ず Python 側・ケース表・references/criteria.md も同時に直すこと。
 *     python scripts/test_logic.py && node scripts/test_logic.js
 *
 * ★ 文法は gate.js と同じ ES5 の範囲に留める(var / function のみ。アロー関数・?. ・?? は使わない)。
 *   find.html 側が ES5 で書かれており、そちらと同じ下限を維持するため。
 *
 * ★ 欠測は必ず「判定不能(null)」に倒す。データが無いことを 0 や好条件として扱うと、
 *   Open-Meteo が非対応項目・期間外を null で返す仕様(400 にならない)と組み合わさって、
 *   「データが取れていない日」が「登山適」として表示される。安全と逆方向の壊れ方なので、
 *   このファイルに判定を足すときは必ず欠測側の挙動を先に決めること。
 */

/* index.html / find.html の <script src="logic.js?v=..."> と一致させる版。
 * 古い logic.js がキャッシュに残ると「画面は新しいのに判定だけ旧版」という気づけない状態に
 * なるため、判定を変えたリリースでは必ず上げる(一致は test_logic.js が機械的に見ている)。 */
var PW_LOGIC_VER = "233";

/* ---- 定数 (scripts/mountain_weather.py と同一) ---- */
// LEVELS[i]=[気圧面hPa, 標準高度m]。500m台の里山から3800m級までを6面でカバー。
var LEVELS=[[925,760],[900,990],[850,1460],[800,1950],[700,3010],[600,4200]];
// 気圧面の最下端は 925hPa = 標準高度760m。ここに地上10m風を「高度10mの面」として足し、
// 標高760m未満は地上風と925hPaの間で内挿する。こうしないと 760m 未満がすべて 925hPa の
// 生値にクランプされ、平地・低山で上空760mの風がそのまま稜線風として出る
// (実測: 仙台市街で 925hPa 7.5m/s に対し地上10m風 0.6m/s / 衣張山122m で最大13.3→5.9m/s)。
var SURFACE_WIND_M=10;
// 900hPa・800hPa は MSM 期間(0〜4日目)にしか配信されない(GSM 期間はこの2面が丸ごと欠測)。
// この2面が両方欠測の時刻は内挿点が4面→2面に減り、稜線風が実測で北ア級-1.2m/s程度弱く出る。
// 呼び出し側はこれを degraded として持ち回り、`*` 印で開示する(埋め合わせは却下済み。下記参照)。
var DEGRADED_LEVELS=[900,800];
// ---- 夏冬モードを冬側へ倒す気温しきい値 (references/criteria.md「夏冬モードの切替」) ----
// 月ベース(6〜10月=夏)を残したまま、寒い日だけ冬モードへ倒す。安全側にのみ効かせるため、
// 冬モードから夏モードへ戻す条件は設けない。純粋な気温ベースにすると 5月の北ア(日中+2〜5℃)が
// 夏モードに落ちて現行より甘くなるため、月ベースは残す必要がある。
var WINTER_TMAX=0, WINTER_TMIN=-3;
// ---- 降格条件のしきい値 (references/criteria.md「降格条件」) ----
var WET_HYPO_TEMP=10, WET_HYPO_PRECIP=1.0, WET_HYPO_WIND_B=8, WET_HYPO_WIND_C=12;
var FEELS_B=-20, FEELS_C=-30;
var VIS_LOW=200, VIS_LOW_WIND=10;
// 視程が欠測のとき ◎(展望良好) を抑止する相対湿度。実測で山頂のRHは中央値89〜91%と高めに
// 出るため、飽和に近い95%を境にする。視程が取れているときは使わない。
var VIEW_RH_GATE=95;
var RANK={A:0,B:1,C:2};
// ---- 主判定の理由ラベル (blockIndex が返す reason に使う) ----
// 「雨」ではなく「降水」。降水量は水換算で、冬は同じ数値が雪を意味する。本アプリは雨/雪を
// 別途 precipPhase で判別表示しているので、判定側が「雨」と名乗ると表示同士が食い違う。
var MAIN_REASON_WIND="風", MAIN_REASON_PRECIP="降水", MAIN_REASON_SEP="・";

// 「その時刻に実際に値がある気圧面」だけで山頂標高の風速を補間する。
// pts=[[標準高度m, 風速], ...] を高度の昇順で渡す。範囲外は最寄りの面の値をそのまま使う。
//
// 標高から気圧面ペアを1回だけ決め打ちにしてはいけない。気圧面のラインナップはモデルで違い、
// MSM(おおむね1〜3日目)は6面すべて配信するが GSM(4日目以降)は 900hPa と 800hPa を
// 配信しない(実測)。決め打ちだと GSM 期間の標高 760〜3010m の山 ── DBの大半 ── で
// 「片面の生値をそのまま使う」動作に落ち、補間されない粗い値になる。
//
// ★ 欠けた 900/800hPa を「日照と同じように別モデルから借りて埋める」のは**やってはいけない**。
//   実測で検証済み: MSM が6面そろう日に 900/800 を意図的に伏せて復元精度を比べたところ、
//     この実装(4面で内挿)      平均誤差 0.76 m/s
//     icon_seamless で穴埋め   平均誤差 1.24 m/s
//     gfs_seamless  で穴埋め   平均誤差 1.32 m/s
//   借りた値は別モデルなので JMA の 925/850/700 との間に段差ができる。モデル間の風速差は
//   4〜7日目で平均 1.74 m/s あり、埋めたい内挿誤差 0.76 m/s より大きい。穴より段差の方が痛い。
//   日照を借りているのは「気象庁モデルに代わりが無い」から。風は自分の隣の面から内挿できるので
//   前提が違う。残る副作用の「4日目以降は風をやや弱めに見積もる」は補正せず開示で倒す。詳細は DEVLOG。
function interpWind(pts,elev){
  if(!pts.length)return null;
  if(elev<=pts[0][0])return pts[0][1];
  for(var i=0;i<pts.length-1;i++){
    var lo=pts[i],hi=pts[i+1];
    if(elev>=lo[0]&&elev<=hi[0])return lo[1]+(hi[1]-lo[1])*((elev-lo[0])/(hi[0]-lo[0]));
  }
  return pts[pts.length-1][1];
}

// 夏冬モードの判定。夏山(6-10月)/冬山・残雪期(11-5月)で風速・降水の閾値を切り替える。
// 月ベースを基本にしつつ、夏の月でも「日最高<0℃」または「日最低<-3℃」なら冬モードへ倒す。
// 月だけで切り替えると、北海道の9月下旬や3000m級の9月下旬〜10月が夏モード(風15m/sでC)の
// ままになり、実質的な冬の稜線を甘く判定するため。冬→夏に戻す条件は設けない(安全側のみ)。
// 気温は「行動時間帯 5〜16時」の最高・最低を渡すこと。1日全体の最低気温を使ってはいけない
// (3000m級では真夏でも明け方に -3℃ を下回ることがあり、日中の判定まで冬モードに倒れる)。
function seasonTh(month,tmax,tmin){
  var winter=!(month>=6&&month<=10);
  if(!winter&&((tmax!=null&&tmax<WINTER_TMAX)||(tmin!=null&&tmin<WINTER_TMIN)))winter=true;
  return winter
    ?{mode:"冬山・残雪期",wind:[8,12],precip:[1,3]}
    :{mode:"夏山",wind:[10,15],precip:[1,5]};
}

// 合計。ただし有効値が1つも無ければ null を返す(mountain_weather.py の sum_or_none と同一)。
// `(v||0)` の合計だと「0mm」と「データ無し」が区別できず、欠測が「降水量0mm＝好条件」に化ける。
function sumOrNull(vals){
  var vs=vals.filter(function(v){return v!=null});
  return vs.length?vs.reduce(function(a,b){return a+b},0):null;
}

// 3時間ブロックの登山指数。[A/B/C, 降格理由] を返す。判定材料が無ければ [null,""]。
// 主判定は稜線風と降水量の2項目のみ。降水確率は参考表示。
// 雷(CAPE)は局地性が高く登山可否とは性質が異なるため指数に含めず、発雷リスクとして独立表示する。
// 主判定のあとに降格条件(D1 湿潤低体温 / D2 体感温度 / D4 視界不良)を安全側にのみ重ねる。
// 風と降水だけでは、冬の-20℃・風7m/s(体感-32℃)や 夏の雨中12m/s が A のまま出てしまい、
// 実際に低体温症・凍傷が起きる条件を「登山適」と表示してしまうため。
// reason は「その評価を決めた条件」の名前。主判定で決まったなら「風」「降水」
// (同じ評価で並んだら「風・降水」)、降格条件が主判定より悪ければその条件名。
// 主判定側にも名前を出すのは、同じ B でも「風が強い」と「雨」で取るべき行動が違うため
// (行程短縮か中止か)。A のときは説明する対象が無いので空文字。
//
// 材料は安全側に寄せて渡すこと(風=ブロック内の最大・降水=合計・気温=最小・視程=最小)。
// visMin に null を渡せば D4 はスキップされる(視程を取得しない find がこの形で呼ぶ)。
function blockIndex(ws,pr3,th,tempMin,feels,visMin){
  // 主判定の材料が両方とも欠測なら「判定不能」。ここで A を返すと、データが無いだけの時間帯が
  // 「登山適」として表示され、安全と逆方向に誤解させる(Open-Meteo は非対応項目や予報期間外を
  // 400 ではなく null で返すため、欠測は現実に起こりうる)
  if(ws==null&&pr3==null)return[null,""];
  // 風と降水を「畳み込む前に」それぞれ評価する。最悪値だけを足していく書き方だと
  // どちらの材料が効いたのかが消え、B の理由を利用者に示せない。
  function grade(v,lo,hi){return v==null?null:(v>=hi?"C":(v>=lo?"B":"A"))}
  var gw=grade(ws,th.wind[0],th.wind[1]), gp=grade(pr3,th.precip[0],th.precip[1]);
  var idx=gw==null?gp:(gp==null?gw:(RANK[gp]>RANK[gw]?gp:gw));
  // 理由は「idx と同じ評価を出した材料」全部。同着で片方しか書かないと、もう片方は
  // 基準内だったと誤解される(風12m/s・降水6mm でどちらもC、のような日が実際に出る)。
  var reason="";
  if(idx!=="A"){
    var mains=[];
    if(gw===idx)mains.push(MAIN_REASON_WIND);
    if(gp===idx)mains.push(MAIN_REASON_PRECIP);
    reason=mains.join(MAIN_REASON_SEP);
  }
  // ---- 降格条件。優先度は 低体温 > 体感 > 視界 (先に立ったものが理由になる) ----
  var dem=[];
  // D1 湿潤低体温: 濡れ+風+低温。2009年トムラウシ(7月・気温8〜10℃・風20m/s・雨)の型。
  // 夏でも起きるので季節に依存させない。
  if(tempMin!=null&&pr3!=null&&ws!=null&&tempMin<=WET_HYPO_TEMP&&pr3>=WET_HYPO_PRECIP){
    if(ws>=WET_HYPO_WIND_C)dem.push(["C","低体温"]);
    else if(ws>=WET_HYPO_WIND_B)dem.push(["B","低体温"]);
  }
  // D2 体感温度: 凍傷リスク。体感温度(Apparent Temperature)は気温・風・湿度から算出する
  if(feels!=null){
    if(feels<=FEELS_C)dem.push(["C","体感"]);
    else if(feels<=FEELS_B)dem.push(["B","体感"]);
  }
  // D4 視界不良: 地吹雪・ホワイトアウト。視程が欠測なら発火させない(欠測を危険側にも倒さない)。
  // 降格先が C なのは、風10m/s が夏(閾値10)でも冬(閾値8)でも主判定で既に B 以上になるため。
  // 「最低B」にすると一度も効かない死んだ条件になる。視程200m未満+風10m/s以上は
  // ホワイトアウト+強風=行動不能に近く、C が実態に合う。
  if(visMin!=null&&ws!=null&&visMin<VIS_LOW&&ws>=VIS_LOW_WIND)dem.push(["C","視界"]);
  // 降格は「厳密に悪い」ときだけ採用する。同着(風でB・低体温もB)なら主判定の理由を残す。
  // 同着でも上書きすると、しきい値を超えた風という一次的な事実が理由から消える。
  for(var i=0;i<dem.length;i++){
    if(RANK[dem[i][0]]>RANK[idx]){idx=dem[i][0];reason=dem[i][1]}
  }
  return[idx,reason];
}

// 体感温度: 豪州気象局の Apparent Temperature (Steadman)。気温・風・湿度から算出する。
//   e  = (RH/100) × 6.105 × exp(17.27×T / (237.7+T))   … 水蒸気圧(hPa)
//   AT = T + 0.33×e − 0.70×風速(m/s) − 4.00
//
// なぜ風冷指数(JAG/TI式)をやめたか: JAG/TI は「気温10℃以下・風速4.8km/h以上」でのみ有効で、
// 式の構造上 +0.3965×T×V^0.16 の項が気温に比例して増えるため **約22℃超で気温より高い値**を返す
// (気温25℃・風14m/s で 25.9℃)。かといって10℃で打ち切って気温を返すと、今度は
// **10〜22℃の帯で冷却がまったく表現されない**(実測: 飯豊山で気温13.8℃・稜線風17m/s・雨でも
// 体感13.8℃)。しかも10℃境界で不連続になる(10.0℃→5.5℃ / 11.0℃→11.0℃)。
// どちらも誤った印象を与えるので、全温度域で有効な AT に置き換えた。
// 寒冷域では JAG/TI とよく一致する(-15℃・12m/s で -27.8 vs -27.0)。
//
// 高温多湿では体感が気温を上回る(30℃・RH90%・微風で 37.2℃)。湿度で熱が逃げないことを表す
// 正しい挙動なので min(f,temp) のような抑えは入れない。日射は考慮しない(日なたでは涼しめに出る)。
// 材料が1つでも欠測なら null(「-」表示)。気温をそのまま返すと欠測だと気づけない。
function feelsLike(temp,ws,rh){
  if(temp==null||ws==null||rh==null)return null;
  var e=(rh/100)*6.105*Math.exp(17.27*temp/(237.7+temp));
  return temp+0.33*e-0.70*ws-4.00;
}

// 山頂からの景色(眺望) ◎/○/△/✕。雲層(下層<2km/中層2-7km)を山頂標高と比較する。
// 山頂レベルの雲=ガス、山頂より下の雲=雲海の可能性。上層雲は眺望を妨げないため引数に取らない。
// rh(相対湿度)は視程が欠測のときだけ使う。視程欠測でも雲量が少なければ ◎ が出るため、
// 「データが無い」が「展望良好」に化けるのを防ぐ代替材料として置いている。
function viewScore(elev,low,mid,pr3,vis,rh){
  // 判定材料(雲量・視程・降水)が1つも無ければ null。全部欠測のまま進むと
  // 「雲量0扱い・視程不明」で ◎(展望良好) が出てしまい、データが無いだけの時間帯を好条件と誤解させる
  if(low==null&&mid==null&&vis==null&&pr3==null)return null;
  var summit,below;
  if(elev<2000){
    // 低山は下に雲層バンドが無い(谷霧は表現できない)。山頂の雲量は下層・中層の大きい方。
    summit=(low==null&&mid==null)?null:Math.max(low==null?0:low,mid==null?0:mid);
    below=null;
  }else{
    summit=mid;
    below=low;
  }
  if(pr3!=null&&pr3>=1)return["✕","雨"];
  if(vis!=null&&vis<2000)return["✕","ガス"];
  if(summit!=null&&summit>=80)return["✕","ガス"];
  if((summit!=null&&summit>=50)||(vis!=null&&vis<10000))return["△",""];
  // ここから下は「良い方」の判定。冒頭のガードは引数のどれかがあれば通すが、
  // 良い方を名乗るには「実際に判定に使う材料」(山頂の雲量 or 視程)が要る。
  // 2000m以上は summit=mid なので、low だけ取れて mid が欠測だと summit が null のままここへ来る。
  // 降水0mmだけを根拠に ○/◎ を出すのも「データが無い→好条件」で安全と逆方向。
  if(summit==null&&vis==null)return null;
  // summit 欠測のまま「雲海」「◎」を名乗らせない (null を雲量0として扱わない)
  var unkai=below!=null&&below>=60&&summit!=null&&summit<=30;
  if(summit!=null&&summit<=20&&(vis==null||vis>=20000)){
    // 視程が欠測のときは相対湿度で裏を取る。高湿ならガスの可能性があるので ◎ にしない
    if(vis==null&&rh!=null&&rh>=VIEW_RH_GATE)return["○",unkai?"雲海":""];
    return["◎",unkai?"雲海":""];
  }
  return["○",unkai?"雲海":""];
}

/* Node(scripts/test_logic.js)から読むための出口。ブラウザでは module が未定義なので素通りする。
 * ここに載せた関数だけが等価性テストの対象になる。 */
if(typeof module!=="undefined"&&module.exports)module.exports={
  PW_LOGIC_VER:PW_LOGIC_VER,LEVELS:LEVELS,SURFACE_WIND_M:SURFACE_WIND_M,
  DEGRADED_LEVELS:DEGRADED_LEVELS,
  interpWind:interpWind,seasonTh:seasonTh,sumOrNull:sumOrNull,
  blockIndex:blockIndex,feelsLike:feelsLike,viewScore:viewScore
};
