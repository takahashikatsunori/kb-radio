"""Generate the ~15-minute technical roundtable script with Koharu, Heizo, and AI Orchestrator Neon-san."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from generate_episode import (
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_SCRIPT_MODEL,
    JST,
    _format_usage,
    _load_json,
    _parse_json_response,
    _strip_tags,
)
from live_feeds import get_verified_kodaira_links

TECH_TALK_DIR = DATA_DIR / "tech_talk"
TECH_EPISODE_PATH = TECH_TALK_DIR / "episode.json"
DEFAULT_NEON_VOICE = "Rasalgethi"

TECH_FACT_BRIEFING = """
## リポジトリ実測・技術仕様（発言の正確性のため厳守）
1. **システム全体像（AIオーケストレーション）**
   - 番組名: 『毎朝7時！こだいら防災＆まちラジオ』（東京都小平市向け）
   - リポジトリ構成: `config/`（設定ファイル群）、`data/`（記憶・編成データ）、`episodes/`（日別台本・タイムライン）、`src/`（Python制作スクリプト群）、`.github/workflows/`（自動実行設定）、`docs/`（公開用Webポータル・MP3）
   - 実行エンジン: Python 3.12+（主要ライブラリ: `google-genai`, `requests`, `jpholiday`, `numpy`, `imageio-ffmpeg`, `edge-tts`, `python-dotenv`）

2. **ステップ1: 情報収集・カレンダー判定・記憶システム**
   - `src/live_feeds.py`:
     - **Open-Meteo API** (`https://api.open-meteo.com/v1/forecast`): 小平市中心座標（緯度 `35.7285`、経度 `139.4775`、タイムゾーン `Asia/Tokyo`）を指定し、現在の気温・湿度・風速・天気コードと3日分の予報・降水確率を取得。APIキー不要のオープンAPI。
     - **P2P地震情報（P2PQuake）JSON API v2** (`https://api.p2pquake.net/v2/history?codes=551`): 直近48時間の地震情報を取得。関東・東京で**震度4以上**、全国で**震度5弱以上**、または津波注意報・警報がある場合は、自動的に4分延長の緊急防災特集コーナー（`special_feature`）を発動する安全設計。
   - `src/schedule_calendar.py`:
     - **`jpholiday`ライブラリ**: 日本の国民の祝日・振替休日を自動判定し、平日約10分（目標約3,200文字）から土日祝15分拡大版（目標約4,800文字）へ自動切り替え。最大尺上限は1,260秒（21分）に設定しAPI日次上限（RPD）を安全に守る。
     - `config/special_days.json`: 1/17、3/11、9/1防災の日などの記念日や小平市イベントの数日前からカウントダウン特集を追加し、前日のエンディング予告（`resolve_tomorrow_preview`）も自動生成。
     - `config/program_schedule.json`: 事前編成カレンダー（SSOT）。リスナーやプロデューサーのリクエスト（`locked: true` や `special_request`）を最優先で反映。
   - 重複防止と成長の記憶:
     - `data/knowledge_log.json`: 毎回の学び（「防災ノート」）と「小平発見」を蓄積し、小春と平蔵の連続成長ストーリーに反映。
     - `data/topic_history.json`: 小平の地域トピックは**直近28日間**、7人の曜日別専門家の解説キーワードは**過去90日間（約3か月）**の重複をプログラム側（`_is_keyword_covered`）で自動チェック＆回避。

