#!/usr/bin/env python3
"""描画の突き合わせ。**同じ1本の予報データ**を CLI と Web の両方に通して比べる。

これまでのテストは関数単位だった(test_display.py)。表を組み立てる経路
── 取得 → 正規化 → 行の組み立て → 表 ── はまるごと未検査で、
**CLI と Web が同じデータから同じ表を出すか**は誰も確かめていなかった。

2つのことを見る:

  (a) ゴールデン比較   … Web が組み立てた表の HTML が references/golden/ と一致するか。
                         描画に手を入れたときに「どこがどう変わったか」を差分で出す。
  (b) CLI ⇄ Web の突合 … 週間表の各セル(日付・指数・天気・気温・稜線風・降水)が
                         CLI の markdown と一字一句そろっているか。

材料は references/fixture_forecast.json に固定した**本物の応答**。通信はしない。
時計も基準時刻に固定するので、日が変わっても結果は動かない。

    python scripts/test_render.py            … 検査する
    python scripts/test_render.py --record   … 実通信して fixture を取り直す(要ネット)
    python scripts/test_render.py --bless    … いまの出力を golden として保存し直す

★ --bless は「変わったのが意図どおりだと目で確かめてから」使うこと。
  落ちるたびに bless すると、この検査は「いまの出力といまの出力を比べる」だけになる。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
FIXTURE = ROOT / "references" / "fixture_forecast.json"
GOLDEN = ROOT / "references" / "golden" / "render_web.html"


def canon(v):
    """値の表記ゆれをならす。Python は 2763.0、JS は 2763 と書くので、そのままだと
    同じリクエストが別の署名になる。カンマ区切りの並び(周辺4方位の緯度経度)にも効かせる。"""
    out = []
    for tok in str(v).split(","):
        try:
            n = float(tok)
        except ValueError:
            out.append(tok)
            continue
        out.append(str(int(n)) if n == int(n) else repr(n))
    return ",".join(out)


def signature(url, params):
    """リクエストの署名。**scripts/test_render.js の signature() と同じ規則**にすること。
    片方だけ変えると「fixture に無い」と言って落ちる(黙って別の応答を返すよりはよい)。"""
    path = urllib.parse.urlsplit(url).path
    items = sorted((k, canon(v)) for k, v in params.items())
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


# ---- Web 側 -----------------------------------------------------------------
def run_web():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "web.json"
        r = subprocess.run([node_bin(), str(ROOT / "scripts" / "test_render.js"), str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise SystemExit("Web 側の描画に失敗しました:\n" + (r.stdout or "") + (r.stderr or ""))
        return json.loads(out.read_text(encoding="utf-8"))["html"]


def node_bin():
    return "node"


def record_web():
    r = subprocess.run([node_bin(), str(ROOT / "scripts" / "test_render.js"), "--record",
                        os.devnull], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        raise SystemExit("fixture の取得に失敗しました:\n" + (r.stdout or "") + (r.stderr or ""))
    sys.stderr.write(r.stderr)


# ---- CLI 側 -----------------------------------------------------------------
def run_cli(fixture, record=False):
    """CLI を fixture の上で走らせて、標準出力(markdown)を返す。

    差し替えるのは**通信層 http_json() と「今日」だけ**。表を作るコードには一切触らないので、
    ここで見ているのは本番とまったく同じ経路になる。"""
    import datetime as _dt
    import types
    import mountain_weather as mw

    now = _dt.datetime.fromtimestamp(fixture["now"] / 1000)
    real_http = mw.http_json
    real_dt = mw.dt
    missing = []

    def fake_http(url, params, retries=3, fatal=True):
        sig = signature(url, params)
        if sig in fixture["responses"]:
            return fixture["responses"][sig]
        if record:
            got = real_http(url, params, retries=retries, fatal=fatal)
            fixture["responses"][sig] = got
            return got
        missing.append(sig)
        # 黙って {} を返すと「取れたが中身が空」に化けるので、必ず表に出す
        raise mw.ApiError("fixture にこのリクエストがありません: " + sig)

    # 「今日」を固定する。本物の datetime モジュールには触らず、mountain_weather が
    # 参照している名前(mw.dt)だけを差し替える(標準ライブラリを書き換えると、
    # このテストの外まで壊れる)。
    class FixedDate(real_dt.date):
        @classmethod
        def today(cls):
            return now.date()

    class FixedDateTime(real_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else real_dt.datetime.now(tz)

    mw.http_json = fake_http
    mw.dt = types.SimpleNamespace(date=FixedDate, datetime=FixedDateTime,
                                  timedelta=real_dt.timedelta, timezone=real_dt.timezone)
    buf = io.StringIO()
    real_stdout, real_argv = sys.stdout, sys.argv
    try:
        sys.stdout = buf
        sys.argv = ["mountain_weather.py", "--name", fixture["name"]]
        mw.main()
    finally:
        sys.stdout, sys.argv = real_stdout, real_argv
        mw.http_json, mw.dt = real_http, real_dt
    if missing:
        raise SystemExit("fixture に無いリクエストがありました:\n  "
                         + "\n  ".join(missing)
                         + "\n  → python scripts/test_render.py --record で取り直してください")
    return buf.getvalue()


# ---- 週間表を取り出して突き合わせる ------------------------------------------
WK_CAPTION = "日間の見通し"


def web_week_table(html):
    """Web の見通し表 → (見出しの列, 行の列)。タグは落とし、空白は1つに詰める。"""
    tbl = next((x for x in re.findall(r"<table[^>]*>.*?</table>", html, re.S) if "wk-row" in x), "")
    head = re.findall(r"<th[^>]*scope=\"col\"[^>]*>(.*?)</th>", tbl, re.S)
    rows = []
    for tr in re.findall(r'<tr class="wk-row.*?</tr>', html, re.S):
        rows.append([clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)])
    return [clean(h) for h in head], rows


def cli_week_table(md):
    """CLI の見通し表 → 同じ形。見出し「### …日間の見通し」の直後の markdown 表を拾う。
    ★ 直近の実況の表も同じ形なので、見出しで選ぶこと(最初に見つけた表を取ると実況を掴む)。"""
    lines = md.splitlines()
    i = next((n for n, l in enumerate(lines)
              if l.startswith("###") and WK_CAPTION in l), None)
    if i is None:
        raise SystemExit("CLI の出力に見通し表が見つかりません")
    rows = []
    for l in lines[i + 1:]:
        if not l.startswith("|"):
            if rows:
                break
            continue
        cells = [clean(c) for c in l.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue          # markdown の区切り行
        rows.append(cells)
    return rows[0], rows[1:]


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def norm(s):
    """比較用にならす。空白と丸括弧は落とす ── 同じ内容を CLI は「(視程25km)」、
    Web は「視程 25km」と書くなど、**体裁だけ**が違う箇所があるため。
    値そのもの(数字・語・記号)が違えば、ならしても残る。"""
    return re.sub(r"[\s()（）]", "", s)


# 見出し名で列を対応させる。列が増減しても、両方にある列だけが自動的に比較対象になる
# (添字で対応させると、片方に列が入った瞬間に全部ずれて毎回落ちる)。
HEAD_ALIAS = {"山頂気温": "気温", "降水%(参考)": "降水確率", "🏔 景色(朝)": "景色"}
SKIP_COLS = {""}          # 見出しの無い列は比べない


def head_key(h):
    h = clean(h)
    h = HEAD_ALIAS.get(h, h)
    return re.sub(r"max\(.*?\)|\(.*?\)", "", h).strip()   # 「稜線風max(5-16時)」の括弧を落とす


def compare_tables(web, cli):
    wh, wr = web
    ch, cr = cli
    fails = []
    wi = {head_key(h): i for i, h in enumerate(wh)}
    ci = {head_key(h): i for i, h in enumerate(ch)}
    cols = [k for k in wi if k in ci and k not in SKIP_COLS]
    if not cols:
        return ["見出しが1つも対応しませんでした (表の構成が変わった可能性があります)"], []
    if len(wr) != len(cr):
        fails.append(f"行数が違います: Web {len(wr)} 行 / CLI {len(cr)} 行")
    for w, c in zip(wr, cr):
        d = norm(w[wi["日付"]]) if "日付" in wi and wi["日付"] < len(w) else "?"
        for k in cols:
            if wi[k] >= len(w) or ci[k] >= len(c):
                continue
            a, b = norm(w[wi[k]]), norm(c[ci[k]])
            if a != b:
                fails.append(f"{d} の{k}: Web={a!r} / CLI={b!r}")
    return fails, cols


# ---- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="描画のゴールデン比較と CLI ⇄ Web の突合")
    ap.add_argument("--record", action="store_true", help="実通信して fixture を取り直す")
    ap.add_argument("--bless", action="store_true", help="いまの出力を golden として保存し直す")
    a = ap.parse_args()

    if a.record:
        record_web()
    if not FIXTURE.exists():
        print("描画の突き合わせ: ⚠ fixture が無いため未検証です "
              "(python scripts/test_render.py --record で作成)")
        return 0
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    html = run_web()
    md = run_cli(fixture, record=a.record)
    if a.record:
        FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        print(f"fixture を書きました: {len(fixture['responses'])} 応答")

    fails = []

    # (a) ゴールデン比較
    if a.bless:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(html, encoding="utf-8")
        print(f"golden を保存しました: {GOLDEN.relative_to(ROOT)} ({len(html)} 文字)")
    elif not GOLDEN.exists():
        print("描画のゴールデン比較: ⚠ golden が無いため未検証です "
              "(python scripts/test_render.py --bless で作成)")
    else:
        want = GOLDEN.read_text(encoding="utf-8")
        if want == html:
            print(f"描画のゴールデン比較: 一致 ({len(html)} 文字)")
        else:
            fails.append("描画が golden と違います。変わったのが意図どおりなら --bless で更新:")
            fails += diff_rows(web_week_table(want)[1], web_week_table(html)[1])

    # (b) CLI ⇄ Web の突合
    web, cli = web_week_table(html), cli_week_table(md)
    tf, cols = compare_tables(web, cli)
    print("CLI ⇄ Web の突合: {} 行 × {}列 ({}) 中 {}".format(
        len(web[1]), len(cols), "/".join(cols),
        "不一致 {} 件".format(len(tf)) if tf else "全件一致"))
    fails += tf

    for f in fails:
        print("  NG " + f)
    return 1 if fails else 0


def diff_rows(want, got):
    """差分は**表の行ごと**に出す。HTML を1文字ずつ比べて「違います」とだけ言うと、
    次に見た人が直せない。"""
    out = []
    for i in range(max(len(want), len(got))):
        w = " | ".join(want[i]) if i < len(want) else "(行なし)"
        g = " | ".join(got[i]) if i < len(got) else "(行なし)"
        if w != g:
            out.append(f"  {i + 1}行目\n      golden = {w}\n      いま   = {g}")
    return out or ["  週間表は同じ。差は表の外(注記・キャプション等)にあります"]


if __name__ == "__main__":
    sys.exit(main())
