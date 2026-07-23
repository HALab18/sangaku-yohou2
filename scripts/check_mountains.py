# -*- coding: utf-8 -*-
"""山岳DB(references/mountains.csv)の健全性チェック

チェック内容:
  1. CSVの形式 (名前の重複・空欄・緯度経度標高が日本の範囲内か)
  2. index.html 内蔵DB(MOUNTAINS配列)との同期 (CSVと1件ずつ突き合わせ)
  3. Open-Meteo Elevation API による標高の照合
     - 座標が山頂から外れていると、その地点のDEM標高がCSVの山頂標高より
       大幅に低くなることを利用して座標ミスを検出する
     - DEMはCopernicus GLO-90 (90m格子) のため、尖った岩峰(槍ヶ岳・剱岳・権現岳等)は
       実際の山頂標高より数十m低く出る。差が中程度なら「要確認」に留める

使い方:
  python scripts/check_mountains.py

終了コード: 0=問題なし / 1=要修正(形式エラー・同期ずれ・座標ミスの疑い)あり
"""
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
MOUNTAINS_CSV = ROOT / "references" / "mountains.csv"
INDEX_HTML = ROOT / "index.html"
ELEV_URL = "https://api.open-meteo.com/v1/elevation"

# DEM標高との差の判定(m)。90m格子DEMは岩峰で低く出るため即エラーにしない
DIFF_OK = 80       # ここまでは正常とみなす
DIFF_WARN = 150    # ここまでは「要確認」(急峻な地形ならありうる)。超えたら座標ミスの疑い

CHUNK_WAIT = 2     # チャンク間の待機(秒)。無料APIのレート制限(429)を避ける
RETRY_WAITS = [10, 30, 60]  # 429/5xx を受けたときの再試行間隔(秒)


def load_rows():
    with open(MOUNTAINS_CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def check_format(rows):
    errors = []
    names = [r["name"] for r in rows]
    for n in sorted({x for x in names if names.count(x) > 1}):
        errors.append(f"名前が重複: {n}")
    for r in rows:
        if not all(r.get(k) for k in ("name", "yomi", "pref", "lat", "lon", "elev")):
            errors.append(f"空欄がある行: {r.get('name', '?')}")
            continue
        try:
            lat, lon, elev = float(r["lat"]), float(r["lon"]), float(r["elev"])
        except ValueError:
            errors.append(f"数値でない値: {r['name']}")
            continue
        if not (24 <= lat <= 46 and 122 <= lon <= 146 and 100 <= elev <= 3776):
            errors.append(f"緯度経度標高が日本の範囲外: {r['name']} ({lat}, {lon}, {elev}m)")
    return errors


def check_sync(rows):
    """index.html の MOUNTAINS 配列とCSVの内容が一致するか"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r"const MOUNTAINS=(\[\[.*?\]\]);", html, re.S)
    if not m:
        return ["index.html に MOUNTAINS 配列が見つかりません"]
    js = json.loads(m.group(1))
    errors = []
    cmap = {r["name"]: r for r in rows}
    jmap = {x[0]: x for x in js}
    for n in sorted(cmap.keys() - jmap.keys()):
        errors.append(f"index.html に無い: {n}")
    for n in sorted(jmap.keys() - cmap.keys()):
        errors.append(f"CSVに無い: {n}")
    for n in cmap.keys() & jmap.keys():
        r, x = cmap[n], jmap[n]
        if (r["yomi"] != x[1] or r["pref"] != x[2]
                or abs(float(r["lat"]) - x[3]) > 1e-9
                or abs(float(r["lon"]) - x[4]) > 1e-9
                or abs(float(r["elev"]) - x[5]) > 1e-9):
            errors.append(f"値が不一致: {n} (CSV={r['lat']},{r['lon']},{r['elev']} / JS={x[3]},{x[4]},{x[5]})")
    return errors


def fetch_elevations(chunk):
    """1チャンク分のDEM標高を取得。429/5xx は RETRY_WAITS の間隔で再試行する"""
    q = urllib.parse.urlencode({
        "latitude": ",".join(r["lat"] for r in chunk),
        "longitude": ",".join(r["lon"] for r in chunk),
    }, safe=",")
    req = urllib.request.Request(f"{ELEV_URL}?{q}", headers={"User-Agent": "sangaku-yohou-check"})
    for wait in RETRY_WAITS + [None]:
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read())["elevation"]
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            if wait is None:
                raise SystemExit(
                    f"Elevation APIが混雑しています (HTTP {e.code})。時間をおいて再実行してください")
            print(f"  … HTTP {e.code}: {wait}秒待って再試行します")
            time.sleep(wait)


def check_elevation(rows):
    """Open-Meteo Elevation API (100地点/リクエスト) でCSV標高とDEM標高を突き合わせる"""
    dems = []
    for i in range(0, len(rows), 100):
        if i:
            time.sleep(CHUNK_WAIT)
        dems += fetch_elevations(rows[i:i + 100])
    suspects, warns = [], []
    for r, dem in zip(rows, dems):
        if dem is None:
            warns.append((float("inf"), f"{r['name']}: DEM標高が取得できません"))
            continue
        diff = abs(float(r["elev"]) - dem)
        line = f"{r['name']}: CSV={float(r['elev']):.0f}m DEM={dem:.0f}m 差={diff:.0f}m"
        if diff > DIFF_WARN:
            suspects.append((diff, line + " ← 座標ミスの疑い"))
        elif diff > DIFF_OK:
            warns.append((diff, line + " (岩峰ならDEMが低く出るだけの可能性あり)"))
    return ([x for _, x in sorted(suspects, reverse=True)],
            [x for _, x in sorted(warns, reverse=True)])


def main():
    rows = load_rows()
    print(f"山岳DBチェック: {len(rows)}座 ({MOUNTAINS_CSV.name})")
    ng = False

    fmt = check_format(rows)
    print(f"\n[1/3] CSV形式: {'OK' if not fmt else f'{len(fmt)}件のエラー'}")
    for e in fmt:
        print(f"  ✕ {e}")
    ng = ng or bool(fmt)

    sync = check_sync(rows)
    print(f"[2/3] index.html との同期: {'OK' if not sync else f'{len(sync)}件のずれ'}")
    for e in sync:
        print(f"  ✕ {e}")
    ng = ng or bool(sync)

    suspects, warns = check_elevation(rows)
    print(f"[3/3] DEM標高照合 (Open-Meteo Elevation API): "
          f"{'OK' if not suspects and not warns else f'疑い{len(suspects)}件 / 要確認{len(warns)}件'}")
    for e in suspects:
        print(f"  ✕ {e}")
    for e in warns:
        print(f"  ⚠ {e}")
    ng = ng or bool(suspects)

    print(f"\n結果: {'要修正あり' if ng else 'すべて正常'}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
