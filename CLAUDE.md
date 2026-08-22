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
| `sw.js` | Service Worker。**画面(HTML/CSS/JS/アイコン)だけ**をネットワーク優先でキャッシュし、圏外でもアプリが開くようにする。気象データは扱わない（予報の保存は index.html の localStorage スナップショット側） |
| `logic.js` | 登山指数 A/B/C の判定ロジック（`blockIndex`/`seasonTh`/`feelsLike`/`viewScore`/`interpWind`/`sumOrNull` と各しきい値）。**JS側の判定はここが唯一の置き場**。`index.html`・`docs/find.html` が `<script src>` で読む |
| `display.js` | 天気の文言・濡れ注意・雨雪判別・積雪や視程の表記（`summarizeDailyWeather`/`dayWeatherPhrase`/`singleCodePhrase`/`wetWarn`/`precipPhase`/`snowCell`/`visTxt`/`timingLabel`/`addPrecipNotes` と語彙 `WMO`/`WMETA`/`SAFETY_OVERRIDE`/`CAT_LABEL` 等）。**JS側の表示はここが唯一の置き場**。`index.html`・`docs/find.html` が `<script src>` で読む。ver 2.46β で3箇所の写しを1つに畳んだ |
| `gate.js` | 規約同意＋認証コードの共通ゲート。**認証定数(AUTH_VER/SALT/HASH)はここが唯一の置き場**。`index.html`・`docs/find.html`・`docs/point.html` が読み込む |
| `scripts/mountain_weather.py` | CLI本体。`--name`/`--lat --lon --elev` で予報を出力（`--html`でレポート保存） |
| `references/mountains.csv` | 内蔵山岳DB（**BOM付きUTF-8・CRLF**）。列: name,yomi,pref,lat,lon,elev |
| `references/criteria.md` | 登山指数A/B/Cの判定基準（閾値の根拠） |
| `docs/` | GitHub Pages公開物。`mountains.html`(対応山リスト・自動生成)・`how-it-works*.html`・`terms.html` |
| `icons/` `manifest.json` | PWAアイコンとマニフェスト |
| `skill/SKILL.md` | Claude Code スキル定義（「◯◯岳の予報を調べて」で自動実行） |
| `skill/auth-renew/SKILL.md` | 認証コード更新スキル（「認証コードを更新して」で年次ローテーションを自動実行） |
| `references/logic_cases.json` `scripts/test_logic.py` `scripts/test_logic.js` | 判定ロジックの等価性テスト。同じ入出力表を CLI(Python) と `logic.js`(Node) で回す |
| `scripts/test_logic_fuzz.py` `scripts/test_logic_fuzz.js` | 同じ9関数を乱数で総当たりし、Python↔JS の一致と**不変条件**（悪化させて指数が良くならない・欠測が好条件に化けない等）を見る。入力表の生成は Python 側の1箇所だけ |
| `scripts/test_display.py` `scripts/test_display.js` | **表示まわり**の等価性テスト（天気の文言・濡れ注意・雨雪判別・積雪や視程の表記）。同じ入出力表を CLI(Python) と `display.js`(Node) で回す。あわせて `display.js?v=` と `PW_DISPLAY_VER` の一致、ページ側に再定義が無いことも見る |
| `scripts/test_find_score.py` `scripts/test_find_score.js` | 山さがしの日和スコア `score()` のテスト。減点方式ゆえ「材料が無い＝100点＝ランクA」に化ける構造なので、値ではなく**壊れ方の向き**を見る。対象は生成物ではなく生成元の `gen_find.py` |
| `scripts/test_render.py` `scripts/test_render.js` `references/fixture_forecast.json` `references/golden/` | **描画そのもの**。固定した本物の応答1本を CLI と Web の両方に通し、(a) Web が組み立てた表が golden と一致するか (b) 週間表の9列が CLI の markdown と一字一句そろっているか、を見る。Web 側は `index.html` の `run()` を**そのまま**回す（`test_stubs.js` の `makeDom()` を document として渡す）。通信も時刻も固定なので結果は動かない。`--record` で fixture 取り直し、`--bless` で golden 更新（**変わったのが意図どおりだと確かめてから**使うこと） |
| `scripts/test_mutation.py` | わざとバグを仕込んで**テストが落ちること**を確かめる。落ちない変異があれば、その範囲についてテストは書いていないのと同じ |
| `scripts/test_weather_codes.py` | 天気コード → 日本語表現の**総当たり**。全28コードで文言が出るか・**安全オーバーライドが必ず日代表に昇格するか**・晴れと雷雨が入れ替わらないか・集約の窓(4〜17時)の外の悪天を拾っていないか。`test_display.py` は「一致」しか見ないので、両方とも同じように間違っている場合を捕まえられない |
| `scripts/test_offline.js` | **圏外・障害時**のふるまい（通信のタイムアウト・再試行・`end_date` クランプ・応答の正規化・スナップショット保存・ゲートの fail-closed）。index.html の DOM に触らない範囲を目印で切り出し、`fetch`・`localStorage`・時間を身代わりに差し替えて回す |
| `scripts/test_sw.js` | `sw.js` のふるまい。**API 応答をキャッシュしていないこと**（規約9）・フラグメント除去・前版キャッシュの掃除・遅い回線での退避。オンラインでは表面化しない壊れ方なので機械で見る |
| `scripts/test_stubs.js` | 上の各テストが共有する身代わりの環境（仮想時計・localStorage・**DOM**・目印での切り出し）。時間を差し替えるので 20秒のタイムアウトも 6秒の待ちも即座に検査できる。`makeDom()` は本物の DOM を真似ない ── 要素は「innerHTML を覚える箱」で、見た目ではなく**組み立てた文字列**を見るためのもの |
| `scripts/check_syntax.py` | 構文と公開物の静的検査。Python / JavaScript / **HTML に直接書かれた `<script>`**（index.html の本体2,000行超はここ）の構文、`logic.js`・`gate.js` が **ES5 の範囲**に留まっているか、`.nojekyll`・manifest のアイコンが揃っているか。`check_mountains.py` の `[1/8]` が呼ぶ |
| `.github/workflows/check.yml` | push / PR ごとに `check_mountains.py --offline` とミューテーションを回す。手元で通し忘れたときの網。通信を伴う DEM 照合だけ外してある |
| `scripts/check_csp.py` | 外部参照の棚卸し。通信相手が「気象データ・地名・アクセス解析」の3系統から増えていないかを見る（貼り付けたコードに知らないタグが付いてきた、を検出）。あわせて CSP を入れるときの下見（`'unsafe-inline'` を要求している箇所の数と、生成した policy）。`check_mountains.py` の `[1/8]` が呼ぶ |
| `scripts/test_api_contract.py` | **通信を伴う**。Open-Meteo の応答を**非null件数で数え**、既知の前提（完全な GSM 日には 900/800hPa と `sunshine_duration` が無い・存在しない項目は 400 にならず全 null・予報長を超えると部分日になって尽きる）を固定する。`--online` を付けたときだけ動く。落ちたら**モデルの配信仕様が変わった合図** |
| `scripts/check_consistency.py` | 2箇所以上に同じ値を書いている場所の突き合わせ（`JMA_DAYS`・`FIND_DAYS`・`AUTH_VER` の `?v=`・日本域の範囲・`sw.js` の `CACHE` 版）と、実装から消えたはずの説明がドキュメントに残っていないかの検査。`check_mountains.py` の `[7/8]` が呼ぶ |
| `scripts/db_*.py gen_*.py check_*.py` | DB保守ツール群（下記パイプライン） |

