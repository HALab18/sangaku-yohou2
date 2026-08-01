# -*- coding: utf-8 -*-
"""山岳地点予報取得スクリプト (Open-Meteo API)

使い方:
  python mountain_weather.py --name 燕岳
  python mountain_weather.py --name 燕岳 --select 2
  python mountain_weather.py --name 天狗岳 --date 2026-07-19 --days 2
  python mountain_weather.py --lat 36.407 --lon 137.713 --elev 2763 --label 燕岳
  python mountain_weather.py --name 燕岳 --weekly
  python mountain_weather.py --name 燕岳 --date 2026-07-19 --compare-models

終了コード: 0=正常 / 2=山名の候補が複数(要選択) / 1=エラー
"""
import argparse
import contextlib
import csv
import datetime as dt
import html as html_mod
import io
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# 基本の取得元は日本域に最適化された気象庁モデル (0-4日=MSM 約5km / 5-11日=GSM。自動で切替わる)。
# JMA_URL に無い項目 (降水確率・突風・CAPE/CIN・視程・積雪深) だけ FORECAST_URL から補完する。
# FORECAST_URL はモデル比較(compare_models)でも引き続き使う。
JMA_URL = "https://api.open-meteo.com/v1/jma"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# 気象庁モデルの予報長。forecast_days=16 等を投げてもAPIはエラーを返さず黙って null を並べるので、
# 期間は必ずこちらで 11日 (today+10) に制限する。
JMA_DAYS = 11
MOUNTAINS_CSV = Path(__file__).resolve().parent.parent / "references" / "mountains.csv"

# 気圧面と標準高度 (m)。その時刻に値がある面から山頂標高に線形補間して稜線風を出す (interp_wind)
PRESSURE_LEVELS = [(925, 760), (900, 990), (850, 1460), (800, 1950), (700, 3010), (600, 4200)]

# 気圧面の最下端は 925hPa = 標準高度760m。ここに地上10m風を「高度10mの面」として足し、
# 標高760m未満は地上風と925hPaの間で内挿する (ridge_wind)。こうしないと 760m 未満が
# すべて 925hPa の生値にクランプされ、平地・低山で上空760mの風がそのまま稜線風として出る
# (実測: 仙台市街で 925hPa 7.5m/s に対し地上10m風 0.6m/s)。内蔵DBでは標高100〜760mに76座あり、
# 旧実装ではこの帯が丸ごと過大評価になっていた。
SURFACE_WIND_M = 10  # 地上10m風を内挿の最下点として扱う高度
# 列見出しを「地上風(10m)」に変える境界。この標高未満では内挿値の実体がほぼ地上10m風になる。
LOW_ELEV_M = 100
# 内挿に地上風が混ざる上限 = 925hPa の標準高度。この未満の山には注記を出す。
BLEND_ELEV_M = 760

# ---- 夏冬モードを冬側へ倒す気温しきい値 (references/criteria.md「夏冬モードの切替」) ----
# 月ベース(6〜10月=夏)を残したまま、寒い日だけ冬モードへ倒す。安全側にのみ効かせるため、
# 冬モードから夏モードへ戻す条件は設けない。純粋な気温ベースにすると 5月の北ア(日中+2〜5℃)が
# 夏モードに落ちて現行より甘くなるため、月ベースは残す必要がある。
WINTER_TMAX_C = 0    # 日最高山頂気温がこれ未満 = 真冬日相当
WINTER_TMIN_C = -3   # 日最低山頂気温がこれ未満

# ---- 降格条件のしきい値 (references/criteria.md「降格条件」) ----
# 主判定(稜線風・降水)のあとに重ね、安全側にのみ効かせる。
WET_HYPO_TEMP_C = 10      # D1 湿潤低体温: 気温がこれ以下
WET_HYPO_PRECIP_MM = 1.0  # D1: かつ 3h降水がこれ以上
WET_HYPO_WIND_B = 8       # D1: かつ稜線風がこれ以上で B
WET_HYPO_WIND_C = 12      # D1: 稜線風がこれ以上なら C
FEELS_B_C = -20           # D2 体感温度がこれ以下で B (露出部の凍傷リスク域)
FEELS_C_C = -30           # D2' これ以下で C
VIS_LOW_M = 200           # D4 視界不良: 視程がこれ未満
VIS_LOW_WIND = 10         # D4: かつ稜線風がこれ以上 (地吹雪・ホワイトアウト) → C
# ★ D4 の降格先は B ではなく C。風10m/s は夏(閾値10)でも冬(閾値8)でも主判定が既に B 以上に
#   なるため、「最低B」にすると D4 は一度も効かない死んだ条件になる(実装時に判明)。
#   視程200m未満で風10m/s以上はホワイトアウト+強風=行動不能に近く、C が実態に合う。

# 視程が欠測のとき ◎(展望良好) を抑止する相対湿度。
# 実測で山頂の RH は中央値 89〜91% と高めに出るため、飽和に近い95%を境にする。
# 視程が取れているときは使わない(視程のほうが直接的な材料のため)。
VIEW_RH_GATE = 95

WMO_CODES = {
    0: "快晴", 1: "晴れ", 2: "晴れ時々曇り", 3: "曇り",
    45: "霧", 48: "着氷性の霧",
    51: "霧雨(弱)", 53: "霧雨", 55: "霧雨(強)",
    56: "着氷性霧雨", 57: "着氷性霧雨(強)",
    61: "雨(弱)", 63: "雨", 65: "雨(強)",
    66: "着氷性の雨", 67: "着氷性の雨(強)",
    71: "雪(弱)", 73: "雪", 75: "雪(強)", 77: "霧雪",
    80: "にわか雨(弱)", 81: "にわか雨", 82: "にわか雨(強)",
    85: "にわか雪", 86: "にわか雪(強)",
    95: "雷雨", 96: "雷雨(雹)", 99: "雷雨(激しい雹)",
}

DIR16 = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
         "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]


def wdir(deg):
    if deg is None:
        return "-"
    return DIR16[int((deg + 11.25) % 360 / 22.5)]


def wcode(code):
    if code is None:
        return "-"
    return WMO_CODES.get(int(code), f"code{int(code)}")


# ---- 日代表天気 (index.html の summarizeDailyWeather と同一ロジック) ----
# Open-Meteo の daily.weather_code は24hのmaxで、短時間の霧/霧雨が晴主体の日を乗っ取る。
# 代わりに hourly.weather_code から窓(4-17時)で日代表を決める: 悪天は昇格保持・軽微降水は注記に降格。
WMETA = {  # code -> (category, severity)
    0: ("clear", 0), 1: ("clear", 1), 2: ("partly", 2), 3: ("cloudy", 3),
    45: ("fog", 4), 48: ("fog", 4),
    51: ("drizzle", 5), 53: ("drizzle", 5), 55: ("drizzle", 6), 56: ("drizzle", 6), 57: ("drizzle", 6),
    61: ("rain", 7), 63: ("rain", 8), 65: ("rain", 9), 66: ("rain", 9), 67: ("rain", 9),
    71: ("snow", 7), 73: ("snow", 8), 75: ("snow", 10), 77: ("snow", 7),
    80: ("showers", 7), 81: ("showers", 8), 82: ("showers", 10),
    85: ("snowshowers", 9), 86: ("snowshowers", 10),
    95: ("thunder", 11), 96: ("thunder", 12), 99: ("thunder", 12),
}
WX_WINDOW = (4, 17)  # 集約する時間帯窓(両端含む)
SAFETY_OVERRIDE = {65, 66, 67, 75, 82, 85, 86, 95, 96, 99}  # 窓内に1hでもあれば日代表に昇格(安全側)
PRECIP_CATS = {"fog", "drizzle", "rain", "showers", "snow", "snowshowers", "thunder"}
CAT_LABEL = {"fog": "霧", "drizzle": "霧雨", "rain": "雨", "showers": "にわか雨",
             "snow": "雪", "snowshowers": "にわか雪", "thunder": "雷雨"}
TOD_ORDER = ["明け方", "朝", "昼前", "昼過ぎ", "夕方"]


def _wcat(code):
    return WMETA[code][0] if code in WMETA else "unknown"


def _wsev(code):
    return WMETA[code][1] if code in WMETA else 0


def _time_of_day(hr):
    if hr <= 6:
        return "明け方"
    if hr <= 9:
        return "朝"
    if hr <= 11:
        return "昼前"
    if hr <= 14:
        return "昼過ぎ"
    return "夕方"


def _timing_label(hours):
    labels = sorted(dict.fromkeys(_time_of_day(h) for h in hours), key=TOD_ORDER.index)
    if len(labels) >= 4:
        return "日中"
    if len(labels) >= 2:
        return f"{labels[0]}〜{labels[-1]}"
    return labels[0]


def _add_precip_notes(win, rep_cat, notes, skip_hours):
    seen = {}
    for e in win:
        if e["hour"] in skip_hours:
            continue
        cat = _wcat(e["code"])
        if cat == rep_cat or cat not in PRECIP_CATS:
            continue
        seen.setdefault(cat, []).append(e["hour"])
    for cat, hours in seen.items():
        notes.append(f"{_timing_label(hours)}に{CAT_LABEL[cat]}")