3. **ステップ2: 3段階ハイブリッドAI制作パイプライン (`src/generate_episode.py` & `src/plan_weekly_editorial.py`)**
   - **Phase A（調査・リアルタイム検証）**: **`gemini-4-hydrogen`** + **Google Search Grounding**（`tools=[{"google_search": {}}]`、`thinking_level=MEDIUM`）で小平市の最新イベント・行政情報・災害ニュースをリアルタイム検索し、臨時拡大特集の要否も判定。
   - **Phase B（台本執筆）**: **`gemini-4-neon`** が **`response_mime_type="application/json"`（JSON構造化出力）** を使い、コーナー構成（オープニング、まちネタ、専門家トーク、防災チェック、エンディング等）と全セリフを生成。
     - 各セリフは **表示用 `text`**（タグなし自然な日本語）と **音声合成用 `tts_text`**（難読地名をひらがな化、`<laugh>`, `<chuckle>`, `<giggle>`, `<short pause>` の感情タグ入り、英語略語はカタカナ読みに開く）および英語の演技指示 **`style`**・発話後の間 **`pause_after`** に分離。
   - **Phase C（ファクトチェック＆自動校閲）**: **`gemini-4-hydrogen`** + Google検索が校閲責任者として台本全行・リンク・防災ノートを検査。特に「前年イベントの混同」や数値基準（耐震基準年、胸骨圧迫回数、備蓄量など）を裏取りし、問題箇所だけピンポイントで書き換える **`=== FACT_CHECK_JSON ===`** 修正パッチを生成・適用する。
     - 小春の「初心者としての素朴な勘違いや質問」は、直後のターンで平蔵や専門家が正しく訂正・補足していれば演出として活かすユニークな校閲ルールも実装。
   - **週1回 編集長AI (`src/plan_weekly_editorial.py`)**: 毎週日曜昼に `gemini-4-hydrogen`（2週間先行リサーチ）＋ `gemini-4-neon`（編成企画）で週間テーマ軸（`weekly_arc`）と編集長ワクワク特集を組み、`data/editorial_plan.json` に週単位でマージ保存。

4. **ステップ3: 音声合成・数式BGM・プロ品質音響マスタリング (`src/build_radio.py` & `src/bgm_synth.py`)**
   - **音声合成エンジン**: **`gemini-3.8-flash-tts`**（`client.interactions.create` マルチスピーカーAPI、オフラインフォールバックとして `edge-tts` も搭載）。
     - 1回のAPIリクエストで最大2話者・4ターン・420文字までに分割（`_group_lines_into_blocks`）。同じブロックは **`SHA-256`** ハッシュで `.cache/tts_gemini/` にキャッシュし再ビルド時のAPI消費を節約。
     - ステレオ定位（パンニング）：小春をほんの少し左（`-0.10`）、平蔵をほんの少し右（`+0.10`）、ゲストを中央（`0.0`）に配置してスタジオの対話感を演出。各発話はサンプリング周波数44.1kHzへ変換し、無音トリミング後にRMS音量を `-20 dBFS` に均一化。
   - **BGM・ジングル完全自前合成 (`src/bgm_synth.py`)**: 外部の著作権音源に頼らず、**NumPy** の純粋な数式（サイン波の倍音合成、指数減衰・ADSRエンベロープ、ハミング窓付きFIRローパスフィルタ、マルチタップ・ステレオリバーブ）で、エレキピアノやベル音、温かいパッドコードの7曲（`opening_jingle`, `stinger`, `guest_jingle`, `outro_jingle`, `bgm_warm`, `bgm_news`, `bgm_feature`）をゼロから生成。BGMは声の帯域とぶつからないよう `4,200 Hz` でローパス処理。
   - **先読みダッキング＆ブロードキャストマスタリング (`src/build_radio.py`)**:
     - スピーチ区間を検出して **0.16秒先読み（Lookahead）** し、人が話し始める直前にBGM音量を `0.36` から `0.11` へ滑らかに下げる自動ダッキング（Attack `0.25s`, Release `0.65s`）を実行。
     - 最後に **FFmpeg** で `70 Hz` ハイパスフィルタ（不要な低域ノイズ除去）とラウドネス正規化 **`loudnorm=I=-16:TP=-1.5:LRA=11`**（ポッドキャスト世界標準 **-16 LUFS**）をかけ、`112 kbps` ステレオMP3として書き出し、全セリフの開始・終了秒数が入った `manifest.json` を同時生成。

5. **ステップ4: 静的Webポータル＆同期台本プレーヤー (`src/build_site.py`)**
   - データベースやサーバー不要の **静的サイトジェネレーター**。`docs/` 配下に `index.html`, `calendar.html`, `archive.html`, `cast.html`, `characters.html`, `tech.html`, 各話ページを生成。
   - 台本・タイムライン・関連リンクなどのJSONデータをHTML内の `<script type="application/json">` に直接埋め込むため、GitHub Pages上だけでなくPCローカルで `docs/index.html` をダブルクリック（`file://`）してもCORSエラーなしでそのまま再生可能。
   - JavaScriptが `<audio>` 要素の `timeupdate` イベントを監視し、現在再生中の秒数に一致するセリフをハイライト・自動スクロールし、セリフタップで `audio.currentTime` へ即座にシーク。

