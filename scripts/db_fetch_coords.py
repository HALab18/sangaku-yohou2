# -*- coding: utf-8 -*-
"""新規山の座標・都道府県の取得 — DB拡張の第2段階(レポートのみ、DBは書き換えない)

db_reconcile.py が出力した candidates.csv の decision=NEW 行について、
yamareco の山データ(詳細ページの JSON-LD 構造化データ)から座標・標高・都道府県を
取得し、enriched.csv に書き出す。東北百名山77座の追加時に実績のある手法。

  検索  : search_pt.php?searchkey=<山名(EUC-JP)>&request=1
          → 結果行の「山名 / よみ (標高m)」をリスト側の標高と突き合わせて同定
            (同名別峰が多いため、名前だけでなく標高±30mの一致を必須にする)
  詳細  : ptinfo.php?ptid=N の JSON-LD から緯度経度、ページ本文から都道府県
  検算  : Open-Meteo Elevation API で取得座標のDEM標高を照合(check_mountains.pyと同基準)

取得できなかった山は status=manual で残す(件数は少ない想定。手動で解決する)。
リクエストは逐次+ディレイ(既定1.2秒)で、途中結果を cache に保存(再実行時はスキップ)。

使い方:
  python scripts/db_fetch_coords.py --candidates candidates.csv --out enriched.csv \
      --cache fetch_cache.json [--tiers 二百名山,三百名山] [--delay 1.2]
"""
import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SEARCH_URL = "https://www.yamareco.com/modules/yamainfo/search_pt.php"
DETAIL_URL = "https://www.yamareco.com/modules/yamainfo/ptinfo.php"
REVGEO_URL = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
ELEV_URL = "https://api.open-meteo.com/v1/elevation"
UA = {"User-Agent": "sangaku-yohou2-db-maintenance (github.com/HALab18/sangaku-yohou2)"}

ELEV_MATCH = 30    # 検索結果の同定に使う標高差(m)。これ以内なら同じ山とみなす
DEM_WARN = 150     # DEM標高との差がこれ(m)を超えたら座標ミスの疑い

PREFS = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
# 市区町村コード上2桁 → 都道府県 (逆ジオコーダのフォールバック用)
PREF_BY_CODE = {f"{i + 1:02d}": p for i, p in enumerate(PREFS)}


def http_get(url, retries=2):
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except Exception:
            if i == retries:
                raise
            time.sleep(3 * (i + 1))