def summarize_daily_weather(times, codes):
    """hourly.time / hourly.weather_code から日ごとの代表天気を決める。
    戻り値: {date_iso: {"code": int, "notes": [str, ...]}}。表示ラベルは既存 wcode を使う。"""
    by_date = {}
    for i, t in enumerate(times):
        # 予報末端(GSM打ち切り後)の時刻は code が None で返る。混ぜると重症度比較が壊れるので落とす
        if codes[i] is None:
            continue
        by_date.setdefault(t[:10], []).append({"hour": int(t[11:13]), "code": codes[i]})
    result = {}
    for date, entries in by_date.items():
        win = [e for e in entries if WX_WINDOW[0] <= e["hour"] <= WX_WINDOW[1]] or entries
        notes = []
        # 第1層: 安全オーバーライド(悪天は無条件で日代表)
        overrides = [e for e in win if e["code"] in SAFETY_OVERRIDE]
        if overrides:
            overrides.sort(key=lambda e: _wsev(e["code"]), reverse=True)
            rep = overrides[0]["code"]
            rep_cat = _wcat(rep)
            # 代表(悪天)自身の時間注記は付けない: 天気列に既に出るため冗長。他の降水系のみ注記に残す。
            _add_precip_notes(win, rep_cat, notes, {e["hour"] for e in overrides})
            result[date] = {"code": rep, "notes": notes}
            continue
        # 第2層: 日中の時間帯多数決(同数なら重症度が高い方)
        cat_hours = {}
        for e in win:
            cat_hours.setdefault(_wcat(e["code"]), []).append(e["hour"])
        rep_cat, rep_count, rep_sev = None, -1, -1
        for cat, hours in cat_hours.items():
            count = len(hours)
            max_sev = max(_wsev(e["code"]) for e in win if _wcat(e["code"]) == cat)
            if count > rep_count or (count == rep_count and max_sev > rep_sev):
                rep_cat, rep_count, rep_sev = cat, count, max_sev
        code_count = {}
        for e in win:
            if _wcat(e["code"]) != rep_cat:
                continue
            code_count[e["code"]] = code_count.get(e["code"], 0) + 1
        rep_code, best, best_sev = None, -1, -1
        for code, cnt in code_count.items():
            sev = _wsev(code)
            if cnt > best or (cnt == best and sev > best_sev):
                rep_code, best, best_sev = code, cnt, sev
        # 第3層: 代表でない降水系は注記に降格
        _add_precip_notes(win, rep_cat, notes, set())
        result[date] = {"code": rep_code, "notes": notes}
    return result


def wx_note_text(notes):
    """注記リストを天気セル併記用のテキストにする(markdown表を壊さない全角括弧)。"""
    return f"（{' / '.join(notes)}）" if notes else ""


def http_json(url, params, retries=3):
    """一時的な通信エラー(接続断・SSLハンドシェイクタイムアウト・5xx等)は指数バックオフで再試行する。
    予報モデルの更新時刻によっては end_date が予報長ぶん受け付けられず HTTP 400 になるため、
    その場合は応答の reason から許容最終日をパースして end_date を縮め、1回だけ再試行する"""
    last_err = None
    clamped = False
    attempt = 1
    while attempt <= retries:
        q = urllib.parse.urlencode(params, safe=",")
        req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "sangaku-yohou-skill"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 400 and not clamped:
                try:
                    reason = json.loads(e.read().decode("utf-8")).get("reason", "")
                except Exception:
                    reason = ""
                m = re.search(r"'end_date'.* to (\d{4}-\d{2}-\d{2})", reason)
                if m and str(params.get("start_date", "")) <= m.group(1) < str(params.get("end_date", "")):
                    params = dict(params, end_date=m.group(1))
                    clamped = True
                    continue  # 再試行回数は消費しない
            if e.code < 500 or attempt == retries:
                sys.exit(f"ERROR: API呼び出しに失敗しました ({url}): HTTP {e.code} {e.reason}")
        except Exception as e:
            last_err = e
            if attempt == retries:
                break
        wait = 1.5 * attempt
        print(f"通信エラーのため再試行します ({attempt}/{retries}, {wait:.0f}秒後): {last_err}",
              file=sys.stderr)
        time.sleep(wait)
        attempt += 1
    sys.exit(f"ERROR: API呼び出しに{retries}回失敗しました ({url}): {last_err}\n"
             f"ネットワーク接続、プロキシ設定、セキュリティソフトのSSL検査機能を確認してください。")