**公開URL**: https://halab18.github.io/sangaku-yohou2/

## 気象データの取得元

基本は Open-Meteo の**気象庁モデル** `/v1/jma`（前半=MSM 約5km / 後半=GSM。自動切替）。
**MSM→GSM の切替日は「N日目」で決め打ちにしないこと。** 切替はモデルのラン時刻で動き、実測で
1日ずれる（しかも「実際より細かいモデルだ」と言う方向＝安全と逆）。境目が要るときは必ず
`model_switch()`（CLI）/ `modelSwitch()`（index.html）から実データで出す。
判定材料は 900/800hPa の有無（`day_model` / `dayModel`）。
**切替は日の途中で起きる**（実測: 切替日は 900hPa が24時間中18時間だけ来て、残りが欠ける）。
つまり「その日は MSM か GSM のどちらか」ではなく、**1日の中に両方が混在する日がある**。
`day_model` は `any` ではなく `all` で見て、混在日を粗い側(GSM)に倒している。逆にすると
「実際より細かいモデルだ」と名乗ることになり、過信の方向に外れる。
**予報期間は10日**（`JMA_DAYS`。CLI・index.html の両方に定数を置いて揃える）。
モデル自体は11日目あたりまで配信するが、**どこで尽きるかはラン時刻で前後する**
（実測 2026-08-21: 11日目は24時間そろい、12日目が部分日だった。以前は11日目が部分日だった）。
部分日を掴むと daily 集計が作れないか、作っても半日ぶんの最悪値になる。
**尽きる位置が動く以上、その手前に余裕を置いて止めるしかない**ので10日にしてある
（「11日目が必ず部分日だから」ではない。ここは配信状況が変われば見直す余地がある）。

