# -*- coding: utf-8 -*-
"""山岳DB(references/mountains.csv)の健全性チェック

チェック内容:
  0. 構文・公開物・外部参照の静的検査 (scripts/check_syntax.py・check_csp.py)
     - Python / JavaScript / HTML に直接書かれた <script> の構文、logic.js と gate.js が
       ES5 の範囲に留まっているか、`.nojekyll` やアイコンが揃っているか
     - 通信する相手が「気象データ・地名・アクセス解析」の3系統から増えていないか
       (貼り付けたコードに知らないタグが付いてきた、を検出する)
     - 構文が壊れていると以下の検査結果は当てにならないので最初に見る
  1. CSVの形式 (名前の重複・空欄・緯度経度標高が日本の範囲内か)
  2. index.html 内蔵DB(MOUNTAINS配列)との同期 (CSVと1件ずつ突き合わせ)
  3. 自動生成ページ(docs/find.html・docs/mountains.html)が生成元と一致しているか
     - 生成物を直接編集すると、次に生成スクリプトを流した時点で修正が消える。
       実際に find.html の z-index 修正がこの経路で失われた前例があるため検査する
  4. 判定・表示・山さがしのスコア (入出力表 + 乱数総当たり + 表示 + find)
     - CLI(scripts/mountain_weather.py) と Web(logic.js) が同じ入力で同じ A/B/C を
       返すかを機械的に確かめる。片方だけ直すと静かにズレるため(CLAUDE.md 規約3)
     - 入出力表だけでは人が思いつかなかった組み合わせが抜けるので、
       乱数総当たりと不変条件(test_logic_fuzz.py)も併せて回す
     - 山さがしの日和スコア(gen_find.py の score)も見る。減点方式なので「材料が無い」が
       「100点=ランクA」に化ける構造で、実際に3回同型の事故を起こしている
     - 天気の文言・濡れ注意・雨雪判別・積雪表記は logic.js に一本化されておらず
       CLI と index.html に2重に書かれているため、test_display.py で突き合わせる
     - 一致だけを見ると「両方とも同じように間違っている」を見逃すので、天気コードは
       test_weather_codes.py で全28コードの性質(悪天の昇格・取り違え・窓)も見る
     - JS 側は Node が必要。無い環境ではスキップし「未検証」と明示する
  5. 圏外・障害時のふるまい (scripts/test_offline.js・scripts/test_sw.js)
     - 通信が返ってこない・失敗する・localStorage が使えない・Service Worker が
       古い画面や古い予報を出す、といった「山でいちばん困る壊れ方」を身代わりの
       環境で注入して確かめる。時間は仮想時計に差し替えるので数秒で終わる
     - この層の壊れ方はオンラインでは表面化しないものが多く、実機では気づけない
     - Node が要る。無い環境ではスキップし「未検証」と明示する
  6. 定数の同期とドキュメントの整合性 (scripts/check_consistency.py)
     - JMA_DAYS・FIND_DAYS・AUTH_VER の ?v=・日本域の範囲・sw.js の CACHE 版など、
       2箇所以上に同じ値を書いている場所を突き合わせる
     - 実装から消えたはずの説明(旧・体感温度の式など)がドキュメントに残っていないか
  7. Open-Meteo Elevation API による標高の照合
     - 座標が山頂から外れていると、その地点のDEM標高がCSVの山頂標高より
       大幅に低くなることを利用して座標ミスを検出する
     - DEMはCopernicus GLO-90 (90m格子) のため、尖った岩峰(槍ヶ岳・剱岳・権現岳等)は
       実際の山頂標高より数十m低く出る。差が中程度なら「要確認」に留める

ここに入っていない検査:
  scripts/test_api_contract.py --online
    Open-Meteo が「いま何を返しているか」を非null件数で数え、既知の前提
    (完全なGSM日には 900/800hPa と日照が無い等)が崩れていないかを見る。
    通信を伴うので毎回は回さない。モデルの配信仕様が変わった疑いがあるときに手で流す。

使い方:
  python scripts/check_mountains.py
  python scripts/check_mountains.py --offline    # 通信を伴う DEM 照合を飛ばす (CI 用)
  python scripts/check_mountains.py --mutation   # テスト自体が効いているかも確かめる
                                                 # (判定・テストを触ったときに付ける。12秒ほど)

終了コード: 0=問題なし / 1=要修正(形式エラー・同期ずれ・座標ミスの疑い)あり
"""
import csv
import json
import re
import subprocess
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
CRLF_INDENT = "\n      "   # 複数行のエラー出力をぶら下げるためのインデント
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


