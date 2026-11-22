"""Daily Kodaira radio episode generator using Gemini 3.8 Flash + Google Search grounding."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

from live_feeds import collect_live_briefing

JST = timezone(timedelta(hours=9))
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
EPISODES_DIR = ROOT_DIR / "episodes"

WEEKDAY_KEYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_redirect_url(url: str, timeout: float = 4.0) -> str:
    """Resolve vertexaisearch grounding redirect URLs to clean target URLs when possible."""
    if not url.startswith("https://"):
        return ""
    if "vertexaisearch.cloud.google.com" not in url:
        return url
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        final_url = resp.url or url
        if final_url.startswith("https://") and "vertexaisearch.cloud.google.com" not in final_url:
            return final_url
    except Exception:  # noqa: BLE001
        pass
    return ""


def _next_episode_number(target_date: str) -> int:
    """Compute sequential episode number across existing episodes."""
    existing_dates = sorted(
        p.name for p in EPISODES_DIR.iterdir()
        if p.is_dir() and (p / "episode.json").exists()
    ) if EPISODES_DIR.exists() else []
    if target_date in existing_dates:
        ep = _load_json(EPISODES_DIR / target_date / "episode.json")
        return int(ep.get("meta", {}).get("episode_number", existing_dates.index(target_date) + 1))
    return len(existing_dates) + 1


def build_research_prompt(
    target_date: str,
    day_cfg: dict[str, Any],
    live_bundle: dict[str, Any],
) -> str:
    """Build Phase A prompt for real-time Kodaira local topics and disaster news research."""
    guest = day_cfg["guest"]
    weather_json = json.dumps(live_bundle["weather"], ensure_ascii=False)
    quakes_json = json.dumps(live_bundle["earthquakes"][:5], ensure_ascii=False)

    return f"""あなたは東京都小平市の朝7時放送ラジオ番組のリサーチャーです。
放送日: {target_date}（{day_cfg['weekday_ja']}）
本日の曜日テーマ: {day_cfg['theme_name']}
本日の専門家ゲスト: {guest['name']}（{guest['title']}）
注目キーワード候補: {', '.join(guest['keywords_bank'][:6])}

参考ライブ気象（小平市）:
{weather_json}

参考直近地震（48時間以内）:
{quakes_json}

Google検索を使って、以下4点を最新の公式情報・地域ニュースから調査し、日本語で簡潔なブリーフィングを作成してください。
1. 【小平市のローカル話題・季節トピック】{target_date}前後の小平市内のイベント、市民ニュース、まちづくり、名所（玉川上水・狭山・境緑道・小川パレット・丸ポスト・図書館・公民館・地元商店街や旬の農産物等）など、聴くと小平市が好きになる話題を2〜3個。
2. 【東京都・小平市の防災・行政お知らせ】最近の市報・公式HP・防災訓練・補助金・ごみ出し注意・防災アプリ等の最新情報。
3. 【全国の最新防災・気象トピック】直近1週間の地震・気象・防災庁や国の防災関連ニュース。
4. 【本日の専門テーマ掘り下げ資料】「{day_cfg['theme_name']}」に関する専門用語・技術・機材・制度で小平市民の暮らしに役立つ正確な豆知識。

※確認できた事実と日付だけを挙げ、推測でイベント日時や数値を作らないでください。"""


def build_script_prompt(
    target_date: str,
    ep_num: int,
    characters: dict[str, Any],
    day_cfg: dict[str, Any],
    schedule_rule: dict[str, Any],
    knowledge_entries: list[dict[str, Any]],
    live_bundle: dict[str, Any],
    research_summary: str,
    grounded_links: list[dict[str, str]],
) -> str:
    """Build Phase B prompt to generate structured episode.json with expressive Gemini TTS tags."""
    koharu = characters["hosts"]["koharu"]
    heizo = characters["hosts"]["heizo"]
    guest = day_cfg["guest"]
    recent_logs = json.dumps(knowledge_entries[-5:], ensure_ascii=False, indent=2)
    weather_json = json.dumps(live_bundle["weather"], ensure_ascii=False)
    quakes_json = json.dumps(live_bundle["earthquakes"][:4], ensure_ascii=False)
    links_json = json.dumps(grounded_links, ensure_ascii=False, indent=2)

    return f"""あなたは「{characters['program']['title']}」のメイン構成作家です。
