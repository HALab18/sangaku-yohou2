# -*- coding: utf-8 -*-
"""index.html の MOUNTAINS 配列から docs/mountains.html (対応山リスト) を生成する。

山岳DBを更新したら再実行して同期する:
    python scripts/gen_mountain_list.py
"""
import json
import re
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUT = ROOT / "docs" / "mountains.html"

REGIONS = [
    ("北海道", ["北海道"]),
    ("東北", ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"]),
    ("関東", ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"]),
    ("甲信越", ["山梨県", "長野県", "新潟県"]),
    ("北陸", ["富山県", "石川県", "福井県"]),
    ("東海", ["岐阜県", "静岡県", "愛知県", "三重県"]),
    ("近畿", ["滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"]),
    ("中国・四国", ["鳥取県", "島根県", "岡山県", "広島県", "山口県",
                  "徳島県", "香川県", "愛媛県", "高知県"]),
    ("九州・沖縄", ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県",
                  "宮崎県", "鹿児島県", "沖縄県"]),
]


def load_mountains():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"const MOUNTAINS=(\[.*?\]);", html, re.S)
    if not m:
        raise SystemExit("index.html に MOUNTAINS 配列が見つかりません")
    return json.loads(m.group(1))


def group_by_region(mountains):
    pref2region = {p: name for name, prefs in REGIONS for p in prefs}
    grouped = {name: [] for name, _ in REGIONS}
    for mt in mountains:
        first_pref = mt[2].split("・")[0]
        region = pref2region.get(first_pref)
        if region is None:
            raise SystemExit(f"地域未定義の都道府県: {first_pref} ({mt[0]})")
        grouped[region].append(mt)
    for rows in grouped.values():
        rows.sort(key=lambda mt: mt[1])  # 読みの五十音順
    return grouped


def build_rows(rows):
    out = []
    for name, yomi, pref, _lat, _lon, elev in rows:
        href = "../index.html#" + urllib.parse.quote(name)
        key = f"{name}{yomi}{pref}"
        out.append(
            f'<tr data-k="{key}"><td class="nm"><a href="{href}">{name}</a>'
            f"<small>{yomi}</small></td>"
            f'<td>{pref}</td><td class="el">{elev:,}m</td></tr>'
        )
    return "\n".join(out)


def build_sections(grouped):
    sections = []
    for region, _ in REGIONS:
        rows = grouped[region]
        if not rows:
            continue
        sections.append(f"""<section class="rg">
<h2>{region} <span class="cnt">({len(rows)}座)</span></h2>
<div class="tbl"><table>
<thead><tr><th>山名（タップで予報へ）</th><th>都道府県</th><th>標高</th></tr></thead>
<tbody>
{build_rows(rows)}
</tbody>
</table></div>
</section>""")
    return "\n\n".join(sections)


def main():
    mountains = load_mountains()
    grouped = group_by_region(mountains)
    total = len(mountains)

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>対応している山の一覧 — PeakWeather</title>
<meta name="description" content="PeakWeather が内蔵データベースで対応している全{total}座の一覧。山名をタップすると山頂・稜線の気象予報を表示します。">
<link rel="icon" type="image/png" href="../icons/favicon-32.png">
<meta name="theme-color" content="#1e2d4a">
<!-- このファイルは scripts/gen_mountain_list.py により index.html から自動生成されます。直接編集しないでください -->
<style>
:root{{--night:#1e2d4a;--slate:#48608c;--sky:#5b87c5;--link:#2b5fa3;
  --btn:#4276b5;--bg:#f4f6f9;--line:#dee4ee;--field:#c9d2e0}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:#222;
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic UI","Meiryo",system-ui,sans-serif;
  font-size:14px;line-height:1.6}}

