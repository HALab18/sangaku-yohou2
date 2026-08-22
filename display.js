"use strict";
/* PeakWeather 表示ロジック — 天気の文言・濡れ注意・雨雪判別・積雪や視程の表記の、
 * **JS 側の唯一の置き場**。
 *
 * index.html(詳細予報) と docs/find.html(山さがし) の両方がこのファイルを読む。
 * ver 2.46β まで、ここにある語彙(WMETA / SAFETY_OVERRIDE / CAT_LABEL / timingLabel など)は
 * **3箇所に写しがあった** ── index.html・scripts/gen_find.py・scripts/mountain_weather.py。
 * しかも find の写しの一致は「値を変えるときは揃えること」というコメントだけが守っており、
 * 機械では見ていなかった(test_display は index.html の写ししか突き合わせていない)。
 * その3つ目をここに畳んだので、いま写しは2つ。
 *
 * ★ **2箇所が下限**。CLI は Python、Web は JS なので、言語をまたぐこの1組はどうやっても
 *   消せない。判定(logic.js ⇄ mountain_weather.py)と同じ形で、機械で突き合わせて守る:
 *     python scripts/test_display.py
 *   表示を足すときは「CLI 側にも対になる実装があるか」を先に決めること。あるならここに書く。
 *
 * ★ HTML やクラス名を組み立てるものはここに置かない(index.html 側に残してある)。
 *   ここに入れてよいのは、CLI の markdown 出力と1対1に比べられる**素の値**を返すものだけ。
 *   比べられない形にした瞬間、上のテストが空振りする。
 *
 * ★ 文法は ES6 で構わない(logic.js / gate.js のような ES5 の縛りは無い)。
 *   docs/find.html 側も完全な ES5 ではない。
 *
 * ★ 欠測は logic.js と同じく「判定不能」に倒す。0 や好条件に化けさせない。
 */

/* index.html / find.html の <script src="display.js?v=..."> と一致させる版。
 * 古い display.js がキャッシュに残ると「画面は新しいのに文言だけ旧版」という気づけない
 * 状態になるため、ここを変えたリリースでは必ず上げる(一致は test_display.js が見ている)。 */
const PW_DISPLAY_VER = "246";

/* ---- 「濡れ注意」の材料 (scripts/mountain_weather.py と同一) ---- */
const WET_PRECIP=0.1;      // 「濡れ注意」を出す最小の降水量(表示専用)
// 濡れ注意を出す気温の上限。D1 の 10℃ より高くしてあるのは意図的で、表示専用の値。
// AT は「乾いた状態」の式で、濡れた衣服の蒸発冷却を含まない。体感の数字そのものはこの帯でも
// 冷えを表すが(飯豊山の気温13.8℃・稜線風17m/s は AT で約2〜3℃)、濡れるとそこからさらに下がる。
// 数字が一桁台に見えても致命的にならない帯こそ濡れ+風の低体温が起きるので印で補う。
// ※旧実装(風冷指数 JAG/TI)は10℃超で適用外になり「体感=気温」を返していたため、同じケースが
//   体感13.8℃と表示されていた。AT への置換でこの欠陥自体は解消済み。
// 判定(D1)のしきい値は 10℃ のまま(15℃に上げても4山×11日で判定の変化はゼロだった)。
const WET_WARN_TEMP=15;

/* ---- 天気コード → 日本語 (scripts/mountain_weather.py の WMO_CODES と同一) ---- */
const WMO={0:"快晴",1:"晴れ",2:"晴れ時々曇り",3:"曇り",45:"霧",48:"着氷性の霧",
 51:"霧雨(弱)",53:"霧雨",55:"霧雨(強)",56:"着氷性霧雨",57:"着氷性霧雨(強)",
 61:"雨(弱)",63:"雨",65:"雨(強)",66:"着氷性の雨",67:"着氷性の雨(強)",
 71:"雪(弱)",73:"雪",75:"雪(強)",77:"霧雪",80:"にわか雨(弱)",81:"にわか雨",82:"にわか雨(強)",
 85:"にわか雪",86:"にわか雪(強)",95:"雷雨",96:"雷雨(雹)",99:"雷雨(激しい雹)"};
const wcode=c=>c==null?"-":(WMO[c]||`code${c}`);