def check_generated():
    """自動生成ページが生成元と一致しているか(生成物の直接編集を検出する)

    生成物を手で直すと再生成で消える。差分が出たら「生成元(scripts/gen_*.py)に
    修正を入れ直してから再生成する」のが正しい直し方。
    """
    import gen_find
    import gen_mountain_list
    errors = []
    for mod, path in ((gen_find, ROOT / "docs" / "find.html"),
                      (gen_mountain_list, ROOT / "docs" / "mountains.html")):
        expected = mod.build_html()
        actual = path.read_text(encoding="utf-8")
        if expected != actual:
            errors.append(
                f"{path.relative_to(ROOT).as_posix()} が {Path(mod.__file__).name} の出力と一致しません"
                f" (生成元を直して python scripts/{Path(mod.__file__).name} を実行してください)")
    return errors


def check_logic():
    """判定ロジックが CLI と Web で一致するか
    (scripts/test_logic.py / test_logic.js / test_logic_fuzz.py)

    ロジックの二重実装は「片方だけ直して気づかない」で壊れる。ここを通ることが、
    CLI・logic.js・references/criteria.md を揃えて直したことの証拠になる。

    入出力表(logic_cases.json)は人が選んだ代表値なので、書いた人が思いつかなかった
    組み合わせは入らない。実際に「山頂雲量が欠測でも雲海を名乗る」バグは表を素通りした。
    そこで乱数総当たりと不変条件(test_logic_fuzz.py)も併せて回す。
    """
    errors, notes = [], []
    py = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'test_logic.py')],
                        capture_output=True, text=True, encoding='utf-8')
    if py.returncode:
        errors.append('CLI側(test_logic.py)が不一致:' + CRLF_INDENT
                      + (py.stdout or py.stderr).strip().replace('\n', CRLF_INDENT))
    try:
        js = subprocess.run(['node', str(ROOT / 'scripts' / 'test_logic.js')],
                            capture_output=True, text=True, encoding='utf-8')
    except (FileNotFoundError, OSError):
        # Node はこのチェックのためだけの依存。無くても CLI 本体は動くので落とさない
        notes.append('Node が無いため JS 側(logic.js)は未検証です'
                     ' (node scripts/test_logic.js を実行できる環境で確認してください)')
        js = None
    if js is not None and js.returncode:
        errors.append('Web側(test_logic.js)が不一致:' + CRLF_INDENT
                      + (js.stdout or js.stderr).strip().replace('\n', CRLF_INDENT))

    # 乱数総当たり + 不変条件。node が無ければ fuzz 側が等価性の比較だけを自動で飛ばす
    fz = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'test_logic_fuzz.py')],
                        capture_output=True, text=True, encoding='utf-8')
    if fz.returncode:
        errors.append('乱数総当たり/不変条件(test_logic_fuzz.py)で違反:' + CRLF_INDENT
                      + (fz.stdout or fz.stderr).strip().replace('\n', CRLF_INDENT))

    # 表示まわり(天気の文言・濡れ注意・雨雪判別・積雪表記)。判定と違って一本化されておらず、
    # CLI と index.html に同じものが2重に書かれているので、ここで突き合わせる。
    # node が無ければ test_display.py 側が未検証として自分で飛ばす
    dp = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'test_display.py')],
                        capture_output=True, text=True, encoding='utf-8')
    if dp.returncode:
        errors.append('表示まわり(test_display.py)が CLI と Web で不一致:' + CRLF_INDENT
                      + (dp.stdout or dp.stderr).strip().replace('\n', CRLF_INDENT))

    # 天気コード → 日本語表現の総当たり。一致だけを見ていると「両方とも同じように
    # 間違っている」を見逃すので、表現そのものが満たすべき性質を全コードで確かめる
    wc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'test_weather_codes.py')],
                        capture_output=True, text=True, encoding='utf-8')
    if wc.returncode:
        errors.append('天気コードの日本語表現(test_weather_codes.py)で違反:' + CRLF_INDENT
                      + (wc.stdout or wc.stderr).strip().replace(chr(10), CRLF_INDENT))

    # 山さがしの日和スコア。減点方式なので「材料が無い→100点=ランクA」に化ける構造で、
    # 実際に3回同型の事故を起こしている。生成物ではなく生成元(gen_find.py)を見る
    fs = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'test_find_score.py')],
                        capture_output=True, text=True, encoding='utf-8')
    if fs.returncode:
        errors.append('山さがしのスコア(test_find_score.py)で違反:' + CRLF_INDENT
                      + (fs.stdout or fs.stderr).strip().replace('\n', CRLF_INDENT))
    return errors, notes


