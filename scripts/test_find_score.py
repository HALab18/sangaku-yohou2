#!/usr/bin/env python3
"""山さがし(docs/find.html)の日和スコア score() のテスト。

score() はこれまで**まったくテストされていなかった**。しかも減点方式なので、
引く材料が無いと 100点=ランクA になり、**「データが無い」が「最高のコンディション」に
化ける**構造をしている。実際にこの型で3回事故が起きている:

  - GSM 期間に稜線風が全行欠測 → 多良岳95点・雲仙岳94点で最上位
  - 気象庁モデルが全滅した地点が「①だけ減点=ランクA」で最上位
  - 冬・快晴・稜線風12m/s(正式判定ではC)が 81点=ランクA で最上位

そこで値を1つずつ書くのではなく、**壊れ方の向き**を確かめる。
「材料が無いなら一覧に出さない」「悪化させてスコアが上がらない」「降水確率は
スコアに入れない」といった性質は、しきい値を変えても書き直しが要らない。

    python scripts/test_find_score.py

docs/find.html は自動生成物なので、対象は**生成元の scripts/gen_find.py**
(CLAUDE.md 規約6。生成物を見ると、生成元を直し忘れた状態でも通ってしまう)。
gen_find.py は1文字も書き換えない。node が無い環境では未検証として飛ばす。

依存は標準ライブラリのみ。
"""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNNER_JS = ROOT / "scripts" / "test_find_score.js"

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# logic.js の LEVELS と同じ気圧面。900/800 は MSM 期間にしか来ない(GSM 期間は欠測)
ALL_LEVELS = [925, 900, 850, 800, 700, 600]
GSM_LEVELS = [925, 850, 700, 600]


def mkday(date="2026-08-12", sun=3600, code=0, precip=0.0, temp=20.0, rh=50.0,
          w10=1.0, wind=2.0, levels=None, snow=None, pprob=None,
          sun_supp=None, sun_gap=0):
    """1日ぶんの hourly/daily を作る。値は毎時一定。

    sun      … 毎時の日照(秒)。窓(7〜15時)の9時間そろって初めて採用される
    sun_gap  … 窓の中で日照を欠測にする時間数(部分欠測の再現)
    levels   … 値を入れる気圧面。None なら全6面(MSM 期間相当)
    """
    if levels is None:
        levels = ALL_LEVELS
    times = ["{}T{:02d}:00".format(date, h) for h in range(24)]
    hr = {"time": times}

    def col(v):
        return [v] * 24

    if sun is not None:
        s = col(sun)
        for i in range(sun_gap):
            s[7 + i] = None          # 窓の頭から欠かす
        hr["sunshine_duration"] = s
    if sun_supp is not None:
        hr["sunshine_supp"] = col(sun_supp)
    if code is not None:
        hr["weather_code"] = col(code)
    if precip is not None:
        hr["precipitation"] = col(precip)
    if pprob is not None:
        hr["precipitation_probability"] = col(pprob)
    if temp is not None:
        hr["temperature_2m"] = col(temp)
    if rh is not None:
        hr["relative_humidity_2m"] = col(rh)
    if w10 is not None:
        hr["wind_speed_10m"] = col(w10)
    if wind is not None:
        for lv in levels:
            hr["wind_speed_{}hPa".format(lv)] = col(wind)
    return {"hourly": hr, "daily": {"snowfall_sum": [snow]}}


MT = {"el": 2500}          # 北ア級。925(760m)〜700(3010m)の間に入る標高


class Batch:
    """呼び出しをためて node に1回だけ渡す(プロセス起動を繰り返さないため)。"""

    def __init__(self):
        self.cases = {}
        self.index = {}

    def add(self, name, fn, args):
        self.cases.setdefault(fn, []).append(args)
        self.index[name] = (fn, len(self.cases[fn]) - 1)
        return name

    def run(self):
        with tempfile.TemporaryDirectory() as d:
            fin = pathlib.Path(d) / "in.json"
            fout = pathlib.Path(d) / "out.json"
            fin.write_text(json.dumps(self.cases, ensure_ascii=False), encoding="utf-8")
            try:
                r = subprocess.run(["node", str(RUNNER_JS), str(fin), str(fout)],
                                   capture_output=True, text=True, encoding="utf-8")
            except (FileNotFoundError, OSError):
                return None
            if r.returncode != 0:
                raise SystemExit("node の実行に失敗しました:\n"
                                 + (r.stdout or "") + "\n" + (r.stderr or ""))
            out = json.loads(fout.read_text(encoding="utf-8"))
        return {n: out[fn][i] for n, (fn, i) in self.index.items()}