/* ヘッダー (本体ヒーローの縮小版) */
header{{background:var(--night);color:#fff;text-align:center;padding:30px 20px 0;position:relative}}
header .back{{position:absolute;left:14px;top:12px;color:#c9d3e5;font-size:.82em;text-decoration:none}}
header .back:hover{{color:#fff}}
header h1{{margin:0;font-size:1.45em;font-weight:800;letter-spacing:.06em}}
header .sub{{margin:8px 0 0;font-size:.85em;color:#c9d3e5}}
.ridge{{display:block;width:100%;height:44px;margin-top:18px}}

main{{max-width:860px;margin:0 auto;padding:18px 14px 8px}}

/* 検索 (本体フォームカードと同デザイン) */
.searchcard{{background:#fff;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 12px rgba(30,45,74,.10);position:sticky;top:8px;z-index:10}}
.searchcard label{{display:flex;flex-direction:column;gap:5px;font-size:.82em;font-weight:600;color:#556}}
.searchcard input{{font-size:16px;padding:11px 12px;border:1.5px solid var(--field);border-radius:10px;
  background:#fff;width:100%;font-family:inherit}}
.searchcard input:focus{{outline:2px solid var(--night);outline-offset:1px}}
#hits{{margin:8px 0 0;font-size:.82em;color:#5b6b8a;font-weight:600}}

.notice{{background:#edf2f9;border-left:5px solid var(--slate);color:#44506b;padding:10px 12px;
  border-radius:0 6px 6px 0;margin:18px 0;font-size:.9em}}
.notice a{{color:var(--link)}}

/* 地域セクション (本体の見出し・表と同デザイン) */
h2{{color:var(--night);font-size:1.08em;margin:24px 0 8px;border-left:5px solid var(--sky);padding-left:8px}}
h2 .cnt{{color:#8a94a8;font-size:.85em;font-weight:600}}
.tbl{{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:6px 0 4px}}
table{{border-collapse:collapse;width:100%}}
th{{background:var(--slate);color:#fff;padding:6px 9px;font-weight:600;font-size:.9em}}
td{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:center;background:#fff}}
tr:nth-child(even) td{{background:#eef1f6}}
td.nm{{text-align:left}}
td.nm a{{color:var(--link);font-weight:600;text-decoration:none}}
td.nm a:hover{{text-decoration:underline}}
td.nm small{{display:block;color:#8a94a8;font-size:.82em;font-weight:400}}
td.el{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
tr[hidden]{{display:none}}

footer{{color:#888;font-size:.82em;margin-top:26px;border-top:1px solid var(--line);padding-top:10px;padding-bottom:16px}}
footer a{{color:var(--link)}}

@media(min-width:700px){{
  header h1{{font-size:1.7em}}
  main{{padding:24px 24px 12px}}
}}
</style>
</head>
<body>

<header>
  <a class="back" href="../index.html">← トップへ戻る</a>
  <h1>対応している山の一覧</h1>
  <p class="sub">PeakWeather 内蔵データベース 全{total}座</p>
  <svg class="ridge" viewBox="0 0 750 44" preserveAspectRatio="none" aria-hidden="true">
    <path d="M0 44 L0 30 L95 12 L185 26 L290 5 L395 24 L500 9 L610 27 L695 15 L750 24 L750 44 Z" fill="#f4f6f9"/>
  </svg>
</header>

<main>

<div class="searchcard">
  <label>山名・読み・都道府県でしぼり込み
    <input id="q" placeholder="例: やり / 槍 / 長野" autocomplete="off">
  </label>
  <p id="hits" hidden></p>
</div>

<div class="notice">
山名をタップすると、その山の予報ページが開きます。<br>
この一覧にない山も、<a href="../index.html">トップページ</a>の山名欄に直接入力すれば
国土地理院の地名検索で自動的に探します。
</div>

{build_sections(grouped)}

<footer>
<a href="../index.html">← PeakWeather トップへ戻る</a> /
収録: 日本百名山・人気の山・東北百名山ほか 全{total}座 /
山岳座標: 国土地理院データ・yamareco 山情報で照合
</footer>

</main>

<script>
"use strict";
(function(){{
  var q=document.getElementById("q"),hits=document.getElementById("hits");
  var rows=[].slice.call(document.querySelectorAll("tbody tr"));
  var secs=[].slice.call(document.querySelectorAll(".rg"));
  var total={total};
  // カタカナ→ひらがな (読み検索用)
  function norm(s){{return s.toLowerCase().replace(/[ァ-ヶ]/g,function(c){{return String.fromCharCode(c.charCodeAt(0)-96)}})}}
  q.addEventListener("input",function(){{
    var v=norm(q.value.trim());
    var n=0;
    rows.forEach(function(tr){{
      var show=!v||norm(tr.dataset.k).indexOf(v)>=0;
      tr.hidden=!show;if(show)n++;
    }});
    secs.forEach(function(sec){{
      sec.hidden=!sec.querySelector("tbody tr:not([hidden])");
    }});
    hits.hidden=!v;
    hits.textContent=v?("全"+total+"座中 "+n+"座が該当"):"";
  }});
}})();
</script>

</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8", newline="\n")
    counts = "、".join(f"{r}{len(grouped[r])}" for r, _ in REGIONS if grouped[r])
    print(f"docs/mountains.html を生成しました (全{total}座: {counts})")


if __name__ == "__main__":
    main()