6. **ステップ5: クラウド自動放送局 (`GitHub Actions` + `GitHub Pages` + `GitHub Secrets`)**
   - サーバーを24時間借りるのではなく、GitHubの仮想マシンを必要なときだけ起動するサーバーレス自動化。
   - APIキー（`GEMINI_API_KEY`）は公開リポジトリには絶対置かず、暗号化された **GitHub Secrets** から実行時だけ環境変数へ安全に注入（ローカル用 `.env` も `.gitignore` で完全除外）。
   - 日次ワークフロー（`.github/workflows/daily-radio.yml`）は、GitHub Actionsの無料枠cron混雑による遅延対策として **日本時間 朝05:17（メイン）** と **朝06:13（バックアップ）** の2段構え＋「すでに当日のJSONとMP3があれば何もしない」冪等（べきとう）設計に強化。
   - 生成完了後、GitHub Actionsボットが自動で `git commit & push` し、`actions/upload-pages-artifact` と `actions/deploy-pages` で7時前にGitHub Pagesへ公開。日曜昼12:17には編集長AIワークフロー（`.github/workflows/weekly-editorial.yml`）も稼働し、カレンダーを最新化する。
"""


def build_tech_talk_prompt(characters: dict[str, Any], neon_voice: str) -> str:
    """Build prompt for Gemini 4 Neon to script the ~15-min tech roundtable."""
    koharu = characters["hosts"]["koharu"]
    heizo = characters["hosts"]["heizo"]

    return f"""あなたは「毎朝7時！こだいら防災＆まちラジオ」の構成作家です。
番組のリスナーから「このラジオが技術的にどのような仕組みで作られているのか知りたい！小春・平蔵・そしてAIオーケストレーターの『ネオンさん』の3人で対談する解説音声を作ってほしい」というリクエストが届きました。

以下の条件・実測技術データをもとに、**約15分間（表示テキスト合計 4,700〜5,200文字、目標 4,950文字）** の特別解説対談ラジオ台本JSONを生成してください。

## 1. 出演キャラクター（`speaker` は必ず `koharu`, `heizo`, `guest` のみ使用）
- `koharu`（小春）: {koharu['personality']}
  → 本回では技術・プログラミング初心者のリスナー代表として、「APIってレストランで言うと何ですか？」「プログラムが勝手にニュースを読むってどうやるの？」「BGMって人が弾いてるんじゃないんですか！？」とワクワク驚きながら素朴な疑問を投げかけ、ネオンさんや平蔵のたとえ話に「あー！なるほど！」と笑顔で納得する役どころ。
- `heizo`（平蔵）: {heizo['personality']}
  → 本回では進行役＆整理担当として、小春の素朴な疑問にやさしく相槌を打ちつつ、ネオンさんの専門的な説明を「つまりポイントは3つですね」「小平市民のみなさんにとって安心なのはここですね」と分かりやすくまとめる。
- `guest`（ネオン／AIオーケストレーター・`gemini_voice`: `{neon_voice}`）:
  → この番組の制作システム全体を設計し、複数のAIモデルやデータ取得・音声合成・公開自動化を指揮する「AIオーケストレーター」。親しみやすく知的で、少しユーモアがあり、専門用語（API、JSON、グラウンディング、ハルシネーション、プロシージャル音源、ダッキング、LUFS、静的サイト、CI/CD、cron、Secrets等）を一つひとつ「オーケストラの指揮者」「レストランの注文票」「レシピカード」「音響ミキサー」などの身近なたとえと背景技術解説を交えて、正確かつ具体的に噛み砕いて説明してくれる頼もしい技術パートナー。