def build(b):
    """検査に使う呼び出しを登録する。"""
    # --- 基準となる良い日 ---
    b.add("perfect", "score", [mkday(), MT])
    # --- 欠測 ---
    b.add("all_missing", "score",
          [mkday(sun=None, code=None, precip=None, temp=None, rh=None,
                 w10=None, wind=None), MT])
    # 補完日照(別モデル)だけがある日。気象庁モデルは全滅している
    b.add("only_supp_sun", "score",
          [mkday(sun=None, code=None, precip=None, temp=None, rh=None,
                 w10=None, wind=None, sun_supp=3600), MT])
    # 気象庁の材料があり、日照だけ補完に落ちた日 → sunAlt が立つ
    b.add("supp_sun_with_jma", "score", [mkday(sun=None, sun_supp=3600), MT])
    # 窓9時間のうち3時間が欠測 → 日照は採用しない(部分合計で実際より悪く採点しない)
    b.add("sun_partial", "score", [mkday(sun_gap=3), MT])
    # --- 降水確率はスコアに入れない(CLAUDE.md の明文規約) ---
    b.add("pprob_0", "score", [mkday(pprob=0), MT])
    b.add("pprob_100", "score", [mkday(pprob=100), MT])
    # --- 単調性 ---
    for w in (2, 6, 10, 14, 18, 25):
        b.add("wind_{}".format(w), "score", [mkday(wind=w), MT])
    for p in (0.0, 1.0, 5.0, 10.0, 30.0):
        b.add("precip_{}".format(p), "score", [mkday(precip=p), MT])
    for s in (3600, 2400, 1200, 0):
        b.add("sun_{}".format(s), "score", [mkday(sun=s), MT])
    # --- 夏冬 ---
    b.add("summer_w10", "score", [mkday(wind=10), MT])
    b.add("winter_w10", "score", [mkday(date="2026-01-12", temp=-10.0, wind=10), MT])
    # --- 足切りの境界 ---
    for w in (17.9, 18.0):
        b.add("cut_summer_{}".format(w), "score", [mkday(wind=w), MT])
    for w in (11.9, 12.0):
        b.add("cut_winter_{}".format(w), "score",
              [mkday(date="2026-01-12", temp=-10.0, wind=w), MT])
    for p in (9.9, 10.0):
        b.add("cut_precip_{}".format(p), "score", [mkday(precip=p), MT])
    # --- ランクの境界 ---
    for v in (100, 70, 69, 45, 44, 0):
        b.add("rank_{}".format(v), "rankOf", [v])
    # --- 稜線風: 気圧面が1つも無い時刻 ---
    # 地上10m風だけを渡すと最下点の生値が返り、稜線20m/s相当の日が地上4m/sで通ってしまう
    b.add("ridge_no_level", "ridgeAt", [[None] * 6, [4.0], 0, 2500])
    b.add("ridge_msm", "ridgeAt", [[[20.0]] * 6, [4.0], 0, 2500])
    b.add("ridge_gsm", "ridgeAt",
          [[[20.0], None, [20.0], None, [20.0], [20.0]], [4.0], 0, 2500])
    # GSM 期間(900/800 欠測)の日はスコアが出せること。全行「-」で最上位に出た事故の逆側
    b.add("gsm_day", "score", [mkday(levels=GSM_LEVELS, wind=20), MT])
    return b


