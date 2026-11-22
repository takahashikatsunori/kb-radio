# 毎朝7時！こだいら防災＆まちラジオ

東京都小平市の毎日の暮らし・季節の話題・まちの魅力と、防災の知識を楽しくお届けする **毎朝7時（JST）自動更新のラジオ番組＆GitHub Pagesポータル** です。

## 番組の特色

- **キャスター2人の成長物語（小平の「小」と「平」）**
  - **小春（こはる）**：明るく活発、常にご機嫌で笑いが絶えないムードメーカー（防災初心者）。
  - **平蔵（へいぞう）**：優しく頼りになるしっかり者（防災知識あり）。
  - 毎日の学びと小平の発見を [data/knowledge_log.json](data/knowledge_log.json) に蓄積し、回を重ねるごとに成長していきます。
- **曜日別テーマ＆7人の架空防災専門家ゲスト**（平日 約10分 ／ **土日・日本の祝日 約15分拡大版**）
  - **月（10分／祝日は15分）**：地震・建築・地盤 ／ **岩城 剛** 博士
  - **火（10分／祝日は15分）**：気象・水害・都市河川 ／ **雨宮 栞**
  - **水（10分／祝日は15分）**：火災・電気・特殊消防機材 ／ **火ノ原 鉄平**
  - **木（10分／祝日は15分）**：災害医療・応急手当・こころのケア ／ **白川 優子**
  - **金（10分／祝日は15分）**：食・備蓄・ライフライン ／ **出雲 健太**
  - **土（15分）**：地域コミュニティ・避難所運営・ペット・福祉防災 ／ **結城 美咲**
  - **日（15分）**：防災テック・ハザードマップ・衛星・最新情報 ／ **星野 創**
- **特別日カウントダウン・ビッグニュース自動拡張・前日予告**
  - `jpholiday` で日本の祝日・振替休日を自動判定し、祝日も15分拡大版として放送します。
  - [config/special_days.json](config/special_days.json) の防災記念日（1/17、3/11、9/1防災の日 等）や小平市の重要イベントが近づくと、数日前からカウントダウン特別コーナーを追加して放送尺を拡張します（前日のエンディングで事前予告も行います）。
  - 大きな地震・重大気象警報・ビッグニュースが発生した日も、`special_feature` コーナーを自動追加して拡大版でお届けします。
- **ハイブリッドAI制作パイプライン ＆ 週1回編集長AI**
  - Phase A 調査（**`gemini-4-hydrogen` + Google検索**）→ Phase B 台本執筆（**`gemini-4-neon`**）→ Phase C ファクトチェック＆自動校閲（**`gemini-4-hydrogen` + Google検索**）→ 音声合成（**`gemini-3.8-flash-tts`**）が連携し、正確性と自然な掛け合いを両立しています。
  - [data/topic_history.json](data/topic_history.json) により直近28日間の小平トピック重複と各専門家ゲスト過去3か月（90日）の専門用語重複を自動防止します。
  - 毎週日曜21時（JST）に編集長AI（[weekly-editorial.yml](.github/workflows/weekly-editorial.yml)）が向こう2週間の小平イベント・季節感を調べ、翌週分のワクワク特集・週間編成（[data/editorial_plan.json](data/editorial_plan.json)）を企画します。
- **Gemini 3.8 Flash TTS による豊かな感情表現**
  - `<laugh>`・`<chuckle>`・`<giggle>`・`<short pause>` 等のインラインタグと `speech_metadata.style` 演技指示、2話者マルチスピーカー合成により、笑い・うなずき・自然な間合いを再現します。
- **ローカルPC ＆ GitHub Pages 両対応ポータル（`docs/`）**
  - 最新回プレーヤー（同期台本・チャプター・関連リンク・防災ノート）、[バックナンバー一覧](docs/archive.html)、[出演者＆累積防災ノート](docs/characters.html) を生成します。

---

## Step A: ローカルPCで本番音声を作成・再生する（ダブルクリック対応）

1. プロジェクト直下の `.env.example` をコピーして **`.env`** ファイルを作成し、Google AI Studio で取得した Gemini API キーを設定します（`.env` は `.gitignore` で除外済みです）：
   ```text
   GEMINI_API_KEY=AIza...あなたのAPIキー...
   ```
2. **ダブルクリックだけで実行できる `.bat` ランチャーを用意しています**：
   - **[run_today_radio.bat](run_today_radio.bat)**（メイン）：今日の番組台本（既存ならスキップ）→ `gemini-3.8-flash-tts` 音声合成 → 同期サイト更新 → ブラウザで再生画面を自動オープンします（`.venv` 未作成時は初回自動セットアップ）。
   - **[rebuild_audio_and_site.bat](rebuild_audio_and_site.bat)**：最新の `episode.json` を手動で微調整した後に、音声とサイトだけを再ビルドします。
   - **[open_radio_player.bat](open_radio_player.bat)**：最新のラジオプレーヤー（`docs/index.html`）をブラウザで開きます。

<details>
<summary>PowerShell から手動でコマンド実行したい場合</summary>

1. 初回のみ仮想環境とパッケージを準備（すでに `.venv` 作成済みの場合は不要）：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. 台本生成・音声合成・サイト更新：
   ```powershell
   $env:PYTHONUTF8="1"
   .\.venv\Scripts\python.exe src\generate_episode.py
   .\.venv\Scripts\python.exe src\build_radio.py --latest --tts-engine gemini --bitrate 112k
   .\.venv\Scripts\python.exe src\build_site.py
   ```
3. [docs/index.html](docs/index.html) をブラウザでそのまま開くと、同期字幕・チャプター・関連リンク付きで再生できます。

</details>

---

## Step B: GitHub Pages 公開 ＆ 毎朝7時（JST）自動更新の有効化

1. **GitHub リポジトリへプッシュ**  
   GitHub Desktop または `git` で本フォルダを GitHub リポジトリへプッシュします（`.env` と `.venv/`、`.cache/` は `.gitignore` により除外されます）。
2. **GitHub Secrets に API キーを登録**  
   GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** から、Name に `GEMINI_API_KEY`、Secret にご自身の API キーを登録します。
3. **GitHub Pages を GitHub Actions モードに設定**  
   **Settings → Pages → Build and deployment → Source** で **`GitHub Actions`** を選択します。
4. **動作確認（手動トリガー）**  
   **Actions → Daily Kodaira Bousai Radio (07:00 JST) → Run workflow** を開いて、`date` に `2026-11-22`（または空欄で当日）を指定して実行すると、MP3合成・サイト更新・GitHub Pages公開が走り、以降は毎日 **日本時間 朝6:35起動 → 7:00前公開** で自動更新されます。
