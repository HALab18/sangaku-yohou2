#!/usr/bin/env python3
"""表示まわりが CLI と Web で一致するかのテスト。

判定ロジック(A/B/C)は logic.js に一本化され、references/logic_cases.json で
機械検証されている。だが**表示の側は一本化されていない** ── 天気の文言・
「濡れ注意」の印・雨雪判別・積雪や視程の表記は、scripts/mountain_weather.py と
index.html に同じものが2重に書かれたままで、どちらもテストされていなかった。

ここが崩れると、判定は正しいのに画面の文言だけが違う。過去には
「表示間隔を1時間ごとに変えると濡れ注意の印が消える」(安全と逆方向)という
壊れ方をしている。値そのものより、**片方だけ直したことに気づけない**のが問題。

    python scripts/test_display.py
    python scripts/test_display.py --n 2000

index.html は一切書き換えない。scripts/test_display.js が DOM に触らない範囲だけを
切り出して評価する。node が無い環境では未検証として飛ばす。

アイコンの有無は CLI(markdown)と Web(HTML)で違って当然なので、フレーズは
文字列の列に落としてから比べる。HTML を組み立てるだけの関数(idxCell・vhtml・ltCell)は
出力形式そのものが違うので対象にしない。

依存は標準ライブラリのみ。
"""
import argparse
import json
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mountain_weather as mw          # noqa: E402
from test_logic import same, norm      # noqa: E402

RUNNER_JS = ROOT / "scripts" / "test_display.js"

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# WMO 天気コード(Open-Meteo が返しうる値)
WMO = [0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
       71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99]


def phrase_text(ph):
    """JS 側と同じ正規化。CLI は既に文字列の列なのでそのまま。"""
    return None if ph is None else list(ph)


# 丸めの向きは ver 2.46β で揃えた。Python は f"{v:.0f}" / round() が偶数丸め、
# JS の Math.round は四捨五入で、ちょうど .5 のときだけ1ズレていた(6,456ケース中532件)。
# CLI 側に r0()/fint() を入れて四捨五入に寄せたので、ここは**厳密比較**に戻してある。
# 例外扱いを復活させないこと(丸め以外の新しいズレまで飲み込んでしまう)。


def py_summarize(times, codes):
    """Python は {日付: {...}} の辞書、JS は配列。どちらも時刻順なので列に揃える。"""
    got = mw.summarize_daily_weather(times, codes)
    return [[d, v["code"], v["notes"], phrase_text(v.get("phrase"))] for d, v in got.items()]


FUNCS = {
    "timingLabel": lambda a: mw._timing_label(a[0]),
    "wetWarn": lambda a: mw.wet_warn(a[0], a[1], a[2]),
    "precipPhase": lambda a: mw.precip_phase(a[0], a[1]),
    "snowCell": lambda a: mw.snow_cell(a[0], a[1]),
    "visTxt": lambda a: mw.vis_text(a[0]),
    "singleCodePhrase": lambda a: phrase_text(mw.single_code_phrase(a[0])),
    "dayWeatherPhrase": lambda a: phrase_text(mw.day_weather_phrase(a[0])),
    "summarizeDailyWeather": lambda a: py_summarize(a[0], a[1]),
}


# ---------------------------------------------------------------- 入力の生成
def maybe(rnd, v, p=0.15):
    return None if rnd.random() < p else v


def gen_win(rnd):
    """[{hour, code}] の窓。集約の窓は 4〜17時なので、その内外を混ぜる。"""
    hours = sorted(rnd.sample(range(0, 24), rnd.randint(1, 12)))
    # 1日ぜんぶ同じ天気・2種類だけ、といった素直な日も混ぜる(実データはこの形が多い)
    pool = rnd.sample(WMO, rnd.choice([1, 1, 2, 2, 3, 5]))
    return [{"hour": h, "code": rnd.choice(pool)} for h in hours]


def gen_series(rnd):
    """hourly.time / hourly.weather_code。末端が null になる形(GSM打ち切り)も作る。"""
    days = rnd.randint(1, 4)
    times, codes = [], []
    pool = rnd.sample(WMO, rnd.choice([1, 2, 3, 5]))
    for d in range(days):
        for h in range(24):
            times.append("2026-08-{:02d}T{:02d}:00".format(10 + d, h))
            codes.append(rnd.choice(pool))
    # 末尾を欠測にする(予報末端の形。混ぜると重症度比較が壊れるので落とす仕様)
    if rnd.random() < 0.4:
        for i in range(rnd.randint(1, 20)):
            codes[-1 - i] = None
    # 途中の飛び欠測
    if rnd.random() < 0.3:
        for _ in range(rnd.randint(1, 5)):
            codes[rnd.randrange(len(codes))] = None
    return [times, codes]


