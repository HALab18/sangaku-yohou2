# -*- coding: utf-8 -*-
"""新規山のDB反映 — DB拡張の最終段階(references/mountains.csv と index.html を書く唯一のスクリプト)

db_fetch_coords.py が出力した enriched.csv の status=ok 行を、CSVと index.html の
MOUNTAINS 配列の両方へ一括追加する(片方だけ更新して同期が壊れる事故を防ぐ)。
status=check/manual の行は取り込まない — enriched.csv を修正して ok にしてから再実行する。

書き込み前の検査(1つでも失敗したら何も書かずに終了):
  - 名前の重複: 既存DBとの衝突・新規同士の衝突(既存エントリは絶対に改名しない。
    衝突したら enriched.csv 側の final_name に「山名(県名)」等の区別名を付けること)
  - 都道府県: 実在の47都道府県名か(・区切りの各要素を検査)
  - 範囲: 緯度24〜46 / 経度122〜146 / 標高100〜3776m (check_mountains.py と同基準)
  - 近接重複: 既存の山・新規同士と2km未満のペアを検出(東北百名山追加時と同じ2段階検査)。
    別々の山だと確認済みのペアは --allow-near 山名A/山名B で明示的に許可する

使い方:
  python scripts/db_merge.py --enriched enriched.csv [--dry-run]
      [--allow-near 山名A/山名B ...]

反映後は必ず実行:
  python scripts/check_mountains.py      # 形式・同期・DEM標高の総合検査
  python scripts/gen_mountain_list.py    # docs/mountains.html を再生成
"""
import argparse
import csv
import io
import json
import math
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
MOUNTAINS_CSV = ROOT / "references" / "mountains.csv"
INDEX_HTML = ROOT / "index.html"

NEAR_KM = 2.0  # これ未満の距離にある山ペアは同一峰の疑いとして要確認

PREFS = {
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
}


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_existing():
    with open(MOUNTAINS_CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_new(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    skipped = [r for r in rows if r["status"] != "ok"]
    news = []
    for r in rows:
        if r["status"] != "ok":
            continue
        news.append({
            "name": r["final_name"].strip(),
            "yomi": r["yomi"].strip(),
            "pref": r["pref"].strip(),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "elev": int(round(float(r["elev"]))),
        })
    return news, skipped


def validate(existing, news, allow_near):
    errors, warns = [], []
    exist_names = {r["name"] for r in existing}

    seen = set()
    for n in news:
        if not n["name"] or not n["yomi"] or not n["pref"]:
            errors.append(f"空欄がある: {n}")
            continue
        if n["name"] in exist_names:
            errors.append(f"既存DBと名前が衝突: {n['name']} → final_name で区別名を付けること")
        if n["name"] in seen:
            errors.append(f"新規同士で名前が衝突: {n['name']}")
        seen.add(n["name"])
        bad = [p for p in n["pref"].split("・") if p not in PREFS]
        if bad:
            errors.append(f"実在しない都道府県: {n['name']} ({'・'.join(bad)})")
        if not (24 <= n["lat"] <= 46 and 122 <= n["lon"] <= 146 and 100 <= n["elev"] <= 3776):
            errors.append(f"緯度経度標高が範囲外: {n['name']} ({n['lat']}, {n['lon']}, {n['elev']}m)")

    # 近接重複 (新規 vs 既存、新規 vs 新規)
    pts = [(r["name"], float(r["lat"]), float(r["lon"])) for r in existing]
    for i, n in enumerate(news):
        for name2, lat2, lon2 in pts + [(m["name"], m["lat"], m["lon"]) for m in news[:i]]:
            d = haversine_km(n["lat"], n["lon"], lat2, lon2)
            if d < NEAR_KM:
                pair = f"{n['name']}/{name2}"
                pair_r = f"{name2}/{n['name']}"
                if pair in allow_near or pair_r in allow_near:
                    warns.append(f"近接ペア(許可済み): {pair} {d:.2f}km")
                else:
                    errors.append(f"近接重複の疑い: {pair} {d:.2f}km"
                                  f" → 別々の山なら --allow-near {pair} で許可")
    return errors, warns


def append_csv(news):
    raw = MOUNTAINS_CSV.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "CSVにBOMがありません"
    tail = b"" if raw.endswith(b"\r\n") else b"\r\n"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for n in news:
        w.writerow([n["name"], n["yomi"], n["pref"], n["lat"], n["lon"], n["elev"]])
    with open(MOUNTAINS_CSV, "ab") as f:
        f.write(tail + buf.getvalue().encode("utf-8"))


def splice_index_html(news):
    html = INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r"const MOUNTAINS=\[\[.*?\]\];", html, re.S)
    if not m:
        raise SystemExit("index.html に MOUNTAINS 配列が見つかりません")
    block = m.group(0)
    add = ",".join(
        json.dumps([n["name"], n["yomi"], n["pref"], n["lat"], n["lon"], n["elev"]],
                   ensure_ascii=False, separators=(",", ":"))
        for n in news)
    new_block = block[:-len("]];")] + "]," + add + "];"
    INDEX_HTML.write_text(html.replace(block, new_block), encoding="utf-8", newline="")


def main():
    ap = argparse.ArgumentParser(description="enriched.csv の ok 行をCSVとindex.htmlへ一括追加")
    ap.add_argument("--enriched", required=True)
    ap.add_argument("--allow-near", action="append", default=[],
                    help="近接していても別の山として許可するペア (山名A/山名B)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    existing = load_existing()
    news, skipped = load_new(a.enriched)
    print(f"既存: {len(existing)}座 / 追加対象(ok): {len(news)}座 / 未解決スキップ: {len(skipped)}座")
    for r in skipped:
        print(f"  スキップ [{r['status']}] {r['name']}: {r['note']}")

    errors, warns = validate(existing, news, set(a.allow_near))
    for wmsg in warns:
        print(f"  ⚠ {wmsg}")
    if errors:
        print(f"\n検査エラー {len(errors)}件 — 何も書き込まずに終了します:")
        for e in errors:
            print(f"  ✕ {e}")
        sys.exit(1)

    if a.dry_run:
        print("\n--dry-run: 検査OK。以下を追加できます:")
        for n in news:
            print(f"  {n['name']},{n['yomi']},{n['pref']},{n['lat']},{n['lon']},{n['elev']}")
        return

    append_csv(news)
    splice_index_html(news)
    print(f"\n反映完了: {len(existing)} → {len(existing) + len(news)}座")
    print("次に実行: python scripts/check_mountains.py && python scripts/gen_mountain_list.py")


if __name__ == "__main__":
    main()