## 2. 構成の重要方針（正確性 ＋ 初心者へのわかりやすさ）
- **技術的に正確・具体的**: 実在するファイル名・モデル名・API名・数値（`gemini-4-hydrogen`, `gemini-4-neon`, `gemini-3.8-flash-tts`, `Open-Meteo`, `P2PQuake v2`, `jpholiday`, `NumPy`, `FFmpeg`, `-16 LUFS`, `0.16秒先読みダッキング`, `28日/90日重複防止`, `GitHub Actions`, `GitHub Secrets`, `05:17/06:13 JST` など）を正確に織り込むこと。
- **背景技術も丁寧に解説**: 「そもそもAPIとは何か」「なぜ検索（Grounding）なしだとAIが嘘をつく（ハルシネーション）ことがあるのか」「JSONという決まった形式にすることでプログラムがどう動けるのか」「なぜBGMを外部ダウンロードせず数学のサイン波から作っているのか」「なぜサーバーを借りずにGitHub Pagesとファイル埋め込みJSONで動かせるのか」「なぜAPIキーをGitHub Secretsに隠すのか」など、初心者が「なるほど、そういう仕組みなのか！」と腹落ちする背景解説を全コーナーに必ず入れること。
- **文字数ボリューム**: 全セリフの `text` 合計文字数を **必ず 4,600〜5,300文字（目標 4,950文字）** に収めること。1セリフあたり75〜160文字程度でテンポ良く掛け合い、全体で55〜70セリフ程度にすると約15分にぴったり収まります。

## 3. セグメント構成（必ず以下の6コーナー構成）
1. `id: "opening"` / `intro_jingle: "opening_jingle"` / `bgm: "bgm_warm"` / `outro_jingle: null`
   - タイトル例：「特別編開局！AIオーケストレーター・ネオンさんって誰？」（目標 ~650文字）
   - 挨拶（朝でも昼でも聴ける特別編のあいさつ）、番組の裏側大公開の宣言、ゲストのネオンさん呼び込み（小春＆平蔵）、そもそも「AIオーケストレーション」とは何か（1つのAIに丸投げするのではなく、適材適所の専門家AI・ツール・プログラムを指揮者のように連携させる仕組み）を解説。
2. `id: "data_and_research"` / `intro_jingle: "guest_jingle"` / `bgm: "bgm_news"` / `outro_jingle: null`
   - タイトル例：「ステップ1：毎朝の天気・地震・小平の話題をどうやって集めるの？」（目標 ~950文字）
   - 「API（エーピーアイ）とは何か」（アプリ同士がデータをやり取りするレストランの注文票・窓口のたとえ）、`Open-Meteo`（小平市の緯度経度 `35.7285, 139.4775`）、`P2PQuake v2`（震度4以上で自動緊急特集）、`jpholiday`（祝日自動15分拡大）、`data/knowledge_log.json`・`topic_history.json`（28日ローカル＆90日専門家重複防止）、事前編成カレンダー `config/program_schedule.json` を解説。
3. `id: "script_and_factcheck"` / `intro_jingle: "stinger"` / `bgm: "bgm_feature"` / `outro_jingle: null`
   - タイトル例：「ステップ2：3段階ハイブリッドAIと『嘘をつかない』自動校閲」（目標 ~1,000文字）
   - なぜAIモデルを使い分けるのか：Phase A 調査（`gemini-4-hydrogen` + Google Search Groundingでハルシネーション対策）、Phase B 台本執筆（`gemini-4-neon` のJSON構造化出力：`text`と`tts_text`の分離）、Phase C 自動ファクトチェック＆外科的パッチ（`gemini-4-hydrogen` + Google検索で前年日付の混同や防災数値を裏取り、さらに小春の初心者ならではのボケ・質問は直後の訂正があれば演出として残す設計！）、日曜日の編集長AI（`plan_weekly_editorial.py`）。
4. `id: "tts_and_audio_dsp"` / `intro_jingle: "stinger"` / `bgm: "bgm_warm"` / `outro_jingle: null`
   - タイトル例：「ステップ3：声の演技とNumPy数式BGM・プロ音響マスタリングの秘密」（目標 ~1,000文字）
   - `gemini-3.8-flash-tts` のマルチスピーカー合成（`<laugh>` などの感情タグ・`style`演技指示・2話者/4ターン/420文字ブロック分割と `SHA-256` キャッシュ・ステレオ左右パンニング）、`bgm_synth.py` による **NumPy数式プロシージャル音源**（著作権クリア＋サイン波の足し算と倍音、声と被らない4,200Hzローパス）、`build_radio.py` の **0.16秒先読みサイドチェインダッキング** と **FFmpeg `-16 LUFS` ブロードキャスト・マスタリング**、`manifest.json` タイムライン生成を分かりやすく噛み砕いて解説。
