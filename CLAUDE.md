# CLAUDE.md — PeakWeather v2 (sangaku-yohou2)

山名を入れると山頂・稜線の気象予報を表にして返すツール。CLI版とWebアプリ版が
**同じ判定ロジック**を持つ（CLIはPython、Webは同ロジックをJSに移植）。

> **まず [DEVLOG.md](DEVLOG.md) の先頭「▶ 次の再開ポイント」を読む。** そこに今の状態と
> 次にやることが書いてある。作業の区切りごとに DEVLOG 先頭へセッション記録を追記する。

## セットアップ（どのPCでも最初にこれだけ）

```bash
git clone https://github.com/HALab18/sangaku-yohou2.git
cd sangaku-yohou2
python scripts/mountain_weather.py --name 富士山   # 動作確認(依存ゼロ・すぐ動く)
```

- **CLI本体・Webアプリは Python 3.8+ 標準ライブラリのみ**。追加インストール不要（これは売り。壊さない）。
- **DB拡張・アイコン再生成をするときだけ** 追加依存が要る: `pip install -r requirements-dev.txt`
  （openpyxl=xlsx読み込み / Pillow=アイコン描画）
- APIキー・アカウント登録は一切不要（Open-Meteo と 国土地理院 の公開APIを叩くのみ）。

## 全体構成

| パス | 役割 |
|---|---|
| `index.html` | Webアプリ本体（CSS/JS内包。CLIと同じ判定ロジックをJSで実装。ゲートのみ `gate.js` に外出し） |
| `gate.js` | 規約同意＋認証コードの共通ゲート。**認証定数(AUTH_VER/SALT/HASH)はここが唯一の置き場**。`index.html`・`docs/find.html`・`docs/point.html` が読み込む |
| `scripts/mountain_weather.py` | CLI本体。`--name`/`--lat --lon --elev` で予報を出力（`--html`でレポート保存） |
| `references/mountains.csv` | 内蔵山岳DB（**BOM付きUTF-8・CRLF**）。列: name,yomi,pref,lat,lon,elev |
| `references/criteria.md` | 登山指数A/B/Cの判定基準（閾値の根拠） |
| `docs/` | GitHub Pages公開物。`mountains.html`(対応山リスト・自動生成)・`how-it-works*.html`・`terms.html` |
| `icons/` `manifest.json` | PWAアイコンとマニフェスト |
| `skill/SKILL.md` | Claude Code スキル定義（「◯◯岳の予報を調べて」で自動実行） |
| `skill/auth-renew/SKILL.md` | 認証コード更新スキル（「認証コードを更新して」で年次ローテーションを自動実行） |
| `scripts/db_*.py gen_*.py check_*.py` | DB保守ツール群（下記パイプライン） |

**公開URL**: https://halab18.github.io/sangaku-yohou2/

## 気象データの取得元

基本は Open-Meteo の**気象庁モデル** `/v1/jma`（0〜4日目=MSM 約5km / 5〜11日目=GSM。自動切替）。
**予報期間は11日**（`JMA_DAYS`。CLI・index.html の両方に定数を置いて揃える）。

- 気象庁モデルに**無い**項目 = `precipitation_probability` / `wind_gusts_10m` / `cape` /
  `convective_inhibition` / `visibility` / `snow_depth`。これらだけ `/v1/forecast` から補完し、
  **時刻をキーにして**貼り合わせる（`_merge_series` / `mergeSeries`）。添字一致は前提にしない
  （2本のAPIで `end_date` のクランプ結果が食い違いうるため）。
- **要注意**: 存在しない項目を `/v1/jma` に投げても **400 にはならず全て null で返る**。
  「エラーが出ないから取れている」と誤解しやすい。期間も同様で、11日を超えて要求しても
  エラーにならず黙って null が並ぶ。**日数はコード側で必ず制限する**。
- 11日目は昼過ぎでモデルが切れ daily 集計値が null になるため、hourly から作り直して表を埋める。
- `docs/find.html`（山さがし）も気象庁モデルだが、**対象は3日間**。スコア主要素の
  `sunshine_duration` が MSM 期間ぶんしか来ず、4日目以降は 7:00〜15:59 が丸ごと欠測になるため。
  find も降水確率だけ `/v1/forecast` から補完するが、**表示専用でスコアには入れない**
  （`score()` の `pprob`）。減点式を触るときは `s-=` の行に `pprob` を足さないこと。
  `sc` の中身を変えたら `cacheKey` / `LAST_KEY` の `findN:` を必ず上げる。