def check_syntax():
    """構文と公開物の静的検査 (scripts/check_syntax.py)

    これまで `node --check` と `py_compile` を都度手打ちしていたもの。
    構文が壊れていれば以下の検査結果は当てにならないので、最初に見る。
    """
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'check_syntax.py')],
                       capture_output=True, text=True, encoding='utf-8')
    if not r.returncode:
        return []
    # 個々の食い違いは check_syntax.py 側が ✕ 付きで出しているので、その行だけ拾う
    lines = [x.strip()[1:].strip() for x in (r.stdout or '').splitlines()
             if x.strip().startswith('✕')]
    return lines or [(r.stdout or r.stderr).strip()]


def check_external():
    """外部参照の棚卸し (scripts/check_csp.py)

    このアプリが通信する相手は「気象データ・地名・アクセス解析」の3系統だけで、
    増えることは通常ありえない。知らないホストが混ざったら、それ自体が異常
    (貼り付けたコードに広告タグが付いてきた等)。
    """
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'check_csp.py')],
                       capture_output=True, text=True, encoding='utf-8')
    if not r.returncode:
        return []
    return [x.strip()[1:].strip() for x in (r.stdout or '').splitlines()
            if x.strip().startswith('✕')] or [(r.stdout or r.stderr).strip()]


def check_offline():
    """圏外・障害時のふるまい (scripts/test_offline.js・scripts/test_sw.js)

    通信のタイムアウト・再試行・端末内保存・Service Worker。DEVLOG で最も重い事故が
    出ている領域で、しかも **オンラインでは表面化しない** 壊れ方が多い
    (API 応答を SW に入れると「古い予報を、いま取れた予報として」正常に見える画面で描く)。

    アプリ本体は書き換えず、DOM に触らない範囲を目印で切り出して身代わりの環境で回す。
    """
    errors, notes = [], []
    for label, script in (("通信・保存・ゲート", "test_offline.js"),
                          ("Service Worker", "test_sw.js")):
        try:
            r = subprocess.run(['node', str(ROOT / 'scripts' / script)],
                               capture_output=True, text=True, encoding='utf-8')
        except (FileNotFoundError, OSError):
            notes.append(f'Node が無いため{label}({script})は未検証です')
            continue
        if r.returncode:
            errors.append(f'{label}({script})で違反:' + CRLF_INDENT
                          + (r.stdout or r.stderr).strip().replace(chr(10), CRLF_INDENT))
    return errors, notes


def check_mutation():
    """テスト自体が効いているか (scripts/test_mutation.py)

    わざとバグを仕込んで「テストが落ちること」を確かめる。落ちない変異があれば、
    その範囲についてテストは書いていないのと同じ。12秒ほどかかるうえ、判定や
    テストを触っていなければ結果が変わらないので、--mutation を付けた時だけ回す。
    """
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'test_mutation.py')],
                       capture_output=True, text=True, encoding='utf-8')
    if not r.returncode:
        return []
    return ['仕込んだバグを検出できないテストがあります:' + CRLF_INDENT
            + (r.stdout or r.stderr).strip().replace('\n', CRLF_INDENT)]