5. `id: "web_and_automation"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null`
   - タイトル例：「ステップ4：サーバー不要の同期サイトと毎朝自動放送局のしくみ」（目標 ~850文字）
   - `build_site.py` が作る静的サイト（`docs/`）と「HTMLの中にJSONを直接埋め込むのでGitHub PagesでもPCローカルでもすぐ動く設計」、`<audio>` の `timeupdate` イベントによる台本ハイライト＆タップシーク、CI/CDと **GitHub Actions**（`daily-radio.yml` の朝5:17メイン＋6:13バックアップと生成済みスキップの冪等設計、日曜12:17の編集長AI、**GitHub Secrets** でのAPIキー保護）。
6. `id: "ending"` / `intro_jingle: "stinger"` / `bgm: "bgm_warm"` / `outro_jingle: "outro_jingle"`
   - タイトル例：「今日のまとめ＆番組カレンダー・技術解説ページのご案内」（目標 ~500文字）
   - 平蔵が今日の学びを「ポイントは3つ」で整理、ネオンさんからの温かいメッセージ（技術はすべて小平の朝の暮らしと安心を届けるための道具）、新しくなった放送カレンダーページや技術解説ページへの案内、3人そろっての明るい締め！

## 4. Gemini 3.8 Flash TTS 音声合成最適化ルール（超重要！！）
- **2話者ブロック厳守**: `build_radio.py` は連続するセリフを「最大2話者・4ターン・420文字」のブロックにまとめて `gemini-3.8-flash-tts` へ送ります。3人が1ターンずつ入れ替わる（小春→平蔵→ネオン→小春→平蔵→ネオン…）と1ターンごとにAPIリクエストが増えてしまうため、**同じコーナー内では「小春 ⇄ ネオン」「平蔵 ⇄ ネオン」「小春 ⇄ 平蔵」のような2人ずつの2〜4往復ペア**が自然に連なるように話者を並べてください（全体で22〜30ブロック程度になるのが理想）。
- **`text`（画面表示用）**: `<laugh>` 等のタグは絶対に入れないこと。英語・ファイル名・技術用語は正確な表記（`Open-Meteo`, `JSON`, `NumPy`, `-16 LUFS`, `GitHub Actions` 等）で書くこと。
- **`tts_text`（音声読み上げ用）**:
  - **重要**: 英語の略語・ライブラリ名・ファイル名・専門用語・記号は、`gemini-3.8-flash-tts` が日本語として自然に美しく発音できるよう、`tts_text` 内で **必ずカタカナ・かな読みに開く** こと！
    例：`API`→`エーピーアイ`、`JSON`→`ジェイソン`、`TTS`→`ティーティーエス`、`LLM`→`エルエルエム`、`DSP`→`ディーエスピー`、`LUFS`→`ラフス`、`dBFS`→`デシベルエフエス`、`HTML`→`エイチティーエムエル`、`CSS`→`シーエスエス`、`JavaScript`→`ジャバスクリプト`、`CI/CD`→`シーアイ・シーディー`、`GitHub Actions`→`ギットハブ・アクションズ`、`GitHub Pages`→`ギットハブ・ページズ`、`GitHub Secrets`→`ギットハブ・シークレッツ`、`Open-Meteo`→`オープンメテオ`、`P2PQuake`→`ピーツーピークエイク`、`jpholiday`→`ジェイピーホリデー`、`NumPy`→`ナムパイ`、`FFmpeg`→`エフエフエムペグ`、`SHA-256`→`シャーニーゴーロク`、`cron`→`クーロン`、`MP3`→`エムピースリー`、`Hz`→`ヘルツ`、`kHz`→`キロヘルツ`、`gemini-4-hydrogen`→`ジェミニ・フォー・ハイドロジェン`、`gemini-4-neon`→`ジェミニ・フォー・ネオン`、`gemini-3.8-flash-tts`→`ジェミニ・サンテンハチ・フラッシュ・ティーティーエス`、`episode.json`→`エピソード・ドット・ジェイソン`、`build_radio.py`→`ビルド・ラジオ・ドット・パイ`、`bgm_synth.py`→`ビージーエム・シンセ・ドット・パイ`、`build_site.py`→`ビルド・サイト・ドット・パイ`、`小平`→`こだいら`、数値の小数点やマイナス（`-16`→`マイナスじゅうろく`、`0.16秒`→`れいてんいちろくびょう`、`35.7285`→`さんじゅうごてん ななにーはちご`）。
  - 笑い・相槌・自然な間合いのため、`<laugh>`, `<chuckle>`, `<giggle>`, `<short pause>`, `<breath>` を自然な位置にバランスよく入れること。
  - 演技ト書き（「明るく：」など）は `tts_text` には絶対に書かず、英語の `style` フィールドに書くこと。

