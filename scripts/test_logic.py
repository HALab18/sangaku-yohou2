#!/usr/bin/env python3
"""判定ロジック(CLI側)の等価性テスト。

references/logic_cases.json の入出力表どおりに scripts/mountain_weather.py の関数が
動くかを確かめる。同じ表を scripts/test_logic.js が logic.js に対して回すので、
両方が通れば「CLI と Web の判定は同じ入力で同じ出力を返す」ことになる
(CLAUDE.md 規約3 を目視ではなく機械で守るための仕掛け)。

    python scripts/test_logic.py

依存は標準ライブラリのみ(CLI本体の依存ゼロを崩さない)。
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mountain_weather as mw  # noqa: E402  (sys.path を通した後に読む)

CASES = ROOT / "references" / "logic_cases.json"
TOL = 1e-9

# ケース表の名前 → CLI 側の関数
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


def norm(v):
    """比較用に正規化する。tuple と list、dict の値の tuple を同じ形にそろえる
    (season_thresholds は Python が tuple・JS が配列を返すため)。"""
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    return v


def same(a, b):
    """期待値と実測の一致判定。浮動小数だけ絶対誤差 TOL を許す(それ以外は厳密一致)。"""
    a, b = norm(a), norm(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=0, abs_tol=TOL)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return a == b


def main():
    data = json.loads(CASES.read_text(encoding="utf-8"))
    fails, total = [], 0
    for fname, fn in FUNCS.items():
        cases = data.get(fname)
        if not cases:
            fails.append(f"{fname}: ケースが1件もありません")
            continue
        for c in cases:
            total += 1
            got = fn(*c["in"])
            if not same(c["out"], got):
                fails.append(f"{fname} / {c['name']}\n"
                             f"    in       = {c['in']}\n"
                             f"    expected = {c['out']}\n"
                             f"    got      = {norm(got)}")
    print(f"判定ロジック(Python): {total - len(fails)}/{total} 件一致")
    for f in fails:
        print("  NG " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