def norm(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def search_yamareco(name, delay):
    """山名検索。結果 [(ptid, 名前, よみ, 標高), ...] を最大3ページ分返す"""
    rows, page = [], 1
    while page <= 3:
        q = urllib.parse.urlencode(
            {"searchkey": name.encode("euc-jp"), "request": 1, "pnum": page})
        html = http_get(f"{SEARCH_URL}?{q}").decode("euc-jp", errors="replace")
        time.sleep(delay)
        found = re.findall(
            r'<a href="ptinfo\.php\?ptid=(\d+)">([^<]+)</a>\s*/\s*([^(<]*)\((\d+(?:\.\d+)?)m\)', html)
        rows += [(pid, norm(n), norm(y), float(e)) for pid, n, y, e in found]
        total = re.search(r"全<strong>(\d+)</strong>件", html)
        if not found or not total or len(rows) >= int(total.group(1)):
            break
        page += 1
    return rows


def pick_result(name, elev, results):
    """検索結果から対象の山を同定。標高±ELEV_MATCH を必須にし、名前の一致度で選ぶ"""
    near = [r for r in results if abs(r[3] - elev) <= ELEV_MATCH]
    exact = [r for r in near if r[1] == name]
    if exact:
        return min(exact, key=lambda r: abs(r[3] - elev))
    contains = [r for r in near if name in r[1] or r[1] in name]
    if contains:
        return min(contains, key=lambda r: abs(r[3] - elev))
    if len(near) == 1:  # 名前は違うが標高一致が1件だけ(山塊名→最高峰名のケース)
        return near[0]
    return None


def fetch_detail(ptid):
    """詳細ページから (lat, lon, 標高, 都道府県リスト) を取る"""
    html = http_get(f"{DETAIL_URL}?ptid={ptid}").decode("euc-jp", errors="replace")
    ld = None
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if d.get("@type") == "Mountain":
            ld = d
            break
    if not ld:
        return None
    geo = ld.get("geo", {})
    lat, lon = geo.get("latitude"), geo.get("longitude")
    elev = (ld.get("elevation") or {}).get("value")
    # 「都道府県」表示の近くに出る都道府県名を拾う(複数県は・で結合)
    prefs = []
    for m in re.finditer("都道府県", html):
        win = html[m.end():m.end() + 400]
        prefs = [p for p in PREFS if p in win]
        if prefs:
            break
    return lat, lon, elev, prefs


def rev_geocode_pref(lat, lon):
    """国土地理院の逆ジオコーダで座標→都道府県(フォールバック)"""
    q = urllib.parse.urlencode({"lat": lat, "lon": lon})
    d = json.loads(http_get(f"{REVGEO_URL}?{q}"))
    muni = str(d.get("results", {}).get("muniCd", ""))
    return PREF_BY_CODE.get(muni[:2].zfill(2), "")


def dem_check(rows):
    """Open-Meteo Elevation API でDEM標高を一括照合(100地点/リクエスト)"""
    ok = [r for r in rows if r["status"] in ("ok", "check") and r["lat"]]
    for i in range(0, len(ok), 100):
        chunk = ok[i:i + 100]
        q = urllib.parse.urlencode({
            "latitude": ",".join(str(r["lat"]) for r in chunk),
            "longitude": ",".join(str(r["lon"]) for r in chunk),
        }, safe=",")
        dems = json.loads(http_get(f"{ELEV_URL}?{q}"))["elevation"]
        for r, dem in zip(chunk, dems):
            if dem is None:
                continue
            r["dem"] = f"{dem:.0f}"
            diff = abs(float(r["elev"]) - dem)
            r["dem_diff"] = f"{diff:.0f}"
            if diff > DEM_WARN:
                r["status"] = "check"
                r["note"] = (r["note"] + " " if r["note"] else "") + f"DEM標高差{diff:.0f}m"


FIELDS = ["no", "area", "tier", "name", "final_name", "yomi", "pref",
          "lat", "lon", "elev", "elev_list", "ym_name", "ym_ptid",
          "dem", "dem_diff", "status", "note"]


def main():
    ap = argparse.ArgumentParser(description="NEW候補の座標・都道府県をyamarecoから取得")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--tiers", default="二百名山,三百名山")
    ap.add_argument("--delay", type=float, default=1.2)
    a = ap.parse_args()

    tiers = set(a.tiers.split(","))
    with open(a.candidates, encoding="utf-8-sig", newline="") as f:
        cands = [r for r in csv.DictReader(f)
                 if r["decision"] == "NEW" and r["tier"] in tiers]
    print(f"対象: {len(cands)}座 ({a.tiers})")

    cache_path = Path(a.cache)
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    rows = []
    for i, c in enumerate(cands, 1):
        key = f"{c['name']}|{c['elev']}"
        if key not in cache:
            elev = float(c["elev"])
            rec = {"status": "manual", "ym_ptid": "", "ym_name": "", "lat": "",
                   "lon": "", "elev": "", "pref": "", "note": ""}
            try:
                results = search_yamareco(c["name"], a.delay)
                hit = pick_result(c["name"], elev, results)
                if hit is None:
                    rec["note"] = ("検索結果に標高一致なし: "
                                   + "; ".join(f"{n}({e:.0f}m)" for _, n, _, e in results[:5]))
                else:
                    ptid, ym_name = hit[0], hit[1]
                    detail = fetch_detail(ptid)
                    time.sleep(a.delay)
                    if detail is None:
                        rec["note"] = f"詳細ページにJSON-LDなし (ptid={ptid})"
                    else:
                        lat, lon, ym_elev, prefs = detail
                        if not prefs:
                            prefs = [p for p in [rev_geocode_pref(lat, lon)] if p]
                            time.sleep(a.delay)
                        rec.update(status="ok", ym_ptid=ptid, ym_name=ym_name,
                                   lat=lat, lon=lon, elev=ym_elev or hit[3],
                                   pref="・".join(prefs))
                        if not prefs:
                            rec["status"], rec["note"] = "check", "都道府県が取得できず"
                        if ym_name != c["name"]:
                            rec["status"] = "check"
                            rec["note"] = (rec["note"] + " " if rec["note"] else "") \
                                + f"名前が異なる: リスト={c['name']} / yamareco={ym_name}"
            except Exception as e:
                rec["note"] = f"取得エラー: {e}"
            cache[key] = rec
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
            print(f"[{i}/{len(cands)}] {c['name']} → {cache[key]['status']}"
                  f" {cache[key].get('note', '')}")
        rec = cache[key]
        rows.append({
            "no": c["no"], "area": c["area"], "tier": c["tier"], "name": c["name"],
            "final_name": c.get("final_name") or c["name"],
            "yomi": c.get("final_yomi") or c["yomi"],
            "pref": rec["pref"], "lat": rec["lat"], "lon": rec["lon"],
            "elev": rec["elev"], "elev_list": c["elev"],
            "ym_name": rec["ym_name"], "ym_ptid": rec["ym_ptid"],
            "dem": "", "dem_diff": "", "status": rec["status"], "note": rec["note"],
        })

    print("\nDEM標高を照合中...")
    dem_check(rows)

    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)

    n = {"ok": 0, "check": 0, "manual": 0}
    for r in rows:
        n[r["status"]] += 1
    print(f"\n結果: ok={n['ok']} / 要確認={n['check']} / 手動解決={n['manual']}")
    print(f"出力: {a.out}")


if __name__ == "__main__":
    main()
