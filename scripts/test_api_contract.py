#!/usr/bin/env python3
"""Open-Meteo が「いま何を返しているか」を数えて確かめる契約テスト。

**「エラーが出ないから取れている」を否定するための検査。** このAPIは
  - 存在しない項目を要求しても 400 にならず、**全て null で返る**
  - モデルの配信期間を超えて要求しても、**黙って null が並ぶ**
ので、レスポンスが 200 でも中身が空という状態が普通に起きる。しかも MSM 期間だけ見て
「取れている」と判断すると、GSM 期間で欠けている項目を見落とす(実測でそうなっている)。

そこで **キーごと・日ごとに非null件数を数え**、既知の前提を固定する:
  1. 完全な GSM 日には 900hPa・800hPa の風が**1件も無い**
     (切替日だけは1日の中で MSM と GSM が混在するので、そこは除いて数える)
  2. 完全な GSM 日には sunshine_duration が**1件も無い**
  3. cloud_cover / weather_code / precipitation / 925・850・700・600hPa は**全期間ある**
  4. 気象庁モデルに無い項目(降水確率・突風・CAPE・視程・積雪深)は /v1/jma では全null、
     /v1/forecast では取れる
  5. 存在しない項目名を投げても 400 にならず全null で返る(この前提が変わったら教えてほしい)
  6. JMA_DAYS を超えて要求してもエラーにならず、**どこかで部分日になって尽きる**
     (JMA_DAYS=10 は「APIが10日しか返さない」からでも「11日目が必ず部分日だから」でもない。
      尽きる位置がラン時刻で前後するので、その手前に余裕を置いている)
  7. 応答の elevation が要求した標高と一致する

ここが変わったら**モデルの配信仕様が変わった合図**なので、落ちること自体が成果になる。

通信するので既定では走らない。無料利用枠を守るのがこのアプリの前提なので、
**手で --online を付けたときだけ**動く(1回あたり4リクエスト)。

    python scripts/test_api_contract.py --online
    python scripts/test_api_contract.py --online --lat 36.34 --lon 137.65 --elev 3180

依存は標準ライブラリのみ。
"""
import argparse
import datetime as dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mountain_weather as mw          # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# 既定は槍ヶ岳(気圧面が6面とも意味を持つ標高)
DEF_LAT, DEF_LON, DEF_ELEV = 36.34193, 137.64752, 3180

# 全期間そろっているはずのもの
ALWAYS = ["temperature_2m", "relative_humidity_2m", "precipitation", "weather_code",
          "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
          "wind_speed_10m", "snowfall",
          "wind_speed_925hPa", "wind_speed_850hPa", "wind_speed_700hPa", "wind_speed_600hPa",
          "temperature_850hPa", "temperature_700hPa", "temperature_500hPa"]
# GSM 期間には無いはずのもの
MSM_ONLY = ["wind_speed_900hPa", "wind_speed_800hPa", "sunshine_duration"]
# 気象庁モデルに無く、補完APIから取るもの
SUPPLEMENT = ["precipitation_probability", "wind_gusts_10m", "cape",
              "convective_inhibition", "visibility", "snow_depth"]

fails, notes = [], []
checks = 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        fails.append(msg)


def count_nonnull(h, key, times, hours):
    """指定の時刻集合について、その項目の非null件数を返す。"""
    vals = h.get(key)
    if not isinstance(vals, list):
        return None            # キーごと欠けている
    return sum(1 for i in hours if i < len(vals) and vals[i] is not None)