## 5. 技術詳細ブリーフィング
{TECH_FACT_BRIEFING}

## 6. 出力JSONスキーマ（厳密にこのJSONのみ出力）
{{
  "subtitle": "特別解説対談 ― 小春・平蔵・AIオーケストレーター ネオンさんが語る『こだいら防災＆まちラジオ』ができるまで",
  "keywords_featured": [
    "AIオーケストレーション",
    "ハイブリッドAI & 自動ファクトチェック",
    "Gemini 3.8 Flash TTS & NumPy数式BGM",
    "先読みダッキング & -16 LUFS",
    "静的Webポータル & GitHub Actions"
  ],
  "learned_notes": {{
    "learned_points": [
      "情報収集（API・祝日判定）→3段階AI台本＆校閲→音声・BGM合成→静的サイト公開までがプログラムで一気通貫に連携していること",
      "調査と校閲に検索付きのHydrogen、執筆にNeon、音声に3.8 Flash TTSを使い分けるハイブリッド構成で正確さと楽しさを両立していること",
      "BGMはNumPyの数式からゼロから作り、0.16秒先読みダッキングと-16 LUFSマスタリングでラジオらしい聴きやすさを実現していること"
    ],
    "kodaira_discovery": "最先端のAIオーケストレーションや自動化の仕組みすべてが、『毎朝7時に小平の街の魅力とやさしい防災を届ける』という一つの目的のために組み合わさっていること。"
  }},
  "references": [
    {{
      "category": "AI制作パイプライン",
      "title": "3フェーズ制作＆自動校閲",
      "detail": "Phase A (gemini-4-hydrogen + Google検索) → Phase B (gemini-4-neon JSON執筆) → Phase C (gemini-4-hydrogen 自動ファクトチェック)",
      "contact": "src/generate_episode.py"
    }},
    {{
      "category": "音声・音響DSP",
      "title": "マルチスピーカーTTS ＆ 数式BGM",
      "detail": "gemini-3.8-flash-tts + NumPyプロシージャル音源 + 0.16秒先読みダッキング + FFmpeg -16 LUFSマスタリング",
      "contact": "src/build_radio.py / src/bgm_synth.py"
    }},
    {{
      "category": "配信・自動化",
      "title": "静的ポータル ＆ GitHub Actions",
      "detail": "JSON埋め込み型HTML (GitHub Pages / ローカル両対応) + 毎日05:17/06:13 JST自動編成＆日曜12:17編集長AI",
      "contact": "src/build_site.py / .github/workflows/"
    }}
  ],
  "segments": [
    {{
      "id": "opening",
      "title": "コーナータイトル",
      "bgm": "bgm_warm",
      "intro_jingle": "opening_jingle",
      "outro_jingle": null,
      "lines": [
        {{
          "speaker": "koharu",
          "text": "画面表示用の台本テキスト（タグなし）",
          "tts_text": "かな読みと<laugh>等を含むTTS用テキスト",
          "style": "bright, cheerful, smiling Japanese morning radio host",
          "pause_after": 0.34
        }}
      ]
    }}
  ]
}}"""


def assemble_tech_episode(
    raw_generated: dict[str, Any],
    characters: dict[str, Any],
    neon_voice: str,
    script_model: str,
) -> dict[str, Any]:
    """Validate and wrap tech-talk segments with metadata compatible with build_radio.py & build_site.py."""
    koharu = characters["hosts"]["koharu"]
    heizo = characters["hosts"]["heizo"]

    voices = {
        "koharu": {
            "name": koharu["name"],
            "reading": koharu["reading"],
            "role": koharu["role"],
            "gemini_voice": koharu["tts"]["gemini_voice"],
            "edge_voice": koharu["tts"]["edge_voice"],
            "edge_rate": koharu["tts"]["edge_rate"],
            "edge_pitch": koharu["tts"]["edge_pitch"],
            "default_style": koharu["tts"]["default_style"],
            "pan": koharu["tts"]["pan"],
            "ui": koharu["ui"],
        },
        "heizo": {
            "name": heizo["name"],
            "reading": heizo["reading"],
            "role": heizo["role"],
            "gemini_voice": heizo["tts"]["gemini_voice"],
            "edge_voice": heizo["tts"]["edge_voice"],
            "edge_rate": heizo["tts"]["edge_rate"],
            "edge_pitch": heizo["tts"]["edge_pitch"],
            "default_style": heizo["tts"]["default_style"],
            "pan": heizo["tts"]["pan"],
            "ui": heizo["ui"],
        },
        "guest": {
            "name": "ネオン",
            "reading": "ねおん",
            "role": "AIオーケストレーター（番組の全体設計・AI連携の指揮者）",
            "gemini_voice": neon_voice,
            "edge_voice": "ja-JP-KeitaNeural",
            "edge_rate": "+2%",
            "edge_pitch": "+0Hz",
            "default_style": "articulate, calm, warm, slightly playful Japanese AI orchestrator and tech guide",
            "pan": 0.0,
            "ui": {"color": "#0891b2", "bg_soft": "#ecfeff"},
        },
    }

    segments = raw_generated.get("segments") or []
    if len(segments) < 5:
        raise ValueError(f"Expected >=5 segments, got {len(segments)}")

    allowed_speakers = {"koharu", "heizo", "guest"}
    cleaned_segments: list[dict[str, Any]] = []
    total_chars = 0

    for seg in segments:
        cleaned_lines: list[dict[str, Any]] = []
        for line in seg.get("lines") or []:
            sp = line.get("speaker")
            if sp not in allowed_speakers:
                sp = "heizo"
            display_text = _strip_tags(str(line.get("text", "")))
            if not display_text:
                continue
            tts_text = str(line.get("tts_text") or display_text).strip()
            style = str(line.get("style") or voices[sp]["default_style"]).strip()
            pause_after = max(0.15, min(1.2, float(line.get("pause_after", 0.34))))
            total_chars += len(display_text)
            cleaned_lines.append(
                {
                    "speaker": sp,
                    "text": display_text,
                    "tts_text": tts_text,
                    "style": style,
                    "pause_after": round(pause_after, 2),
                }
            )
        if cleaned_lines:
            cleaned_segments.append(
                {
                    "id": str(seg.get("id") or f"seg_{len(cleaned_segments) + 1}"),
                    "title": str(seg.get("title") or "コーナー"),
                    "bgm": seg.get("bgm") or "bgm_warm",
                    "intro_jingle": seg.get("intro_jingle"),
                    "outro_jingle": seg.get("outro_jingle"),
                    "lines": cleaned_lines,
                }
            )

    if total_chars < 3500:
        raise ValueError(f"Generated tech talk script too short ({total_chars} chars)")

    return {
        "meta": {
            "title": "毎朝7時！こだいら防災＆まちラジオ",
            "subtitle": raw_generated.get("subtitle")
            or "特別解説対談 ― 小春・平蔵・AIオーケストレーター ネオンさんが語る『こだいら防災＆まちラジオ』ができるまで",
            "episode_date": "2026-11-23",
            "episode_slug": "tech-talk-neon",
            "episode_number": 0,
            "episode_label": "技術解説対談スペシャル",
            "is_tech_special": True,
            "weekday": "monday",
            "weekday_ja": "月曜日",
            "is_weekend": False,
            "is_holiday": True,
            "holiday_name": "勤労感謝の日",
            "edition_label": "特別解説対談（約15分）",
            "theme_name": "番組制作アーキテクチャ＆AIオーケストレーション解説",
            "theme_badge": "技術解説スペシャル：小春×平蔵×AIオーケストレーター ネオン",
            "target_duration_sec": 900,
            "output_filename": "kodaira_radio_tech_talk_neon.mp3",
            "kodaira_topics": [
                "AIオーケストレーション全体設計",
                "Open-Meteo・P2PQuake・jpholiday連携",
                "Hydrogen × Neon 3段階制作＆自動校閲",
                "Gemini 3.8 Flash TTS・NumPy数式BGM・-16 LUFS",
                "静的ポータル＆GitHub Actions自動化",
            ],
            "models": {
                "script": script_model,
                "tts": "gemini-3.8-flash-tts",
            },
            "voices": voices,
            "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        },
        "guest": {
            "id": "guest_neon",
            "name": "ネオン",
            "reading": "ねおん",
            "title": "AIオーケストレーター（番組の全体設計・AI連携の指揮者）",
            "theme": "番組制作のしくみ＆AIオーケストレーション技術解説",
            "voice_name": neon_voice,
            "personality": "複数のAIモデルやデータ取得・音声合成・公開自動化を指揮者のようにまとめ上げるAIオーケストレーター。難しい技術も身近なたとえで楽しく紐解きます。",
            "keywords_featured": raw_generated.get("keywords_featured")
            or [
                "AIオーケストレーション",
                "ハイブリッドAI & 自動ファクトチェック",
                "Gemini 3.8 Flash TTS & NumPy数式BGM",
                "先読みダッキング & -16 LUFS",
                "静的Webポータル & GitHub Actions",
            ],
        },
        "links": get_verified_kodaira_links()[:4],
        "references": raw_generated.get("references") or [],
        "learned_notes": raw_generated.get("learned_notes")
        or {
            "learned_points": [],
            "kodaira_discovery": "",
        },
        "segments": cleaned_segments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ~15-min technical explanation script with Neon-san")
    parser.add_argument("--force", action="store_true", help="Overwrite existing data/tech_talk/episode.json")
    parser.add_argument("--model", default=DEFAULT_SCRIPT_MODEL, help="Gemini model for scripting (default: gemini-4-neon)")
    parser.add_argument("--neon-voice", default=DEFAULT_NEON_VOICE, help=f"Gemini TTS voice for Neon-san (default: {DEFAULT_NEON_VOICE})")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt summary without calling Gemini API")
    args = parser.parse_args()

    load_dotenv(CONFIG_DIR.parent / ".env")
    if TECH_EPISODE_PATH.exists() and not args.force and not args.dry_run:
        print(f"Tech talk episode already exists at {TECH_EPISODE_PATH}; skipping (use --force to regenerate).")
        return

    characters = _load_json(CONFIG_DIR / "characters.json")
    prompt = build_tech_talk_prompt(characters, args.neon_voice)

    if args.dry_run:
        print("=== DRY RUN TECH TALK GENERATOR ===")
        print(f"Target output : {TECH_EPISODE_PATH}")
        print(f"Script model  : {args.model}")
        print(f"Neon TTS voice: {args.neon_voice}")
        print(f"Prompt chars  : {len(prompt)}")
        return

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        print("ERROR: GEMINI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    print(f"Generating ~15-min technical roundtable script via {args.model} (Neon voice={args.neon_voice})...")
    resp = client.models.generate_content(
        model=args.model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    print(f"Script usage  : {_format_usage(resp)}")
    raw_json = _parse_json_response(getattr(resp, "text", "") or "")
    episode = assemble_tech_episode(raw_json, characters, args.neon_voice, args.model)

    TECH_TALK_DIR.mkdir(parents=True, exist_ok=True)
    TECH_EPISODE_PATH.write_text(
        json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total_lines = sum(len(s["lines"]) for s in episode["segments"])
    total_chars = sum(len(l["text"]) for s in episode["segments"] for l in s["lines"])
    print(f"Generated tech talk script: {TECH_EPISODE_PATH} ({total_lines} lines, {total_chars} chars)")


if __name__ == "__main__":
    main()