以下の条件・設定・事実データをもとに、ラジオ番組1回分の完全台本JSONを生成してください。

## 1. 放送メタ条件
- 放送日: {target_date}（{day_cfg['weekday_ja']}） / 第{ep_num}回
- 番組尺タイプ: {schedule_rule['label']}
- **必須文字数目標**: 全セリフの `text` 合計文字数を **{schedule_rule['min_chars']}〜{schedule_rule['max_chars']}文字（目標 {schedule_rule['target_chars']}文字）** に収めること。
- 平日（10分）はテンポ良く約55〜70セリフ、土日（15分）はたっぷり深掘りして約80〜98セリフで構成する。

## 2. 登場人物（スピーカーIDは必ず `koharu`, `heizo`, `guest` のみ使用）
- `koharu`（小春）: {koharu['personality']}
- `heizo`（平蔵）: {heizo['personality']}
- `guest`（{guest['name']} / {guest['title']}）: {guest['personality']} 小平とのつながり: {guest['kodaira_connection']}
- 専門家キーワード候補（この中から2〜4個を必ず噛み砕いて解説）: {', '.join(guest['keywords_bank'])}

## 3. 連続成長・過去の学び（自然な流れで振り返りや成長を取り入れる）
{recent_logs}

## 4. ライブ気象・地震・調査ブリーフィング（事実厳守）
小平市気象: {weather_json}
直近地震: {quakes_json}
調査ブリーフィング:
{research_summary}

利用可能な検証済み公式リンク候補:
{links_json}

## 5. Gemini 3.8 Flash TTS 表現力ルール（超重要）
- 各セリフは `speaker`, `text`, `tts_text`, `style`, `pause_after` を持つ。
- **`text`（画面表示用）**: `<laugh>` 等のタグは絶対に入れず、自然な日本語台本にする。
- **`tts_text`（Gemini 3.8 Flash TTS 読み上げ用）**:
  - 笑い・相槌・間合いを豊かにするため、半角英語の山括弧タグ `<laugh>`, `<chuckle>`, `<giggle>`, `<sigh>`, `<breath>`, `<short pause>` を会話の自然な位置にバランスよく入れる（特に小春は明るく `<laugh>` や `<giggle>` 多め、平蔵やゲストも温かく `<chuckle>` や `<short pause>` を活用）。
  - 演技のト書き（「明るく笑って：」など）は絶対に `tts_text` に書かないこと（そのまま読まれてしまうため）。
  - 難読の小平地名（小川町=おがわちょう、津田町=つだまち、御幸町=みゆきちょう、上水南町=じょうすいみなみちょう、狭山・境緑道=さやま・さかいりょくどう 等）や電話番号（042-341-0793=ぜろよんに、さんよんいち、ぜろななきゅうさん）、英略語（GIS=ジーアイエス、DMAT=ディーマット 等）は `tts_text` 内でかな・カタカナ読みに開く。
- **`style`**: 各ターンごとの英語の短い演技ディレクション（例: `"bright, cheerful, smiling"`, `"warm, gentle and reassuring"`, `"curious and amused"`, `"enthusiastic expert explaining clearly"`）。
- **話者配列ルール（重要）**: 1つの会話ブロック内で自然に掛け合いできるよう、できるだけ2人の会話が続いたあと交代する（3人が1文ごとに順番に回り続けるより、`小春⇄ゲスト`、`平蔵⇄ゲスト`、`小春⇄平蔵` の2〜4往復ペアが連なる自然なラジオ進行が望ましい）。

