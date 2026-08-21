# -*- coding: utf-8 -*-
"""構文と、公開物が壊れていないかの静的検査。

これまで `node --check` と `py_compile` を **都度手打ち** していた。手順が人の記憶に
だけあると、急いでいるときほど飛ばされる。1本にまとめて `check_mountains.py` から
自動で回す。

チェック内容:
  1. Python (scripts/*.py) の構文
  2. JavaScript (*.js, scripts/*.js) の構文
  3. HTML に**直接書かれた** <script> の構文
     - index.html は本体の 2,000行超がここに入っている。外部ファイルと違い、
       構文エラーを入れてもファイル単位のチェックでは見つからない
  4. logic.js / gate.js が **ES5 の範囲** に留まっていること
     - どちらも先頭に「var / function のみ。アロー関数・?. ・?? は使わない」と
       明記してある。ビルド工程を持たない方針なので、書いたものがそのまま古い端末で
       動く必要がある(山で使う端末は新しいとは限らない)
  5. 公開に要るファイルが揃っていること
     - **`.nojekyll`**: これが無いと GitHub Pages が Jekyll 変換を試みてビルドに失敗する。
       2026-07-25 に実際に公開が止まり、API 上は status=building のまま止まって見えて
       原因が非常に見えにくかった
     - manifest.json / references/logic_cases.json が JSON として読めること
     - manifest.json と index.html が指しているアイコンが実在すること

使い方:
  python scripts/check_syntax.py

終了コード: 0=問題なし / 1=要修正
依存は標準ライブラリのみ (node があれば JS も見る。無ければその旨を出して飛ばす)。
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# ES5 に留めると明記してあるファイル。index.html / gen_find.py 側は対象外
# (index.html の本体スクリプトはアロー関数もテンプレートリテラルも使っている)。
ES5_FILES = ["logic.js", "gate.js"]

# (説明, 正規表現)。コメントと文字列を落としてから当てる。
ES5_BANNED = [
    ("アロー関数 (=>)", r"=>"),
    ("オプショナルチェーン (?.)", r"\?\."),
    ("Null 合体 (??)", r"\?\?"),
    ("テンプレートリテラル (`)", r"`"),
    ("let 宣言", r"\blet\s"),
    ("const 宣言", r"\bconst\s"),
    ("class 構文", r"\bclass\s"),
]

HTML_FILES = ["index.html", "404.html"] + sorted(
    "docs/" + p.name for p in (ROOT / "docs").glob("*.html"))

JSON_FILES = ["manifest.json", "references/logic_cases.json"]


def strip_comments_and_strings(src):
    """コメントと文字列リテラルを空白に潰す。

    ES5 かどうかを見るための粗い前処理。`?.` や `=>` が **説明文の中に**書かれている
    のを構文の混入と誤認しないためにやる (logic.js の冒頭がまさにそう書いてある)。
    テンプレートリテラルの検出だけは潰す前に済ませる必要があるので、
    バッククォートは残す。
    """
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def inline_scripts(html):
    """HTML に直接書かれた <script> の中身を [(開始行, 中身), ...] で返す。

    src 付き(外部ファイル)は対象外。それらは JS ファイルとして別に見ている。
    """
    out = []
    for m in re.finditer(r"<script([^>]*)>(.*?)</script\s*>", html, re.S | re.I):
        attrs, body = m.group(1), m.group(2)
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        t = re.search(r'\btype\s*=\s*["\']?([^"\'\s>]+)', attrs, re.I)
        if t and t.group(1).lower() not in ("text/javascript", "module", "application/javascript"):
            continue          # JSON-LD など。JS として構文チェックしない
        if not body.strip():
            continue
        out.append((html[:m.start()].count("\n") + 1, body))
    return out


def check_python():
    errors = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        try:
            compile(src, str(p), "exec")
        except SyntaxError as e:
            errors.append("scripts/{}:{} 構文エラー: {}".format(p.name, e.lineno, e.msg))
    return errors


def node_check(src, label, errors):
    """一時ファイルに書き出して node --check にかける。"""
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "chk.js"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        detail = next((x for x in msg if "SyntaxError" in x), msg[-1] if msg else "")
        errors.append("{} 構文エラー: {}".format(label, detail.strip()))


def check_js(have_node):
    errors, notes = [], []
    files = sorted(ROOT.glob("*.js")) + sorted((ROOT / "scripts").glob("*.js"))
    if not have_node:
        notes.append("node が無いため JavaScript の構文は未検証です"
                     " ({}ファイル + HTML 内のスクリプト)".format(len(files)))
        return errors, notes
    for p in files:
        node_check(p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)).replace("\\", "/"), errors)
    return errors, notes


def check_html_scripts(have_node):
    """HTML に直接書かれたスクリプトの構文。ここが index.html の本体。"""
    errors, notes = [], []
    total = 0
    for rel in HTML_FILES:
        p = ROOT / rel
        if not p.exists():
            errors.append("{} が見つかりません".format(rel))
            continue
        blocks = inline_scripts(p.read_text(encoding="utf-8"))
        total += len(blocks)
        if not have_node:
            continue
        for line, body in blocks:
            node_check(body, "{} の {}行目からの <script>".format(rel, line), errors)
    if not have_node:
        notes.append("node が無いため HTML 内のスクリプト {}件 は未検証です".format(total))
    elif total == 0:
        errors.append("HTML 内のスクリプトが1件も見つかりません(抽出が壊れている可能性)")
    return errors, notes


def check_es5():
    """logic.js / gate.js が ES5 の範囲に留まっているか。

    ビルド工程を持たない方針なので、書いたものがそのまま古い端末で動く必要がある。
    どちらのファイルも冒頭でその約束を明記している。
    """
    errors = []
    for rel in ES5_FILES:
        p = ROOT / rel
        if not p.exists():
            errors.append("{} が見つかりません".format(rel))
            continue
        code = strip_comments_and_strings(p.read_text(encoding="utf-8"))
        for label, pat in ES5_BANNED:
            m = re.search(pat, code)
            if m:
                line = code[:m.start()].count("\n") + 1
                errors.append("{}:{} に {} が入っています"
                              "(ES5 の範囲に留める約束。ファイル冒頭のコメント参照)"
                              .format(rel, line, label))
    return errors


def check_publish():
    """公開に要るものが揃っているか。"""
    errors = []
    if not (ROOT / ".nojekyll").exists():
        errors.append(".nojekyll がありません。無いと GitHub Pages が Jekyll 変換を試みて"
                      "ビルドに失敗し、公開が止まります(2026-07-25 に実際に発生)")

    for rel in JSON_FILES:
        p = ROOT / rel
        if not p.exists():
            errors.append("{} が見つかりません".format(rel))
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            errors.append("{} が JSON として読めません: {}".format(rel, e))
            continue
        if rel == "manifest.json":
            for ic in data.get("icons", []):
                src = (ic.get("src") or "").split("?")[0]
                if src and not (ROOT / src).exists():
                    errors.append("manifest.json が指すアイコンがありません: {}".format(src))

    # index.html が <link rel="icon"> 等で指しているローカルの画像
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r'<link[^>]+href="((?!https?:|data:|#)[^"]+)"', html, re.I):
        ref = m.group(1).split("?")[0]
        if not (ROOT / ref).exists():
            errors.append("index.html が指すファイルがありません: {}".format(ref))
    return errors


def main():
    have_node = shutil.which("node") is not None
    print("静的検査 (構文・ES5・公開物)")
    ng = False

    for label, (errs, notes) in [
        ("Python の構文", (check_python(), [])),
        ("JavaScript の構文", check_js(have_node)),
        ("HTML 内のスクリプトの構文", check_html_scripts(have_node)),
        ("logic.js / gate.js が ES5 の範囲か", (check_es5(), [])),
        ("公開物 (.nojekyll・JSON・アイコン)", (check_publish(), [])),
    ]:
        print("  {}: {}".format(label, "OK" if not errs else "{}件".format(len(errs))))
        for e in errs:
            print("    ✕ {}".format(e))
        for n in notes:
            print("    ⚠ {}".format(n))
        ng = ng or bool(errs)

    print("結果: {}".format("要修正あり" if ng else "問題なし"))
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