def main():
    ap = argparse.ArgumentParser(description="Open-Meteo の配信内容を数えて確かめる")
    ap.add_argument("--online", action="store_true",
                    help="実際に通信する。付けないと何もしない(無料枠を守るため)")
    ap.add_argument("--lat", type=float, default=DEF_LAT)
    ap.add_argument("--lon", type=float, default=DEF_LON)
    ap.add_argument("--elev", type=float, default=DEF_ELEV)
    a = ap.parse_args()

    if not a.online:
        print("API契約テスト: --online が無いので実行しません")
        print("  通信を伴うため既定では走りません。確かめるときは --online を付けてください")
        print("  (1回あたり4リクエスト。モデルの配信仕様が変わっていないかを見る検査です)")
        return 0

    today = dt.date.today()
    end = today + dt.timedelta(days=mw.JMA_DAYS - 1)
    common = {"latitude": a.lat, "longitude": a.lon, "elevation": a.elev,
              "timezone": "Asia/Tokyo", "wind_speed_unit": "ms",
              "start_date": today.isoformat(), "end_date": end.isoformat()}

    hourly = ALWAYS + MSM_ONLY
    print("API契約テスト: {},{} 標高{}m / {} 〜 {}".format(
        a.lat, a.lon, int(a.elev), today, end))

    # ---- 1本目: 気象庁モデル本体 -----------------------------------------
    d = mw.http_json(mw.JMA_URL, dict(common, hourly=",".join(hourly),
                                      daily="weather_code,temperature_2m_max,precipitation_sum"))
    h = d.get("hourly") or {}
    times = h.get("time") or []
    ok(len(times) > 0, "気象庁モデルの hourly.time が空です")
    if not times:
        return report()

    # 応答の標高が要求と一致するか(ずれると気圧面からの内挿がまるごとずれる)
    got_elev = d.get("elevation")
    ok(got_elev is not None and abs(float(got_elev) - a.elev) < 1.0,
       "応答の elevation が要求と違います: 要求={} 応答={}".format(a.elev, got_elev))

    # MSM 期間 / GSM 期間の切り分けは、日数の決め打ちではなく実データから出す
    dates = sorted({t[:10] for t in times})
    day_model = {}
    for ds in dates:
        # day_model は date オブジェクトを取る(内部で isoformat する)
        day_model[ds] = mw.day_model(h, times, dt.date.fromisoformat(ds))
    msm_days = [ds for ds, m in day_model.items() if m == "MSM"]
    gsm_days = [ds for ds, m in day_model.items() if m != "MSM"]
    ok(msm_days and gsm_days,
       "MSM 期間と GSM 期間の両方が取れていません (MSM={}日 / GSM={}日)".format(
           len(msm_days), len(gsm_days)))
    print("  モデルの切替: MSM {}日 ({} 〜) / GSM {}日 ({} 〜)".format(
        len(msm_days), msm_days[0] if msm_days else "-",
        len(gsm_days), gsm_days[0] if gsm_days else "-"))

    idx_of = {ds: [i for i, t in enumerate(times) if t.startswith(ds)] for ds in dates}
    msm_hours = [i for ds in msm_days for i in idx_of[ds]]
    gsm_hours = [i for ds in gsm_days for i in idx_of[ds]]

    # 切替日は MSM と GSM が混在するので、3つに分けて数える
    boundary = gsm_days[0] if gsm_days else None
    bnd_hours = idx_of[boundary] if boundary else []
    pure_gsm = [i for ds in gsm_days[1:] for i in idx_of[ds]]

    print("  非null件数 (MSM {}h / 切替日 {}h / 完全なGSM日 {}h)".format(
        len(msm_hours), len(bnd_hours), len(pure_gsm)))
    for key in hourly:
        m = count_nonnull(h, key, times, msm_hours)
        b = count_nonnull(h, key, times, bnd_hours)
        g = count_nonnull(h, key, times, pure_gsm)
        want_all = key in ALWAYS
        bad = (not m or not g) if want_all else (g not in (0, None))
        print("    {}{:<26} MSM {:>4} / 切替日 {:>3} / GSM {:>4}".format(
            "✕ " if bad else "  ", key,
            "なし" if m is None else m, "なし" if b is None else b,
            "なし" if g is None else g))

    for key in ALWAYS:
        m = count_nonnull(h, key, times, msm_hours)
        g = count_nonnull(h, key, times, pure_gsm)
        ok(m, "{} が MSM 期間に1件もありません (全期間そろう前提が崩れました)".format(key))
        ok(g, "{} が GSM 期間に1件もありません (全期間そろう前提が崩れました)".format(key))

    # ★ 切替日は1日の中に MSM の時間と GSM の時間が**混在する**(day_model は all で見るので
    #   その日は GSM 扱いになるが、午前中は 900/800hPa が来ている)。なので「GSM 期間は0件」を
    #   期間まるごとに当てると必ず落ちる。切替日を除いた**完全な GSM 日**で 0 件を確かめる。
    if boundary:
        part = {k: count_nonnull(h, k, times, idx_of[boundary]) for k in MSM_ONLY}
        print("  切替日 {} は混在: {}".format(
            boundary, " / ".join("{} {}h".format(k.replace("wind_speed_", ""), v)
                                 for k, v in part.items())))
    for key in MSM_ONLY:
        m = count_nonnull(h, key, times, msm_hours)
        g = count_nonnull(h, key, times, pure_gsm)
        ok(m, "{} が MSM 期間にもありません (補間・日照の前提が崩れました)".format(key))
        ok(g == 0 or g is None,
           "{} が 完全なGSM日 に {} 件あります。**配信仕様が変わった可能性**があります "
           "(いまは『GSM には無い』前提で、稜線風は残りの面から内挿し、"
           "日照は補完APIから別名で取っています)".format(key, g))

    # 気象庁モデルに無い項目は、投げても 400 にならず全null で返る
    d2 = mw.http_json(mw.JMA_URL, dict(common, hourly=",".join(SUPPLEMENT[:3])))
    h2 = d2.get("hourly") or {}
    for key in SUPPLEMENT[:3]:
        n = count_nonnull(h2, key, h2.get("time") or [],
                          range(len(h2.get("time") or [])))
        ok(n in (0, None),
           "気象庁モデルに無いはずの {} が {} 件返っています (補完の要否が変わりました)".format(key, n))
    ok(h2.get("time"), "存在しない項目を投げたら 400 になりました "
                       "(全null で返る前提が変わりました。日数制限の考え方も見直しが要ります)")

    # ---- 2本目: 補完API ---------------------------------------------------
    d3 = mw.http_json(mw.FORECAST_URL, dict(common, hourly=",".join(SUPPLEMENT)))
    h3 = d3.get("hourly") or {}
    t3 = h3.get("time") or []
    print("  補完API (/v1/forecast) の非null件数 (全 {}h)".format(len(t3)))
    for key in SUPPLEMENT:
        n = count_nonnull(h3, key, t3, range(len(t3)))
        print("    {}{:<26} {}".format("  " if n else "✕ ", key, "なし" if n is None else n))
        ok(n, "補完APIでも {} が1件も取れません (この項目は表示できなくなります)".format(key))

    # 2本の期間がずれることがある = 添字一致を前提にしてはいけない、の根拠
    if len(t3) != len(times):
        notes.append("本体と補完で時刻の本数が違います ({} vs {})。"
                     "時刻をキーにして貼り合わせている前提が効いています".format(len(times), len(t3)))

    # ---- 3本目: 期間を超えて要求してもエラーにならないこと ----------------
    over = today + dt.timedelta(days=mw.JMA_DAYS + 4)
    try:
        d4 = mw.http_json(mw.JMA_URL, dict(common, end_date=over.isoformat(),
                                           hourly="temperature_2m"), fatal=False)
    except mw.ApiError:
        d4 = None
    if d4 is None:
        notes.append("予報長を超えた要求が拒否されました。"
                     "いまはコード側(JMA_DAYS)で制限しているので実害はありません")
    else:
        h4 = d4.get("hourly") or {}
        t4 = h4.get("time") or []
        # ★ JMA_DAYS=10 は「APIが10日しか返さないから」ではない。モデルは11日目あたりまで
        #   配信するが、**どこで尽きるかはラン時刻で前後する**(実測 2026-08-21 は11日目が
        #   24時間そろい、12日目が部分日。それ以前は11日目が部分日だった)。部分日を掴むと
        #   日別集計が作れないので、尽きる位置の手前に余裕を置いて10日で止めている。
        #   ここで確かめるのはその前提: 「超えて要求してもエラーにならない」ことと
        #   「どこかで必ず尽きる」こと。日付を決め打ちで縛らない(縛ると毎日落ちる)。
        extra = sorted({t[:10] for t in t4 if t[:10] > end.isoformat()})
        counts = []
        for ds in extra:
            ii = [i for i, t in enumerate(t4) if t.startswith(ds)]
            counts.append((ds, count_nonnull(h4, "temperature_2m", t4, ii), len(ii)))
        print("  予報長({}日)を超えた日の非null件数".format(mw.JMA_DAYS))
        for ds, n, tot in counts:
            print("    {}  {}/{}h {}".format(
                ds, n, tot, "(部分日 = 日別集計が作れない)" if 0 < n < 24 else
                            "(丸ごと欠測)" if n == 0 else ""))
        ok(counts, "予報長を超えて要求したのに、その日の時刻が1つも返っていません")
        ok(any(n < 24 for _, n, _ in counts),
           "予報長を超えた日がすべて丸々埋まっています。APIの配信期間が伸びた可能性が"
           "あります (JMA_DAYS を伸ばせるかの見直し余地)")
        ok(any(n == 0 for _, n, _ in counts),
           "予報長を超えた日がどこまでも埋まっています。日数制限の根拠を確かめ直してください")

    return report()


def report():
    print()
    if fails:
        print("API契約テスト: {} 項目中 {} 件が期待と違います".format(checks, len(fails)))
        for m in fails:
            print("  ✕ " + m)
        print("  ※ ここが落ちたらモデルの配信仕様が変わった合図です。"
              "コード側の前提(補完の要否・稜線風の内挿・日数制限)を見直してください")
        return 1
    print("API契約テスト: {} 項目 ... 既知の前提どおり".format(checks))
    for m in notes:
        print("  ⚠ " + m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
