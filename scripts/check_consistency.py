#!/usr/bin/env python3
"""定数の同期と、ドキュメントと実装の食い違いを機械で見る。

このリポジトリには「2箇所以上に同じ値を書く」場所が多く、コメントで
「片方だけ変えないこと」と書いて守っている。だが実際に守れなかった事故が起きている:

  - `gate.js` の AUTH_VER を上げたのに読み込み側の `?v=` が4箇所とも旧版のままで、
    HTTPキャッシュに旧 gate.js を持つ端末では新コードが弾かれた
  - README の体感温度が「風冷指数(JAG/TI式)」のまま残り、実装(Apparent Temperature)と
    食い違っていた。体感列の読み違えに直結する
  - 行動時間帯を 5〜16時に統一した後も README は 5〜17時のままだった

いずれも「動くので気づけない」型。ここで機械的に見ておく。

    python scripts/check_consistency.py

終了コード: 0=問題なし / 1=食い違いあり

依存は標準ライブラリのみ。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def grab(rel, pattern, label):
    """1箇所だけ出てくるはずの値を取り出す。取れなければ食い違い扱いにする
    (コードが動いて検査が空振りしているのを「問題なし」と数えないため)。"""
    m = re.search(pattern, read(rel))
    if not m:
        return None, "{} から {} を読み取れません (コードが動いた可能性があります)".format(rel, label)
    return m.group(1), None


# ---------------------------------------------------------------- 定数の同期
def check_jma_days():
    """予報期間 JMA_DAYS。ここがズレると find の日付リンクが本体の予報範囲外を指す。"""
    errors = []
    vals = {}
    for rel, pat in (("index.html", r"const JMA_DAYS=(\d+)"),
                     ("docs/point.html", r"const JMA_DAYS=(\d+)"),
                     ("scripts/mountain_weather.py", r"\bJMA_DAYS = (\d+)")):
        v, err = grab(rel, pat, "JMA_DAYS")
        if err:
            errors.append(err)
        else:
            vals[rel] = int(v)
    if len(set(vals.values())) > 1:
        errors.append("JMA_DAYS がファイルごとに違います: "
                      + " / ".join("{}={}".format(k, v) for k, v in vals.items()))
    return errors, vals


def check_find_days(jma):
    """不変条件 FIND_DAYS <= JMA_DAYS。山さがしのリンク先は本体の予報範囲内でなければならない。"""
    errors = []
    v, err = grab("scripts/gen_find.py", r"var FIND_DAYS=(\d+);", "FIND_DAYS")
    if err:
        return [err]
    find_days = int(v)
    if not jma:
        return errors
    limit = min(jma.values())
    if find_days > limit:
        errors.append("FIND_DAYS={} が JMA_DAYS={} を超えています"
                      " (山さがしのリンク先が本体の予報範囲外になります)".format(find_days, limit))
    return errors


def check_auth_ver():
    """gate.js の AUTH_VER と、読み込み側の ?v= が一致しているか。

    ずれても画面は普通に出る。旧 gate.js を HTTP キャッシュに持つ端末だけが
    「新しい認証コードを渡されたのに弾かれる」という状態になり、手元では再現しない。
    """
    errors = []
    ver, err = grab("gate.js", r'PW_AUTH_VER\s*=\s*"([^"]+)"', "PW_AUTH_VER")
    if err:
        return [err]
    for rel in ("index.html", "docs/point.html", "docs/find.html", "scripts/gen_find.py"):
        found = re.findall(r'gate\.js\?v=([^"]+)"', read(rel))
        if not found:
            errors.append("{}: gate.js の読み込みが見つかりません".format(rel))
            continue
        for got in set(found):
            if got != ver:
                errors.append("{}: gate.js?v={} が PW_AUTH_VER={} と違います"
                              " (旧 gate.js がキャッシュに残り、新コードが弾かれます)"
                              .format(rel, got, ver))
    return errors


def check_japan_bbox():
    """日本域の範囲。/v1/jma は域外でも 400 を返さず値を 200 で返すため、
    ここが片方だけずれると海外の座標に「気象庁モデルの予報」を出してしまう。"""
    m = re.search(r"const JP_LAT=\[([\d.]+),([\d.]+)\],JP_LON=\[([\d.]+),([\d.]+)\]",
                  read("index.html"))
    if not m:
        return ["index.html から JP_LAT/JP_LON を読み取れません (コードが動いた可能性があります)"]
    want = [m.group(i) for i in (1, 2, 3, 4)]
    p = re.search(r"if\(!\(lat>=([\d.]+)&&lat<=([\d.]+)\)\|\|!\(lon>=([\d.]+)&&lon<=([\d.]+)\)\)",
                  read("docs/point.html"))
    if not p:
        return ["docs/point.html から日本域の範囲を読み取れません (コードが動いた可能性があります)"]
    got = [p.group(i) for i in (1, 2, 3, 4)]
    if [float(x) for x in got] != [float(x) for x in want]:
        return ["日本域の範囲が index.html と docs/point.html で違います: "
                "index={} / point={}".format(want, got)]
    return []


def check_sw_cache():
    """sw.js の CACHE 版とフッターの版表記。

    上げ忘れると activate の掃除が走らず前版のシェルが残る。ネットワーク優先なので
    オンラインでは表面化せず、完全オフラインで開いたときだけ古い画面が出る。
    """
    cache, err = grab("sw.js", r'const CACHE = "pw-shell-([\d.]+)"', "CACHE")
    if err:
        return [err]
    ver, err2 = grab("index.html", r"PeakWeather Ver\.([\d.]+)", "フッターの版表記")
    if err2:
        return [err2]
    if cache != ver:
        return ["sw.js の CACHE=pw-shell-{} がフッターの Ver.{} と揃っていません"
                " (完全オフラインで開いたときだけ古い画面が出ます)".format(cache, ver)]
    return []


# ------------------------------------------------- ドキュメントと実装の食い違い
def check_thresholds_in_docs():
    """主判定のしきい値が、実装どおりの数字でドキュメントに書かれているか。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import mountain_weather as mw
    summer, winter = mw.season_thresholds(7), mw.season_thresholds(1)
    errors = []
    want = [
        ("夏山の風", "{}/{}".format(*summer["wind"])),
        ("夏山の降水", "{}/{}".format(*summer["precip"])),
        ("冬山の風", "{}/{}".format(*winter["wind"])),
        ("冬山の降水", "{}/{}".format(*winter["precip"])),
    ]
    text = read("README.md")
    for label, s in want:
        if s not in text:
            errors.append("README.md に {} のしきい値 {} が見当たりません"
                          " (実装を変えたら説明も直すこと)".format(label, s))
    return errors