def half_step(rnd, lo, hi, step):
    """ちょうど .5 で終わる値を厚めに引く。丸め方の違い(偶数丸め ⇄ 四捨五入)は
    ここでしか表に出ない。"""
    if rnd.random() < 0.6:
        return round(rnd.randrange(lo, hi) + 0.5, 4) * step
    return round(rnd.uniform(lo, hi) * step, 4)


def gen_cases(rnd, n):
    c = {k: [] for k in FUNCS}
    for _ in range(n):
        c["timingLabel"].append([sorted(rnd.sample(range(0, 24), rnd.randint(1, 8)))])
        c["wetWarn"].append([maybe(rnd, round(rnd.choice([15, 10, 0]) + rnd.choice([-0.1, 0, 0.1]), 2)),
                             maybe(rnd, round(rnd.choice([8, 12]) + rnd.choice([-0.1, 0, 0.1]), 2)),
                             maybe(rnd, round(rnd.choice([0.1, 1.0]) + rnd.choice([-0.01, 0, 0.01]), 3))])
        elev = rnd.choice([120, 800, 1500, 2500, 3776])
        c["precipPhase"].append([maybe(rnd, round(elev + rnd.choice([-200, -101, -100, -99, 0,
                                                                     199, 200, 201]), 1)), elev])
        # 積雪深(m)・新雪(cm)。cm 換算がちょうど .5 になる値を厚めに入れる
        c["snowCell"].append([maybe(rnd, half_step(rnd, 0, 300, 0.01), 0.25),
                              maybe(rnd, half_step(rnd, 0, 50, 1), 0.25)])
        c["visTxt"].append([maybe(rnd, half_step(rnd, 0, 50, 1000) / 1000 * 1000, 0.1)])
        c["singleCodePhrase"].append([rnd.choice(WMO)])
        c["dayWeatherPhrase"].append([gen_win(rnd)])
        c["summarizeDailyWeather"].append(gen_series(rnd))
    # 天気コードは全値を必ず1回は通す(乱数まかせだと珍しいコードが漏れる)
    for code in WMO:
        c["singleCodePhrase"].append([code])
        c["dayWeatherPhrase"].append([[{"hour": h, "code": code} for h in range(4, 18)]])
    return c


# ---------------------------------------------------------------- 実行
def run_python(cases):
    out = {}
    for name, args_list in cases.items():
        fn = FUNCS[name]
        out[name] = [fn(args) for args in args_list]
    return out


def run_node(cases):
    with tempfile.TemporaryDirectory() as d:
        fin = pathlib.Path(d) / "in.json"
        fout = pathlib.Path(d) / "out.json"
        fin.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        try:
            r = subprocess.run(["node", str(RUNNER_JS), str(fin), str(fout)],
                               capture_output=True, text=True, encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        if r.returncode != 0:
            raise SystemExit("node の実行に失敗しました:\n"
                             + (r.stdout or "") + "\n" + (r.stderr or ""))
        return json.loads(fout.read_text(encoding="utf-8"))


def compare(cases, py, js, max_report):
    """関数ごとに (不一致件数, 全件数, 実例) を返す。"""
    report = {}
    for name in cases:
        fails, shown = 0, []
        for i, args in enumerate(cases[name]):
            if same(py[name][i], js[name][i]):
                continue
            fails += 1
            if len(shown) < max_report:
                shown.append("    in     = {}\n    CLI    = {}\n    Web    = {}".format(
                    json.dumps(args, ensure_ascii=False)[:160],
                    json.dumps(norm(py[name][i]), ensure_ascii=False)[:160],
                    json.dumps(js[name][i], ensure_ascii=False)[:160]))
        report[name] = (fails, len(cases[name]), shown)
    return report


def main():
    ap = argparse.ArgumentParser(description="表示まわりが CLI と Web で一致するか")
    ap.add_argument("--n", type=int, default=800, help="1関数あたりのケース数 (既定 800)")
    ap.add_argument("--seed", type=int, default=20260821)
    ap.add_argument("--max-report", type=int, default=3)
    a = ap.parse_args()

    rnd = random.Random(a.seed)
    cases = gen_cases(rnd, a.n)
    py = run_python(cases)
    js = run_node(cases)
    if js is None:
        print("表示の一致(CLI vs Web): ⚠ node が見つからないため未検証です")
        return 0

    report = compare(cases, py, js, a.max_report)
    total = sum(v[1] for v in report.values())
    bad = sum(v[0] for v in report.values())
    print("表示の一致(CLI vs Web): {} ケース中 {}".format(
        total, "不一致 {} 件".format(bad) if bad else "全件一致"))
    for name, (fails, n, shown) in report.items():
        mark = "OK" if not fails else "NG"
        print("  {} {:<22} {}/{}".format(mark, name, n - fails, n))
        for s2 in shown:
            print(s2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