- 気象庁モデルに**無い**項目 = `precipitation_probability` / `wind_gusts_10m` / `cape` /
  `convective_inhibition` / `visibility` / `snow_depth`。これらだけ `/v1/forecast` から補完し、
  **時刻をキーにして**貼り合わせる（`_merge_series` / `mergeSeries`）。添字一致は前提にしない
  （2本のAPIで `end_date` のクランプ結果が食い違いうるため）。
- **欠測は「判定不能」に倒す**。`block_index`/`blockIndex` は稜線風・降水がどちらも欠測なら
  `None`、`view_score`/`viewScore` は材料が1つも無ければ `None` を返し、表示は `-` になる。
  降水の合計は `sum_or_none`/`sumOrNull` を使う（`sum(v or 0)` だと「0mm」と「データ無し」が
  区別できず、欠測が「降水量0mm＝好条件」に化ける）。find の `score()` も主要素が全欠測なら
  `null` を返して一覧から外す（減点方式なので引く材料が無いと100点＝ランクAになるため）。
  **この手の「データが無い→好条件」は安全と逆方向なので、判定を足すときは必ず欠測側を確認する。**
- **要注意**: 存在しない項目を `/v1/jma` に投げても **400 にはならず全て null で返る**。
  「エラーが出ないから取れている」と誤解しやすい。期間も同様で、モデルの実配信期間(11日)を
  超えて要求してもエラーにならず黙って null が並ぶ。**日数はコード側(`JMA_DAYS`)で必ず制限する**。
- **MSM と GSM で配信される要素が違う**（実測）。GSM 期間に無いもの:
  `sunshine_duration` / `shortwave_radiation`、および気圧面 **900hPa・800hPa**。
  `cloud_cover`・`weather_code`・`precipitation`・925/850/700/600hPa は全期間ある。
  **要素を足すときは MSM 期間だけ見て「取れている」と判断しないこと。必ず後半日の非null件数を数える。**
  稜線風は CLI・index.html・find のいずれも「その時刻に値がある面だけで山頂標高へ補間する」
  （`interp_wind`/`interpWind`）で倒している。気圧面が1面も無い時刻だけ `None`（判定不能）。
- **欠けた気圧面を別モデルから借りて埋めてはいけない**（実測で却下済み。再検討しないこと）。
  借りた値は別モデルなので隣の面との間に段差ができ、その段差（モデル間差 平均1.74m/s）の方が
  埋めたい内挿誤差（0.76m/s）より大きい。実測: 現行0.76 → icon補完1.24 / gfs補完1.32 m/s と悪化。
  **日照を借りているのとは前提が違う**（日照は代替が無い。風は自分の隣の面から内挿できる）。
  残る副作用は「GSM 期間は風を弱めに見積もる」（北ア級 −1.2m/s）で、補正せず開示で倒している
  （週間表の区切り行・「全球」印・稜線風の `*` 印）。
