#!/usr/bin/env python3
"""天気コード → 日本語表現の**総当たり**テスト。

scripts/test_display.py は CLI と Web が一致するかを乱数で見ているが、
「一致していれば、両方とも同じように間違っていてもよい」という穴がある。
ここは一致とは別に、**表現そのものが満たすべき性質**を全コードで確かめる。

見ているもの:
  1. WMO の全コード(28種)で、日代表の文言が**必ず出る**(空・None にならない)
  2. **安全オーバーライド**(強い雨・強い雪・雷雨など10コード)は、窓内に1時間でもあれば
     必ず日代表に出る。晴れ23時間 + 雷雨1時間の日が「晴れ」になってはいけない
  3. 晴れの日に雷雨・雨の語が出ない / 雷雨の日に「晴れ」だけで終わらない(取り違えの検出)
  4. 軽微な降水(霧雨など)は日代表を乗っ取らないが、**画面からも消えない**
  5. **集約の窓(4〜17時)の外**にある悪天は日代表にしない。ただし窓内が空なら全時刻で決める
  6. 未知のコード(将来 Open-Meteo が増やしたもの)でも日代表コードが失われない。
     全時刻が欠測の日は、空の行を描かずに結果から落ちる
  7. 1〜6 のすべてで CLI(Python)と Web(index.html)の出力が一致する

test_display.js をそのまま実行係に使う(index.html は書き換えない)。
node が無い環境では Python 側の性質検査だけを行い、その旨を出す。

    python scripts/test_weather_codes.py

依存は標準ライブラリのみ。
"""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mountain_weather as mw            # noqa: E402
from test_display import phrase_text, py_summarize, WMO   # noqa: E402

RUNNER_JS = ROOT / "scripts" / "test_display.js"

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# ★ 実装から読み込まない。SAFETY_OVERRIDE を空にする変異を仕掛けたとき、実装から読むと
#    **検査するケースごと消えて素通りする**(実際にミューテーションで露見した)。
#    ここは「どの天気を必ず日代表に出すか」という安全上の決めごとなので、テスト側に持つ。
SAFETY = [65, 66, 67, 75, 82, 85, 86, 95, 96, 99]
#    強い雨 / 着氷性の雨 / 着氷性の雨(強) / 強い雪 / 強いにわか雨 /
#    にわか雪 / にわか雪(強) / 雷雨 / 雷雨(雹) / 雷雨(激しい雹)
WIN_LO, WIN_HI = (4, 17)   # 集約の窓も同じ理由でテスト側に持つ
CLEAR = [0, 1]                      # 快晴・晴れ
LIGHT = [51, 53, 45, 48]            # 日代表を乗っ取ってはいけない軽微なもの
THUNDER = [95, 96, 99]

# 文言の取り違えを見るための語。カテゴリではなく**画面に出る文字**で確かめる
WORD_CLEAR = ("快晴", "晴")
WORD_THUNDER = ("雷",)
WORD_RAIN = ("雨",)
WORD_SNOW = ("雪",)

fails = []
checks = 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        fails.append(msg)


def day(codes_by_hour, date="2026-08-21"):
    """{時: コード} から (times, codes) を作る。指定の無い時刻は欠測にしない
    (欠測にすると別の経路の検査になるので、必ず全24時間を埋める)。"""
    times, codes = [], []
    for h in range(24):
        times.append("{}T{:02d}:00".format(date, h))
        codes.append(codes_by_hour.get(h))
    return times, codes


def all_day(code, date="2026-08-21"):
    return day({h: code for h in range(24)}, date)


def txt(rec):
    """1日ぶんの結果 [date, code, notes, phrase] を、画面に出る文字列にまとめる。"""
    _, _, notes, phrase = rec
    return "".join(phrase or []) + "／" + "／".join(notes or [])


# ---------------------------------------------------------------- 入力を作る
CASES = []          # [(ラベル, times, codes, 検査関数)]


def add(label, times, codes, verify):
    CASES.append((label, times, codes, verify))


