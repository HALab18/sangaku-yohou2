# -*- coding: utf-8 -*-
"""山リスト(xlsx)と内蔵山岳DBの照合 — DB拡張の第1段階(レポートのみ、何も書き換えない)

外部の山リスト(tenki_mountain_list.xlsx 形式: No./エリア区分/山名/よみかた/標高(m)/
百名山/二百名山/三百名山/選定なし)を読み、references/mountains.csv と多段照合して
「既存と重複 / 要判定 / 新規」に振り分けた candidates.csv を出力する。

照合は名前の完全一致だけでは不十分(表記ゆれの例: 後方羊蹄山=羊蹄山、甲武信岳=
甲武信ヶ岳、大菩薩岳=大菩薩嶺、旧名の例: 黒岳=水晶岳[標高一致でのみ検出可])。
多段シグナルで検出し、確信が持てないものは自動判定せず review に回す:

  auto_dup … 名前レベル一致(完全/かな正規化/括弧除去) or 読み一致+地域一致、かつ標高差50m以内
  review   … 括弧内別名の一致 / 接尾語ゆれ(岳/嶺/山) / 名前の包含 /
             地域一致+標高ほぼ一致(旧名検出) / 名前一致だが標高差大(同名別峰の疑い)
  new      … どのシグナルにも掛からない(高確度の新規)

使い方:
  python scripts/db_reconcile.py --xlsx 山リスト.xlsx --out candidates.csv

candidates.csv の decision 列は auto_dup=DUP / new=NEW を自動記入、review は空欄。
review 行を目視判定して DUP か NEW を記入してから db_fetch_coords.py に渡す。
"""
import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
MOUNTAINS_CSV = ROOT / "references" / "mountains.csv"

TIERS = ["百名山", "二百名山", "三百名山", "選定なし"]