- `docs/find.html`（山さがし）も気象庁モデル。**対象は7日間**（`FIND_DAYS`。ここ1箇所で決まる。
  `FIND_DAYS <= JMA_DAYS` は不変条件）。スコア主要素の `sunshine_duration` だけは MSM 期間ぶんしか
  来ないので、`/v1/forecast` から `sunshine_supp` という**別名**で取得して補完する
  （同名で貼ると1〜3日目の MSM の日照を上書きしてしまう）。補完した日は `sc.sunAlt=true` で
  `*` 印を出す。日照は**窓9時間そろっている時だけ採用**（部分欠測の合計は使わない）。
  find の**欠測ガードは気象庁モデル由来の材料で数える**こと（補完日照を材料に数えると、
  気象庁モデルが全滅した地点が「①だけ減点＝ランクA」で最上位に出る）。
  降水確率は `/v1/forecast` から補完するが **表示専用でスコアには入れない**
  （`score()` の `pprob`）。減点式を触るときは `s-=` の行に `pprob` を足さないこと。
  `sc` の中身を変えたら `cacheKey` / `LAST_KEY` の `findN:` を必ず上げる。
- **確度**（週間表の「確度」列）は `/v1/forecast?models=` で3モデル（JMA/ECMWF/GFS）を1本で取り、
  ECMWF と GFS に**同じ判定手順**を回して指数の段階差を見る（`fetch_models`/`splitModels` →
  `day_index_of`/`dayIndexOf` → `model_agree`/`modelAgree`）。気象庁メンバーには
  **アプリが表示している指数そのもの**を使う（`models=jma_seamless` から計算し直すと実測で
  7.5%食い違い、「◎なのに表示中の指数がどのメンバーとも違う」が起きる）。
  取得失敗は握って確度を `-` にする（主要な予報表を巻き添えにしない）。
  ECMWF は 900/800hPa を配信しないが、影響は平均0.29m/s でモデル間差3.51m/s より十分小さいので
  補正しない（**別モデルからの穴埋めは却下済み**）。確度は**判定には一切使わない**。

## 厳守する規約

1. **既存の山名(mountains.csv の name)は絶対に変えない。** 検索結果URL（`#燕岳/2026-07-19`）が
   name に依存しており、改名すると共有済みリンクが壊れる。同名別峰を足すときは
   **新規側だけ**「山名(県名)」等の区別名にする。
2. **mountains.csv は BOM付きUTF-8 を維持。** Excelでの文字化け防止。`check_mountains.py` が読めることを検証する。改行は **リポジトリには LF で入っており**（`core.autocrlf` によりWindows の作業コピーだけ CRLF になる）、行末そのものは機械検査していない。文字化けを防いでいるのは BOM の方なので、実質はこれで足りている。
3. **CLIとWebの判定ロジックは同一に保つ。** 判定の実装は **`scripts/mountain_weather.py`(CLI) と `logic.js`(Web) の2箇所だけ**。
   片方だけ閾値やロジックを変えない。基準変更は `references/criteria.md`・CLI・`logic.js`・
   `references/logic_cases.json`・図解ページを揃え、下記を通すこと（`check_mountains.py` の `[5/8]` が同じ3本を呼ぶ）:

   ```bash
   python scripts/test_logic.py && node scripts/test_logic.js && python scripts/test_logic_fuzz.py
   ```

   **入出力表だけを信用しない。** `logic_cases.json` は人が選んだ代表値なので、書いた人が
   思いつかなかった組み合わせは入らない（実際に「山頂雲量が欠測でも雲海を名乗る」変異は
   表を素通りし、乱数側だけが捕まえた）。判定を触ったら、テスト自体が効いているかも確かめる:

   ```bash
   python scripts/test_mutation.py
   ```

   しきい値を変えたときは `test_mutation.py` の `MUTATIONS` が「変異が当たりません」と
   言い出すので、置換前の文字列も併せて直すこと（当たっていない変異を通ったと数えると、
   この仕掛け自体が嘘になる）。

   `logic.js` の関数を index.html / docs/find.html 側に再定義しないこと（後勝ちで上書きされ、
   `logic.js` を直しても反映されないという壊れ方をする。`test_logic.js` が検出する）。

   **表示まわり（天気の文言・濡れ注意・雨雪判別・積雪や視程の表記）の実装も2箇所だけ** ──
   `scripts/mountain_weather.py`(CLI) と **`display.js`**(Web)。ver 2.46β まではここに
   `index.html` と `scripts/gen_find.py` の**2つの写し**があり、find 側の一致は
   「値を変えるときは揃えること」というコメントだけが守っていた。`display.js` に畳んだので、
   **index.html / gen_find.py 側に再定義しないこと**（後勝ちで潰れる。`test_display.js` が検出する）。
   言語をまたぐ Python↔JS の1組は消せないので**2箇所が下限**。片方だけ直さないこと。突き合わせは
   `python scripts/test_display.py`（`check_mountains.py` の `[5/8]` が呼ぶ）。
   `display.js` には**素の値を返すものだけ**を置く（HTML やクラス名を組み立てるものは
   index.html 側に残す）。CLI の markdown 出力と1対1に比べられなくなると、この検査が空振りする。

   **整数の丸めは `r0()`/`fint()` を必ず通す**（CLI 側）。Python の `f"{v:.0f}"` と `round()` は
   偶数丸めで、JS の `Math.round` と**ちょうど .5 のときだけ1ズレる**（ver 2.46β で解消）。
   小数1桁の側は、ちょうど中間の値が2進で表せないため厳密なタイが発生せず、揃える必要は無い。
