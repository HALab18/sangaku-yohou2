#!/usr/bin/env python3
"""配色(theme.css)を**明・暗の両方**で機械的に検査する。

ver 2.47β で暗い配色に対応し、2.48β で手動の切り替え(自動/ライト/ダーク)を足した。
ここで守りたいのは、
「暗い配色のときだけ読めない」という壊れ方を作らないこと ── これは開発者が
明るい配色で作業しているかぎり**画面を見ても気づけない**(手元では常に正常に見える)。

見るのは3つ:

  [1] トークンの対応     明るい配色にあるトークンが、暗い配色にも全部あるか。
                         片方だけだと、書かなかった側で明るい配色の値が残る
                         (＝暗い地に暗い文字)。ページは普通に描画されるので落ちない。
  [2] コントラスト比     下の PAIRS(どの文字色がどの面の上に載るか)を両方の配色で計算し、
                         WCAG AA を満たすか。本文は 4.5:1、大きい文字と部品は 3:1。
  [5] head の作り        <style> と </style> と theme.css の読み込みが各1つずつか。
                         生成物の <style> ブロックを文字列で切り出して差し替えたとき、
                         コメントの中の「<style>」に先に当たって範囲がずれ、head に
                         <!-- の無い <style> と <link> の写しが残った(実際にやった)。
                         ブラウザは黙って解釈するので、画面はほぼ正常に見える。
  [4] 面と文字の取り違え  --slate / --night は「面」のトークンで、暗い配色でも暗いまま。
                         これを color: に使うと暗い配色で地に沈む(明るい配色では読める)。
                         実際に h3 が 2.06:1 になっていたのをこれで見つけた。
  [3] 色のベタ書き       ページ側の <style> に残っている色リテラルを数える。
                         増えたら「トークンを通さずに色を足した」合図で、その色は
                         暗い配色で差し替わらない。ALLOW に用途を書いた分だけ許す。

    python scripts/check_contrast.py

終了コード: 0=問題なし / 1=違反あり

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


# ---------------------------------------------------------------- 色の計算
def parse_hex(s):
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError("色として読めません: #" + s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    """WCAG 2.x の相対輝度。"""
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    a, b = luminance(fg), luminance(bg)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


# ---------------------------------------------------------------- theme.css
def load_themes():
    """theme.css から明・暗の2つのトークン表を取り出す。

    暗い側は :root[data-theme="dark"] の中(ver 2.48β で手動の切り替えを足した際に、
    @media(prefers-color-scheme:dark) から移した。「端末に従う」は theme.js が起動時に
    light/dark のどちらかに解決して属性を付ける形)。単純な文字列切り出しで足りるが、
    目印がちょうど1つでなければ落とす(黙って空の表を検査して「問題なし」と言わないため)。
    """
    css = (ROOT / "theme.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)      # コメントを落とす
    mark = ':root[data-theme="dark"]'
    if css.count(mark) != 1:
        raise SystemExit("theme.css の暗い配色の目印が {} 箇所あります".format(css.count(mark)))
    light_src, dark_src = css.split(mark)
    # 目印の後ろには切り替えスイッチの見た目(.pw-theme …)が続く。トークンの表だけ見たいので
    # 最初の閉じ括弧までで切る(ここを切らないと var(--…) の参照をトークン定義と読み違える)。
    dark_src = dark_src.split("}", 1)[0]

    def toks(src):
        out = {}
        for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)", src):
            out[m.group(1)] = m.group(2).strip()
        return out
    return toks(light_src), toks(dark_src)


def resolve(tokens, name):
    """トークンを色(RGB)にする。色でないもの(url など)は None。"""
    v = tokens.get(name)
    if v is None:
        return None
    if not v.startswith("#"):
        return None
    return parse_hex(v)


# --------------------------------------------- どの文字がどの面の上に載るか
# (前景トークン, 背景トークン, 最低比, 用途)
# 最低比 3.0 は WCAG AA の「大きい文字(18pt/14pt太字以上)」と「部品の境界」の基準。
# 実データを載せている文字は、小さくても 4.5 を要求する(読めないと判断を誤る)。
AA, LARGE = 4.5, 3.0
# DECOR = 「暗い配色が明るい配色より悪くなっていないこと」だけを見る組。
# 入力欄の枠・説明ブロックの左罫・区切り行の上罫は、**明るい配色の時点で 3:1 に届いていない**
# (実測: 入力欄の枠 1.52:1 / 同意欄の枠 1.74:1 / 左罫 2.29:1 / 上罫 1.69:1)。
# これは暗い配色とは別の、既存の配色そのものの話なので、ここで勝手に色を濃くして
# 見た目を変えることはしない。ただし**暗い配色でさらに薄くなる**のは今回の作業の落ち度なので、
# 「明るい配色以上であること」を条件にして、後退だけを止める。
DECOR = "decor"
PAIRS = [
    # ---- 本文まわり
    ("--text",    "--bg",        AA,    "本文 / ページの地"),
    ("--text",    "--surface",   AA,    "本文 / カード"),
    ("--text",    "--surface-2", AA,    "本文 / 表の縞"),
    ("--text-2",  "--surface",   AA,    "同意欄の文字 / カード"),
    ("--text-3",  "--bg",        AA,    "箇条書きの補足 / ページの地"),
    ("--muted",   "--bg",        AA,    "補足文字 / ページの地"),
    ("--muted",   "--surface",   AA,    "補足文字 / カード"),
    ("--muted",   "--surface-2", AA,    "補足文字 / 表の縞 (視程・CAPE の実数値)"),
    ("--muted",   "--chip-bg",   AA,    "全球印の文字 / 印の地"),
    ("--head",    "--bg",        AA,    "見出し / ページの地"),
    ("--head-2",  "--surface-3", AA,    "説明ブロックの文字 / その地"),
    ("--link",    "--bg",        AA,    "リンク / ページの地"),
    ("--link",    "--surface",   AA,    "リンク / カード"),
    ("--link",    "--surface-3", AA,    "リンク / 説明ブロック"),
    # ---- 濃紺の面(ヒーロー・ヘッダ)。ここは両方の配色で濃紺のまま
    ("--on-night",   "--night",  AA,    "ヒーローの見出し / 濃紺"),
    ("--on-night-2", "--night",  AA,    "タグライン / 濃紺"),
    ("--on-night-3", "--night",  LARGE, "三次リンク / 濃紺 (小さな装飾リンク)"),
    ("--on-night",   "--slate",  AA,    "表のヘッダ文字 / ヘッダ面"),
    ("--on-night",   "--btn",    AA,    "ボタンの文字 / ボタン"),
    ("--on-night",   "--btn-d",  AA,    "ボタンの文字 / ボタン(ホバー)"),
    ("--sel-fg",     "--sel",    AA,    "選択中のセグメント"),
    # ---- 指数 A/B/C とそれに連なる注意
    ("--ok-fg",   "--ok-bg",     AA,    "指数A"),
    ("--warn-fg", "--warn-bg",   AA,    "指数B"),
    ("--bad-fg",  "--bad-bg",    AA,    "指数C・⚠バッジ"),
    ("--bad-fg",  "--surface",   AA,    "降格理由・エラー文字 / カード"),
    ("--bad-fg",  "--surface-2", AA,    "降格理由 / 表の縞"),
    ("--ok-fg",   "--surface-2", AA,    "眺望「絶」 / 表の縞"),
    ("--v-ok",    "--surface-2", AA,    "眺望「良」 / 表の縞"),
    ("--warn-fg", "--surface-2", AA,    "眺望「並」 / 表の縞"),
    ("--sat",     "--surface-2", AA,    "土曜 / 表の縞"),
    ("--sun",     "--surface-2", AA,    "日曜 / 表の縞"),
    ("--lt-0",    "--surface-2", AA,    "発雷リスク0 / 表の縞"),
    ("--lt-1",    "--surface-2", AA,    "発雷リスク1 / 表の縞"),
    ("--lt-2",    "--surface-2", AA,    "発雷リスク2 / 表の縞"),
    ("--lt-3",    "--surface-2", AA,    "発雷リスク3 / 表の縞"),
    ("--info-fg", "--info-bg",   AA,    "冬モード印"),
    ("--sep-fg",  "--sep-bg",    AA,    "週間表の区切り行"),
    ("--off-fg",  "--off-bg",    AA,    "保存済み予報の帯"),
    ("--stale-fg", "--bad-bg",   AA,    "1日以上経った保存済み予報"),
    # ---- 部品の境界(3:1)。ここが見えないと入力欄や罫線の在り処が分からない
    ("--field",   "--surface",   DECOR, "入力欄の枠 / カード"),
    ("--field",   "--bg",        DECOR, "入力欄の枠 / ページの地"),
    ("--line-2",  "--surface",   DECOR, "同意欄・認証欄の枠"),
    ("--rule",    "--bg",        LARGE, "説明ブロックの左罫 / ページの地"),
    ("--rule",    "--surface-3", LARGE, "説明ブロックの左罫 / その地"),
    ("--sky",     "--night",     LARGE, "濃紺の上の補助の青"),
    ("--off-line", "--off-bg",   LARGE, "保存済み予報の帯の左罫"),
    ("--sep-line", "--sep-bg",   DECOR, "区切り行の上罫"),
]


# ------------------------------------------------------- 色のベタ書きの棚卸し
# ページ側の <style> に残してよい色リテラル。数と理由をここに書く。
# ★ ここを増やすときは「なぜトークンで書けないのか」を必ず書くこと。
#   書けるのに書かなかった色は、暗い配色で差し替わらず取り残される。
ALLOW = {
    # ヒーローは明暗どちらでも濃紺のまま。残っているのは
    #   ・その上に敷くグラデーション rgba(13,20,38,…) ×3 と文字影 rgba(0,0,0,…) ×4
    #   ・ガラス調のボタン面 rgba(255,255,255,…) ×10
    #     (濃紺の地に対する相対値なので、トークンに名前を付けるほうが分かりにくい)
    #   ・横スクロールの手がかりの mask-image の #000 ×2 (色ではなく不透明度の指定)
    "index.html": 19,
    # 山さがしに残る2つは index.html と同じ mask-image の #000。
    # 他のページはベタ書きゼロ(ヘッダの濃紺も --night / --on-night で書いてある)。
    "docs/find.html": 2,
    "docs/find-score.html": 0,
    "docs/history.html": 0,
    # 図解の SVG は色を焼き込んだ図版なので、暗い配色でも明るい面のまま置く。
    # その面の色 #f4f6f9 の1つだけが残る(theme.css の --bg と同じ値だが、これは
    # 「地の色」ではなく「図版の紙の色」で、暗い配色でも変わらないので別物)。
    "docs/how-it-works.html": 1,
    "docs/how-it-works-web.html": 1,
    "docs/mountains.html": 0,
    "docs/point.html": 0,
    "docs/terms.html": 0,
    "docs/weather-links.html": 0,
}


def count_literals(rel):
    """そのページの <style> ブロックに残っている色リテラルの数。"""
    text = (ROOT / rel).read_text(encoding="utf-8")
    total = 0
    for m in re.finditer(r"<style>(.*?)</style>", text, flags=re.S):
        body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
        total += len(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", body))
    return total


# ---------------------------------------------------- 面と文字の取り違え
# color: に使ってはいけないトークン。どれも「暗い配色でも暗いまま」の面なので、
# 文字に使うと暗い配色で地に沈む。文字が要るなら --head / --head-2 / --on-night を使う。
SURFACE_ONLY = ("--slate", "--night", "--night-d", "--bg",
                "--surface", "--surface-2", "--surface-3", "--surface-4", "--surface-soft")


def check_surface_as_text():
    errors = []
    targets = ["index.html", "gate.js", "scripts/gen_find.py", "scripts/gen_mountain_list.py"]
    targets += [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "docs").glob("*.html"))]
    for rel in targets:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for tok in SURFACE_ONLY:
            for m in re.finditer(r"color\s*:\s*var\(" + re.escape(tok) + r"[,)]", text):
                # border-color / background-color は面なので対象外
                pre = text[max(0, m.start() - 12):m.start()]
                if pre.endswith("-") or pre.endswith("background"):
                    continue
                errors.append("[4] {}: color に面のトークン {} を使っています"
                              " (暗い配色で地に沈みます。文字は --head / --head-2 / --on-night)"
                              .format(rel, tok))
    return errors


# ------------------------------------------------------ head の作りの検査
def check_head():
    """<style> / </style> / theme.css の読み込みが、各ページに1つずつか。

    数が合わないのは、たいてい「head に壊れた写しが混ざった」とき。ブラウザは
    閉じていない <style> を黙って解釈して以降を CSS として飲み込むので、
    画面を見ても(ほぼ)正常に見える ── 機械で数えるしかない。
    """
    errors = []
    targets = ["index.html"]
    targets += [str(x.relative_to(ROOT)).replace("\\", "/") for x in sorted((ROOT / "docs").glob("*.html"))]
    for rel in targets:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for needle, label in (("<style>", "<style>"), ("</style>", "</style>"),
                              ("theme.css?v=", "theme.css の読み込み")):
            n = text.count(needle)
            if n != 1:
                errors.append("[5] {}: {} が {} 箇所です (1つであるべき。"
                              "head に壊れた写しが混ざっていないか見ること)".format(rel, label, n))
    return errors


# ------------------------------------------------------------ 読み込みの版
def check_version():
    """theme.css の版と、各ページの `?v=` が一致しているか(規約8と同じ形)。

    theme.js(切り替え)も同じ版で動かす。片方だけ上げると「配色は新しいが切り替えだけ旧版」
    (またはその逆)が端末のキャッシュに残り、画面を見ても分からない。
    """
    css = (ROOT / "theme.css").read_text(encoding="utf-8")
    m = re.search(r'--pw-theme-ver:\s*"([^"]+)"', css)
    if not m:
        return ["theme.css から --pw-theme-ver を読み取れません"]
    ver = m.group(1)
    errors = []
    # 生成物(find.html / mountains.html)ではなく生成元も見る(規約6)
    targets = ["index.html", "scripts/gen_find.py", "scripts/gen_mountain_list.py"]
    targets += [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "docs").glob("*.html"))]
    for rel in targets:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for what, why in (("theme.css", "このページだけ暗い配色に追従しません"),
                          ("theme.js", "このページだけ配色を切り替えられません")):
            found = set(re.findall(re.escape(what) + r'\?v=([^"\']+)', text))
            if not found:
                errors.append("{}: {} を読み込んでいません ({})".format(rel, what, why))
                continue
            for got in found - {ver}:
                errors.append("{}: {}?v={} が --pw-theme-ver={} と違います"
                              " (旧い版がキャッシュに残ります)".format(rel, what, got, ver))
    return errors


def main():
    light, dark = load_themes()
    errors, warnings = [], []

    # [1] トークンの対応
    for name in sorted(light):
        if name in ("--pw-theme-ver",):
            continue
        if name not in dark:
            errors.append("[1] {} が暗い配色に定義されていません"
                          " (明るい配色の値が残り、暗い地に暗い文字になります)".format(name))
    for name in sorted(dark):
        if name not in light:
            errors.append("[1] {} が明るい配色に定義されていません"
                          " (暗い配色だけで使う色は作らないこと)".format(name))

    # [2] コントラスト比
    for fg, bg, need, label in PAIRS:
        got = {}
        for theme_name, toks in (("明", light), ("暗", dark)):
            f, b = resolve(toks, fg), resolve(toks, bg)
            if f is None or b is None:
                errors.append("[2] {}: {} または {} が色として読めません".format(theme_name, fg, bg))
                continue
            got[theme_name] = ratio(f, b)
        if len(got) != 2:
            continue
        if need == DECOR:
            if got["暗"] < got["明"] - 0.05:
                errors.append("[2] {} が暗い配色で薄くなっています ({:.2f}:1 → {:.2f}:1)"
                              " ── 明るい配色より見えにくくしないこと ({} on {})"
                              .format(label, got["明"], got["暗"], fg, bg))
            continue
        for theme_name, r in got.items():
            if r < need:
                errors.append("[2] {}: {} が {:.2f}:1 で基準 {}:1 に未達 ({} on {})"
                              .format(theme_name, label, r, need, fg, bg))
            elif r < need + 0.3:
                warnings.append("[2] {}: {} は {:.2f}:1 で基準ぎりぎり ({} on {})"
                                .format(theme_name, label, r, fg, bg))

    # [3] 色のベタ書き
    for rel, allowed in sorted(ALLOW.items()):
        if not (ROOT / rel).exists():
            errors.append("[3] {} がありません".format(rel))
            continue
        got = count_literals(rel)
        if got > allowed:
            errors.append("[3] {}: <style> の色リテラルが {} 個 (許容 {} 個)。"
                          "増えた色は暗い配色で差し替わりません ── theme.css に"
                          "トークンを足して var() で書くこと".format(rel, got, allowed))
        elif got < allowed:
            errors.append("[3] {}: <style> の色リテラルが {} 個で許容 {} 個より少ない。"
                          "減らせたなら ALLOW の数字も下げること"
                          "(緩いままだと次に増えても気づけません)".format(rel, got, allowed))

    # [4] 面と文字の取り違え
    errors += check_surface_as_text()

    # [5] head の作り
    errors += check_head()

    # 読み込みの版
    errors += check_version()

    for w in warnings:
        print("警告 " + w)
    if errors:
        for e in errors:
            print("NG  " + e)
        print("\n配色: {} 件の違反".format(len(errors)))
        return 1
    print("配色: OK (トークン {} 個 / コントラスト {} 組を明暗の両方で検査)"
          .format(len(light) - 1, len(PAIRS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