- モデル比較表（`compare_models`）は別目的の機能なので `/v1/forecast?models=` のまま。

## 厳守する規約

1. **既存の山名(mountains.csv の name)は絶対に変えない。** 検索結果URL（`#燕岳/2026-07-19`）が
   name に依存しており、改名すると共有済みリンクが壊れる。同名別峰を足すときは
   **新規側だけ**「山名(県名)」等の区別名にする。
2. **mountains.csv は BOM付きUTF-8・CRLF を維持。** Excelでの文字化け防止。`check_mountains.py` が形式を検証する。
3. **CLIとWebの判定ロジックは同一に保つ。** 片方だけ閾値やロジックを変えない。基準変更は
   `references/criteria.md`・CLI・index.html・図解ページを揃える。
4. **CLI本体に第三者パッケージを足さない**（依存ゼロを維持）。保守スクリプト側はOK。
5. **座標変更・DB編集をしたら必ず `python scripts/check_mountains.py` を通す**
   （形式・CLI/Web同期・自動生成ページの同期・DEM照合）。
6. **`docs/find.html` と `docs/mountains.html` は自動生成物。直接編集しない。**
   修正は `scripts/gen_find.py` / `scripts/gen_mountain_list.py` に入れて再生成する。
   生成物だけ直すと次の再生成で消える（実際に find.html の z-index 修正がこれで失われた）。
   `check_mountains.py` の「[3/4] 自動生成ページの同期」がこのずれを検出する。
7. **認証コードの定数は `gate.js` にのみ置く。** index.html や各ページに複製しない
   （複製すると年次更新の漏れで「認証済みなのに弾かれる」事故になる）。
   新しく操作系ページを足すときは `<script src="…/gate.js">` を読み、
   本体スクリプトの先頭で `if(!pwGuardPage())return;` を入れること。

## 山岳DB拡張パイプライン

xlsx の山リストを内蔵DBに取り込む定番手順（詳細と過去の実績は DEVLOG 参照）:

```bash
pip install -r requirements-dev.txt   # 初回のみ
# 1. 既存DBと照合して候補CSVを作る
python scripts/db_reconcile.py --xlsx references/tenki_mountain_list.xlsx --out candidates.csv
# 2. candidates.csv を手で判定: bucket=review 行の decision に DUP/NEW、同名別峰は final_name に区別名
# 3. yamareco/国土地理院から座標・標高・県を取得(status=manual は別表記やGSI地名検索で解決)
python scripts/db_fetch_coords.py --candidates candidates.csv --out enriched.csv --cache fetch_cache.json
# 4. dry-run で2km近接を確認 → 別峰と確認できたら --allow-near "山名A/山名B" を付けて本実行
python scripts/db_merge.py --enriched enriched.csv --dry-run
# 5. 検証 & 対応山リスト(docs/mountains.html)を再生成
python scripts/check_mountains.py && python scripts/gen_mountain_list.py
# 6. 座数の表記を更新: README.md / docs/how-it-works.html / docs/how-it-works-web.html / skill/SKILL.md
```

作業中の中間ファイル（candidates.csv, enriched.csv, fetch_cache.json）はコミットしない。

## PWAアイコンの再生成

ヒーローのロゴマーク（index.html の `.logomark` SVG）を変えたら:
```bash
pip install -r requirements-dev.txt   # 初回のみ
python scripts/gen_icons.py           # icons/ の4サイズを再生成
```
iOSのホーム画面アイコンはキャッシュが強い。更新時は端末で削除→再追加が必要。

## ローカル確認

Webアプリはブラウザで直接開けるが、`docs/mountains.html` 等の相対リンクや
サジェストを含めて確認するなら簡易サーバ経由が確実:
```bash
python -m http.server 8000     # → http://localhost:8000/index.html
```

## 公開フロー

作業は `master` 以外のブランチで行い、確認後に master へ fast-forward で反映する:
```bash
git push origin <作業ブランチ>:master
```
push すると GitHub Pages に数分で自動反映される（外部公開・取り消し注意）。
コミット前に `check_mountains.py` を通すこと。