// ---- 日代表天気 (scripts/mountain_weather.py の summarize_daily_weather と同一ロジック) ----
// Open-Meteo の daily.weather_code は24hのmaxで、短時間の霧/霧雨が晴主体の日を乗っ取る。
// 代わりに hourly.weather_code から窓(4-17時)で日代表を決める: 悪天は昇格保持・軽微降水は注記に降格。
const WMETA={0:["clear",0],1:["clear",1],2:["partly",2],3:["cloudy",3],
 45:["fog",4],48:["fog",4],51:["drizzle",5],53:["drizzle",5],55:["drizzle",6],56:["drizzle",6],57:["drizzle",6],
 61:["rain",7],63:["rain",8],65:["rain",9],66:["rain",9],67:["rain",9],
 71:["snow",7],73:["snow",8],75:["snow",10],77:["snow",7],
 80:["showers",7],81:["showers",8],82:["showers",10],85:["snowshowers",9],86:["snowshowers",10],
 95:["thunder",11],96:["thunder",12],99:["thunder",12]};
const WCAT=c=>WMETA[c]?WMETA[c][0]:"unknown";
const WSEV=c=>WMETA[c]?WMETA[c][1]:0;
const WX_WINDOW=[4,17]; // 集約する時間帯窓(両端含む)
const SAFETY_OVERRIDE=new Set([65,66,67,75,82,85,86,95,96,99]); // 窓内に1hでもあれば日代表に昇格(安全側)
const PRECIP_CATS=new Set(["fog","drizzle","rain","showers","snow","snowshowers","thunder"]);
const CAT_LABEL={fog:"霧",drizzle:"霧雨",rain:"雨",showers:"にわか雨",snow:"雪",snowshowers:"にわか雪",thunder:"雷雨"};
const WLABEL2CAT=Object.fromEntries(Object.entries(CAT_LABEL).map(([c,l])=>[l,c])); // 逆引き(注記の重複防止用)
const TOD_ORDER=["明け方","朝","昼前","昼過ぎ","夕方"];
const timeOfDay=hr=>hr<=6?"明け方":hr<=9?"朝":hr<=11?"昼前":hr<=14?"昼過ぎ":"夕方";
function timingLabel(hours){
  const labels=[...new Set(hours.map(timeOfDay))].sort((a,b)=>TOD_ORDER.indexOf(a)-TOD_ORDER.indexOf(b));
  if(labels.length>=4)return"日中";
  if(labels.length>=2)return`${labels[0]}〜${labels[labels.length-1]}`;
  return labels[0];
}
function addPrecipNotes(win,repCat,notes,skipHours,excludeCats=new Set()){
  const seen=new Map();
  for(const e of win){
    if(skipHours.has(e.hour))continue;
    const cat=WCAT(e.code);
    if(cat===repCat||!PRECIP_CATS.has(cat)||excludeCats.has(cat))continue;
    if(!seen.has(cat))seen.set(cat,[]);
    seen.get(cat).push(e.hour);
  }
  for(const[cat,hours]of seen)notes.push(`${timingLabel(hours)}に${CAT_LABEL[cat]}`);
}
// times=hourly.time, codes=hourly.weather_code → [{date,code,notes[]}]。表示ラベルは既存 wcode を使う。
function summarizeDailyWeather(times,codes){
  const byDate=new Map();
  for(let i=0;i<times.length;i++){
    // 予報末端(GSM打ち切り後)の時刻は code が null。混ぜると重症度比較が壊れるので落とす
    if(codes[i]==null)continue;
    const date=times[i].slice(0,10),hour=+times[i].slice(11,13);
    if(!byDate.has(date))byDate.set(date,[]);
    byDate.get(date).push({hour,code:codes[i]});
  }
  const result=[];
  for(const[date,entries]of byDate){
    let win=entries.filter(e=>e.hour>=WX_WINDOW[0]&&e.hour<=WX_WINDOW[1]);
    if(!win.length)win=entries; // 保険: 窓が空なら全時間
    const notes=[];
    // フレーズを先に決め、フレーズに出す降水カテゴリは注記から除外(重複防止)。3つ目以降の降水系だけ注記に残る。
    let phrase=dayWeatherPhrase(win);
    const phraseCats=new Set();
    if(phrase)for(const s of phrase)if(s.label&&WLABEL2CAT[s.label])phraseCats.add(WLABEL2CAT[s.label]);
    // 第1層: 安全オーバーライド(悪天は無条件で日代表)
    const overrides=win.filter(e=>SAFETY_OVERRIDE.has(e.code));
    if(overrides.length){
      overrides.sort((a,b)=>WSEV(b.code)-WSEV(a.code));
      const rep=overrides[0].code,repCat=WCAT(rep);
      // 代表(悪天)自身の時間注記は付けない: 天気列に既に出るため冗長。他の降水系のみ注記に残す。
      addPrecipNotes(win,repCat,notes,new Set(overrides.map(e=>e.hour)),phraseCats);
      // 単一天気の日は従来の詳細ラベル(快晴/弱/強等)を維持しアイコンだけ付ける
      if(phrase&&phrase.length===1)phrase=singleCodePhrase(rep);
      result.push({date,code:rep,notes,phrase});
      continue;
    }
    // 第2層: 日中の時間帯多数決(同数なら重症度が高い方)
    const catHours=new Map();
    for(const e of win){const c=WCAT(e.code);if(!catHours.has(c))catHours.set(c,[]);catHours.get(c).push(e.hour);}
    let repCat=null,repCount=-1,repSev=-1;
    for(const[cat,hours]of catHours){
      const count=hours.length;
      const maxSev=Math.max(...win.filter(e=>WCAT(e.code)===cat).map(e=>WSEV(e.code)));
      if(count>repCount||(count===repCount&&maxSev>repSev)){repCat=cat;repCount=count;repSev=maxSev;}
    }
    const codeCount=new Map();
    for(const e of win){if(WCAT(e.code)!==repCat)continue;codeCount.set(e.code,(codeCount.get(e.code)||0)+1);}
    let repCode=null,best=-1,bestSev=-1;
    for(const[code,cnt]of codeCount){const sev=WSEV(code);if(cnt>best||(cnt===best&&sev>bestSev)){repCode=code;best=cnt;bestSev=sev;}}
    // 第3層: 代表でない降水系は注記に降格
    addPrecipNotes(win,repCat,notes,new Set(),phraseCats);
    // 単一天気の日は従来の詳細ラベル(快晴/晴れ時々曇り/弱/強等)を維持しアイコンだけ付ける
    if(phrase&&phrase.length===1)phrase=singleCodePhrase(repCode);
    result.push({date,code:repCode,notes,phrase});
  }
  return result;
}
// ---- 日内変化フレーズ (のち/時々/一時。scripts/mountain_weather.py の day_weather_phrase と同一ロジック) ----
// CLI は markdown なのでラベルと接続語だけを連結する(phrase_text)。分岐は両者で揃えること。
// 気象庁 予報用語準拠: 前半後半で優勢が入れ替わる=のち / 断続的<1/2=時々 / 連続的<1/4=一時。
// カテゴリ→[表示ラベル, アイコンID]。partly は晴れに畳む(真の曇天は cloudy が拾う)。詳細表は弱/強を wcode で別表示。
const WBASE={clear:["晴れ","wx-sun"],partly:["晴れ","wx-sun"],cloudy:["曇り","wx-cloud"],
 fog:["霧","wx-fog"],drizzle:["霧雨","wx-rain"],rain:["雨","wx-rain"],showers:["にわか雨","wx-rain"],
 snow:["雪","wx-snow"],snowshowers:["にわか雪","wx-snow"],thunder:["雷雨","wx-thunder"]};