# エリア区分(リスト側の粗い地域)→ 都道府県セット。
# 標高一致シグナルの誤検出を抑える地域ゲート専用(広めに取って取りこぼしを防ぐ)
AREA_PREFS = {
    "北海道": {"北海道"},
    "東北": {"青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"},
    "北関東・尾瀬・日光": {"茨城県", "栃木県", "群馬県", "福島県", "新潟県", "埼玉県"},
    "上信越": {"群馬県", "長野県", "新潟県"},
    "秩父・多摩・南関東": {"埼玉県", "東京都", "神奈川県", "千葉県", "山梨県", "長野県", "静岡県"},
    "北アルプス周辺": {"長野県", "富山県", "岐阜県", "新潟県"},
    "中央アルプス周辺": {"長野県", "岐阜県", "山梨県"},
    "南アルプス周辺": {"長野県", "山梨県", "静岡県"},
    "北陸・東海": {"富山県", "石川県", "福井県", "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県"},
    "近畿": {"滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "三重県"},
    "中国・四国": {"鳥取県", "島根県", "岡山県", "広島県", "山口県",
                 "徳島県", "香川県", "愛媛県", "高知県"},
    "九州": {"福岡県", "佐賀県", "長崎県", "熊本県", "大分県",
            "宮崎県", "鹿児島県", "沖縄県"},
}

ELEV_DUP_MAX = 50    # 名前一致でも標高差がこれ(m)を超えたら同名別峰の疑い → review
ELEV_NEAR = 10       # 地域一致+標高差これ以内 → 旧名・別名の疑い → review
PAREN_RE = re.compile(r"[（(](.*?)[）)]")


def norm(s):
    """表記ゆれ正規化: NFKC・空白除去・全角括弧→半角"""
    s = unicodedata.normalize("NFKC", s or "").strip()
    return s.replace("（", "(").replace("）", ")").replace(" ", "").replace("　", "")


def name_variants(name):
    """かな・記号ゆれを吸収した名前バリアント集合(括弧内は含めない)"""
    base = PAREN_RE.sub("", norm(name))
    v = {norm(name), base}
    v.add(re.sub(r"[ヶヵケが]", "", base))   # 甲武信ヶ岳=甲武信岳
    v.add(re.sub(r"[ノ之の]", "", base))     # 塔ノ岳=塔の岳
    v.discard("")
    return v


def suffix_stripped(name):
    """接尾語(山/岳/嶺/峰/嶽/森)を落とした語幹。大菩薩岳=大菩薩嶺 の検出用"""
    base = PAREN_RE.sub("", norm(name))
    m = re.match(r"^(.{2,})[山岳嶺峰嶽森]$", base)
    return m.group(1) if m else None


def paren_parts(name):
    """括弧内の別名(那須岳(茶臼岳)→茶臼岳)"""
    return {norm(p) for p in PAREN_RE.findall(norm(name))}


def load_db():
    with open(MOUNTAINS_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_variants"] = name_variants(r["name"])
        r["_parts"] = paren_parts(r["name"])
        r["_stem"] = suffix_stripped(r["name"])
        r["_prefs"] = set(r["pref"].split("・"))
        r["_elev"] = float(r["elev"])
    return rows


def load_xlsx(path):
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("openpyxl が必要です: pip install openpyxl")
    ws = openpyxl.load_workbook(path, data_only=True)["山一覧"]
    out = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[2]:
            continue
        no, area, name, yomi, elev = r[0], norm(r[1]), norm(r[2]), norm(r[3]), float(r[4])
        flags = r[5:9]
        tier = next((t for t, f in zip(TIERS, flags) if f), "選定なし")
        out.append({"no": no, "area": area, "name": name, "yomi": yomi,
                    "elev": elev, "tier": tier})
    return out


def match_one(cand, db):
    """1候補をDB全件と照合し (bucket, 相手DB名, 判定根拠) を返す"""
    cv = name_variants(cand["name"])
    cp = paren_parts(cand["name"])
    cstem = suffix_stripped(cand["name"])
    cbase = PAREN_RE.sub("", norm(cand["name"]))
    area_prefs = AREA_PREFS.get(cand["area"], set())
    hits = []  # (優先度, bucket, db名, 根拠)

    for r in db:
        d = abs(cand["elev"] - r["_elev"])
        dtxt = f"標高差{d:.0f}m({cand['elev']:.0f}/{r['_elev']:.0f})"
        in_region = bool(area_prefs & r["_prefs"])

        if cv & r["_variants"]:
            if d <= ELEV_DUP_MAX:
                hits.append((0, "auto_dup", r["name"], f"名前一致 {dtxt}"))
            else:
                hits.append((2, "review", r["name"], f"名前一致だが標高差大 {dtxt}"))
            continue
        if cand["yomi"] and cand["yomi"] == r["yomi"] and in_region:
            if d <= ELEV_DUP_MAX:
                hits.append((1, "auto_dup", r["name"], f"読み一致+地域一致 {dtxt}"))
            else:
                hits.append((2, "review", r["name"], f"読み一致だが標高差大 {dtxt}"))
            continue
        if (cp & r["_variants"]) or (cv & r["_parts"]) or (cp & r["_parts"]):
            hits.append((3, "review", r["name"], f"括弧内別名が一致 {dtxt}"))
            continue
        if cstem and cstem == r["_stem"]:
            hits.append((4, "review", r["name"], f"接尾語ゆれ {dtxt}"))
            continue
        rbase = PAREN_RE.sub("", norm(r["name"]))
        shorter, longer = sorted([cbase, rbase], key=len)
        if len(shorter) >= 2 and shorter in longer and in_region and d <= 80:
            hits.append((5, "review", r["name"], f"名前の包含+地域一致 {dtxt}"))
            continue
        if in_region and d <= ELEV_NEAR:
            hits.append((6, "review", r["name"], f"地域一致+標高ほぼ一致 {dtxt} ※旧名/別名の疑い"))

    if not hits:
        return "new", "", ""
    hits.sort(key=lambda h: h[0])
    top = hits[0]
    others = "; ".join(f"{h[2]}[{h[3]}]" for h in hits[1:3])
    detail = top[3] + (f" / 他候補: {others}" if others else "")
    return top[1], top[2], detail


def main():
    ap = argparse.ArgumentParser(description="山リスト(xlsx)とDBの照合レポートを作る")
    ap.add_argument("--xlsx", required=True, help="山リスト .xlsx のパス")
    ap.add_argument("--out", default="candidates.csv", help="出力先CSV (既定: candidates.csv)")
    a = ap.parse_args()

    db = load_db()
    cands = load_xlsx(a.xlsx)
    print(f"DB: {len(db)}座 / リスト: {len(cands)}座")

    counts = {}
    rows = []
    for c in cands:
        bucket, dbname, detail = match_one(c, db)
        counts[(c["tier"], bucket)] = counts.get((c["tier"], bucket), 0) + 1
        rows.append([c["no"], c["area"], c["name"], c["yomi"], f"{c['elev']:.0f}",
                     c["tier"], bucket, dbname, detail,
                     {"auto_dup": "DUP", "new": "NEW"}.get(bucket, ""), ""])

    rows.sort(key=lambda r: (TIERS.index(r[5]), r[0]))
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["no", "area", "name", "yomi", "elev", "tier",
                    "bucket", "db_match", "detail", "decision", "notes"])
        w.writerows(rows)

    print(f"\n{'':12s} {'auto_dup':>8s} {'review':>8s} {'new':>8s}")
    for t in TIERS:
        print(f"{t:12s} {counts.get((t, 'auto_dup'), 0):8d} "
              f"{counts.get((t, 'review'), 0):8d} {counts.get((t, 'new'), 0):8d}")
    print(f"\n出力: {a.out}")


if __name__ == "__main__":
    main()