# ---------------------------------------------------------------- 山名解決
def load_csv():
    """CSVはBOM付きUTF-8が標準(Excelでそのまま開ける)。utf-8-sigはBOM無しも読める。
    ExcelがShift_JIS(CP932)で保存し直した場合にも読めるようフォールバックする"""
    if not MOUNTAINS_CSV.exists():
        return []
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(MOUNTAINS_CSV, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    sys.exit(f"ERROR: {MOUNTAINS_CSV} の文字コードが判別できません。UTF-8で保存し直してください。")


def resolve_mountain(name, select=None):
    """(label, lat, lon, elev, source) を返す。曖昧なら候補を表示して exit(2)"""
    rows = load_csv()
    hits = [r for r in rows if r["name"] == name or r.get("yomi") == name]
    if not hits:
        hits = [r for r in rows if name in r["name"]]
    if len(hits) == 1:
        r = hits[0]
        return (f'{r["name"]}({r["pref"]})', float(r["lat"]), float(r["lon"]),
                float(r["elev"]), "内蔵DB")
    if len(hits) > 1:
        if select and 1 <= select <= len(hits):
            r = hits[select - 1]
            return (f'{r["name"]}({r["pref"]})', float(r["lat"]), float(r["lon"]),
                    float(r["elev"]), "内蔵DB")
        print(f"「{name}」は複数候補があります。--select N で選択してください:")
        for i, r in enumerate(hits, 1):
            print(f"  {i}. {r['name']}({r['pref']}) {r['elev']}m")
        sys.exit(2)

    # ジオコーディングAPI
    data = http_json(GEOCODE_URL, {"name": name, "count": 10, "language": "ja"})
    results = data.get("results") or []
    jp = [r for r in results if r.get("country_code") == "JP"]
    mt = [r for r in jp if r.get("feature_code") in ("MT", "PK", "VLC", "HLL", "MTS")]
    cands = mt or jp or results
    if not cands:
        sys.exit(f"ERROR: 「{name}」が見つかりませんでした。--lat/--lon/--elev で直接指定してください。")
    sel_ok = select is not None and 1 <= select <= len(cands)
    if len(cands) > 1 and not sel_ok:
        print(f"「{name}」は複数候補があります(ジオコーディング)。--select N で選択してください:")
        for i, r in enumerate(cands, 1):
            print(f"  {i}. {r['name']}({r.get('admin1', '?')}{'/' + r['admin2'] if r.get('admin2') else ''}) "
                  f"標高{r.get('elevation', '?')}m [{r['latitude']:.4f}, {r['longitude']:.4f}]")
        sys.exit(2)
    r = cands[select - 1] if sel_ok else cands[0]
    elev = r.get("elevation")
    if elev is None:
        sys.exit(f"ERROR: 標高情報が取得できません。--elev で指定してください。")
    return (f'{r["name"]}({r.get("admin1", "?")})', r["latitude"], r["longitude"],
            float(elev), "ジオコーディング(標高はグリッド値: 実際の山頂標高と差がある場合あり)")


# ---------------------------------------------------------------- 稜線風
def interp_wind(pts, elev):
    """「その時刻に実際に値がある気圧面」だけで山頂標高の風速を補間する
    (docs/find.html の interpWind・index.html の interpWind と同一ロジック)。
    pts=[(標準高度m, 風速), ...] を高度の昇順で渡す。範囲外は最寄りの面の値をそのまま使う。

    標高から気圧面ペアを1回だけ決め打ちにしてはいけない。気圧面のラインナップはモデルで違い、
    MSM(おおむね1〜3日目)は6面すべて配信するが GSM(4日目以降)は 900hPa と 800hPa を
    配信しない(実測)。決め打ちだと GSM 期間の標高 760〜3010m の山 ── DBの大半 ── で
    「片面の生値をそのまま使う」動作に落ち、補間されない粗い値になる。

    ★ 欠けた 900/800hPa を「日照と同じように別モデルから借りて埋める」のはやってはいけない。
      実測で検証済み: MSM が6面そろう日に 900/800 を意図的に伏せて復元精度を比べたところ、
        この実装(4面で内挿)     平均誤差 0.76 m/s
        icon_seamless で穴埋め  平均誤差 1.24 m/s
        gfs_seamless  で穴埋め  平均誤差 1.32 m/s
      借りた値は別モデルなので JMA の 925/850/700 との間に段差ができる。モデル間の風速差は
      4〜7日目で平均 1.74 m/s あり、埋めたい内挿誤差 0.76 m/s より大きい。穴より段差が痛い。
      日照を借りているのは「気象庁モデルに代わりが無い」から。風は自分の隣の面から内挿できるので
      前提が違う。残る副作用の「4日目以降は風をやや弱めに見積もる」は補正せず開示で倒す。"""
    if not pts:
        return None
    if elev <= pts[0][0]:
        return pts[0][1]
    for lo, hi in zip(pts, pts[1:]):
        if lo[0] <= elev <= hi[0]:
            return lo[1] + (hi[1] - lo[1]) * ((elev - lo[0]) / (hi[0] - lo[0]))
    return pts[-1][1]


def ridge_wind(h, i, elev):
    """i時刻の稜線風速(m/s)・風向を6気圧面から求める。材料が1つも無ければ (None, None)。
    風速は値のある面だけで線形補間。風向は角度なので同じ式では補間できず、
    「値のある面のうち標高的に一番近い面の値をそのまま採用」する(固定2面時代の t<0.5 の一般化)。"""
    def val(key):
        a = h.get(key)
        return a[i] if a and i < len(a) else None
    # 地上10m風を「高度10mの面」として内挿の最下点に置く。925hPa(760m)より低い標高が
    # 最下面の生値にクランプされるのを防ぐため。標高100m の不連続な切り替えも同時に消える。
    pts, dirs = [], []
    s10 = val("wind_speed_10m")
    if s10 is not None:
        pts.append((SURFACE_WIND_M, s10))
    d10 = val("wind_direction_10m")
    if d10 is not None:
        dirs.append((SURFACE_WIND_M, d10))
    for p, z in PRESSURE_LEVELS:
        s = val(f"wind_speed_{p}hPa")
        if s is not None:
            pts.append((z, s))
        d = val(f"wind_direction_{p}hPa")
        if d is not None:
            dirs.append((z, d))
    direction = min(dirs, key=lambda zd: abs(zd[0] - elev))[1] if dirs else None
    return interp_wind(pts, elev), direction


# ---------------------------------------------------------------- 登山指数
def wind_label(elev):
    """表の風の列見出し。標高 LOW_ELEV_M 未満は内挿値の実体がほぼ地上10m風になるため
    (ridge_wind 参照)、見出しもそれに合わせる。index.html の windLbl と同一。"""
    return "地上風(10m)" if elev < LOW_ELEV_M else "稜線風"


ACT_HOURS = (5, 17)  # 行動時間帯。日別指数とモード判定の対象


def mode_temps(h, times, date):
    """夏冬モードの判定に使う気温 (行動時間帯 5〜17時の最高・最低)。

    1日全体の最低気温を使ってはいけない。3000m級では真夏でも明け方に -3℃ を下回ることが
    あり(実測: 富士山の8月)、行動時間帯は 5℃前後なのに日中の判定まで冬モードに倒れる。
    指数が対象にしているのは行動時間帯なので、モードもその帯の気温で決める。"""
    act = [i for i in day_indices(times, date)
           if ACT_HOURS[0] <= int(times[i][11:13]) <= ACT_HOURS[1]]
    vs = [h["temperature_2m"][i] for i in act if h["temperature_2m"][i] is not None]
    return (max(vs), min(vs)) if vs else (None, None)


def season_thresholds(month, tmax=None, tmin=None):
    """予報対象日の月と山頂気温で夏山/冬山・残雪期の判定閾値を切り替える
    夏山(6〜10月): 風10/15m/s・降水1/5mm / 冬山・残雪期(11〜5月): 風8/12m/s・降水1/3mm

    月ベースを基本にしつつ、夏の月でも「日最高<0℃」または「日最低<-3℃」なら冬モードへ倒す。
    月だけで切り替えると、北海道の9月下旬や 3000m級の9月下旬〜10月が夏モード(風15m/sでC)の
    ままになり、実質的な冬の稜線を甘く判定するため。冬→夏に戻す条件は設けない(安全側のみ)。
    index.html の seasonTh・gen_find.py の seasonTh と同一。"""
    winter = not (6 <= month <= 10)
    if not winter and ((tmax is not None and tmax < WINTER_TMAX_C)
                       or (tmin is not None and tmin < WINTER_TMIN_C)):
        winter = True
    if winter:
        return {"mode": "冬山・残雪期", "wind": (8, 12), "precip": (1, 3)}
    return {"mode": "夏山", "wind": (10, 15), "precip": (1, 5)}


def sum_or_none(vals):
    """合計。ただし有効値が1つも無ければ None を返す。
    `sum(v or 0 ...)` だと「0mm」と「データ無し」が区別できず、データ欠測が
    「降水量0mm＝好条件」に化けてしまうため、区別できる形で合計する。"""
    vs = [v for v in vals if v is not None]
    return sum(vs) if vs else None


RANK = {"A": 0, "B": 1, "C": 2}


def block_index(ridge_ws, precip_3h, th, temp_min=None, feels=None, vis_min=None):
    """3時間ブロックの登山指数。(A/B/C, 降格理由) を返す。判定材料が無ければ (None, "")

    主判定は稜線風と降水量の2項目。降水確率は参考表示のみ。
    雷(CAPE)は局地性が高く「その時間帯に登山行動が適しているか」とは性質が異なるため
    指数には含めず、⚡発雷リスクとして独立表示する(lightning_risk)。

    主判定のあとに降格条件(D1 湿潤低体温 / D2 体感温度 / D4 視界不良)を重ねる。
    風と降水だけでは、冬の-20℃・風7m/s や 夏の雨中12m/s が A のまま出てしまい、
    実際に低体温症・凍傷が起きる条件を「登山適」と表示してしまうため。
    降格は安全側にのみ効かせ、材料が欠測の条件はスキップする。

    降格理由は「主判定より悪い評価を出した条件」の名前。主判定どおりなら空文字。
    理由を出さずに B が出ると、風も雨も基準内なのに B になる理由が利用者に分からない。"""
    # 主判定の材料が両方とも欠測なら「判定不能」。ここで A を返すと、データが無いだけの
    # 時間帯が「登山適」として表示され、安全と逆方向に誤解させる (Open-Meteo は非対応項目や
    # 予報期間外を 400 ではなく null で返すため、欠測は現実に起こりうる)
    if ridge_ws is None and precip_3h is None:
        return None, ""
    idx = "A"

    def worse(v):
        nonlocal idx
        if v == "C" or idx == "C":
            idx = "C"
        elif v == "B":
            idx = "B"

    w_b, w_c = th["wind"]
    p_b, p_c = th["precip"]
    if ridge_ws is not None:
        if ridge_ws >= w_c:
            worse("C")
        elif ridge_ws >= w_b:
            worse("B")
    if precip_3h is not None:
        if precip_3h >= p_c:
            worse("C")
        elif precip_3h >= p_b:
            worse("B")

    # ---- 降格条件。優先度は 低体温 > 体感 > 視界 (先に立ったものが理由になる) ----
    demotions = []
    # D1 湿潤低体温: 濡れ + 風 + 低温。2009年トムラウシ(7月・気温8〜10℃・風20m/s・雨)の型。
    # 夏でも起きるので季節に依存させない。
    if (temp_min is not None and precip_3h is not None and ridge_ws is not None
            and temp_min <= WET_HYPO_TEMP_C and precip_3h >= WET_HYPO_PRECIP_MM):
        if ridge_ws >= WET_HYPO_WIND_C:
            demotions.append(("C", "低体温"))
        elif ridge_ws >= WET_HYPO_WIND_B:
            demotions.append(("B", "低体温"))
    # D2 体感温度: 凍傷リスク。体感温度(Apparent Temperature)は気温・風・湿度から算出する
    if feels is not None:
        if feels <= FEELS_C_C:
            demotions.append(("C", "体感"))
        elif feels <= FEELS_B_C:
            demotions.append(("B", "体感"))
    # D4 視界不良: 地吹雪・ホワイトアウト。視程が欠測のときは発火させない(欠測を危険側にも倒さない)
    if (vis_min is not None and ridge_ws is not None
            and vis_min < VIS_LOW_M and ridge_ws >= VIS_LOW_WIND):
        demotions.append(("C", "視界"))

    reason = ""
    for grade, label in demotions:
        if RANK[grade] > RANK[idx]:
            idx, reason = grade, label
    return idx, reason


LT_LABEL = ("低", "やや注意", "注意", "高い")


def lightning_risk(cape, cin):
    """発雷リスク(表示専用。A/B/C 指数の判定には使わない。index.html の lightningRisk と同一)

    CAPE = 対流の「燃料」、CIN = 上昇を抑える「蓋」。燃料が多くても蓋が厚ければ発雷しにくい。
    そこで CAPE で大枠の段階を決め、蓋が厚いぶんだけ段階を下げる。
    CAPE の区切り 500/1000/2500 は一般的な雷雨の目安に合わせたもの
    (references/criteria.md の「CAPEの目安」参照)。

    CIN 側は「下げる」方向にのみ効かせる。Open-Meteo の convective_inhibition は
    絶対値(J/kg)で返り、実データでは中央値 1〜15・約半数が 0 と「蓋なし」が既定状態のため、
    蓋が薄いことを理由に段階を上げると、ほぼ全ての時刻が上振れして意味を成さなくなる。
    呼び出し側は「蓋が最も薄い時刻」= |CIN| 最小値を渡す(安全側)。
    """
    if cape is None:
        return None
    lv = 3 if cape >= 2500 else 2 if cape >= 1000 else 1 if cape >= 500 else 0
    if cin is not None:
        a = abs(cin)
        if a >= 100:
            lv -= 2  # 強い蓋。よほどの引き金がなければ対流は始まらない
        elif a >= 50:
            lv -= 1  # ある程度の蓋
    lv = max(0, min(3, lv))
    return lv, LT_LABEL[lv]


def lightning_cell(cape, cin):
    """詳細表の発雷リスクセル。アイコンの本数(1〜4)と段階ラベル、続けて元の数値を併記"""
    lt = lightning_risk(cape, cin)
    if lt is None:
        return "-"
    lv, label = lt
    # CIN は API が絶対値で返すが、慣例に合わせて負値表記で見せる(0 は素の 0)
    num = f"CAPE {cape:.0f}"
    if cin is not None:
        num += f" / CIN {0 if abs(cin) < 0.5 else -abs(cin):.0f}"
    return f"{'⚡' * (lv + 1)} {label} ({num})"


def feels_like(temp, ridge_ws, rh):
    """体感温度: 豪州気象局の Apparent Temperature (Steadman)。気温・風・湿度から算出する。

        e  = (RH/100) × 6.105 × exp(17.27×T / (237.7+T))   … 水蒸気圧(hPa)
        AT = T + 0.33×e − 0.70×風速(m/s) − 4.00

    **なぜ風冷指数(JAG/TI式)をやめたか**
    JAG/TI は「気温10℃以下・風速4.8km/h以上」でのみ有効な式で、寒冷時の顔面の熱損失に
    較正されている。式の構造上 `+0.3965×T×V^0.16` の項が気温に比例して増えるため、
    **約22℃を超えると気温より高い値を返す**(気温25℃・風14m/s で 25.9℃)。
    かといって10℃で打ち切って気温をそのまま返すと、今度は
    **10〜22℃の帯で冷却がまったく表現されない**(実測: 飯豊山で気温13.8℃・稜線風17m/s・
    雨1.9mm でも体感13.8℃)。しかも10℃境界で不連続になる(10.0℃→5.5℃ / 11.0℃→11.0℃)。
    どちらも登山者に誤った印象を与えるので、全温度域で有効な AT に置き換えた。

    実測での整合: 寒冷域では JAG/TI とよく一致する(-15℃・12m/s で -27.8 vs -27.0)。
    山岳では平均 2〜6℃ 低め、夏の低山では高め(蒸し暑さを反映)に出る。

    **高温多湿では体感が気温を上回る**(30℃・RH90%・微風で 37.2℃)。これは湿度で
    熱が逃げないことを表す正しい挙動なので、`min(f, temp)` のような抑えは入れない。

    - 日射は考慮しない(日なたでは実際より涼しく出る)。
    - 風は稜線風(山頂標高)を渡す。式は地上10m風を前提にしているが、
      登山者が受ける風は稜線の風なのでこちらを使う(JAG/TI 時代と同じ扱い)。
    - 材料が1つでも欠測なら None を返す(「-」表示)。ここで気温をそのまま返すと、
      他の欠測が全て「-」なのにこの列だけ数値が出て、欠測だと気づけない。
    """
    if temp is None or ridge_ws is None or rh is None:
        return None
    e = (rh / 100.0) * 6.105 * math.exp(17.27 * temp / (237.7 + temp))
    return temp + 0.33 * e - 0.70 * ridge_ws - 4.00


IDX_MARK = {"A": "A", "B": "B", "C": "C"}


def idx_cell(bi, reason=""):
    """指数セル。降格条件で落ちたときはその理由を併記する。
    理由が無いと「風も降水も基準内なのに B」になった説明が利用者に付かない。
    index.html の idxCell と同一。"""
    if bi is None:
        return "-"
    return IDX_MARK[bi] + (f" {reason}" if reason else "")


# 雨雪判別。雪片は0℃高度から落下する間に融けるので、雨雪の境界は0℃高度より下に出る。
PHASE_SNOW_MARGIN_M = 100  # 0℃高度が「山頂標高 - これ」より低ければ雪
PHASE_RAIN_MARGIN_M = 200  # 0℃高度が「山頂標高 + これ」より高ければ雨


def precip_phase(freezing_level, elev):
    """降水の形態 雪/みぞれ/雨。材料が無ければ None。表示のみでA/B/C判定には使わない。
    冬モードの「3h降水3mm以上=C」は水換算なので、雨か雪かは表示側で補う必要がある
    (1℃の雨は-5℃の雪より低体温リスクが高いのに、数字は同じ 3.0mm にしかならない)。"""
    if freezing_level is None or elev is None:
        return None
    if freezing_level < elev - PHASE_SNOW_MARGIN_M:
        return "雪"
    if freezing_level > elev + PHASE_RAIN_MARGIN_M:
        return "雨"
    return "みぞれ"


WET_PRECIP_MM = 0.1   # 濡れ注意を出す最小の降水量
# 濡れ注意を出す気温の上限。D1 の 10℃ より高くしてあるのは意図的で、表示専用の値。
# 風冷指数は10℃超で適用外になり「体感=気温」を返す。つまり気温10〜15℃の帯は
# **体感の数字が冷えを一切表さなくなる**(実測: 飯豊山で気温13.8℃・稜線風17m/s・雨1.9mm でも
# 体感13.8℃と表示される)。数字が穏やかに見える帯こそ濡れ+風の低体温が起きるので、
# ここは印で補う。判定(D1)のしきい値は 10℃ のまま変えていない
# (15℃に上げても4山×11日で判定の変化はゼロだった。主判定の風・降水が既に拾っている)。
WET_WARN_TEMP_C = 15


def wet_warn(temp, ridge_ws, precip_3h):
    """濡れ+風+低温がそろっているか。体感温度の数字だけでは伝わらない冷えを補う印。
    体感温度は乾いた状態の値なので、濡れているときは表示より大きく下がる。

    ★ 相対湿度は条件に使わない。実測(7日間・毎時)で山頂の RH は中央値 89〜91%、
      95%以上が 23〜40% の時間を占め、視程45kmの快晴でも 95% を超える。
      RH を条件にすると印がほぼ常時点灯し、本当に濡れる日と区別できなくなる。"""
    if temp is None or ridge_ws is None or precip_3h is None:
        return False
    return (temp <= WET_WARN_TEMP_C and ridge_ws >= WET_HYPO_WIND_B
            and precip_3h >= WET_PRECIP_MM)


# ---------------------------------------------------------------- 景色(眺望)
V_LABEL = {"◎": "展望良好", "○": "良好", "△": "ガス", "✕": "雨・濃霧"}
# ✕ は原因(雨/ガス)が分かるので、そのときは「雨・濃霧」より具体的なラベルにする
V_LABEL_NG = {"雨": "雨", "ガス": "濃霧"}


def view_score(elev, low, mid, precip_3h, vis, rh=None):
    """山頂からの景色(眺望) ◎/○/△/✕。雲層(下層<2km/中層2-7km/上層>7km)を山頂標高と比較。
    山頂レベルの雲=ガス、山頂より下の雲=雲海の可能性。
    上層雲(すじ雲等)は眺望を妨げないため引数に取らない。
    判定材料(雲量・視程・降水)が1つも無ければ None を返す。

    rh(相対湿度)は視程が欠測のときだけ使う。視程欠測でも雲量が少なければ ◎ が出るため、
    「データが無い」が「展望良好」に化けるのを防ぐ代替材料として置いている。"""
    # 全部欠測のまま進むと「雲量0扱い・視程不明」で ◎(展望良好) が出てしまい、
    # データが無いだけの時間帯を好条件と誤解させる
    if low is None and mid is None and vis is None and precip_3h is None:
        return None
    if elev < 2000:
        summit_cl = max(v for v in (low, mid) if v is not None) if (low is not None or mid is not None) else None
        below_cl = None  # 低山は下に雲層バンドなし(谷霧は表現できない)
    else:
        summit_cl = mid
        below_cl = low
    if precip_3h is not None and precip_3h >= 1:
        return "✕", "雨"
    if vis is not None and vis < 2000:
        return "✕", "ガス"
    if summit_cl is not None and summit_cl >= 80:
        return "✕", "ガス"
    if (summit_cl is not None and summit_cl >= 50) or (vis is not None and vis < 10000):
        return "△", ""
    unkai = below_cl is not None and below_cl >= 60 and (summit_cl or 0) <= 30
    if (summit_cl or 0) <= 20 and (vis is None or vis >= 20000):
        # 視程が欠測のときは相対湿度で裏を取る。高湿ならガスの可能性があるので ◎ にしない
        if vis is None and rh is not None and rh >= VIEW_RH_GATE:
            return "○", "雲海" if unkai else ""
        return "◎", "雲海" if unkai else ""
    return "○", "雲海" if unkai else ""


def vis_text(vis):
    """視程の表記。1km以上はkm・未満はmで丸める"""
    if vis is None:
        return None
    return f"{vis / 1000:.0f}km" if vis >= 1000 else f"{vis:.0f}m"


def view_cell(vw, note, vis=None):
    """景色(眺望)セル。記号+ラベル、雲海なら付記、判定に使った視程を括弧で併記
    (Web版 index.html の vhtml と同じ内容。Markdownは改行できないので1行にまとめる)。
    雨/ガスの付記は ✕「雨・濃霧」/ △「ガス」のラベル自体に含まれるので出さない。"""
    label = V_LABEL_NG.get(note, V_LABEL[vw]) if vw == "✕" else V_LABEL[vw]
    s = f"{vw} {label}" + ("(雲海)" if note == "雲海" else "")
    vt = vis_text(vis)
    return s + (f" (視程{vt})" if vt else "")


# ---------------------------------------------------------------- 予報取得
# 気象庁モデルに存在しない項目。JMA_URL に投げても 400 にはならず全て null で返ってくるため、
# 「エラーが出ないから取れている」と誤解しやすい。必ず FORECAST_URL 側から補完する。
# freezing_level_height は実測で気象庁モデルは全期間 null、FORECAST_URL は 264/264 取得できた。
SUPPLEMENT_HOURLY = ["precipitation_probability", "wind_gusts_10m",
                     "cape", "convective_inhibition", "visibility", "snow_depth",
                     "freezing_level_height"]
SUPPLEMENT_DAILY = ["precipitation_probability_max"]

# 周辺CAPE を見る方位オフセット(度)。緯度0.25度 ≒ 28km / 経度0.25度 ≒ 22km(北緯36度)。
# 山岳雷を起こすのは谷や麓の湿った下層気塊が地形に持ち上げられたもので、山頂格子の CAPE は
# その気塊を表さない。実測(槍ヶ岳・11日間): 山頂格子 CAPE最大 1340 に対し松本 3050、
# 264時刻中172時刻で麓が上回り最大差 2410 J/kg。山頂だけ見ると1〜2段階低く出る。
CAPE_NEIGHBOR_DEG = 0.25


def _merge_series(base, extra, keys):
    """extra の系列を base の time 軸に「時刻をキーにして」貼り直す。
    2本のAPIは end_date のクランプ結果が食い違いうるので、添字が揃っている前提を置かない。
    足りない時刻は None で埋めるため、下流は必ず base["time"] と同じ長さの列を得る。"""
    pos = {t: i for i, t in enumerate(extra.get("time") or [])}
    for k in keys:
        src = extra.get(k) or []
        base[k] = [src[pos[t]] if t in pos and pos[t] < len(src) else None
                   for t in base["time"]]


def _merge_neighbor_cape(base, lat, lon, common):
    """周辺4方位の CAPE/CIN を取り、山頂と合わせた最大値を cape_area / cin_area に入れる。

    山岳雷を起こすのは谷や麓の湿った下層気塊が地形に持ち上げられたもので、山頂格子の CAPE は
    その気塊を表さない。実測(槍ヶ岳・11日間): 山頂格子の CAPE最大 1340 に対し周辺は 3050、
    264時刻中172時刻で周辺が上回り最大差 2410 J/kg。山頂だけ見ると1〜2段階低く出る。

    ★ 山頂の cape / convective_inhibition は上書きせず別キーに入れる。
      ⚠夕方フラグの雷条件(lv>=2)にこの値を入れると、夏は周辺のどこかが必ず 1000 J/kg を
      超えるためフラグがほぼ毎日立ち、日を区別できなくなる(実測: 槍ヶ岳で 11日中 1日 → 10日)。
      毎日出る警告は無視されるので、安全と逆方向に働く。
      発雷リスクの「表示」だけ周辺最大を使い、フラグの入力は山頂格子のままにする。

    Open-Meteo はカンマ区切りのマルチ地点に対応し、1リクエストで配列が返るので
    リクエスト数は増えない。CIN は CAPE が最大だった地点のものを使う
    (持ち上げられる気塊の蓋を見たいので、山頂の蓋ではなく燃料の出どころの蓋)。
    取得に失敗しても山頂の値だけで従来どおり動く(発雷リスクは補助表示のため)。"""
    o = CAPE_NEIGHBOR_DEG
    lats = [lat + o, lat - o, lat, lat]
    lons = [lon, lon, lon + o, lon - o]
    # elevation は外す。CAPE は気柱の量で標高指定に依存せず、1つの値を4地点に渡すと
    # 地点ごとの標高と食い違う。期間指定(start/end)とタイムゾーンだけ引き継ぐ。
    params = {k: v for k, v in common.items() if k not in ("latitude", "longitude", "elevation")}
    try:
        res = http_json(FORECAST_URL, dict(
            params, latitude=",".join(f"{v:.4f}" for v in lats),
            longitude=",".join(f"{v:.4f}" for v in lons),
            hourly="cape,convective_inhibition"))
    except Exception:
        return False
    if not isinstance(res, list):
        return False
    times = base["time"]
    cape = list(base.get("cape") or [None] * len(times))
    cin = list(base.get("convective_inhibition") or [None] * len(times))
    for loc in res:
        hr = loc.get("hourly") or {}
        pos = {t: k for k, t in enumerate(hr.get("time") or [])}
        ca, ci = hr.get("cape") or [], hr.get("convective_inhibition") or []
        for i, t in enumerate(times):
            k = pos.get(t)
            if k is None or k >= len(ca) or ca[k] is None:
                continue
            if cape[i] is None or ca[k] > cape[i]:
                cape[i] = ca[k]
                cin[i] = ci[k] if k < len(ci) else None
    base["cape_area"], base["cin_area"] = cape, cin
    return True


def area_cape(h, block):
    """ブロックの発雷リスク入力 (CAPE=最大, CIN=|最小|)。周辺を含めた最大値を使う。
    周辺の取得に失敗していれば山頂格子の値に落ちる。"""
    ca = h.get("cape_area") or h.get("cape") or []
    ci = h.get("cin_area") or h.get("convective_inhibition") or []
    cape = max((ca[i] for i in block if i < len(ca) and ca[i] is not None), default=None)
    cin = min((ci[i] for i in block if i < len(ci) and ci[i] is not None), key=abs, default=None)
    return cape, cin


def fetch_forecast(lat, lon, elev, start, end, levels):
    hourly = ["temperature_2m", "relative_humidity_2m", "precipitation",
              "weather_code", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
              "wind_speed_10m", "wind_direction_10m", "snowfall",
              # 上空の寒気。実測で気象庁モデルは 850/700/500hPa とも全期間そろう
              # (気圧面「風」が MSM 6面 / GSM 4面と違うのとは別扱い)
              "temperature_850hPa", "temperature_700hPa", "temperature_500hPa"]
    for p, _ in levels:
        hourly += [f"wind_speed_{p}hPa", f"wind_direction_{p}hPa"]
    common = {
        "latitude": lat, "longitude": lon, "elevation": elev,
        "timezone": "Asia/Tokyo", "wind_speed_unit": "ms",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    }
    data = http_json(JMA_URL, dict(common,
        hourly=",".join(dict.fromkeys(hourly)),
        daily="weather_code,temperature_2m_max,temperature_2m_min,"
              "precipitation_sum,snowfall_sum,sunrise,sunset"))
    sup = http_json(FORECAST_URL, dict(common,
        hourly=",".join(SUPPLEMENT_HOURLY), daily=",".join(SUPPLEMENT_DAILY)))
    _merge_series(data["hourly"], sup.get("hourly") or {}, SUPPLEMENT_HOURLY)
    _merge_series(data["daily"], sup.get("daily") or {}, SUPPLEMENT_DAILY)
    data["cape_neighbor"] = _merge_neighbor_cape(data["hourly"], lat, lon, common)
    return data


def day_indices(times, date):
    pre = date.isoformat()
    return [i for i, t in enumerate(times) if t.startswith(pre)]


def fnum(v, fmt="{:.0f}", none="-"):
    return none if v is None else fmt.format(v)


PAST_DAYS = 3  # 直近実況(モデル解析値)として遡る日数


def has_snow_period(h):
    """取得期間内に積雪・降雪が一度でもあるか。無ければ各表の積雪列自体を省略して夏山の表を簡潔に保つ"""
    depth = h.get("snow_depth") or []
    fall = h.get("snowfall") or []
    return (any(v is not None and v >= 0.01 for v in depth)
            or any(v is not None and v >= 0.1 for v in fall))


def snow_cell(depth_m, sf_cm):
    """積雪列の表示。「85cm(+12)」= 積雪深85cm・新雪12cm"""
    if depth_m is None and sf_cm is None:
        return "-"
    txt = "-" if depth_m is None else f"{depth_m * 100:.0f}cm"
    if sf_cm is not None and sf_cm >= 0.5:
        txt += f"(+{sf_cm:.0f})"
    return txt


# ---------------------------------------------------------------- 直近実況
def past_summary_rows(data, dates, elev):
    """直近数日の実況(モデル解析値)の日別行"""
    h, d = data["hourly"], data["daily"]
    times = h["time"]
    wx = summarize_daily_weather(times, h["weather_code"])
    depth_all = h.get("snow_depth") or []
    sf_all = d.get("snowfall_sum") or [None] * len(d["time"])
    rows = []
    for date in dates:
        try:
            di = d["time"].index(date.isoformat())
        except ValueError:
            continue
        idxs = day_indices(times, date)
        act = [i for i in idxs if 5 <= int(times[i][11:13]) <= 17]
        rws = [ridge_wind(h, i, elev) for i in act]
        ws = max((s for s, _ in rws if s is not None), default=None)
        wd = next((dd for s, dd in rws if s == ws), None)
        depth = max((depth_all[i] for i in idxs if i < len(depth_all) and depth_all[i] is not None),
                    default=None)
        wxd = wx.get(date.isoformat(), {})
        rows.append({"date": date, "code": wxd.get("code", d["weather_code"][di]),
                     "notes": wxd.get("notes", []),
                     "tmin": d["temperature_2m_min"][di], "tmax": d["temperature_2m_max"][di],
                     "ws": ws, "wd": wd, "pr": d["precipitation_sum"][di], "sf": sf_all[di],
                     "depth": depth})
    return rows


def print_past_summary(rows, has_snow, elev):
    if not rows:
        return
    print(f"\n### 直近の実況(モデル解析値・過去{len(rows)}日)")
    snow_h = " 積雪max(新雪) |" if has_snow else ""
    snow_sep = "---|" if has_snow else ""
    print(f"| 日付 | 天気 | 山頂気温 | {wind_label(elev)}max(5-17時) | 降水量 |{snow_h}")
    print(f"|---|---|---|---|---|{snow_sep}")
    for r in rows:
        wj = "月火水木金土日"[r["date"].weekday()]
        snow_c = f" {snow_cell(r['depth'], r['sf'])} |" if has_snow else ""
        print(f"| {r['date'].strftime('%m/%d')}({wj}) | {wcode(r['code'])}{wx_note_text(r.get('notes'))} "
              f"| {fnum(r['tmin'], '{:.0f}')}〜{fnum(r['tmax'], '{:.0f}')}℃ "
              f"| {wdir(r['wd'])} {fnum(r['ws'], '{:.1f}')}m/s "
              f"| {fnum(r['pr'], '{:.1f}')}mm |{snow_c}")
    print("- ※モデル解析値であり観測所の実測ではありません。現地の最新情報を優先してください")


# ---------------------------------------------------------------- 出力
def print_detail_day(data, date, elev, has_snow=False, step=3):
    h = data["hourly"]
    times = h["time"]
    idxs = day_indices(times, date)
    if not idxs:
        return
    d = data["daily"]
    suntxt = ""
    try:
        di = d["time"].index(date.isoformat())
        if d.get("sunrise") and d["sunrise"][di]:
            suntxt = f" (日の出{d['sunrise'][di][11:16]} / 日の入{d['sunset'][di][11:16]})"
    except (ValueError, KeyError):
        pass
    # 夏冬モードはその日の山頂気温も見て決める。日単位で決め、その日の全ブロックに同じ閾値を使う
    # (同一日の中でブロックごとに閾値が変わると、表の中で基準がぶれて読めなくなるため)
    th = season_thresholds(date.month, *mode_temps(h, times, date))
    depth_all = h.get("snow_depth") or []
    sfh_all = h.get("snowfall") or []
    vis_hall = h.get("visibility") or []
    rh_hall = h.get("relative_humidity_2m") or []
    snow_h = " 積雪(新雪) |" if has_snow else ""
    snow_sep = "---|" if has_snow else ""

    def block_abc(start_h3):
        """指数は表示間隔によらず3時間ブロック単位で判定 (A/B/Cの降水閾値がmm/3h定義のため)。
        降格条件の材料もこの3時間ブロックから安全側に取る(気温=最小・風=最大・視程=最小)。"""
        blk3 = [i for i in idxs if int(times[i][11:13]) // 3 * 3 == start_h3]
        if not blk3:
            return None, ""
        rws3 = [ridge_wind(h, i, elev) for i in blk3]
        ws3 = max((s for s, _ in rws3 if s is not None), default=None)
        pr3 = sum_or_none(h["precipitation"][i] for i in blk3)
        t3 = min((h["temperature_2m"][i] for i in blk3
                  if h["temperature_2m"][i] is not None), default=None)
        v3 = min((vis_hall[i] for i in blk3
                  if i < len(vis_hall) and vis_hall[i] is not None), default=None)
        # 湿度は最大値(最も熱が逃げにくい = 安全側)
        rh3 = max((rh_hall[i] for i in blk3
                   if i < len(rh_hall) and rh_hall[i] is not None), default=None)
        return block_index(ws3, pr3, th, t3, feels_like(t3, ws3, rh3), v3)

    print(f"\n### {date.isoformat()} ({'月火水木金土日'[date.weekday()]}) "
          f"{'1時間ごと' if step == 1 else '3時間ごと'}詳細{suntxt}")
    print(f"| 時刻 | 指数 | 天気 | 🏔 景色(眺望) | 気温 | 体感 | {wind_label(elev)} | 突風 | 降水 | 降水%(参考) | ⚡発雷リスク | 雲(下/中/上) |{snow_h}")
    print(f"|---|---|---|---|---|---|---|---|---|---|---|---|{snow_sep}")
    for start_h in range(0, 24, step):
        block = [i for i in idxs if int(times[i][11:13]) // step * step == start_h]
        if not block:
            continue
        i0 = block[0]
        temp = h["temperature_2m"][i0]
        rws = [ridge_wind(h, i, elev) for i in block]
        ws = max((s for s, _ in rws if s is not None), default=None)
        wd = next((d for s, d in rws if s == ws), None)
        gust = max((h["wind_gusts_10m"][i] for i in block if h["wind_gusts_10m"][i] is not None), default=None)
        pr = sum_or_none(h["precipitation"][i] for i in block)
        prob = max((h["precipitation_probability"][i] for i in block
                    if h["precipitation_probability"][i] is not None), default=None)
        # CAPE は周辺4方位を含めた最大、CIN は「蓋が最も薄い時刻」(絶対値の最小 = 安全側)
        cape, cin = area_cape(h, block)
        rh_all = h.get("relative_humidity_2m") or []
        rh = rh_all[i0] if i0 < len(rh_all) else None
        feel = feels_like(temp, ws, rh)
        cl = f'{fnum(h["cloud_cover_low"][i0])}/{fnum(h["cloud_cover_mid"][i0])}/{fnum(h["cloud_cover_high"][i0])}%'
        vis_all = h.get("visibility") or []
        vis = min((vis_all[i] for i in block if i < len(vis_all) and vis_all[i] is not None), default=None)
        vw = view_score(elev, h["cloud_cover_low"][i0], h["cloud_cover_mid"][i0],
                        None if pr is None else pr * 3 / step, vis, rh)
        vw_txt = view_cell(*vw, vis) if vw else "-"
        bi, reason = block_abc(start_h // 3 * 3)
        # 体感は乾いた状態の値。濡れ+風+低温がそろう時間帯は印を付けて「表示より下がる」と示す。
        # 桁数は必ず気温と揃える。気温が小数1桁・体感が整数だと、風冷式の適用外(気温10℃超)で
        # 「体感=気温」を返したときに 12.8℃ → 体感13℃ となり、風で暖まるように見える。
        feel_c = fnum(feel, '{:.1f}') + ("℃ 濡れ注意" if wet_warn(temp, ws, pr) else "℃")
        # 降水は水換算なので、雨か雪かを 0℃高度から補って出す(表示のみ・判定には使わない)
        fl_all = h.get("freezing_level_height") or []
        fl = min((fl_all[i] for i in block if i < len(fl_all) and fl_all[i] is not None), default=None)
        phase = precip_phase(fl, elev)
        pr_c = fnum(pr, '{:.1f}') + "mm" + (f"({phase})" if phase and pr and pr >= 0.1 else "")
        snow_c = ""
        if has_snow:
            depth = max((depth_all[i] for i in block if i < len(depth_all) and depth_all[i] is not None),
                        default=None)
            sf_blk = sum(sfh_all[i] or 0 for i in block if i < len(sfh_all))
            snow_c = f" {snow_cell(depth, sf_blk)} |"
        print(f"| {start_h:02d}時 | {idx_cell(bi, reason)} | {wcode(h['weather_code'][i0])} | {vw_txt} | {fnum(temp, '{:.1f}')}℃ "
              f"| {feel_c} | {wdir(wd)} {fnum(ws, '{:.1f}')}m/s | {fnum(gust, '{:.0f}')}m/s "
              f"| {pr_c} | {fnum(prob)}% | {lightning_cell(cape, cin)} | {cl} |{snow_c}")


def morning_view(h, times, idxs, elev):
    """朝(4-8時)の景色の最良値。ご来光・朝の展望の目安。
    併記する視程は「採用した時刻そのもの」の値を使う(ブロックの最小値ではない)"""
    order = {"◎": 0, "○": 1, "△": 2, "✕": 3}
    best, best_note, best_vis = None, "", None
    vis_all = h.get("visibility") or []
    rh_all = h.get("relative_humidity_2m") or []
    for i in idxs:
        hr = int(times[i][11:13])
        if not 4 <= hr <= 8:
            continue
        vis = vis_all[i] if i < len(vis_all) else None
        rh = rh_all[i] if i < len(rh_all) else None
        p1 = h["precipitation"][i]
        pr3 = None if p1 is None else p1 * 3
        sc = view_score(elev, h["cloud_cover_low"][i], h["cloud_cover_mid"][i], pr3, vis, rh)
        if sc is None:
            continue  # その時刻は判定材料なし。最良値の候補に入れない
        vw, note = sc
        if best is None or order[vw] < order[best]:
            best, best_note, best_vis = vw, note, vis
    if best is None:
        return "-"
    return view_cell(best, best_note, best_vis)


def daily_summary_rows(data, dates, elev):
    h = data["hourly"]
    d = data["daily"]
    times = h["time"]
    wx = summarize_daily_weather(times, h["weather_code"])
    depth_all = h.get("snow_depth") or []
    sf_all = d.get("snowfall_sum") or [None] * len(d["time"])
    rows = []
    for date in dates:
        try:
            di = d["time"].index(date.isoformat())
        except ValueError:
            continue
        idxs = day_indices(times, date)
        vis_all = h.get("visibility") or []
        rh_all = h.get("relative_humidity_2m") or []

        def blk_verdict(block, th):
            """ブロックの指数と降格理由。降格条件の材料は安全側に取る
            (気温=最小・風=最大・降水=合計・視程=最小)"""
            rws = [ridge_wind(h, i, elev) for i in block]
            ws = max((s for s, _ in rws if s is not None), default=None)
            pr = sum_or_none(h["precipitation"][i] for i in block)
            tmn = min((h["temperature_2m"][i] for i in block
                       if h["temperature_2m"][i] is not None), default=None)
            vmn = min((vis_all[i] for i in block
                       if i < len(vis_all) and vis_all[i] is not None), default=None)
            # 湿度は最大値(最も熱が逃げにくい = 安全側)
            rhx = max((rh_all[i] for i in block
                       if i < len(rh_all) and rh_all[i] is not None), default=None)
            bi, rs = block_index(ws, pr, th, tmn, feels_like(tmn, ws, rhx), vmn)
            return bi, rs, ws, rws

        # 夏冬モードはその日の山頂気温も見て決める(日単位。同一日内では閾値を変えない)
        th = season_thresholds(date.month, *mode_temps(h, times, date))
        # 行動時間帯 5-17時で指数判定
        act = [i for i in idxs if ACT_HOURS[0] <= int(times[i][11:13]) <= ACT_HOURS[1]]
        # 判定できたブロックだけを集め、その最悪値を日の指数にする。
        # 1つも判定できなければ day_idx は None (判定不能) のままにする
        verdicts = []
        ws_max, wd_max = None, None
        for start_h in range(3, 18, 3):
            block = [i for i in act if int(times[i][11:13]) // 3 * 3 == start_h]
            if not block:
                continue
            bi, rs, ws, rws = blk_verdict(block, th)
            if ws is not None and (ws_max is None or ws > ws_max):
                ws_max = ws
                wd_max = next((dd for s, dd in rws if s == ws), None)
            if bi is not None:
                verdicts.append((bi, rs))
        day_idx = next((v for v in ("C", "B", "A") if v in [b for b, _ in verdicts]), None)
        # 日の指数を決めたブロックの降格理由を採用する(最悪値と同じ評価の最初のもの)
        day_reason = next((r for b, r in verdicts if b == day_idx and r), "")
        # 日中がA/Bで夕方(17-20時)が荒れるなら急変警告フラグ (日中の指数は変えない)。
        # 風雨がC相当のときに加えて、発雷リスクが「注意」以上のときも立てる
        eve = [i for i in idxs if 17 <= int(times[i][11:13]) <= 20]
        evening = False
        if eve and day_idx is not None and day_idx != "C":
            evening = blk_verdict(eve, th)[0] == "C"
            if not evening:
                # 雷の条件は「山頂格子の」CAPE で見る。周辺最大を入れると夏はほぼ毎日
                # lv>=2 に達してフラグが日を区別できなくなる(_merge_neighbor_cape の注記参照)
                ca = h.get("cape") or []
                ci = h.get("convective_inhibition") or []
                cape_e = max((ca[i] for i in eve if i < len(ca) and ca[i] is not None), default=None)
                cin_e = min((ci[i] for i in eve if i < len(ci) and ci[i] is not None),
                            key=abs, default=None)
                lt_e = lightning_risk(cape_e, cin_e)
                evening = lt_e is not None and lt_e[0] >= 2
        # 夜間(21時〜翌5時)の荒天フラグ。行動時間帯にも夕方にも入らないため、これまで
        # この帯は完全に無評価だった。冬型では風のピークが夜間に来ることが多く、
        # テント泊・小屋泊・早発ち(アルパインスタート)で最初に効く。
        # 発雷は条件に入れない(夜間のテント泊で効くのは風)。
        nxt = (date + dt.timedelta(days=1)).isoformat()
        night = [i for i, t in enumerate(times)
                 if (t.startswith(date.isoformat()) and int(t[11:13]) >= 21)
                 or (t.startswith(nxt) and int(t[11:13]) <= 5)]
        night_bad = False
        if night and day_idx is not None and day_idx != "C":
            night_bad = blk_verdict(night, th)[0] == "C"
        depth = max((depth_all[i] for i in idxs if i < len(depth_all) and depth_all[i] is not None),
                    default=None)
        # 最終日(11日目)は GSM が昼過ぎで切れるため daily の集計値が丸ごと null で返る。
        # その日の hourly が部分的にでも残っていれば、そこから同じ値を作り直して行を埋める。
        def hmax(key, fn=max):
            vs = [h[key][i] for i in idxs if h.get(key) and h[key][i] is not None]
            return fn(vs) if vs else None

        def hsum(key):
            vs = [h[key][i] for i in idxs if h.get(key) and h[key][i] is not None]
            return sum(vs) if vs else None

        tmax = d["temperature_2m_max"][di]
        tmin = d["temperature_2m_min"][di]
        pr_d = d["precipitation_sum"][di]
        sf_d = sf_all[di]
        if tmax is None:
            tmax = hmax("temperature_2m")
        if tmin is None:
            tmin = hmax("temperature_2m", min)
        if pr_d is None:
            pr_d = hsum("precipitation")
        if sf_d is None:
            sf_d = hsum("snowfall")
        wxd = wx.get(date.isoformat(), {})
        rows.append({
            "date": date, "idx": day_idx, "reason": day_reason,
            "evening": evening, "night": night_bad, "mode": th["mode"],
            "code": wxd.get("code", d["weather_code"][di]), "notes": wxd.get("notes", []),
            "tmin": tmin, "tmax": tmax,
            "ws": ws_max, "wd": wd_max,
            "pr": pr_d, "prob": d["precipitation_probability_max"][di],
            "sf": sf_d, "depth": depth,
            "view": morning_view(h, times, idxs, elev),
        })
    return rows


def print_daily_summary(rows, title, has_snow=False, elev=None):
    print(f"\n### {title}")
    snow_h = " 積雪max(新雪) |" if has_snow else ""
    snow_sep = "---|" if has_snow else ""
    print(f"| 日付 | 指数 | 天気 | 🏔 景色(朝) | 山頂気温 | {wind_label(elev)}max(5-17時) | 降水量 | 降水%(参考) |{snow_h}")
    print(f"|---|---|---|---|---|---|---|---|{snow_sep}")
    for r in rows:
        wj = "月火水木金土日"[r["date"].weekday()]
        mark = (idx_cell(r["idx"], r.get("reason", ""))
                + (" ⚠夕方" if r.get("evening") else "")
                + (" ⚠夜間" if r.get("night") else ""))
        snow_c = f" {snow_cell(r.get('depth'), r.get('sf'))} |" if has_snow else ""
        print(f"| {r['date'].strftime('%m/%d')}({wj}) | {mark} | {wcode(r['code'])}{wx_note_text(r.get('notes'))} "
              f"| {r['view']} | {fnum(r['tmin'], '{:.0f}')}〜{fnum(r['tmax'], '{:.0f}')}℃ "
              f"| {wdir(r['wd'])} {fnum(r['ws'], '{:.1f}')}m/s "
              f"| {fnum(r['pr'], '{:.1f}')}mm | {fnum(r['prob'])}% |{snow_c}")
    if any(r.get("evening") for r in rows):
        print("- ⚠夕方: 17〜20時に天候の急変(C相当)、または発雷リスク「注意」以上が予想されます。"
              "日中の指数には含めていませんが、"
              "下山遅れ・テント泊・ご来光待ちの際は特に注意してください。")
    if any(r.get("night") for r in rows):
        print("- ⚠夜間: 21時〜翌朝5時にC相当の荒天が予想されます。"
              "日中の指数には含めていませんが、"
              "テント泊・小屋泊・早発ち(アルパインスタート)の際は特に注意してください。")
    # 降格理由の凡例。出た日だけ出す(理由の付かない表に説明だけ残らないように)
    reasons = {r.get("reason") for r in rows if r.get("reason")}
    if reasons:
        legend = {
            "低体温": "低体温=気温10℃以下+降水+風8m/s以上(濡れによる低体温症の条件)",
            "体感": "体感=体感温度-20℃以下(凍傷リスク域)",
            "視界": "視界=視程200m未満+風10m/s以上(地吹雪・ホワイトアウトで行動困難)",
        }
        print("- 指数に付く語は、風・降水の基準ではなく降格条件で下がったことを示します: "
              + " / ".join(legend[k] for k in ("低体温", "体感", "視界") if k in reasons))
    # 今どちらの閾値で判定したかを示す。10/31 と 11/1、寒い日と暖かい日で基準が変わるため
    modes = [r["mode"] for r in rows if r.get("mode")]
    if modes:
        uniq = list(dict.fromkeys(modes))
        th_txt = {"夏山": "稜線風10/15m/s・3h降水1/5mm", "冬山・残雪期": "稜線風8/12m/s・3h降水1/3mm"}
        print("- 判定モード: " + " / ".join(f"{m}({th_txt[m]})" for m in uniq)
              + ("（日ごとに山頂気温を見て切り替わります）" if len(uniq) > 1 else ""))


def signed_c(v):
    """上空気温の表記。寒気は符号が意味を持つので +/- を明示する。
    丸めてから符号を付けないと -0.4℃ が "-0℃" になる。"""
    r = round(v)
    return "0℃" if r == 0 else f"{r:+.0f}℃"


UPPER_LEVELS = [("temperature_850hPa", "850hPa(約1500m)"),
                ("temperature_700hPa", "700hPa(約3000m)"),
                ("temperature_500hPa", "500hPa(約5500m)")]


def print_upper_cold(data, dates):
    """上空の寒気。日中(9-15時)の平均を日ごとに出す。

    寒気の強さは冬型の荒れ方と夏の大気不安定度の両方を規定するが、山頂気温だけでは読めない。
    「なぜ荒れるのか」を自分で判断したい経験者向けの材料として置く。A/B/C判定には使わない。"""
    h = data["hourly"]
    times = h["time"]
    rows = []
    for date in dates:
        idxs = [i for i in day_indices(times, date) if 9 <= int(times[i][11:13]) <= 15]
        if not idxs:
            continue
        cells = []
        for key, _ in UPPER_LEVELS:
            a = h.get(key) or []
            vs = [a[i] for i in idxs if i < len(a) and a[i] is not None]
            # 丸めてから符号を付ける。"{:+.0f}" だと -0.4 が "-0℃" になる
            cells.append(signed_c(sum(vs) / len(vs)) if vs else "-")
        if any(c != "-" for c in cells):
            rows.append((date, cells))
    if not rows:
        return
    print("\n### 上空の寒気(日中9〜15時の平均)")
    print("| 日付 | " + " | ".join(lbl for _, lbl in UPPER_LEVELS) + " |")
    print("|---|---|---|---|")
    for date, cells in rows:
        wj = "月火水木金土日"[date.weekday()]
        print(f"| {date.strftime('%m/%d')}({wj}) | " + " | ".join(cells) + " |")
    print("- 500hPa(上空約5500m)は大気の不安定度の目安。気象庁の雷注意報では"
          "夏-6℃以下・冬-36℃以下が発雷しやすい目安とされます")
    print("- 850hPa(上空約1500m)は冬型の強さの目安。-6℃以下で平地でも雪、"
          "-12℃以下で日本海側は大雪になりやすい")
    print("- A/B/C判定には使いません(気圧配置を自分で読むための参考値です)")


def compare_models(lat, lon, elev, start, end):
    models = ["jma_seamless", "ecmwf_ifs025", "gfs_seamless"]
    labels = {"jma_seamless": "気象庁JMA", "ecmwf_ifs025": "欧州ECMWF", "gfs_seamless": "米国GFS"}
    params = {
        "latitude": lat, "longitude": lon, "elevation": elev,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,cloud_cover",
        "timezone": "Asia/Tokyo", "wind_speed_unit": "ms",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "models": ",".join(models),
    }
    data = http_json(FORECAST_URL, params)
    h = data["hourly"]
    times = h["time"]
    print(f"\n### モデル間比較（予報の確度確認: 各モデルが一致するほど信頼度が高い）")
    print("| 日付 | モデル | 気温min〜max | 降水量 | 10m風max | 平均雲量 |")
    print("|---|---|---|---|---|---|")
    date = start
    while date <= end:
        idxs = day_indices(times, date)
        for m in models:
            def col(v):
                key = f"{v}_{m}"
                if key not in h:
                    key = v
                return [h[key][i] for i in idxs if h.get(key) and h[key][i] is not None]
            temps, precs = col("temperature_2m"), col("precipitation")
            winds, clouds = col("wind_speed_10m"), col("cloud_cover")
            if not temps:
                print(f"| {date.strftime('%m/%d')} | {labels[m]} | (データなし) | | | |")
                continue
            pr_txt = f"{sum(precs):.1f}mm" if precs else "-"
            wind_txt = f"{max(winds):.1f}m/s" if winds else "-"
            cloud_txt = f"{sum(clouds) / len(clouds):.0f}%" if clouds else "-"
            print(f"| {date.strftime('%m/%d')} | {labels[m]} | {min(temps):.0f}〜{max(temps):.0f}℃ "
                  f"| {pr_txt} | {wind_txt} | {cloud_txt} |")
        date += dt.timedelta(days=1)


# ---------------------------------------------------------------- HTML出力
HTML_CSS = """
:root{--accent:#2d6a4f;--accent2:#b5451b;--night:#1e2d4a;--warn:#7b5e00;--bg:#f7f5f0}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:#222;
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic UI","Meiryo",system-ui,sans-serif;
  font-size:14px;line-height:1.6}
main{max-width:1080px;margin:0 auto}
h1{color:var(--accent);font-size:1.4em;border-bottom:3px solid var(--accent);
  padding-bottom:6px;margin:0 0 12px}
h2{color:var(--night);font-size:1.1em;margin:22px 0 8px;border-left:5px solid var(--accent);
  padding-left:8px}
ul.meta{margin:0 0 8px;padding-left:1.2em;color:#555;font-size:.92em}
.tbl{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:6px 0 4px}
table{border-collapse:collapse;white-space:nowrap;width:100%}
th{background:var(--accent);color:#fff;padding:6px 9px;font-weight:600;font-size:.92em}
td{padding:5px 9px;border-bottom:1px solid #e2ddd2;text-align:center;background:#fff}
tr:nth-child(even) td{background:#f3f0e8}
.b{display:inline-block;min-width:2.6em;padding:1px 7px;border-radius:10px;
  font-weight:700;font-size:.92em}
.b-a{background:#d8efe1;color:#1c5b3f}.b-b{background:#fdeec9;color:#7b5e00}
.b-c{background:#f9d9cf;color:#a03415}
.v-ex{color:#1c5b3f;font-weight:700}.v-ok{color:#2d6a4f}.v-so{color:#7b5e00}
.v-ng{color:#a03415}
.sat{color:#1857a4;font-weight:600}.sun{color:#c0392b;font-weight:600}
/* 発雷リスク: 稲妻の本数と色の二重表現。下段に CAPE/CIN の実数値 */
.lt{font-weight:600;white-space:nowrap}
.lt-0{color:#7b6a00}.lt-1{color:#8a5a00}.lt-2{color:#8f4212}.lt-3{color:#a03415}
.ltnum,.vwnum{display:block;font-size:.78em;color:#6b7280;margin-top:2px;line-height:1.3}
.notice{background:#fff8e6;border-left:5px solid var(--warn);padding:10px 12px;
  border-radius:0 6px 6px 0;margin:18px 0;font-size:.92em}
footer{color:#888;font-size:.85em;margin-top:20px}
@media(max-width:600px){body{padding:8px;font-size:13px}}
"""


def _decorate_cell(cell):
    """表セル内の指数/眺望/曜日マークに色クラスを付与"""
    c = html_mod.escape(cell)
    m = re.match(r"^([ABC])($|\s.*)", c)
    if m:
        cls = {"A": "b b-a", "B": "b b-b", "C": "b b-c"}[m.group(1)]
        return f'<span class="{cls}">{m.group(1)}</span>{m.group(2)}'
    m = re.match(r"^(⚡+)\s(低|やや注意|注意|高い)\s\((.+)\)$", c)
    if m:
        # 発雷リスク: 段階に応じた色を付け、CAPE/CIN の実数値は下段に小さく表示
        lv = min(len(m.group(1)) - 1, 3)
        return (f'<span class="lt lt-{lv}">{m.group(1)} {m.group(2)}</span>'
                f'<span class="ltnum">{m.group(3)}</span>')
    m = re.match(r"^([◎○△✕])\s(\S+?)(\s\(視程(.+)\))?$", c)
    if m:
        # 景色(眺望): 判定色を付け、併記の視程は下段に小さく表示 (Web版の2段構成に合わせる)
        cls = {"◎": "v-ex", "○": "v-ok", "△": "v-so", "✕": "v-ng"}[m.group(1)]
        vis = f'<span class="vwnum">視程 {m.group(4)}</span>' if m.group(4) else ""
        return f'<span class="{cls}">{m.group(1)} {m.group(2)}</span>{vis}'
    c = c.replace("(土)", '<span class="sat">(土)</span>').replace("(日)", '<span class="sun">(日)</span>')
    return c


def md_to_html(md, title):
    """本スクリプトが出力するMarkdown(見出し/箇条書き/表/引用)をHTMLに変換"""
    out, table, ul = [], [], False

    def flush_table():
        nonlocal table
        if not table:
            return
        out.append('<div class="tbl"><table>')
        for ri, row in enumerate(table):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if ri == 1 and all(set(c) <= set("-: ") for c in cells):
                continue
            tag = "th" if ri == 0 else "td"
            out.append("<tr>" + "".join(
                f"<{tag}>{_decorate_cell(c) if tag == 'td' else html_mod.escape(c)}</{tag}>"
                for c in cells) + "</tr>")
        out.append("</table></div>")
        table = []

    def flush_ul():
        nonlocal ul
        if ul:
            out.append("</ul>")
            ul = False

    for line in md.splitlines():
        if line.startswith("|"):
            flush_ul()
            table.append(line)
            continue
        flush_table()
        if line.startswith("## "):
            flush_ul()
            out.append(f"<h1>{html_mod.escape(line[3:])}</h1>")
        elif line.startswith("### "):
            flush_ul()
            out.append(f"<h2>{html_mod.escape(line[4:])}</h2>")
        elif line.startswith("- "):
            if not ul:
                out.append('<ul class="meta">')
                ul = True
            out.append(f"<li>{html_mod.escape(line[2:])}</li>")
        elif line.startswith("> "):
            flush_ul()
            out.append(f'<div class="notice">{html_mod.escape(line[2:])}</div>')
        elif line.strip():
            flush_ul()
            out.append(f"<p>{html_mod.escape(line)}</p>")
    flush_table()
    flush_ul()
    out.append("<footer>データ: Open-Meteo (CC BY 4.0) / PeakWeather</footer>")
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html_mod.escape(title)}</title><style>{HTML_CSS}</style></head>"
            "<body><main>" + "\n".join(out) + "</main></body></html>")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="山名")
    ap.add_argument("--select", type=int, help="候補が複数の時に選ぶ番号")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--elev", type=float, help="山頂標高m (この高さの気象を出す)")
    ap.add_argument("--label", default="指定地点")
    ap.add_argument("--date", help="詳細表示の開始日 YYYY-MM-DD (省略時は今日から)")
    ap.add_argument("--interval", type=int, choices=[1, 3], default=3,
                    help="詳細の表示間隔 (時間)。既定3、1で1時間ごと")
    # 旧オプション。互換のため受け付けるが動作には影響しない
    # (常に4日詳細・11日見通し・モデル比較を表示)
    ap.add_argument("--days", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--weekly", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--compare-models", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--html", nargs="?", const="AUTO", metavar="PATH",
                    help="HTMLレポートも保存 (パス省略時はカレントに自動命名)")
    ap.add_argument("--open", action="store_true", help="--html 保存後にブラウザで開く")
    args = ap.parse_args()

    if args.name:
        label, lat, lon, elev, src = resolve_mountain(args.name, args.select)
        if args.elev:
            elev, src = args.elev, src + " (標高は指定値)"
    elif args.lat is not None and args.lon is not None and args.elev is not None:
        label, lat, lon, elev, src = args.label, args.lat, args.lon, args.elev, "座標指定"
    else:
        ap.error("--name か --lat/--lon/--elev を指定してください")

    today = dt.date.today()
    horizon = today + dt.timedelta(days=JMA_DAYS - 1)
    if args.date:
        start = dt.date.fromisoformat(args.date)
        if start > horizon:
            sys.exit(f"ERROR: {args.date} は予報範囲外です(最長{JMA_DAYS}日先={horizon}まで)。"
                     f"直前に再確認してください。")
        if start < today:
            sys.exit(f"ERROR: {args.date} は過去日です。予報は本日以降のみ対応です。")
    else:
        start = today
    detail_end = min(start + dt.timedelta(days=3), horizon)  # 詳細は固定4日間
    fetch_start = today - dt.timedelta(days=PAST_DAYS)  # 直近実況ぶんを遡って取得
    fetch_end = horizon  # 常に11日見通しを表示

    # 気圧面は常に6面すべて取得する。どの面が配信されるかはリクエスト前には分からず
    # (無い面は 400 ではなく全 null で返る)、標高から2面に絞ると GSM 期間に補間できなくなる
    data = fetch_forecast(lat, lon, elev, fetch_start, fetch_end, PRESSURE_LEVELS)

    def emit():
        print(f"## {label} の山岳気象予報")
        print(f"- 地点: 北緯{lat:.4f} 東経{lon:.4f} / 標高 {elev:.0f}m ({src})")
        if elev < LOW_ELEV_M:
            print(f"- 地上風(10m): 標高{LOW_ELEV_M}m未満のため、表示している風はほぼ地上10mの風です"
                  f"(登山指数・体感温度もこの値で判定) / 気温は標高{elev:.0f}m面の値")
        elif elev < BLEND_ELEV_M:
            print(f"- 稜線風: 標高{BLEND_ELEV_M}m未満のため、地上10mの風と上空約{BLEND_ELEV_M}m"
                  f"(925hPa)の風を標高で内挿して算出 / 気温は標高{elev:.0f}m面の値")
        else:
            print(f"- 稜線風: 気象庁モデルの気圧面風(925〜600hPa)と地上10m風のうち、その時刻に値が"
                  f"ある高度から山頂標高に線形補間して算出 / 気温は標高{elev:.0f}m面の値")
        print("- ⚠ 4日目以降は気圧面が2面(900/800hPa)減るため、稜線風をやや弱めに見積もる傾向が"
              "あります(実測: 標高1950〜3010mで平均 -1.2m/s)。指数の風閾値の刻みに対して"
              "1段階ぶんに相当するため、後半の日は強めに読んでください")
        wind_src = '地上風(10m)の風速' if elev < LOW_ELEV_M else '稜線風速'
        print(f"- 登山指数: A=登山適 / B=要注意(経験者向き・行程短縮検討) / C=登山不適。"
              f"主判定は{wind_src}と降水量の2項目。"
              f"これに降格条件(低体温=気温10℃以下+降水+風8m/s以上 / 体感=体感温度-20℃以下 / "
              f"視界=視程200m未満+風10m/s以上)を安全側にのみ重ねます。"
              f"夏山=6〜10月/冬山・残雪期=11〜5月を対象日の月で自動切替し、"
              f"夏の月でも日最高<0℃または日最低<-3℃なら冬モードへ倒します。降水確率は参考表示")
        print("- ⚡発雷リスク: CAPE(対流の燃料)と CIN(上昇を抑える蓋)から算出した4段階の参考表示"
              "(低/やや注意/注意/高い)。指数A/B/Cの判定には使いません。"
              + ("CAPEは山頂と周辺4方位(±0.25度)のうち最大値を採用しています"
                 "(山岳雷の源は谷の下層気塊で、山頂格子だけ見ると過小評価になるため)"
                 if data.get("cape_neighbor") else
                 "周辺CAPEの取得に失敗したため、山頂格子の値のみで算出しています"))
        print("- 🏔 景色(眺望): 山頂付近の雲・視程・降水の3つを組み合わせた4段階(◎○△✕)。"
              "視程は判定に使っている内部要素で、参考として景色欄に併記しています。"
              "展望が無いこと自体より、ガスの中でのルートロストに注意してください")
        print("- 体感温度 = 風冷指数 (JAG/TI式。風速4.8km/h未満と気温10℃超は気温をそのまま採用)。"
              "乾いた状態の値なので、雨や汗で濡れるとこれより大きく下がります"
              "(「濡れ注意」の印が付く時間帯は特に)")
        print("- 突風は地上10mの値です。稜線風(山頂標高の気圧面)とは高度が違うため、"
              "稜線での実際の突風はこの値より強いことがあります")
        print(f"- データ: 気象庁モデル (0〜4日目=MSM 約5km / 5〜{JMA_DAYS}日目=GSM。自動切替)。"
              f"降水確率・突風・CAPE/CIN・視程・積雪深・0℃高度は気象庁モデルに無いため別モデルで補完"
              f" / 取得: {dt.datetime.now():%Y-%m-%d %H:%M} / 出典: Open-Meteo")
        print("- ⚠ 気象庁の警報・注意報も必ず確認してください: https://www.jma.go.jp/bosai/warning/")

        has_snow = has_snow_period(data["hourly"])
        past_dates = [today - dt.timedelta(days=i) for i in range(PAST_DAYS, 0, -1)]
        print_past_summary(past_summary_rows(data, past_dates, elev), has_snow, elev)

        n_days = (fetch_end - today).days + 1
        dates = [today + dt.timedelta(days=i) for i in range(n_days)]
        rows = daily_summary_rows(data, dates, elev)
        print_daily_summary(rows, f"{JMA_DAYS}日間の見通し", has_snow, elev)

        d = start
        while d <= detail_end:
            print_detail_day(data, d, elev, has_snow, step=args.interval)
            d += dt.timedelta(days=1)

        compare_models(lat, lon, elev, start, detail_end)
        # 上空の寒気はモデル間比較の下に置く。行動判断に直結する表(見通し・詳細)を先に読ませ、
        # 気圧配置を自分で読むための参考値は後ろにまとめる。
        print_upper_cold(data, dates)

        print("\n> ⚠️ 数値予報は山岳地形では誤差が大きく、局地的な突風・雷雨・視界不良は表現しきれません。"
              "登山指数は目安です。最終判断は最新の予報と現地の状況で行ってください。")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        emit()
    md = buf.getvalue()
    sys.stdout.write(md)

    if args.html:
        page_title = f"{label} 山岳気象予報 {start.strftime('%m/%d')}"
        if args.html == "AUTO":
            safe = re.sub(r"[^\w぀-ヿ一-鿿]+", "_", label).strip("_")
            path = Path.cwd() / f"yohou_{safe}_{start.isoformat()}.html"
        else:
            path = Path(args.html)
        path.write_text(md_to_html(md, page_title), encoding="utf-8")
        print(f"\nHTML保存: {path}")
        if args.open:
            import webbrowser
            webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