const wbaseLabel=c=>WBASE[WCAT(c)]?WBASE[WCAT(c)][0]:null;
const wbaseIcon=c=>WBASE[WCAT(c)]?WBASE[WCAT(c)][1]:null;
const LABEL_ICON=Object.fromEntries(Object.values(WBASE).map(([l,i])=>[l,i]));
// win=[{hour,code}] → セグメント配列 [{label,icon}|{conn}] (最大2天気+接続語1)。窓が空なら null。
function dayWeatherPhrase(win){
  const seq=win.filter(e=>wbaseLabel(e.code)!=null)
    .map(e=>({hour:e.hour,label:wbaseLabel(e.code),sev:WSEV(e.code),code:e.code}))
    .sort((a,b)=>a.hour-b.hour);
  const N=seq.length;
  if(!N)return null;
  const seg=label=>({label,icon:LABEL_ICON[label]});
  const dominant=sub=>{ // 最多ラベル(同数は重症度が高い方)
    const cnt=new Map(),sv=new Map();
    for(const e of sub){cnt.set(e.label,(cnt.get(e.label)||0)+1);sv.set(e.label,Math.max(sv.get(e.label)??-1,e.sev));}
    let best=null,bc=-1,bs=-1;
    for(const[l,c]of cnt){const s=sv.get(l);if(c>bc||(c===bc&&s>bs)){best=l;bc=c;bs=s;}}
    return best;
  };
  if(new Set(seq.map(e=>e.label)).size===1)return[seg(seq[0].label)]; // 単一天気
  // 安全側: 窓内の悪天(最悪)は必ずフレーズに残す
  const sevHours=seq.filter(e=>SAFETY_OVERRIDE.has(e.code));
  const severeLabel=sevHours.length?sevHours.reduce((a,b)=>b.sev>a.sev?b:a).label:null;
  // 第1優先: 前半/後半で優勢が入れ替われば「のち」
  const half=Math.ceil(N/2);
  const domA=dominant(seq.slice(0,half)),domB=dominant(seq.slice(half));
  if(domA!==domB&&(severeLabel==null||severeLabel===domA||severeLabel===domB))
    return[seg(domA),{conn:"のち"},seg(domB)];
  // 第2: 主天気P + 副次S を「一時/時々」で連結
  const P=dominant(seq);
  let S=null;
  if(severeLabel!=null&&severeLabel!==P)S=severeLabel; // 悪天は最優先で副次に採用
  else{
    const cnt=new Map(),sv=new Map();
    for(const e of seq){if(e.label===P)continue;cnt.set(e.label,(cnt.get(e.label)||0)+1);sv.set(e.label,Math.max(sv.get(e.label)??-1,e.sev));}
    let bc=-1,bs=-1;for(const[l,c]of cnt){const s=sv.get(l);if(c>bc||(c===bc&&s>bs)){S=l;bc=c;bs=s;}}
  }
  if(S==null)return[seg(P)];
  const share=seq.filter(e=>e.label===S).length/N;
  let runs=0,prev=false;for(const e of seq){const is=e.label===S;if(is&&!prev)runs++;prev=is;} // Sの連続塊数
  const conn=(runs===1&&share<0.25)?"一時":"時々";
  return[seg(P),{conn},seg(S)];
}
// フレーズ→HTML(アイコン+ラベル)。日別サマリ用。
// 単一天気の日の表示フレーズを作る。code=2("晴れ時々曇り")だけは複合ラベルなので
// 晴れ/曇り2アイコンに分解する(他コードはWMOラベル1つ+カテゴリアイコン1つで足りる)。
function singleCodePhrase(code){
  if(code===2)return[{label:"晴れ",icon:"wx-sun"},{conn:"時々"},{label:"曇り",icon:"wx-cloud"}];
  return[{label:wcode(code),icon:wbaseIcon(code)}];
}