def check_stale_wording():
    """実装から消えたはずの説明が、**現行の説明として**残っていないか。

    どれも「読んだ人が現物を誤解する」もので、動作では気づけない。

    ただし「以前は風冷指数(JAG/TI式)を使っていましたが…」のような経緯の説明は残ってよい
    ── むしろ、なぜ今の式にしたのかを伝える大事な記述で、消すと同じ議論を蒸し返す。
    そこで、過去形の目印(以前・かつて・廃止・やめ・旧)が近くにある出現は見逃す。
    """
    # 出現の前後これだけの範囲に過去形の目印があれば「経緯の説明」とみなす
    WINDOW = 80
    PAST_MARKERS = ("以前", "かつて", "廃止", "やめ", "旧", "2.15β", "置き換え", "していました")
    # (説明, 探す文字列, 対象ファイル, なぜ駄目か)
    STALE = [
        ("体感温度の式", "JAG/TI",
         ["README.md", "docs/how-it-works.html", "docs/how-it-works-web.html"],
         "実装は Apparent Temperature(Steadman)。風冷指数は 2.15β で廃止済みで、"
         "体感列の読み違えに直結する"),
        ("行動時間帯", "5〜17時",
         ["README.md", "references/criteria.md"],
         "実装の ACT_HOURS は 5〜16時 (2.23β で統一)"),
        ("モデル間比較表", "モデル間比較（常時表示）",
         ["references/criteria.md", "README.md"],
         "2.35β で廃止し、週間表の「確度」列に置き換えた"),
        ("発雷の旧呼称", "「粗」印",
         ["docs/find-score.html", "docs/how-it-works-web.html"],
         "2.32β で「全球」印に改名済み"),
    ]
    errors = []
    for label, needle, files, why in STALE:
        for rel in files:
            if not (ROOT / rel).exists():
                continue
            text = read(rel)
            for m in re.finditer(re.escape(needle), text):
                around = text[max(0, m.start() - WINDOW):m.end() + WINDOW]
                if any(k in around for k in PAST_MARKERS):
                    continue          # 経緯の説明。残っていてよい
                errors.append("{}: 古い記述「{}」が現行の説明として残っています ({}: {})"
                              .format(rel, needle, label, why))
                break                 # 同じファイルで何件も並べても読みにくいだけ
    return errors


def check_feels_like_impl():
    """体感温度の実装が本当に Apparent Temperature か。

    上の check_stale_wording は「ドキュメントが古い」ことしか見ない。実装のほうが
    差し戻された場合に、両方そろって古くなったのを見逃さないための裏取り。
    """
    src = read("scripts/mountain_weather.py")
    if "Apparent Temperature" not in src:
        return ["scripts/mountain_weather.py の体感温度が Apparent Temperature でなくなっています"
                " (ドキュメント側の記述も併せて見直してください)"]
    return []


def main():
    checks = []

    jma_errors, jma = check_jma_days()
    checks.append(("予報期間 JMA_DAYS の同期", jma_errors))
    checks.append(("不変条件 FIND_DAYS <= JMA_DAYS", check_find_days(jma)))
    checks.append(("認証コード版 (gate.js の AUTH_VER と ?v=)", check_auth_ver()))
    checks.append(("日本域の範囲", check_japan_bbox()))
    checks.append(("Service Worker のキャッシュ版", check_sw_cache()))
    checks.append(("しきい値の説明", check_thresholds_in_docs()))
    checks.append(("古い記述の残り", check_stale_wording()))
    checks.append(("体感温度の実装", check_feels_like_impl()))

    print("定数同期とドキュメントの整合性チェック")
    ng = False
    for i, (label, errors) in enumerate(checks, 1):
        print("[{}/{}] {}: {}".format(
            i, len(checks), label, "OK" if not errors else "{}件".format(len(errors))))
        for e in errors:
            print("  ✕ " + e)
        ng = ng or bool(errors)

    print("\n結果: {}".format("要修正あり" if ng else "すべて正常"))
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