## 6. セグメント構成（この5コーナー構成を厳守）
1. `id: "opening"` / `intro_jingle: "opening_jingle"` / `bgm: "bgm_warm"` / `outro_jingle: null` — 朝7時の挨拶・小平市の今朝の天気＆直近地震・季節の小平トーク
2. `id: "kodaira_life"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null` — 小平が好きになる今日のまち・生活・防災トピック
3. `id: "guest_talk"` / `intro_jingle: "guest_jingle"` / `bgm: "{day_cfg['bgm_mood']}"` / `outro_jingle: null` — 本日のテーマ「{day_cfg['theme_name']}」専門家 {guest['name']} さんの深掘り解説＆3人の質疑応答・掛け合い
4. `id: "daily_bousai"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null` — 暮らしに直結する防災チェック・自治体サービスやイベント案内
5. `id: "ending"` / `intro_jingle: "stinger"` / `bgm: "bgm_warm"` / `outro_jingle: "outro_jingle"` — 今日の「小春＆平蔵の防災ノート」まとめ＆明日の予告＆いってらっしゃい！

## 7. 出力JSONスキーマ（厳密にこのキー構造のJSONのみ出力）
{{
  "subtitle": "第{ep_num}回・{target_date}（{day_cfg['weekday_ja']}）朝7時号 ― テーマ要約サブタイトル",
  "keywords_featured": ["解説した専門用語1", "専門用語2", "専門用語3"],
  "links": [
    {{"category": "カテゴリ", "title": "タイトル", "url": "https://...（必ず上記候補や実在URLから選択）", "note": "一言説明"}}
  ],
  "references": [
    {{"category": "カテゴリ", "title": "防災メモ見出し", "detail": "具体的要点", "contact": "確認先や番号"}}
  ],
  "learned_notes": {{
    "learned_points": ["今日学んだこと1", "学んだこと2", "学んだこと3"],
    "kodaira_discovery": "今日見つけた小平市の魅力・防災と暮らしのつながり1文"
  }},
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
          "text": "画面表示用の台本テキスト",
          "tts_text": "かな読みと<laugh>等を含むTTS用テキスト",
          "style": "bright, cheerful, smiling",
          "pause_after": 0.32
        }}
      ]
    }}
  ]
}}"""


def _extract_grounding_links(response: Any, base_links: list[dict[str, str]]) -> list[dict[str, str]]:
    """Extract clean https URLs from Gemini Search grounding metadata merged with curated links."""
    merged: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            meta = getattr(candidates[0], "grounding_metadata", None)
            chunks = getattr(meta, "grounding_chunks", None) or []
            for ch in chunks:
                web = getattr(ch, "web", None)
                if not web:
                    continue
                raw_uri = getattr(web, "uri", "") or ""
                title = getattr(web, "title", "") or "参考情報"
                resolved = _resolve_redirect_url(raw_uri)
                if resolved and resolved not in seen_urls:
                    seen_urls.add(resolved)
                    merged.append(
                        {
                            "category": "最新検索ソース",
                            "title": title,
                            "url": resolved,
                            "note": "番組リサーチ時の参照公式・関連ページ",
                        }
                    )
                if len(merged) >= 4:
                    break
    except Exception:  # noqa: BLE001
        pass

    for item in base_links:
        u = item.get("url", "")
        if u.startswith("https://") and u not in seen_urls:
            seen_urls.add(u)
            merged.append(item)

    return merged


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _assemble_and_validate_episode(
    raw_generated: dict[str, Any],
    target_date: str,
    ep_num: int,
    day_key: str,
    characters: dict[str, Any],
    day_cfg: dict[str, Any],
    schedule_rule: dict[str, Any],
    live_bundle: dict[str, Any],
    fallback_links: list[dict[str, str]],
) -> dict[str, Any]:
    """Wrap generated segments with full program metadata and validate every line."""
    guest = day_cfg["guest"]
    date_compact = target_date.replace("-", "")
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
            "name": guest["name"],
            "reading": guest["reading"],
            "role": guest["title"],
            "gemini_voice": guest["voice_name"],
            "edge_voice": guest["edge_voice"],
            "edge_rate": "+1%",
            "edge_pitch": "+0Hz",
            "default_style": guest["default_style"],
            "pan": 0.0,
            "ui": guest["ui"],
        },
    }

    segments = raw_generated.get("segments") or []
    if len(segments) < 3:
        raise ValueError(f"Expected >=3 segments, got {len(segments)}")

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
            pause_after = float(line.get("pause_after", 0.32))
            pause_after = max(0.15, min(1.2, pause_after))
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
                    "id": str(seg.get("id") or f"seg_{len(cleaned_segments)+1}"),
                    "title": str(seg.get("title") or "コーナー"),
                    "bgm": seg.get("bgm") or "bgm_warm",
                    "intro_jingle": seg.get("intro_jingle"),
                    "outro_jingle": seg.get("outro_jingle"),
                    "lines": cleaned_lines,
                }
            )

    if total_chars < 1500:
        raise ValueError(f"Generated script too short ({total_chars} chars)")

    raw_links = raw_generated.get("links") or []
    valid_links = [
        lk for lk in raw_links
        if isinstance(lk, dict) and str(lk.get("url", "")).startswith("https://")
    ]
    if not valid_links:
        valid_links = fallback_links
    else:
        seen = {lk["url"] for lk in valid_links}
        for fl in fallback_links:
            if fl["url"] not in seen and len(valid_links) < 8:
                valid_links.append(fl)
                seen.add(fl["url"])

    learned_notes = raw_generated.get("learned_notes") or {
        "learned_points": ["今日の放送テーマを確認しました"],
        "kodaira_discovery": "小平の暮らしと防災のつながりを再発見しました。",
    }

    return {
        "meta": {
            "title": characters["program"]["title"],
            "subtitle": raw_generated.get("subtitle")
            or f"第{ep_num}回・{target_date}（{day_cfg['weekday_ja']}）朝7時号 ― {day_cfg['theme_name']}",
            "episode_date": target_date,
            "episode_number": ep_num,
            "weekday": day_key,
            "weekday_ja": day_cfg["weekday_ja"],
            "is_weekend": bool(day_cfg["is_weekend"]),
            "theme_name": day_cfg["theme_name"],
            "theme_badge": day_cfg["theme_badge"],
            "target_duration_sec": int(schedule_rule["target_duration_sec"]),
            "output_filename": f"kodaira_radio_{date_compact}.mp3",
            "voices": voices,
        },
        "guest": {
            "id": guest["id"],
            "name": guest["name"],
            "reading": guest["reading"],
            "title": guest["title"],
            "theme": day_cfg["theme_name"],
            "voice_name": guest["voice_name"],
            "personality": guest["personality"],
            "keywords_featured": raw_generated.get("keywords_featured")
            or guest["keywords_bank"][:3],
        },
        "weather_summary": live_bundle["weather"],
        "earthquake_summary": live_bundle["earthquakes"][:3],
        "links": valid_links,
        "references": raw_generated.get("references") or [],
        "learned_notes": learned_notes,
        "segments": cleaned_segments,
    }


def _update_knowledge_log(episode: dict[str, Any]) -> None:
    """Append episode learned_notes into data/knowledge_log.json without duplicating dates."""
    log_path = DATA_DIR / "knowledge_log.json"
    if log_path.exists():
        data = _load_json(log_path)
    else:
        data = {"entries": []}

    ep_date = episode["meta"]["episode_date"]
    entries: list[dict[str, Any]] = [
        e for e in data.get("entries", []) if e.get("date") != ep_date
    ]
    notes = episode.get("learned_notes") or {}
    entries.append(
        {
            "date": ep_date,
            "weekday": episode["meta"]["weekday_ja"],
            "theme": episode["meta"]["theme_name"],
            "guest_name": episode["guest"]["name"],
            "learned_points": notes.get("learned_points", []),
            "kodaira_discovery": notes.get("kodaira_discovery", ""),
        }
    )
    entries.sort(key=lambda e: e["date"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate daily Kodaira radio episode.json")
    parser.add_argument(
        "--date",
        default=datetime.now(JST).strftime("%Y-%m-%d"),
        help="Broadcast date YYYY-MM-DD in JST (default: today JST)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing episode.json")
    parser.add_argument(
        "--dry-run-prompt",
        action="store_true",
        help="Print research/generation prompts without calling Gemini API",
    )
    parser.add_argument(
        "--model",
        default="gemini-3.8-flash",
        help="Gemini text model for research & script generation",
    )
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")
    target_date = args.date
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    day_key = WEEKDAY_KEYS[dt.weekday()]

    ep_dir = EPISODES_DIR / target_date
    ep_json_path = ep_dir / "episode.json"
    if ep_json_path.exists() and not args.force and not args.dry_run_prompt:
        print(f"Episode already exists at {ep_json_path}; skipping (use --force to regenerate).")
        return

    characters = _load_json(CONFIG_DIR / "characters.json")
    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    day_cfg = themes["days"][day_key]
    schedule_rule = themes["schedule_rules"]["weekend" if day_cfg["is_weekend"] else "weekday"]
    knowledge_data = _load_json(DATA_DIR / "knowledge_log.json") if (DATA_DIR / "knowledge_log.json").exists() else {"entries": []}
    ep_num = _next_episode_number(target_date)

    print(f"Collecting live Kodaira weather & earthquake feeds for {target_date} ({day_cfg['weekday_ja']})...")
    live_bundle = collect_live_briefing()
    research_prompt = build_research_prompt(target_date, day_cfg, live_bundle)

    if args.dry_run_prompt:
        sample_script_prompt = build_script_prompt(
            target_date=target_date,
            ep_num=ep_num,
            characters=characters,
            day_cfg=day_cfg,
            schedule_rule=schedule_rule,
            knowledge_entries=knowledge_data.get("entries", []),
            live_bundle=live_bundle,
            research_summary="[Dry-run: Phase A Google Search grounding output goes here]",
            grounded_links=live_bundle["verified_links"],
        )
        print("\n=== DRY RUN CONFIG SUMMARY ===")
        print(f"Date        : {target_date} ({day_cfg['weekday_ja']}) | Episode #{ep_num}")
        print(f"Schedule    : {schedule_rule['label']} (target {schedule_rule['target_duration_sec']}s / ~{schedule_rule['target_chars']} chars)")
        print(f"Theme       : {day_cfg['theme_name']}")
        print(f"Guest       : {day_cfg['guest']['name']} ({day_cfg['guest']['voice_name']})")
        print(f"Weather OK  : {live_bundle['weather'].get('ok')} | Quakes (48h): {len(live_bundle['earthquakes'])}")
        print("\n=== PHASE A RESEARCH PROMPT (Preview) ===\n" + research_prompt)
        print("\n=== PHASE B SCRIPT PROMPT (First 1200 chars) ===\n" + sample_script_prompt[:1200] + "\n...")
        return

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        print(
            "ERROR: GEMINI_API_KEY is not set. Copy .env.example to .env and add your Gemini API key.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    print(f"Phase A: Researching latest Kodaira & disaster news via {args.model} + Google Search...")
    research_resp = client.models.generate_content(
        model=args.model,
        contents=research_prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            temperature=0.4,
        ),
    )
    research_text = getattr(research_resp, "text", "") or ""
    grounded_links = _extract_grounding_links(research_resp, live_bundle["verified_links"])

    print(f"Phase B: Generating structured episode script ({schedule_rule['label']})...")
    script_prompt = build_script_prompt(
        target_date=target_date,
        ep_num=ep_num,
        characters=characters,
        day_cfg=day_cfg,
        schedule_rule=schedule_rule,
        knowledge_entries=knowledge_data.get("entries", []),
        live_bundle=live_bundle,
        research_summary=research_text,
        grounded_links=grounded_links,
    )
    script_resp = client.models.generate_content(
        model=args.model,
        contents=script_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.75,
        ),
    )
    raw_json = json.loads(script_resp.text)
    episode = _assemble_and_validate_episode(
        raw_generated=raw_json,
        target_date=target_date,
        ep_num=ep_num,
        day_key=day_key,
        characters=characters,
        day_cfg=day_cfg,
        schedule_rule=schedule_rule,
        live_bundle=live_bundle,
        fallback_links=grounded_links,
    )

    ep_dir.mkdir(parents=True, exist_ok=True)
    ep_json_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_knowledge_log(episode)

    total_lines = sum(len(s["lines"]) for s in episode["segments"])
    total_chars = sum(len(l["text"]) for s in episode["segments"] for l in s["lines"])
    print(f"Generated episode.json: {ep_json_path} ({total_lines} lines, {total_chars} chars)")


if __name__ == "__main__":
    main()
