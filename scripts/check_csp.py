# -*- coding: utf-8 -*-
"""外部参照先の棚卸しと、CSP を入れる前の下ごしらえ。

**まず regression guard として使う。** このアプリが通信する相手は「気象データ(Open-Meteo)・
地名(国土地理院)・アクセス解析(Google)」の3系統だけで、増えることは通常ありえない。
知らないホストが混ざったら、それ自体が異常(貼り付けたコードに広告タグが付いてきた等)。
許可表に無いホストが出たら落とす。

**そのうえで CSP の下見をする。** Content-Security-Policy は meta 版だと Report-Only が
使えず、書き間違えると**無言で機能が死ぬ**。実際に「5経路(山名検索・現在地・座標指定・
山さがし・GA送信)を全部通す自動シナリオを先に作ってから入れる」と決めて見送られている。
ここでは、いま入れるとしたらどう書くことになるかを実装から機械的に出しておく。
どこが 'unsafe-inline' を必要としているかも数える(インラインの <script> と on〜 属性)。

    python scripts/check_csp.py
    python scripts/check_csp.py --policy   # 生成した CSP を出す

終了コード: 0=問題なし / 1=知らない外部参照あり
依存は標準ライブラリのみ。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# 見に行くファイル。docs/*.html は自動生成物も含めて全部見る(生成元だけ見ると、
# 生成し忘れた状態のページに何が入っているか分からない)。
def targets():
    fs = [ROOT / "index.html", ROOT / "404.html", ROOT / "manifest.json"]
    fs += sorted((ROOT / "docs").glob("*.html"))
    fs += sorted(ROOT.glob("*.js")) + sorted((ROOT / "scripts").glob("gen_*.py"))
    return [f for f in fs if f.exists()]


# 許可するホストと、その理由。ここに無いものが出たら落とす。
ALLOWED = {
    "api.open-meteo.com":            "気象データ本体(気象庁モデル・補完・モデル比較・発表時刻)",
    "geocoding-api.open-meteo.com":  "山名から座標を引く(内蔵DBに無い山)",
    "open-meteo.com":                "出典表示のリンク先",
    "mreversegeocoder.gsi.go.jp":    "現在地の市町村名(国土地理院)",
    "maps.gsi.go.jp":                "市町村コード表 muni.js(国土地理院)",
    "www.googletagmanager.com":      "アクセス解析 gtag.js",
    "www.jma.go.jp":                 "気象庁へのリンク(気象情報・警報)",
    "weathernews.jp":                "気象情報へのリンク",
    "yamap.com":                     "登山情報へのリンク",
    "tools.google.com":              "GA オプトアウトの案内リンク",
    "policies.google.com":           "Google のプライバシーポリシーへのリンク",
    "marketingplatform.google.com":  "Google アナリティクスの説明へのリンク",
    "halab18.github.io":             "自分の公開URL",
    "www.w3.org":                    "SVG の名前空間(通信は発生しない)",
    "fonts.googleapis.com":          "(未使用) 予約",
    "localhost":                     "ローカル確認の案内",
}

# 通信が実際に発生する取得(fetch / script src / link href / img src)と、
# ただのリンク(<a href>)は分けて数える。CSP に効くのは前者だけ。
FETCHY = re.compile(
    r'(?:src|href)\s*=\s*["\'](https?://[^"\'\s]+)'          # 属性
    r'|fetch\(\s*[`"\']?(https?://[^`"\'\s,)]+)'              # fetch("…")
    r'|["\'`](https?://[^"\'`\s]+)["\'`]\s*(?:\+|\))',        # 組み立て中のURL
)
ANY_URL = re.compile(r'https?://([a-zA-Z0-9.\-]+)')
ANCHOR = re.compile(r'<a\b[^>]*href\s*=\s*["\'](https?://[^"\'\s]+)', re.I)
INLINE_SCRIPT = re.compile(r'<script(?![^>]*\bsrc\s*=)[^>]*>', re.I)
INLINE_STYLE = re.compile(r'<style\b', re.I)
INLINE_HANDLER = re.compile(r'\son[a-z]+\s*=\s*["\']', re.I)
SCRIPT_SRC = re.compile(r'<script[^>]*\bsrc\s*=\s*["\']([^"\']+)', re.I)


def host_of(url):
    m = ANY_URL.match(url)
    return m.group(1) if m else None


def scan():
    hosts = {}          # host -> set(理由となったファイル)
    anchors = set()
    inline = {"script": 0, "style": 0, "handler": 0}
    for f in targets():
        src = f.read_text(encoding="utf-8-sig", errors="replace")
        rel = f.relative_to(ROOT).as_posix()
        for h in ANY_URL.findall(src):
            hosts.setdefault(h, set()).add(rel)
        for m in ANCHOR.finditer(src):
            h = host_of(m.group(1))
            if h:
                anchors.add(h)
        if f.suffix in (".html", ".py"):
            inline["script"] += len(INLINE_SCRIPT.findall(src))
            inline["style"] += len(INLINE_STYLE.findall(src))
            inline["handler"] += len(INLINE_HANDLER.findall(src))
    return hosts, anchors, inline


def build_policy():
    """いま入れるとしたら、という CSP。実装から出しているので手書きより取りこぼしが少ない。"""
    connect = ["'self'", "https://api.open-meteo.com", "https://geocoding-api.open-meteo.com",
               "https://mreversegeocoder.gsi.go.jp", "https://www.google-analytics.com"]
    script = ["'self'", "'unsafe-inline'", "https://www.googletagmanager.com",
              "https://maps.gsi.go.jp"]
    return "; ".join([
        "default-src 'self'",
        "script-src " + " ".join(script),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src " + " ".join(connect),
        "font-src 'self'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'none'",
    ])


def main():
    hosts, anchors, inline = scan()
    unknown = sorted(h for h in hosts if h not in ALLOWED)

    print("外部参照の棚卸し")
    print("  参照しているホスト: {}件 (うちリンク先のみ {}件)".format(len(hosts), len(anchors)))
    for h in sorted(hosts):
        kind = "リンク" if h in anchors and h not in (
            "api.open-meteo.com", "geocoding-api.open-meteo.com",
            "mreversegeocoder.gsi.go.jp", "maps.gsi.go.jp",
            "www.googletagmanager.com") else "取得"
        mark = "  " if h in ALLOWED else "✕ "
        print("    {}{:<32} {} … {}".format(
            mark, h, kind, ALLOWED.get(h, "**許可表にありません**")))

    print()
    print("CSP に 'unsafe-inline' を要求しているもの")
    print("    インラインの <script>: {}箇所".format(inline["script"]))
    print("    インラインの <style> : {}箇所".format(inline["style"]))
    print("    on〜 属性のハンドラ  : {}箇所".format(inline["handler"]))
    if inline["handler"]:
        print("      ※ on〜 属性は nonce でも救えない。将来 'unsafe-inline' を外すなら"
              "先にここを addEventListener へ寄せる必要がある")

    if "--policy" in sys.argv:
        print()
        print("いま入れるとしたら (meta 版・未適用):")
        print("    " + build_policy())

    print()
    if unknown:
        print("結果: 許可表に無いホストが {}件あります".format(len(unknown)))
        for h in unknown:
            print("  ✕ {} ({})".format(h, " / ".join(sorted(hosts[h]))))
        print("  意図した追加なら scripts/check_csp.py の ALLOWED に理由つきで足してください")
        return 1
    print("結果: 問題なし (知らない外部参照はありません)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