def check(r):
    """性質を確かめる。返すのは違反の説明の列。"""
    f = []

    def rank_ok(name, want):
        got = r[name] and r[name]["v"]
        return got

    # ---- 満点 ----
    p = r["perfect"]
    if p is None or p["v"] != 100:
        f.append("快晴・無風・無降水の日が100点にならない: {}".format(p and p["v"]))
    if p and any(v > 0.001 for v in p["brk"].values()):
        f.append("満点の日に減点が付いている: {}".format(p["brk"]))

    # ---- 欠測ガード ----
    if r["all_missing"] is not None:
        f.append("材料が全部欠測なのにスコアが出た: {}"
                 " (減点方式なので一覧の最上位に出てしまう)".format(r["all_missing"]["v"]))
    if r["only_supp_sun"] is not None:
        f.append("気象庁モデルが全滅し補完日照しか無い日にスコアが出た: {}"
                 " (欠測ガードは sunFrac ではなく sunJma で数えること)"
                 .format(r["only_supp_sun"]["v"]))
    if r["supp_sun_with_jma"] is None or not r["supp_sun_with_jma"]["sunAlt"]:
        f.append("補完日照を使った日に sunAlt が立っていない(表示の `*` 印が出ない)")
    if r["perfect"]["sunAlt"]:
        f.append("気象庁の日照を使った日に sunAlt が立っている")
    if r["sun_partial"]["sunFrac"] is not None:
        f.append("日照が窓9時間そろっていないのに採用された: sunFrac={}"
                 " (部分合計は実際より悪く採点する)".format(r["sun_partial"]["sunFrac"]))

    # ---- 降水確率はスコアに入れない ----
    if r["pprob_0"]["v"] != r["pprob_100"]["v"]:
        f.append("降水確率でスコアが動いた: 0%={} / 100%={}"
                 " (pprob は表示専用。減点式に足さないこと)"
                 .format(r["pprob_0"]["v"], r["pprob_100"]["v"]))
    if r["pprob_100"]["pprob"] != 100:
        f.append("降水確率が表示用の値として拾えていない")

    # ---- 単調性 ----
    for key, seq in (("稜線風", [2, 6, 10, 14, 18, 25]),
                     ("降水量", [0.0, 1.0, 5.0, 10.0, 30.0]),
                     ("日照", [3600, 2400, 1200, 0])):
        pre = "wind_" if key == "稜線風" else ("precip_" if key == "降水量" else "sun_")
        vals = [r[pre + str(x)]["v"] for x in seq]
        for i in range(len(vals) - 1):
            if vals[i + 1] > vals[i]:
                f.append("{}を悪くしたのにスコアが上がった: {} -> {} ({})"
                         .format(key, vals[i], vals[i + 1], seq[i + 1]))

    # ---- 減点の上限 ----
    LIMITS = {"sun": 36, "pre": 30, "wind": 32, "cold": 10}   # ①28+悪天8 / ② / ③ / ④
    for name, s in r.items():
        if not isinstance(s, dict) or "brk" not in s:
            continue
        for k, lim in LIMITS.items():
            if s["brk"][k] > lim + 1e-9:
                f.append("{}: 減点 {} が上限 {} を超えた: {}".format(name, k, lim, s["brk"][k]))
        if not (0 <= s["v"] <= 100):
            f.append("{}: スコアが 0〜100 の外: {}".format(name, s["v"]))

    # ---- 冬は同じ風でも厳しい ----
    # 総スコアで比べてはいけない。冬の日は寒気の減点(④)も乗るので、風のスパンを夏と
    # 同じに戻しても総スコアは夏より低いままになり、違いが埋もれる(実際にこの書き方だと
    # 「冬の風スパンを夏に戻す」変異が素通りした)。減点③そのものを見る。
    ws_s, ws_w = r["summer_w10"]["brk"]["wind"], r["winter_w10"]["brk"]["wind"]
    if ws_w <= ws_s:
        f.append("冬モードなのに同じ風速(10m/s)で風の減点が夏以下: 夏={:.2f} / 冬={:.2f}"
                 " (冬は正式判定の 8/12m/s に合わせて前倒しするはず)".format(ws_s, ws_w))
    if not r["winter_w10"]["winter"]:
        f.append("1月・気温-10℃の日が冬モードになっていない")

    # ---- 足切りの境界 ----
    # isDangerous は score の戻り値を見るので、ここでは材料が境界どおり出ているかを確かめる
    for name, want, label in (("cut_summer_17.9", 17.9, "夏の足切り直下"),
                              ("cut_summer_18.0", 18.0, "夏の足切りちょうど"),
                              ("cut_winter_11.9", 11.9, "冬の足切り直下"),
                              ("cut_winter_12.0", 12.0, "冬の足切りちょうど")):
        got = r[name]["ridgeWmax"]
        if got is None or abs(got - want) > 1e-6:
            f.append("{}: 稜線風が {} で渡らない (got={})".format(label, want, got))
    if abs(r["cut_precip_9.9"]["psum"] - 9.9 * 9) > 1e-6:
        f.append("降水量の窓(7〜15時の9時間)の合計が合わない: {}"
                 .format(r["cut_precip_9.9"]["psum"]))

    # ---- ランクの境界 ----
    for v, want in ((100, "a"), (70, "a"), (69, "b"), (45, "b"), (44, "c"), (0, "c")):
        got = r["rank_{}".format(v)]
        if got != want:
            f.append("rankOf({}) が {} (期待 {})".format(v, got, want))

    # ---- 稜線風 ----
    if r["ridge_no_level"] is not None:
        f.append("気圧面が1つも無い時刻に稜線風の値が出た: {}"
                 " (地上10m風だけで内挿すると、稜線20m/s相当の日が地上4m/sで通る)"
                 .format(r["ridge_no_level"]))
    if r["ridge_msm"] is None or r["ridge_msm"]["degraded"]:
        f.append("6面そろっているのに degraded 扱いになった: {}".format(r["ridge_msm"]))
    if r["ridge_gsm"] is None or not r["ridge_gsm"]["degraded"]:
        f.append("900/800hPa が欠測なのに degraded が立たない: {}".format(r["ridge_gsm"]))
    if r["gsm_day"] is None or r["gsm_day"]["ridgeWmax"] is None:
        f.append("GSM 期間(900/800欠測)の日に稜線風が出ない"
                 " (全行「-」の山が減点されず最上位に出る)")
    if r["gsm_day"] and not r["gsm_day"]["ridgeDegraded"]:
        f.append("GSM 期間の日に ridgeDegraded が立たない(`*` 印が出ない)")

    return f


def main():
    b = build(Batch())
    r = b.run()
    if r is None:
        print("山さがしのスコア: ⚠ node が見つからないため未検証です")
        return 0
    fails = check(r)
    print("山さがしのスコア(gen_find.py の score): {} 項目 ... {}".format(
        len(r), "違反 {} 件".format(len(fails)) if fails else "違反なし"))
    for x in fails:
        print("  NG " + x)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
