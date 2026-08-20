#!/usr/bin/env python3
"""判定ロジックの乱数総当たり + 不変条件テスト。

references/logic_cases.json は「人が選んだ代表値」の表で、書いた人が思いつかなかった
組み合わせは当然入らない。ここでは同じ9関数を乱数で大量に叩き、次の2つを見る。

  1. 等価性  … 同じ入力に対して Python(CLI) と JS(logic.js) が同じ出力を返すか
                (入力表の生成は Python 側の1箇所だけで行い、node へ渡す。
                 生成を両言語に書くと「同じ入力で比べている」前提自体が崩れる)
  2. 不変条件… 値そのものではなく「壊れ方の向き」を見る。
                風を強くしたら指数は決して良くならない、材料が全部欠測なら判定不能、
                欠測が好条件に化けない ── といった性質を確かめる。
                期待値を1つずつ書く方式と違い、しきい値を変えても書き直しが要らず、
                このリポジトリで実際に何度も起きた「欠測→好条件」型の事故を直接突ける。

    python scripts/test_logic_fuzz.py              # 既定 3000 ケース/関数
    python scripts/test_logic_fuzz.py --n 20000    # 増やす
    python scripts/test_logic_fuzz.py --seed 7     # 種を変える

種は既定で固定(再現するため)。node が無い環境では等価性の比較だけを飛ばし、
不変条件は Python 側だけで走らせる(scripts/check_mountains.py の [4/5] と同じ扱い)。

依存は標準ライブラリのみ(CLI本体の依存ゼロを崩さない)。
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
from test_logic import same, norm      # noqa: E402  (比較器は等価性テストと同じものを使う)

RUNNER_JS = ROOT / "scripts" / "test_logic_fuzz.js"

# 不一致の中身には判定記号(◎ ✕ など)が入る。cp932 のコンソールで落ちると、
# 検査は終わっているのに結果だけ読めなくなるので、置き換えて出す。
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# ケース表の名前 → CLI 側の関数 (test_logic.py の FUNCS と同じ並び)
FUNCS = {
    "seasonTh": mw.season_thresholds,
    "blockIndex": mw.block_index,
    "feelsLike": mw.feels_like,
    "viewScore": mw.view_score,
    "interpWind": mw.interp_wind,
    "sumOrNull": mw.sum_or_none,
    "lightningRisk": mw.lightning_risk,
    "eveThunder": mw.eve_thunder,
    "modelAgree": mw.model_agree,
}

IDX_RANK = {None: -1, "A": 0, "B": 1, "C": 2}
VIEW_RANK = {None: -1, "✕": 0, "△": 1, "○": 2, "◎": 3}


# ---------------------------------------------------------------- 入力の生成
def pick(rnd, thresholds, lo, hi, jitter=0.01):
    """しきい値の直上・直下・ちょうどを厚めに、たまに全域から引く。
    一様乱数だけだと境界(風10.0・降水1.0 など)をまたぐケースがほとんど出ず、
    判定が変わる場所を素通りしてしまう。"""
    if rnd.random() < 0.65 and thresholds:
        t = rnd.choice(thresholds)
        return round(t + rnd.choice([-jitter, 0.0, jitter]), 6)
    return round(rnd.uniform(lo, hi), 2)


def maybe(rnd, v, p=0.15):
    """確率 p で欠測(None)に落とす。欠測は現実に起こるうえ、このアプリで最も危険な入力。"""
    return None if rnd.random() < p else v


def gen_wind(rnd, p=0.15):
    return maybe(rnd, pick(rnd, [8, 10, 12, 15, 18], 0, 40), p)


def gen_precip(rnd, p=0.15):
    return maybe(rnd, pick(rnd, [0, 1, 3, 5, 10], 0, 40), p)


def gen_temp(rnd, p=0.15):
    return maybe(rnd, pick(rnd, [-30, -20, -3, 0, 10, 15], -45, 40), p)


def gen_th(rnd):
    """blockIndex に渡すしきい値。実際に使われる2種類だけを渡す
    (ここで架空のしきい値を混ぜると、実装が持っていない組み合わせを検証してしまう)。"""
    return mw.season_thresholds(rnd.choice([1, 3, 5, 7, 9, 11]))


def gen_pts(rnd):
    """interpWind に渡す [標準高度, 風速] の列。
    MSM(6面) / GSM(900・800が欠測) / 1面だけ / 0面 を織り交ぜる。"""
    levels = [h for _, h in mw.PRESSURE_LEVELS]
    r = rnd.random()
    if r < 0.05:
        keep = []
    elif r < 0.35:
        keep = [h for (hpa, h) in mw.PRESSURE_LEVELS if hpa not in mw.DEGRADED_LEVELS]
    elif r < 0.45:
        keep = [rnd.choice(levels)]
    else:
        keep = [h for h in levels if rnd.random() < 0.8]
    pts = [[mw.SURFACE_WIND_M, round(rnd.uniform(0, 25), 2)]] if rnd.random() < 0.7 else []
    pts += [[h, round(rnd.uniform(0, 45), 2)] for h in sorted(keep)]
    return pts


def gen_cases(rnd, n):
    """9関数ぶんの引数表を作る。ここで作った表をそのまま node へ渡す。"""
    c = {k: [] for k in FUNCS}
    for _ in range(n):
        c["seasonTh"].append([rnd.randint(1, 12), gen_temp(rnd, 0.3), gen_temp(rnd, 0.3)])
        c["blockIndex"].append([gen_wind(rnd), gen_precip(rnd), gen_th(rnd),
                                gen_temp(rnd, 0.25), gen_temp(rnd, 0.25),
                                maybe(rnd, pick(rnd, [200, 2000], 0, 50000), 0.35)])
        c["feelsLike"].append([gen_temp(rnd, 0.12), gen_wind(rnd, 0.12),
                               maybe(rnd, pick(rnd, [95], 0, 100), 0.12)])
        c["viewScore"].append([rnd.choice([120, 800, 1999, 2000, 2001, 3000, 3776]),
                               maybe(rnd, pick(rnd, [20, 30, 50, 60, 80], 0, 100), 0.2),
                               maybe(rnd, pick(rnd, [20, 30, 50, 60, 80], 0, 100), 0.2),
                               gen_precip(rnd, 0.2),
                               maybe(rnd, pick(rnd, [2000, 10000, 20000], 0, 60000, 1), 0.3),
                               maybe(rnd, pick(rnd, [95], 0, 100), 0.3)])
        c["interpWind"].append([gen_pts(rnd), rnd.choice([50, 500, 760, 990, 1460,
                                                          1950, 2500, 3010, 3776, 4200, 5000])])
        c["sumOrNull"].append([[maybe(rnd, round(rnd.uniform(0, 20), 2), 0.4)
                                for _ in range(rnd.randint(0, 4))]])
        c["lightningRisk"].append([maybe(rnd, pick(rnd, [500, 1000, 2500], 0, 4000, 1), 0.2),
                                   maybe(rnd, pick(rnd, [-100, -50, 50, 100], -300, 300, 1), 0.3)])
        c["eveThunder"].append([maybe(rnd, pick(rnd, [500, 1000, 2500], 0, 4000, 1), 0.2),
                                maybe(rnd, pick(rnd, [-100, -50, 50, 100], -300, 300, 1), 0.3),
                                gen_precip(rnd, 0.25)])
        c["modelAgree"].append([[rnd.choice(["A", "B", "C", None, "D", ""])
                                 for _ in range(rnd.choice([2, 3, 3, 3, 4]))]])
    return c


# ---------------------------------------------------------------- 等価性
def run_python(cases):
    out = {}
    for name, args_list in cases.items():
        fn = FUNCS[name]
        out[name] = [fn(*args) for args in args_list]
    return out


def run_node(cases):
    """node で logic.js を回す。node が無ければ None(未検証)を返す。"""
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
            raise SystemExit("node の実行に失敗しました:\n" + (r.stdout or "") + "\n" + (r.stderr or ""))
        return json.loads(fout.read_text(encoding="utf-8"))


def compare(cases, py, js, max_report=5):
    fails = []
    for name in cases:
        shown = 0
        for i, args in enumerate(cases[name]):
            if not same(py[name][i], js[name][i]):
                shown += 1
                if shown <= max_report:
                    fails.append("{} #{}\n    in     = {}\n    python = {}\n    js     = {}".format(
                        name, i,
                        json.dumps(args, ensure_ascii=False),
                        json.dumps(norm(py[name][i]), ensure_ascii=False),
                        json.dumps(js[name][i], ensure_ascii=False)))
        if shown > max_report:
            fails.append("{}: 他 {} 件の不一致は省略".format(name, shown - max_report))
    return fails


# ---------------------------------------------------------------- 不変条件
def inv_block_index(rnd, n):
    """指数は「悪くなる方向」にしか動かない。ここが崩れると安全と逆方向の誤表示になる。"""
    f = []
    for _ in range(n):
        th = gen_th(rnd)
        ws, pr = gen_wind(rnd, 0), gen_precip(rnd, 0)
        tmin, feels = gen_temp(rnd, 0.3), gen_temp(rnd, 0.3)
        vis = maybe(rnd, pick(rnd, [200], 0, 50000), 0.3)
        base = mw.block_index(ws, pr, th, tmin, feels, vis)

        # 材料を悪化させたら決して良くならない
        variants = (
            ("稜線風を強くした", mw.block_index(ws + rnd.uniform(0.1, 10), pr, th, tmin, feels, vis)),
            ("降水を増やした", mw.block_index(ws, pr + rnd.uniform(0.1, 10), th, tmin, feels, vis)),
            ("気温を下げた", mw.block_index(ws, pr, th,
                                     None if tmin is None else tmin - rnd.uniform(0.1, 10),
                                     feels, vis)),
            ("体感を下げた", mw.block_index(ws, pr, th, tmin,
                                     None if feels is None else feels - rnd.uniform(0.1, 10), vis)),
            ("視程を下げた", mw.block_index(ws, pr, th, tmin, feels,
                                     None if vis is None else max(0, vis - rnd.uniform(0.1, 500)))),
        )
        for label, worse in variants:
            if IDX_RANK[worse[0]] < IDX_RANK[base[0]]:
                f.append("blockIndex: {}のに指数が良くなった {} -> {} (ws={}, pr3={}, th={})".format(
                    label, base, worse, ws, pr, th["mode"]))

        # 降格条件は決してランクを上げない(RANK[dem] > RANK[idx] の厳密比較)
        plain = mw.block_index(ws, pr, th, None, None, None)
        if IDX_RANK[base[0]] < IDX_RANK[plain[0]]:
            f.append("blockIndex: 降格材料を足したら指数が良くなった {} -> {}".format(plain, base))

        # B/C には必ず理由が付く(理由が空だと利用者が取るべき行動を選べない)
        if base[0] in ("B", "C") and not base[1]:
            f.append("blockIndex: {} なのに理由が空 (ws={}, pr3={})".format(base[0], ws, pr))
        if base[0] in (None, "A") and base[1]:
            f.append("blockIndex: {} なのに理由が付いた {}".format(base[0], base))

    # 主判定の材料が両方欠測なら必ず判定不能
    for _ in range(n):
        got = mw.block_index(None, None, gen_th(rnd), gen_temp(rnd, 0), gen_temp(rnd, 0),
                             pick(rnd, [200], 0, 50000))
        if norm(got) != [None, ""]:
            f.append("blockIndex: 風・降水が両方欠測なのに判定が出た {}".format(got))
    return f


def inv_feels_like(rnd, n):
    f = []
    for _ in range(n):
        t = round(rnd.uniform(-40, 40), 2)
        ws = round(rnd.uniform(0, 40), 2)
        rh = round(rnd.uniform(0, 100), 2)
        base = mw.feels_like(t, ws, rh)
        # 風が強まって体感が上がるのは「風が吹くと暖かくなる」表示になる(過去に丸めで発生)
        if mw.feels_like(t, ws + 1.0, rh) >= base:
            f.append("feelsLike: 風を強めたのに体感が下がらない t={} ws={} rh={}".format(t, ws, rh))
        if rh < 99 and mw.feels_like(t, ws, rh + 1.0) < base:
            f.append("feelsLike: 湿度を上げたのに体感が下がった t={} ws={} rh={}".format(t, ws, rh))
        # 材料が1つでも欠測なら None(気温をそのまま返すと欠測だと気づけない)
        for args in ((None, ws, rh), (t, None, rh), (t, ws, None)):
            if mw.feels_like(*args) is not None:
                f.append("feelsLike: 材料が欠測なのに値が出た {}".format(args))
    return f


def inv_view_score(rnd, n):
    f = []
    for _ in range(n):
        elev = rnd.choice([120, 800, 1999, 2000, 3000, 3776])
        low = round(rnd.uniform(0, 100), 1)
        mid = round(rnd.uniform(0, 100), 1)
        pr = round(rnd.uniform(0, 5), 2)
        vis = round(rnd.uniform(0, 50000), 1)
        rh = round(rnd.uniform(0, 100), 1)
        base = mw.view_score(elev, low, mid, pr, vis, rh)
        base_rank = VIEW_RANK[base[0] if base else None]

        worse = mw.view_score(elev, min(100, low + 10), min(100, mid + 10), pr, vis, rh)
        if VIEW_RANK[worse[0] if worse else None] > base_rank:
            f.append("viewScore: 雲量を増やしたのに眺望が良くなった {} -> {}".format(base, worse))
        worse = mw.view_score(elev, low, mid, pr, max(0, vis - 3000), rh)
        if VIEW_RANK[worse[0] if worse else None] > base_rank:
            f.append("viewScore: 視程を下げたのに眺望が良くなった {} -> {}".format(base, worse))

        # 材料が1つも無ければ判定不能
        if mw.view_score(elev, None, None, None, None, rh) is not None:
            f.append("viewScore: 材料が全部欠測なのに判定が出た")
        # 「良い方」を名乗るには山頂の雲量か視程が要る(降水0mmだけを根拠に ○/◎ を出さない)
        got = mw.view_score(elev, None, None, 0.0, None, rh)
        if got is not None and got[0] in ("○", "◎"):
            f.append("viewScore: 降水0mmだけを根拠に {} が出た (elev={}, rh={})".format(
                got[0], elev, rh))
    return f


def inv_sum_or_null(rnd, n):
    f = []
    if mw.sum_or_none([]) is not None or mw.sum_or_none([None, None]) is not None:
        f.append("sumOrNull: 有効値が無いのに None を返さない")
    # 0mm と欠測の区別。ここが崩れると欠測が「降水量0mm＝好条件」に化ける
    if mw.sum_or_none([0.0]) != 0 or mw.sum_or_none([None, 0.0]) != 0:
        f.append("sumOrNull: 実測0mm が欠測と同じ扱いになっている")
    for _ in range(n):
        vals = [maybe(rnd, round(rnd.uniform(0, 20), 2), 0.4) for _ in range(rnd.randint(0, 5))]
        got = mw.sum_or_none(vals)
        alive = [v for v in vals if v is not None]
        if not alive:
            if got is not None:
                f.append("sumOrNull: 全欠測なのに {} {}".format(got, vals))
        elif abs(got - sum(alive)) > 1e-9:
            f.append("sumOrNull: 合計が合わない {} -> {}".format(vals, got))
    return f


def inv_interp_wind(rnd, n):
    f = []
    if mw.interp_wind([], 1000) is not None:
        f.append("interpWind: 面が1つも無いのに値を返した")
    for _ in range(n):
        pts = [p for p in gen_pts(rnd) if p]
        if not pts:
            continue
        elev = rnd.choice([50, 760, 1460, 2500, 3776, 5000])
        got = mw.interp_wind(pts, elev)
        speeds = [s for _, s in pts]
        # 内挿・端のクランプしかしないので、必ず既存の面の値の範囲に収まる
        if got is None or got < min(speeds) - 1e-9 or got > max(speeds) + 1e-9:
            f.append("interpWind: 面の値の範囲外を返した {} not in [{}, {}] pts={} elev={}".format(
                got, min(speeds), max(speeds), pts, elev))
    return f


def inv_lightning(rnd, n):
    f = []
    if mw.lightning_risk(None, 0) is not None:
        f.append("lightningRisk: CAPE 欠測なのに段階が出た")
    for _ in range(n):
        cape = round(rnd.uniform(0, 4000), 1)
        cin = round(rnd.uniform(-300, 300), 1)
        base = mw.lightning_risk(cape, cin)
        if not (0 <= base["lv"] <= 3) or base["label"] != mw.LT_LABEL[base["lv"]]:
            f.append("lightningRisk: 段階か表示が壊れている {}".format(base))
        if mw.lightning_risk(cape + rnd.uniform(1, 500), cin)["lv"] < base["lv"]:
            f.append("lightningRisk: CAPE を増やしたのに段階が下がった cape={} cin={}".format(cape, cin))
        # CIN は「蓋」。厚くして段階が上がることはない
        thicker = -(abs(cin) + rnd.uniform(1, 100))
        if mw.lightning_risk(cape, thicker)["lv"] > base["lv"]:
            f.append("lightningRisk: CIN を厚くしたのに段階が上がった cape={} cin={}".format(cape, cin))
    return f


def inv_eve_thunder(rnd, n):
    f = []
    for _ in range(n):
        cape = round(rnd.uniform(0, 4000), 1)
        cin = round(rnd.uniform(-300, 300), 1)
        pr = round(rnd.uniform(0, 10), 2)
        if mw.eve_thunder(None, cin, pr):
            f.append("eveThunder: CAPE 欠測なのに警告が立った")
        # 「降水が欠測→警告を出さない」は安全と逆方向。欠測時は降水条件を課さない
        if mw.eve_thunder(cape, cin, None) != mw.eve_thunder(cape, cin, mw.EVE_THUNDER_PRECIP):
            f.append("eveThunder: 降水欠測が警告を抑えた cape={} cin={}".format(cape, cin))
        if mw.eve_thunder(cape, cin, pr) and not mw.eve_thunder(cape + rnd.uniform(1, 500), cin, pr):
            f.append("eveThunder: CAPE を増やしたら警告が消えた cape={} cin={} pr={}".format(
                cape, cin, pr))
    return f


def inv_model_agree(rnd, n):
    f = []
    for _ in range(n):
        idxs = [rnd.choice(["A", "B", "C"]) for _ in range(3)]
        base = mw.model_agree(idxs)
        shuffled = idxs[:]
        rnd.shuffle(shuffled)
        # 並び順で確度が変わるなら「どのモデルが悪いか」を見てしまっている
        if mw.model_agree(shuffled) != base:
            f.append("modelAgree: 並び順で結果が変わった {} -> {}".format(idxs, shuffled))
        # 1つでも欠測・未知なら判定不能(「取れなかった→揃っている」に倒さない)
        for bad in (None, "D", ""):
            broken = idxs[:]
            broken[rnd.randrange(3)] = bad
            if mw.model_agree(broken) is not None:
                f.append("modelAgree: 欠測を含むのに確度が出た {}".format(broken))
        if mw.model_agree(idxs[:2]) is not None:
            f.append("modelAgree: 3モデル未満なのに確度が出た")
    return f


def inv_season_th(rnd, n):
    f = []
    for m in range(1, 13):
        th = mw.season_thresholds(m, None, None)
        want = "夏山" if 6 <= m <= 10 else "冬山・残雪期"
        if th["mode"] != want:
            f.append("seasonTh: {}月が {} になった (気温欠測なら月だけで決まるはず)".format(
                m, th["mode"]))
    w, s = mw.season_thresholds(1), mw.season_thresholds(7)
    if not (w["wind"][0] < s["wind"][0] and w["wind"][1] < s["wind"][1]
            and w["precip"][1] < s["precip"][1]):
        f.append("seasonTh: 冬の閾値が夏より厳しくない")
    for _ in range(n):
        m = rnd.randint(1, 12)
        tmax = round(rnd.uniform(-20, 30), 1)
        tmin = round(rnd.uniform(-30, 20), 1)
        th = mw.season_thresholds(m, tmax, tmin)
        # 冬に倒れたら、さらに寒くしても冬のまま(冬→夏に戻す条件は設けていない)
        if th["mode"] == "冬山・残雪期":
            colder = mw.season_thresholds(m, tmax - rnd.uniform(0, 10), tmin - rnd.uniform(0, 10))
            if colder["mode"] != "冬山・残雪期":
                f.append("seasonTh: 冬モードが寒くして夏に戻った m={} tmax={} tmin={}".format(
                    m, tmax, tmin))
    return f


INVARIANTS = {
    "blockIndex": inv_block_index, "feelsLike": inv_feels_like, "viewScore": inv_view_score,
    "sumOrNull": inv_sum_or_null, "interpWind": inv_interp_wind, "lightningRisk": inv_lightning,
    "eveThunder": inv_eve_thunder, "modelAgree": inv_model_agree, "seasonTh": inv_season_th,
}


# ---------------------------------------------------------------- 実行
def main():
    ap = argparse.ArgumentParser(description="判定ロジックの乱数総当たり + 不変条件テスト")
    ap.add_argument("--n", type=int, default=3000, help="1関数あたりのケース数 (既定 3000)")
    ap.add_argument("--seed", type=int, default=20260821, help="乱数の種 (既定は固定)")
    ap.add_argument("--max-report", type=int, default=5, help="1関数あたりの不一致の表示上限")
    a = ap.parse_args()

    ng = False

    # ---- 1. 等価性 ----
    rnd = random.Random(a.seed)
    cases = gen_cases(rnd, a.n)
    total = sum(len(v) for v in cases.values())
    py = run_python(cases)
    js = run_node(cases)
    if js is None:
        print("等価性(Python vs JS): ⚠ node が見つからないため未検証です ({} ケース)".format(total))
        print("  Node.js を入れると logic.js との突き合わせも走ります")
    else:
        fails = compare(cases, py, js, a.max_report)
        print("等価性(Python vs JS): {} ケース中 {}".format(
            total, "不一致 {} 件".format(len(fails)) if fails else "全件一致"))
        for x in fails:
            print("  NG " + x)
        ng = ng or bool(fails)

    # ---- 2. 不変条件 ----
    inv_n = max(200, a.n // 10)
    inv_fails = []
    for name, fn in INVARIANTS.items():
        inv_fails += fn(random.Random(a.seed + len(name)), inv_n)
    print("不変条件: {} 関数 × {} 回 ... {}".format(
        len(INVARIANTS), inv_n,
        "違反 {} 件".format(len(inv_fails)) if inv_fails else "違反なし"))
    # 同じ性質の違反が何百件も並ぶと本数が読めなくなるので、種類ごとに1件だけ出す
    seen = set()
    for x in inv_fails:
        head = x.split("(")[0][:60]
        if head in seen:
            continue
        seen.add(head)
        print("  NG " + x)
    ng = ng or bool(inv_fails)

    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