/* ---- 濡れ注意・雨雪判別・視程・積雪 ---- */
// 濡れ+風+低温がそろっているか。D1 の手前(3h降水0.1〜1.0mm)の弱い降水を拾う印。
// 体感温度は乾いた状態の値なので、濡れているときは表示より大きく下がる。
// ★ 相対湿度は条件に使わない。実測で山頂のRHは中央値89〜91%、95%以上が23〜40%の時間を占め、
//   視程45kmの快晴でも95%を超える。RHを条件にすると印がほぼ常時点灯し区別できなくなる。
function wetWarn(temp,ws,pr3){
  if(temp==null||ws==null||pr3==null)return false;
  return temp<=WET_WARN_TEMP&&ws>=WET_HYPO_WIND_B&&pr3>=WET_PRECIP;
}
// 雨雪判別。雪片は0℃高度から落下する間に融けるので、雨雪の境界は0℃高度より下に出る。
// 表示のみでA/B/C判定には使わない。冬モードの「3h降水3mm以上=C」は水換算なので、
// 雨か雪かは表示側で補う必要がある(1℃の雨は-5℃の雪より低体温リスクが高いのに数字は同じ)。
function precipPhase(fl,elev){
  if(fl==null||elev==null)return null;
  if(fl<elev-100)return"雪";
  if(fl>elev+200)return"雨";
  return"みぞれ";
}
const visTxt=vis=>vis==null?null:vis>=1000?`${Math.round(vis/1000)}km`:`${Math.round(vis)}m`;
function snowCell(depthM,sfCm){
  // 積雪列の表示。「85cm(+12)」= 積雪深85cm・新雪12cm
  if(depthM==null&&sfCm==null)return"-";
  let s=depthM==null?"-":`${Math.round(depthM*100)}cm`;
  if(sfCm!=null&&sfCm>=0.5)s+=`(+${Math.round(sfCm)})`;
  return s;
}

// Node(scripts/test_display.js)から読むためだけの出口。ブラウザでは module が無いので素通りする。
if(typeof module!=="undefined"&&module.exports)module.exports={
  PW_DISPLAY_VER,WMO,wcode,WMETA,WCAT,WSEV,WX_WINDOW,SAFETY_OVERRIDE,PRECIP_CATS,CAT_LABEL,
  TOD_ORDER,timeOfDay,timingLabel,addPrecipNotes,summarizeDailyWeather,
  WBASE,wbaseLabel,wbaseIcon,LABEL_ICON,dayWeatherPhrase,singleCodePhrase,
  WET_PRECIP,WET_WARN_TEMP,wetWarn,precipPhase,visTxt,snowCell};