# 1. 全コードで文言が出る
for c in WMO:
    def v(rec, c=c):
        _, code, _, phrase = rec
        ok(phrase and any(s.strip() for s in phrase),
           "コード {} だけの日で文言が空になる: {}".format(c, phrase))
        ok(code is not None, "コード {} だけの日で日代表コードが None".format(c))
    t, cs = all_day(c)
    add("全時刻 {}".format(c), t, cs, v)

# 2. 安全オーバーライド: 晴れ23時間 + 悪天1時間 でも悪天が日代表に出る
for c in SAFETY:
    for hour in (WIN_LO, 12, WIN_HI):
        def v(rec, c=c, hour=hour):
            _, code, _, _ = rec
            ok(code == c,
               "窓内 {}時 の悪天コード {} が日代表に昇格していない (日代表={})".format(hour, c, code))
            s = txt(rec)
            ok(not (s.startswith("快晴") or s.startswith("晴れ")) or "のち" in s or "時々" in s or "一時" in s,
               "悪天コード {} の日が「晴れ」で始まっている: {}".format(c, s))
        d = {h: 1 for h in range(24)}
        d[hour] = c
        t, cs = day(d)
        add("晴れ+{}({}時)".format(c, hour), t, cs, v)

# 3. 取り違えの検出
for c in CLEAR:
    def v(rec, c=c):
        s = txt(rec)
        ok(not any(w in s for w in WORD_THUNDER), "快晴/晴れの日に雷の語が出ている: {}".format(s))
        ok(not any(w in s for w in WORD_RAIN), "快晴/晴れの日に雨の語が出ている: {}".format(s))
        ok(not any(w in s for w in WORD_SNOW), "快晴/晴れの日に雪の語が出ている: {}".format(s))
        ok(any(w in s for w in WORD_CLEAR), "快晴/晴れの日に晴の語が無い: {}".format(s))
    t, cs = all_day(c)
    add("取り違え 晴れ {}".format(c), t, cs, v)

for c in THUNDER:
    def v(rec, c=c):
        s = txt(rec)
        ok(any(w in s for w in WORD_THUNDER), "雷雨の日に雷の語が出ていない: {}".format(s))
    t, cs = all_day(c)
    add("取り違え 雷雨 {}".format(c), t, cs, v)

# 4. 軽微な降水は日代表を乗っ取らず注記に降りる
for c in LIGHT:
    def v(rec, c=c):
        _, code, notes, _ = rec
        ok(code in CLEAR,
           "晴れ11時間に対し軽微な {} 1時間が日代表を乗っ取っている (日代表={})".format(c, code))
        # 乗っ取らないことと「消えない」ことは別。フレーズか注記のどちらかに必ず残ること
        s = txt(rec)
        want = "霧雨" if c in (51, 53) else "霧"
        ok(want in s,
           "軽微な {} が画面から消えている (フレーズにも注記にも出ない): {}".format(c, s))
    d = {h: 1 for h in range(24)}
    d[10] = c
    t, cs = day(d)
    add("晴れ+軽微 {}".format(c), t, cs, v)

# 5. 窓の外(4時より前・17時より後)の悪天は日代表にしない
for c in (95, 65):
    for hour in (WIN_LO - 1, WIN_HI + 1, 0, 23):
        def v(rec, c=c, hour=hour):
            _, code, _, _ = rec
            ok(code != c,
               "行動時間帯の外({}時)の悪天コード {} が日代表になっている".format(hour, c))
        d = {h: 1 for h in range(WIN_LO, WIN_HI + 1)}
        d[hour] = c
        t, cs = day(d)
        add("窓外 {}({}時)".format(c, hour), t, cs, v)

# 5b. 窓内が1時間も無い日(予報末端など)は、全時刻で決める(黙って空にしない)
def v_winempty(rec):
    _, code, _, phrase = rec
    ok(code is not None and phrase, "窓内が空の日で文言が出ていない")
