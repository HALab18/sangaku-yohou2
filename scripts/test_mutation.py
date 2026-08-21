#!/usr/bin/env python3
"""テストが本当に効いているかを確かめるミューテーションテスト。

判定ロジックにわざとバグを仕込み、**テストが落ちること**を確認する。落ちない変異が
1つでもあれば、その種類のバグは今のテストでは検出できない ── つまりその範囲について
テストは「書いていないのと同じ」。

このリポジトリでは ver 2.30β に手作業で1回だけ実施した記録が DEVLOG にあるが、
スクリプトが残っておらず再実行できなかった。テスト側が劣化したときに気づける唯一の
仕掛けなので、繰り返し回せる形にしてある。

    python scripts/test_mutation.py            # 全変異
    python scripts/test_mutation.py --list     # 変異の一覧だけ見る
    python scripts/test_mutation.py --only 3   # 3番だけ試す

原本は絶対に書き換えない。一時ディレクトリへ複製し、そこへパッチを当てて実行する。

変異ごとに「どの層が捕まえたか」も出す。
  表     … references/logic_cases.json の入出力表 (test_logic.py / test_logic.js)
  乱数   … 乱数総当たり + 不変条件 (test_logic_fuzz.py)
  表示   … CLI と Web の表示関数の突き合わせ (test_display.py)
  山さがし … 日和スコアの性質 (test_find_score.py)
  障害   … 通信・保存・ゲートの異常系 (test_offline.js)
  SW     … Service Worker (test_sw.js)
両方が捕まえるなら表だけでも足りているし、片方しか捕まえない変異があるなら
その層が実際に守備範囲を広げているということになる。

依存は標準ライブラリのみ。
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 変異の説明や判定記号(⚠ ◎ ✕ など)は cp932 のコンソールに出せない。そこで落ちる代わりに
# 置き換えて出す。ここで例外になると、検査そのものは終わっているのに結果が読めなくなる。
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# 複製する対象。判定と、その検証に要るものだけ(DEVLOG や画像は写さない)。
COPY = [
    "logic.js",
    "index.html",
    "scripts/mountain_weather.py",
    "scripts/test_logic.py",
    "scripts/test_logic.js",
    "scripts/test_logic_fuzz.py",
    "scripts/test_logic_fuzz.js",
    "scripts/test_display.py",
    "scripts/test_display.js",
    "scripts/test_find_score.py",
    "scripts/test_find_score.js",
    "scripts/gen_find.py",
    "references/logic_cases.json",
    "docs/find.html",
    "sw.js",
    "gate.js",
    "scripts/test_stubs.js",
    "scripts/test_offline.js",
    "scripts/test_sw.js",
]

LOGIC = "logic.js"
CLI = "scripts/mountain_weather.py"
INDEX = "index.html"
FIND = "scripts/gen_find.py"
SW = "sw.js"
GATE = "gate.js"

# (説明, 対象ファイル, 置換前, 置換後)
# 置換前は「その時点のコードに1回だけ出てくる文字列」であること。
# 見つからなくなったらコードが動いた合図なので、変異が当たらないことを NG として報告する。
MUTATIONS = [
    ("夏山の風しきい値を 10 → 11 にずらす",
     LOGIC, 'wind:[10,15]', 'wind:[11,15]'),
    ("冬山の風しきい値を 8 → 9 にずらす",
     LOGIC, 'wind:[8,12]', 'wind:[9,12]'),
    ("CLI 側の夏山の風しきい値を 10 → 11 にずらす",
     CLI, '"wind": (10, 15)', '"wind": (11, 15)'),
    ("CLI 側の降水しきい値を 5 → 6 にずらす(夏山)",
     CLI, '"precip": (1, 5)', '"precip": (1, 6)'),
    ("欠測ガードを外す(風・降水が両方欠測でも A を返す)",
     LOGIC, 'if(ws==null&&pr3==null)return[null,""];', 'if(false)return[null,""];'),
    ("CLI 側の欠測ガードを外す",
     CLI, "if ridge_ws is None and precip_3h is None:\n        return None, \"\"",
     "if False:\n        return None, \"\""),
    ("D1 湿潤低体温の降格を無効化する",
     LOGIC, 'if(tempMin!=null&&pr3!=null&&ws!=null&&', 'if(false&&tempMin!=null&&pr3!=null&&ws!=null&&'),
    ("D2 体感温度の降格を無効化する",
     LOGIC, 'if(feels!=null){\n    if(feels<=FEELS_C)', 'if(false){\n    if(feels<=FEELS_C)'),
    ("D4 視界不良の降格を無効化する",
     LOGIC, 'if(visMin!=null&&ws!=null&&visMin<VIS_LOW', 'if(false&&visMin!=null&&ws!=null&&visMin<VIS_LOW'),
    ("降格の判定を厳密比較から同着でも上書きに変える",
     LOGIC, 'if(RANK[dem[i][0]]>RANK[idx])', 'if(RANK[dem[i][0]]>=RANK[idx])'),
    ("sumOrNull を sum(v||0) に戻す(0mm と欠測が区別できなくなる)",
     LOGIC, 'return vs.length?vs.reduce(function(a,b){return a+b},0):null;',
     'return vals.reduce(function(a,b){return a+(b||0)},0);'),
    ("CLI 側の sum_or_none を sum(v or 0) に戻す",
     CLI, 'return sum(vs) if vs else None', 'return sum(v or 0 for v in vals)'),
    ("体感温度の風の符号を反転する(風が吹くと暖かくなる)",
     LOGIC, '-0.70*ws', '+0.70*ws'),
    ("CIN(蓋)を段階を上げる向きに使う",
     LOGIC, 'if(a>=100)lv-=2;else if(a>=50)lv-=1;', 'if(a>=100)lv+=2;else if(a>=50)lv+=1;'),
    ("確度の欠測を「揃っている(◎)」に倒す",
     LOGIC, 'if(idxList[i]==null||RANK[idxList[i]]==null)return null;',
     'if(idxList[i]==null||RANK[idxList[i]]==null)return AGREE_HIGH;'),
    ("⚠夕方で「降水が欠測なら警告を出さない」に倒す",
     LOGIC, '(precipEve==null||precipEve>=EVE_THUNDER_PRECIP)',
     '(precipEve!=null&&precipEve>=EVE_THUNDER_PRECIP)'),
    ("眺望の「良い方には材料が要る」ガードを外す",
     LOGIC, 'if(summit==null&&vis==null)return null;', 'if(false)return null;'),
    ("眺望の雲海判定から summit の欠測チェックを外す",
     LOGIC, 'var unkai=below!=null&&below>=60&&summit!=null&&summit<=30;',
     'var unkai=below!=null&&below>=60&&(summit==null||summit<=30);'),
    ("interpWind で面が1つも無いときに 0 を返す",
     LOGIC, 'if(!pts.length)return null;', 'if(!pts.length)return 0;'),
    ("季節判定の冬倒しを無効化する(夏の月は必ず夏山)",
     LOGIC, 'if(!winter&&((tmax!=null&&tmax<WINTER_TMAX)', 'if(false&&((tmax!=null&&tmax<WINTER_TMAX)'),
    ("PW_LOGIC_VER だけを古い版に戻す(キャッシュに旧判定が残る形)",
     LOGIC, 'var PW_LOGIC_VER = "', 'var PW_LOGIC_VER = "0'),
    ("index.html に blockIndex を再定義する(logic.js の実装が上書きされる)",
     INDEX, '<script src="logic.js?v=', '<script>function blockIndex(){return["A",""]}</script>\n<script src="logic.js?v='),
    # ---- 表示まわり。CLI と Web に同じものが2重に書かれている範囲 ----
    ("Web 側の「濡れ注意」の気温を境界ちょうどで外す",
     INDEX, 'return temp<=WET_WARN_TEMP&&', 'return temp<WET_WARN_TEMP&&'),
    ("CLI 側の「濡れ注意」の気温しきい値を 15 → 14 にずらす",
     CLI, 'WET_WARN_TEMP_C = 15', 'WET_WARN_TEMP_C = 14'),
    ("Web 側の雨雪判別の margin を 100 → 200 にずらす",
     INDEX, 'if(fl<elev-100)return"雪";', 'if(fl<elev-200)return"雪";'),
    ("CLI 側の天気を集約する時間帯窓をずらす",
     CLI, "WX_WINDOW = (4, 17)", "WX_WINDOW = (4, 16)"),
    ("Web 側の安全オーバーライドから雷を外す(悪天が日代表に昇格しなくなる)",
     INDEX, 'const SAFETY_OVERRIDE=new Set([65,66,67,75,82,85,86,95,96,99]);',
     'const SAFETY_OVERRIDE=new Set([65,66,67,75,82,85,86]);'),
    # ---- 山さがしのスコア。減点方式なので「材料が無い→100点=ランクA」に化ける ----
    ("find の欠測ガードを sunJma から sunFrac に戻す(補完日照でガードをすり抜ける)",
     FIND, 'if(sunJma==null&&code==null', 'if(sunFrac==null&&code==null'),
    ("find の稜線風で気圧面0面のときに地上10m風を返す",
     FIND, 'if(!lv)return null;', 'if(false)return null;'),
    ("find のスコアに降水確率を足す(表示専用のはずの pprob を減点式に入れる)",
     FIND, 'if(psum!=null){dPre=Math.min(psum,10)/10*30;s-=dPre}',
     'if(psum!=null){dPre=Math.min(psum,10)/10*30;s-=dPre}if(pprob!=null)s-=pprob/20;'),
    ("find の日照から「窓9時間そろっている時だけ」の条件を外す",
     FIND, 'return (n!=null&&n>=WIN_HOURS)?agg(key,"sum"):null;', 'return agg(key,"sum");'),
    ("find の冬の風スパンを夏と同じに戻す(冬12m/s が甘く採点される)",
     FIND, 'var w0=winter?4:6, wSpan=winter?8:12;', 'var w0=6, wSpan=12;'),
    ("find のランク境界を 70 → 71 にずらす",
     FIND, 'function rankOf(v){return v>=70?"a":v>=45?"b":"c"}',
     'function rankOf(v){return v>=71?"a":v>=45?"b":"c"}'),
    # ---- 通信の異常系。山で最も困る「画面が固まる」型 ----
    ("主要データのタイムアウトを効かなくする(応答が返らないと永久に待つ)",
     INDEX, 'const timer=setTimeout(()=>ac.abort(),API_TIMEOUT_MS);',
     'const timer=setTimeout(()=>{},API_TIMEOUT_MS);'),
    ("発表時刻の取得の上限を主要データと同じにする(2.28β の固まる事故)",
     INDEX, 'const META_TIMEOUT_MS=5000;', 'const META_TIMEOUT_MS=20000;'),
    ("発表時刻の取得の失敗を握らずに投げる(補助表示が予報全体を巻き添えにする)",
     INDEX, '}catch(e){return null}\n  finally{clearTimeout(timer)}',
     '}catch(e){throw e}\n  finally{clearTimeout(timer)}'),
    ("429 の待ちを他のエラーと同じ長さに戻す(無料枠を守れなくなる)",
     INDEX, '(e.status===429?6000:1500)*a', '1500*a'),
    ("投げ直しても直らない 4xx も再試行する",
     INDEX, 'if(r.status!==429&&r.status<500)', 'if(false)'),
    ("end_date のクランプ再試行を無効化する",
     INDEX, 'params={...params,end_date:m[1]};clamped=true;a--;continue;',
     'params={...params};clamped=true;a--;continue;'),
    ("補完APIの貼り合わせを添字一致に戻す(2本のAPIで期間がずれると全部ずれる)",
     INDEX, 'base[k]=base.time.map(t=>pos.has(t)&&pos.get(t)<src.length?src[pos.get(t)]:null);',
     'base[k]=base.time.map((t,i)=>i<src.length?src[i]:null);'),
    ("キーごと欠けた項目の欠測正規化を外す(生の TypeError になる)",
     INDEX, 'if(!Array.isArray(data.hourly[k]))data.hourly[k]=new Array(n).fill(null);',
     'if(false)data.hourly[k]=new Array(n).fill(null);'),
    # ---- 端末内保存。汚染データと quota ----
    ("スナップショット索引の「未来の保存時刻」の検査を外す",
     INDEX, '&&typeof x.p==="string"&&typeof x.t==="number"&&x.t<=now',
     '&&typeof x.p==="string"&&typeof x.t==="number"'),
    ("期限切れスナップショットの本体を消さない(領域を食い続ける)",
     INDEX, 'ok.filter(x=>x.l<today).forEach(x=>snapDrop(snapBodyKey(x.id)));', ''),
    ("保存に失敗したときの残骸を消さない(圏外で開くと空の表になる)",
     INDEX, 'snapDrop(snapBodyKey(id)); // 半端な残骸を索引に載せない', ''),
    ("固定を「切ってから先頭へ移す」順に戻す(押しても何も起きないように見える)",
     INDEX, 'const x=a[i];x.keep=true;a.splice(i,1);a.unshift(x);', 'const x=a[i];x.keep=true;'),
    ("ゲートからローカルファイル直開きの検査を外す(fail-closed が崩れる)",
     GATE, 'return !pwIsLocalFile() && pwIsAgreed() && pwIsAuthed()',
     'return pwIsAgreed() && pwIsAuthed()'),
    # ---- Service Worker。オンラインでは表面化しない壊れ方 ----
    ("SW が別オリジンにも手を出す(API 応答をキャッシュしてしまう)",
     SW, 'if (new URL(req.url).origin !== self.location.origin) return;', ''),
    ("SW がキャッシュのキーからフラグメントを落とさない",
     SW, 'const key = req.url.split("#")[0];', 'const key = req.url;'),
    ("SW の先読みを addAll に戻す(1つの404で全体が失敗する)",
     SW, 'Promise.all(SHELL.map(u => c.add(u).catch(() => {})))', 'c.addAll(SHELL)'),
    ("SW の activate から前版キャッシュの掃除を外す",
     SW, 'ks.filter(k => k !== CACHE)', 'ks.filter(k => false)'),
    ("SW が失敗した応答もキャッシュする(壊れた応答を後で返すことになる)",
     SW, 'if (r && r.ok && r.type === "basic")', 'if (r)'),
    ("SW をキャッシュ優先に変える(push した修正が端末に届かなくなる)",
     SW, '  return Promise.race([', '  return cached;\n  return Promise.race(['),
]


def prepare(dst):
    """判定と検証に要るファイルだけを一時ディレクトリへ複製する。"""
    for rel in COPY:
        src = ROOT / rel
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)


def run(cmd, cwd):
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return None          # 実行系が無い(node 未導入など)
    return r.returncode


def check_layers(work, have_node):
    """変異を当てた作業ツリーでテストを回し、落ちた層の名前を返す。"""
    caught = []
    py = sys.executable or "python"
    if run([py, "scripts/test_logic.py"], work) not in (0, None):
        caught.append("表")
    if have_node and run(["node", "scripts/test_logic.js"], work) not in (0, None):
        if "表" not in caught:
            caught.append("表")
    if run([py, "scripts/test_logic_fuzz.py", "--n", "400"], work) not in (0, None):
        caught.append("乱数")
    if have_node and run([py, "scripts/test_display.py", "--n", "300"], work) not in (0, None):
        caught.append("表示")
    if have_node and run([py, "scripts/test_find_score.py"], work) not in (0, None):
        caught.append("山さがし")
    if have_node and run(["node", "scripts/test_offline.js"], work) not in (0, None):
        caught.append("障害")
    if have_node and run(["node", "scripts/test_sw.js"], work) not in (0, None):
        caught.append("SW")
    return caught


def main():
    ap = argparse.ArgumentParser(description="テストが本当に効いているかを確かめる")
    ap.add_argument("--list", action="store_true", help="変異の一覧を出して終わる")
    ap.add_argument("--only", type=int, help="番号を指定して1件だけ試す")
    a = ap.parse_args()

    if a.list:
        for i, (desc, rel, _, _) in enumerate(MUTATIONS, 1):
            print("{:2d}. [{}] {}".format(i, rel, desc))
        return 0

    targets = list(enumerate(MUTATIONS, 1))
    if a.only:
        targets = [t for t in targets if t[0] == a.only]
        if not targets:
            raise SystemExit("--only {} は範囲外です(1〜{})".format(a.only, len(MUTATIONS)))

    have_node = shutil.which("node") is not None
    if not have_node:
        print("⚠ node が見つかりません。logic.js 側の変異は Python との等価性でのみ検出されます")

    survived, stale = [], []
    print("ミューテーションテスト: {} 件".format(len(targets)))
    for num, (desc, rel, old, new) in targets:
        with tempfile.TemporaryDirectory() as d:
            work = pathlib.Path(d)
            prepare(work)
            target = work / rel
            src = target.read_text(encoding="utf-8")
            hits = src.count(old)
            if hits != 1:
                # 置換前の文字列がコードから消えた/増えた = 変異が当たらない。
                # 「当たっていないのにテストが通った」を成功と数えると、この仕掛け自体が嘘になる。
                stale.append("{:2d}. {} … 置換対象が {} 箇所 ({} 内)".format(num, desc, hits, rel))
                print("  ?? {:2d}. {} [変異が当たりません]".format(num, desc))
                continue
            target.write_text(src.replace(old, new), encoding="utf-8")
            caught = check_layers(work, have_node)
        if caught:
            print("  OK {:2d}. {} … {} が検出".format(num, desc, "・".join(caught)))
        else:
            print("  NG {:2d}. {} … どのテストも素通り".format(num, desc))
            survived.append("{:2d}. {} ({})".format(num, desc, rel))

    print()
    if stale:
        print("変異が当たらなかったもの {} 件(コードが動いた可能性があります):".format(len(stale)))
        for s in stale:
            print("  " + s)
    if survived:
        print("生き残った変異 {} 件 ── この種類のバグは今のテストでは捕まりません:".format(len(survived)))
        for s in survived:
            print("  " + s)
    else:
        print("生き残った変異はありません(仕込んだバグは全て検出されました)")
    return 1 if (survived or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