4. **CLI本体に第三者パッケージを足さない**（依存ゼロを維持）。保守スクリプト側はOK。
5. **座標変更・DB編集をしたら必ず `python scripts/check_mountains.py` を通す**
   （構文・形式・CLI/Web同期・自動生成ページの同期・判定ロジックの等価性・**圏外や障害時のふるまい**・
   **定数同期とドキュメントの整合性**・DEM照合）。判定やテストを触ったときは `--mutation` も付ける。
   `--offline` を付けると通信を伴う DEM 照合だけ飛ばす（CI が使うのはこの形）。
   push / PR では `.github/workflows/check.yml` が同じものを自動で回すが、**手元で通すのを
   やめない**こと（CI は通し忘れの網であって、手元の確認の代わりではない）。
6. **`docs/find.html` と `docs/mountains.html` は自動生成物。直接編集しない。**
   修正は `scripts/gen_find.py` / `scripts/gen_mountain_list.py` に入れて再生成する。
   生成物だけ直すと次の再生成で消える（実際に find.html の z-index 修正がこれで失われた）。
   `check_mountains.py` の「[3/6] 自動生成ページの同期」がこのずれを検出する。
   **テストも生成物ではなく生成元に対して書く**（`scripts/test_find_score.py` は
   `gen_find.py` の中の JS を切り出して回す）。生成物を見ると、生成元を直し忘れた状態でも通る。
7. **認証コードの定数は `gate.js` にのみ置く。** index.html や各ページに複製しない
   （複製すると年次更新の漏れで「認証済みなのに弾かれる」事故になる）。
   新しく操作系ページを足すときは `<script src="…/gate.js">` を読み、
   本体スクリプトの先頭で `if(!pwGuardPage())return;` を入れること。
8. **`logic.js` を変えたら `PW_LOGIC_VER` と、index.html・`gen_find.py` の `?v=` を同時に上げる。**
   上げないと古い `logic.js` がキャッシュに残り、「画面は新しいのに判定だけ旧版」という
   気づけない状態になる（一致は `test_logic.js` が機械的に見ている）。
   **`display.js` も同じ形**（`PW_DISPLAY_VER` と2ページの `?v=`。一致は `test_display.js` が見る）。
   こちらを上げ忘れると「画面は新しいのに文言だけ旧版」になる。
9. **リリースのたびに `sw.js` の `CACHE` の版を上げる。** 上げないと `activate` の掃除が走らず、
   前版のシェルがキャッシュに残る。ネットワーク優先なのでオンラインでは表面化せず、
   **完全オフラインで開いたときだけ古い画面が出る**という再現困難な状態になる。
   併せて、**API 応答を `sw.js` でキャッシュしてはいけない**（気象データの保存は
   index.html の `pw-snap-v1` 側に限る）。SW に入れると「古い予報を、いま取れた予報として」
   描いてしまい、画面上は完全に正常に見える＝気づけない誤表示になる。
   この2点（版の更新・API を入れないこと）は `node scripts/test_sw.js` が機械的に見る。
   通信の障害時と端末内保存は `node scripts/test_offline.js`。どちらも
   `check_mountains.py` の `[6/8]` が呼ぶ。

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