def check_consistency():
    """定数の同期とドキュメントの整合性 (scripts/check_consistency.py)

    「2箇所以上に同じ値を書く」場所を機械で突き合わせる。ここが守れずに
    AUTH_VER と ?v= がずれ、新しい認証コードを渡された利用者が弾かれた前例がある。
    外部通信を伴わないので毎回回す。
    """
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'check_consistency.py')],
                       capture_output=True, text=True, encoding='utf-8')
    if not r.returncode:
        return []
    body = (r.stdout or r.stderr).strip()
    # 個々の食い違いは check_consistency.py 側が ✕ 付きで出しているので、その行だけ拾う
    return [ln.strip()[2:] for ln in body.splitlines() if ln.strip().startswith("✕")] \
        or [body.replace('\n', CRLF_INDENT)]


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
    want_mutation = "--mutation" in sys.argv
    # 通信を伴うのは DEM 照合だけ。CI ではここを飛ばす(無料枠を無駄撃ちしない)
    offline = "--offline" in sys.argv
    rows = load_rows()
    print(f"山岳DBチェック: {len(rows)}座 ({MOUNTAINS_CSV.name})")
    ng = False

    syn = check_syntax() + check_external()
    print(f"\n[1/8] 構文・公開物・外部参照: {'OK' if not syn else f'{len(syn)}件のエラー'}")
    for e in syn:
        print(f"  ✕ {e}")
    ng = ng or bool(syn)

    fmt = check_format(rows)
    print(f"[2/8] CSV形式: {'OK' if not fmt else f'{len(fmt)}件のエラー'}")
    for e in fmt:
        print(f"  ✕ {e}")
    ng = ng or bool(fmt)

    sync = check_sync(rows)
    print(f"[3/8] index.html との同期: {'OK' if not sync else f'{len(sync)}件のずれ'}")
    for e in sync:
        print(f"  ✕ {e}")
    ng = ng or bool(sync)

    gen = check_generated()
    print(f"[4/8] 自動生成ページの同期: {'OK' if not gen else f'{len(gen)}件のずれ'}")
    for e in gen:
        print(f"  ✕ {e}")
    ng = ng or bool(gen)

    logic, logic_notes = check_logic()
    print(f"[5/8] 判定・表示・山さがしのスコア (入出力表・乱数・不変条件・表示・天気コード・find): "
          f"{'OK' if not logic else f'{len(logic)}件の不一致'}")
    for e in logic:
        print(f"  ✕ {e}")
    for e in logic_notes:
        print(f"  ⚠ {e}")
    ng = ng or bool(logic)

    if want_mutation:
        mut = check_mutation()
        print(f"[+] テストの有効性 (ミューテーション): "
              f"{'OK' if not mut else '検出できない変異あり'}")
        for e in mut:
            print(f"  ✕ {e}")
        ng = ng or bool(mut)

    off, off_notes = check_offline()
    print(f"[6/8] 圏外・障害時のふるまい (通信・保存・Service Worker): "
          f"{'OK' if not off else f'{len(off)}件の違反'}")
    for e in off:
        print(f"  ✕ {e}")
    for e in off_notes:
        print(f"  ⚠ {e}")
    ng = ng or bool(off)

    cons = check_consistency()
    print(f"[7/8] 定数同期とドキュメントの整合性: "
          f"{'OK' if not cons else f'{len(cons)}件の食い違い'}")
    for e in cons:
        print(f"  ✕ {e}")
    ng = ng or bool(cons)

    if offline:
        suspects, warns = [], []
        print("[8/8] DEM標高照合: スキップ (--offline。通信を伴うのはここだけ)")
    else:
        suspects, warns = check_elevation(rows)
        print(f"[8/8] DEM標高照合 (Open-Meteo Elevation API): "
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