t, cs = day({0: 95, 1: 95, 22: 95, 23: 95})
add("窓内が空", t, cs, v_winempty)

# 6. 未知のコード
# Open-Meteo が将来コードを増やしても落ちないこと。文言(phrase)は付かず、表示側が
# `code123` の形に落とす仕様なので、**日代表コードが失われないこと**をここで縛る
# (コードさえ残っていれば画面には出る)。
def v_unknown(rec, want):
    _, code, _, _ = rec
    ok(code == want, "未知のコード {} が日代表から消えている (画面に何も出せなくなる)".format(want))
for unk in (4, 123):
    t, cs = all_day(unk)
    add("未知のコード {}".format(unk), t, cs, (lambda u: (lambda rec: v_unknown(rec, u)))(unk))


def check_constants():
    """テスト側に持っている決めごとと、実装側の定義が食い違っていないか。

    テストが実装を読んでしまうと、実装を空にする変異でテストごと消えて素通りする。
    かといって黙ってずれるのも困るので、ここで突き合わせだけしておく
    (基準を変えたいときは、テスト側のこの2つも一緒に直すこと)。
    """
    ok(sorted(mw.SAFETY_OVERRIDE) == sorted(SAFETY),
       "安全オーバーライドの中身が実装とテストで食い違っています: "
       "実装={} / テスト={}".format(sorted(mw.SAFETY_OVERRIDE), sorted(SAFETY)))
    ok(tuple(mw.WX_WINDOW) == (WIN_LO, WIN_HI),
       "集約の窓が実装とテストで食い違っています: "
       "実装={} / テスト={}".format(tuple(mw.WX_WINDOW), (WIN_LO, WIN_HI)))


def run_python():
    out = []
    for label, times, codes, _ in CASES:
        got = py_summarize(times, codes)
        out.append(got)
    return out


def run_node(cases):
    with tempfile.TemporaryDirectory() as d:
        ip = pathlib.Path(d) / "in.json"
        op = pathlib.Path(d) / "out.json"
        ip.write_text(json.dumps({"summarizeDailyWeather": cases}, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(["node", str(RUNNER_JS), str(ip), str(op)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip())
        return json.loads(op.read_text(encoding="utf-8"))["summarizeDailyWeather"]


def main():
    check_constants()
    py = run_python()

    # 性質の検査 (Python 側の出力に対して)
    for (label, _, _, verify), got in zip(CASES, py):
        if len(got) != 1:
            fails.append("{}: 1日ぶんのはずが {} 日ぶん返っている".format(label, len(got)))
            continue
        verify(got[0])

    # 全欠測の日は「その日が結果に出ない」ことを確かめる(空の行を描かない)
    global checks
    checks += 1
    if py_summarize(*day({})) != []:
        fails.append("全時刻が欠測の日が結果に残っている(空の行が描かれる)")

    # CLI ⇄ Web の一致
    node_note = None
    try:
        js = run_node([[t, c] for _, t, c, _ in CASES])
    except (FileNotFoundError, OSError):
        js = None
        node_note = "node が無いため Web 側(index.html)は未検証です"
    except RuntimeError as e:
        js = None
        fails.append("実行係(test_display.js)が失敗しました: {}".format(e))

    if js is not None:
        for (label, _, _, _), a, b in zip(CASES, py, js):
            checks += 1
            if json.dumps(a, ensure_ascii=False) != json.dumps(b, ensure_ascii=False):
                fails.append("{}: CLI と Web で文言が違う\n      CLI={}\n      Web={}"
                             .format(label, a, b))

    if fails:
        print("天気コードの総当たり: {} 件の入力 / {} 項目中 {} 件が期待どおりでない\n"
              .format(len(CASES), checks, len(fails)))
        for m in fails:
            print("  - " + m)
        return 1
    print("天気コードの総当たり: {} 件の入力 / {} 項目 ... 違反なし".format(len(CASES), checks))
    if node_note:
        print("  ⚠ " + node_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
