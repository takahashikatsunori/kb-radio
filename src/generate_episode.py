"""Daily Kodaira radio episode generator: Hydrogen research -> Neon script -> Hydrogen fact-check."""

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
from schedule_calendar import (
    CHARS_PER_MINUTE,
    MAX_TARGET_DURATION_SEC,
    resolve_day_plan,
    resolve_tomorrow_preview,
)

JST = timezone(timedelta(hours=9))
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
EPISODES_DIR = ROOT_DIR / "episodes"
DEFAULT_RESEARCH_MODEL = "gemini-4-hydrogen"
DEFAULT_SCRIPT_MODEL = "gemini-4-neon"
DEFAULT_FACTCHECK_MODEL = "gemini-4-hydrogen"
RECENT_LOCAL_DEDUP_DAYS = 14
EXPERT_HISTORY_DAYS = 90


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
    existing_dates = (
        sorted(
            p.name
            for p in EPISODES_DIR.iterdir()
            if p.is_dir() and (p / "episode.json").exists()
        )
        if EPISODES_DIR.exists()
        else []
    )
    if target_date in existing_dates:
        ep = _load_json(EPISODES_DIR / target_date / "episode.json")
        return int(
            ep.get("meta", {}).get(
                "episode_number", existing_dates.index(target_date) + 1
            )
        )
    return len(existing_dates) + 1


def _detect_live_quake_special(earthquakes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Check if recent earthquakes warrant an automatic breaking-news special corner."""
    for q in earthquakes:
        scale_num = int(q.get("max_scale_num") or -1)
        is_kanto = bool(q.get("is_kanto_or_tokyo"))
        tsunami = str(q.get("tsunami") or "")
        has_tsunami = tsunami in ("Watch", "Warning")
        if (is_kanto and scale_num >= 40) or scale_num >= 50 or has_tsunami:
            hypo = q.get("hypocenter", "国内")
            scale_ja = q.get("max_scale", "")
            return {
                "title": f"緊急防災特集：{hypo}（{scale_ja}）を受けた備え",
                "summary": f"直近の地震（{q.get('time', '')} {hypo} {scale_ja}）を踏まえた安全確認・余震や二次災害への備え",
                "extra_minutes": 4,
            }
    return None


def _parse_breaking_special(
    research_text: str,
    live_quake_special: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    """Extract === BREAKING_SPECIAL === JSON block from Phase A output safely."""
    marker = "=== BREAKING_SPECIAL ==="
    clean_text = research_text
    parsed_special: dict[str, Any] | None = None

    if marker in research_text:
        head, tail = research_text.split(marker, 1)
        clean_text = head.strip()
        m = re.search(r"\{.*\}", tail, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                if obj.get("has_breaking_special") and str(obj.get("title", "")).strip():
                    extra_min = max(3, min(5, int(obj.get("extra_minutes") or 3)))
                    parsed_special = {
                        "title": str(obj["title"]).strip(),
                        "summary": str(obj.get("summary") or "").strip(),
                        "extra_minutes": extra_min,
                    }
            except Exception:  # noqa: BLE001
                parsed_special = None

    if live_quake_special and not parsed_special:
        parsed_special = live_quake_special
    elif live_quake_special and parsed_special:
        parsed_special["summary"] = f"{live_quake_special['summary']} ／ {parsed_special['summary']}"
        parsed_special["extra_minutes"] = max(
            parsed_special["extra_minutes"], live_quake_special["extra_minutes"]
        )

    return clean_text, parsed_special


def _apply_breaking_extension(
    day_plan: dict[str, Any],
    breaking_special: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Extend target duration/chars when breaking news or scheduled special day applies."""
    plan = dict(day_plan)
    sched = plan.get("scheduled_special")

    if not sched and not breaking_special:
        return plan, None

    if sched and breaking_special:
        extra_min = min(6, int(sched["extra_minutes"]) + int(breaking_special["extra_minutes"]))
        special_meta = {
            "kind": "combined",
            "title": f"{sched['title']} ＆ {breaking_special['title']}",
            "phase_label": sched["phase_label"],
            "focus": f"{sched['theme_focus']} ／ 緊急トピック: {breaking_special['summary']}",
            "extra_minutes": extra_min,
        }
    elif sched:
        extra_min = int(sched["extra_minutes"])
        special_meta = {
            "kind": "scheduled_countdown",
            "title": sched["title"],
            "phase_label": sched["phase_label"],
            "focus": sched["theme_focus"],
            "extra_minutes": extra_min,
        }
    else:
        assert breaking_special is not None
        extra_min = int(breaking_special["extra_minutes"])
        special_meta = {
            "kind": "breaking_news",
            "title": breaking_special["title"],
            "phase_label": "速報特集",
            "focus": breaking_special["summary"],
            "extra_minutes": extra_min,
        }

    base_dur = int(plan["base_duration_sec"])
    target_dur = min(MAX_TARGET_DURATION_SEC, base_dur + extra_min * 60)
    added_sec = max(0, target_dur - base_dur)
    added_chars = round((added_sec / 60.0) * CHARS_PER_MINUTE)

    plan["target_duration_sec"] = target_dur
    plan["target_chars"] = int(plan["base_chars"]) + added_chars
    plan["min_chars"] = int(plan["base_min_chars"]) + round(added_chars * 0.85)
    plan["max_chars"] = int(plan["base_max_chars"]) + round(added_chars * 1.15)
    total_min = round(target_dur / 60)

    if plan["is_holiday"]:
        plan["edition_label"] = f"祝日15分＋特別特集拡大版（{plan['holiday_name']}・約{total_min}分）"
    elif plan["is_weekend"]:
        plan["edition_label"] = f"土日15分＋特別特集拡大版（約{total_min}分）"
    else:
        plan["edition_label"] = f"特別コーナー拡大版（約{total_min}分）"

    return plan, special_meta


def _normalize_kw(s: str) -> str:
    """Normalize keyword/topic string for matching across parenthetical variants."""
    base = re.sub(r"（[^）]*）|\([^)]*\)", "", s or "")
    return re.sub(r"[\s・／/、。・「」『』\-_]+", "", base).lower()


def _is_keyword_covered(bank_kw: str, covered_list: list[str]) -> bool:
    """Return True if bank_kw overlaps substantially with any recently covered keyword."""
    b_full = re.sub(r"[\s・／/、。・「」『』（）()\-_]+", "", bank_kw or "").lower()
    b_core = _normalize_kw(bank_kw)
    for cov in covered_list:
        c_full = re.sub(r"[\s・／/、。・「」『』（）()\-_]+", "", cov or "").lower()
        c_core = _normalize_kw(cov)
        if len(c_core) >= 3 and c_core in b_full:
            return True
        if len(b_core) >= 3 and b_core in c_full:
            return True
        for sub in re.findall(r"（([^）]+)）|\(([^)]+)\)", cov or ""):
            tok = re.sub(r"[\s・／/\-_]+", "", (sub[0] or sub[1] or "")).lower()
            if len(tok) >= 5 and tok in b_full:
                return True
    return False


def build_dedup_context(
    target_date_str: str,
    day_plan: dict[str, Any],
    topic_history_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build 14-day local topic dedup & 90-day per-expert keyword history context."""
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    day_key = day_plan["day_key"]
    guest = day_plan["day_cfg"]["guest"]
    guest_id = guest["id"]

    recent_local_lines: list[str] = []
    recent_topic_count = 0
    expert_lines: list[str] = []
    covered_keywords: list[str] = []
    seen_cov: set[str] = set()

    sorted_entries = sorted(
        (e for e in topic_history_entries if isinstance(e, dict) and e.get("date")),
        key=lambda e: e["date"],
        reverse=True,
    )

    for entry in sorted_entries:
        try:
            e_dt = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        age_days = (target_dt - e_dt).days
        if age_days <= 0:
            continue

        if age_days <= RECENT_LOCAL_DEDUP_DAYS:
            topics = [str(t).strip() for t in (entry.get("kodaira_topics") or []) if str(t).strip()]
            areas = [str(a).strip() for a in (entry.get("kodaira_areas") or []) if str(a).strip()]
            sp_title = str(entry.get("special_feature_title") or "").strip()
            recent_topic_count += len(topics)
            parts: list[str] = []
            if areas:
                parts.append(f"エリア[{', '.join(areas)}]")
            if topics:
                parts.append(f"話題[{'; '.join(topics)}]")
            if sp_title:
                parts.append(f"特集[{sp_title}]")
            if parts:
                recent_local_lines.append(f"- {entry['date']}（{entry.get('weekday', '')}）: " + " / ".join(parts))

        if age_days <= EXPERT_HISTORY_DAYS and (
            entry.get("guest_id") == guest_id or entry.get("day_key") == day_key
        ):
            kws = [str(k).strip() for k in (entry.get("keywords_featured") or []) if str(k).strip()]
            for kw in kws:
                if kw not in seen_cov:
                    seen_cov.add(kw)
                    covered_keywords.append(kw)
            sub = str(entry.get("subtitle") or "").strip()
            expert_lines.append(
                f"- {entry['date']}: 解説済み=[{', '.join(kws) or '記録なし'}]（{sub}）"
            )

    fresh_keywords = [
        kw for kw in guest.get("keywords_bank", []) if not _is_keyword_covered(kw, covered_keywords)
    ]
    all_bank_covered = len(fresh_keywords) == 0

    return {
        "recent_local_count": recent_topic_count,
        "recent_local_text": "\n".join(recent_local_lines) if recent_local_lines else "（直近14日間の過去放送記録なし）",
        "expert_covered_keywords": covered_keywords,
        "expert_history_text": "\n".join(expert_lines) if expert_lines else "（過去90日間の同専門家回の記録なし）",
        "fresh_keywords": fresh_keywords if not all_bank_covered else list(guest.get("keywords_bank", [])),
        "all_bank_covered": all_bank_covered,
    }


def _format_editorial_guide_block(day_plan: dict[str, Any]) -> str:
    """Format editorial_plan daily guide block for prompts when available."""
    guide = day_plan.get("editorial_guide")
    if not guide:
        return ""
    arc = guide.get("weekly_arc") or {}
    lines = ["【今週の編集長プラン（企画ガイドライン）】"]
    if arc.get("title"):
        lines.append(f"- 週間テーマ軸: {arc['title']}（{arc.get('concept', '')}）")
    if guide.get("focus_area"):
        lines.append(f"- 本日の重点エリア: {guide['focus_area']}")
    if guide.get("kodaira_angle"):
        lines.append(f"- 本日のまちネタ切り口: {guide['kodaira_angle']}")
    if guide.get("expert_angle"):
        lines.append(f"- 専門家トークの角度: {guide['expert_angle']}")
    hints = guide.get("search_hints") or []
    if hints:
        lines.append(f"- 優先検索ヒント: {', '.join(hints)}")
    lines.append("※ 当日に重大な地震・気象警報・速報ニュースが発生した場合は、上記ガイドより当日の緊急安全情報を最優先してください。")
    return "\n".join(lines)


def build_research_prompt(
    target_date: str,
    day_plan: dict[str, Any],
    live_bundle: dict[str, Any],
    dedup_ctx: dict[str, Any] | None = None,
) -> str:
    """Build Phase A prompt for real-time Kodaira topics, disaster news, and breaking-special detection."""
    day_cfg = day_plan["day_cfg"]
    guest = day_cfg["guest"]
    weather_json = json.dumps(live_bundle["weather"], ensure_ascii=False)
    quakes_json = json.dumps(live_bundle["earthquakes"][:5], ensure_ascii=False)
    dedup = dedup_ctx or build_dedup_context(target_date, day_plan, [])

    holiday_note = (
        f"※本日は国民の祝日「{day_plan['holiday_name']}」のため15分拡大版です。休日の小平での過ごし方やイベント情報も厚めに調べてください。"
        if day_plan["is_holiday"]
        else ""
    )
    sched = day_plan.get("scheduled_special")
    special_note = (
        f"※本日は特別テーマ期間中：【{sched['title']}（{sched['phase_label']}）】／ 焦点: {sched['theme_focus']}"
        if sched
        else ""
    )
    editorial_block = _format_editorial_guide_block(day_plan)
    fresh_kws_str = ", ".join(dedup["fresh_keywords"][:6])
    covered_kws_str = ", ".join(dedup["expert_covered_keywords"]) or "なし"
    fresh_note = (
        "（キーワード候補が一巡済みのため、過去90日とは異なる発展サブトピックや小平での応用例を深掘りしてください）"
        if dedup["all_bank_covered"]
        else ""
    )

    return f"""あなたは東京都小平市の朝7時放送ラジオ番組のリサーチャーです。
放送日: {target_date}（{day_plan['weekday_ja']}）
編成タイプ: {day_plan['edition_label']}
本日の曜日テーマ: {day_cfg['theme_name']}
本日の専門家ゲスト: {guest['name']}（{guest['title']}）
今回優先すべき未解説キーワード候補: {fresh_kws_str} {fresh_note}
{holiday_note}
{special_note}

{editorial_block}

【重複禁止①：直近14日間に放送済みの小平トピック・エリア】
{dedup['recent_local_text']}
※上記とまったく同じ場所・話題を連日繰り返さないでください（開催当日リマインドや明確な続報がある場合を除く）。小平市内の別エリア・新しい話題を優先して調べてください。

【重複禁止②：この専門家（{guest['name']}）が過去3か月（90日）間に解説済みの専門用語・テーマ】
既出キーワード: {covered_kws_str}
{dedup['expert_history_text']}
※上記で既出のキーワードは主テーマにせず、未解説の候補や新しい切り口を調査してください。

参考ライブ気象（小平市）:
{weather_json}

参考直近地震（48時間以内）:
{quakes_json}

Google検索を使って、以下4点を最新の公式情報・地域ニュースから調査し、日本語で簡潔なブリーフィングを作成してください。
1. 【小平市のローカル話題・季節トピック】{target_date}前後の小平市内のイベント、市民ニュース、まちづくり、名所（玉川上水・狭山・境緑道・小川パレット・丸ポスト・図書館・公民館・地元商店街や旬の農産物等）など、直近14日と重複しない「聴くと小平市が好きになる話題」を2〜3個。
2. 【東京都・小平市の防災・行政お知らせ】最近の市報・公式HP・防災訓練・補助金・ごみ出し注意・防災アプリ等の最新情報。
3. 【全国の最新防災・気象トピック】直近1週間の地震・気象・防災庁や国の防災関連ニュース。
4. 【本日の専門テーマ掘り下げ資料】「{day_cfg['theme_name']}」に関して過去90日と被らない専門用語・技術・機材・制度で小平市民の暮らしに役立つ正確な豆知識。

※【開催年・事実の厳密確認】イベント日時・開催期間を挙げる際は必ず {target_date[:4]}年（令和{int(target_date[:4]) - 2018}年）の公式情報であることを確認し、前年以前の開催日を今年の日程として記載しないでください。確認できない日時・店舗営業情報は書かないでください。
※確認できた事実と日付だけを挙げ、推測でイベント日時や数値を作らないでください。

最後に必ず以下の区切り行とJSONだけを出力し、本日「臨時の拡大特別コーナーを設けるべき重大な防災ニュース・災害警報・大規模防災イベント」があるか判定してください（通常の小規模ニュースのみなら false にしてください）:
=== BREAKING_SPECIAL ===
{{"has_breaking_special": false, "title": "", "summary": "", "extra_minutes": 0}}"""


def build_script_prompt(
    target_date: str,
    ep_num: int,
    characters: dict[str, Any],
    day_plan: dict[str, Any],
    special_meta: dict[str, Any] | None,
    tomorrow_preview: dict[str, Any],
    knowledge_entries: list[dict[str, Any]],
    live_bundle: dict[str, Any],
    research_summary: str,
    grounded_links: list[dict[str, str]],
    dedup_ctx: dict[str, Any] | None = None,
) -> str:
    """Build Phase B prompt to generate structured episode.json with holiday/special/dedup/editorial support."""
    day_cfg = day_plan["day_cfg"]
    koharu = characters["hosts"]["koharu"]
    heizo = characters["hosts"]["heizo"]
    guest = day_cfg["guest"]
    recent_logs = json.dumps(knowledge_entries[-7:], ensure_ascii=False, indent=2)
    weather_json = json.dumps(live_bundle["weather"], ensure_ascii=False)
    quakes_json = json.dumps(live_bundle["earthquakes"][:4], ensure_ascii=False)
    links_json = json.dumps(grounded_links, ensure_ascii=False, indent=2)
    dedup = dedup_ctx or build_dedup_context(target_date, day_plan, [])
    editorial_block = _format_editorial_guide_block(day_plan)
    fresh_kws_str = ", ".join(dedup["fresh_keywords"])
    covered_kws_str = ", ".join(dedup["expert_covered_keywords"]) or "なし"

    holiday_instruction = ""
    if day_plan["is_holiday"]:
        holiday_instruction = (
            f"- **祝日拡大版ポイント**: 本日は国民の祝日「{day_plan['holiday_name']}」です！"
            f"オープニングで祝日の挨拶とともに、休日の小平のお出かけ・防災点検の楽しみ方を盛り込んで15分拡大版としてゆったり届けてください。"
        )

    if special_meta:
        segment_rules = f"""## 7. セグメント構成（特別コーナー含む全6コーナー構成を厳守）
1. `id: "opening"` / `intro_jingle: "opening_jingle"` / `bgm: "bgm_warm"` / `outro_jingle: null` — 朝7時の挨拶・小平市の今朝の天気＆直近地震・季節の小平トーク
2. `id: "kodaira_life"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null` — 小平が好きになる今日のまち・生活・防災トピック
3. `id: "guest_talk"` / `intro_jingle: "guest_jingle"` / `bgm: "{day_cfg['bgm_mood']}"` / `outro_jingle: null` — 本日のテーマ「{day_cfg['theme_name']}」専門家 {guest['name']} さんの深掘り解説＆3人の掛け合い
4. `id: "special_feature"` / `intro_jingle: "stinger"` / `bgm: "bgm_feature"` / `outro_jingle: null` — **【特別拡大コーナー】{special_meta['title']}（{special_meta['phase_label']}）**：{special_meta['focus']} について小春・平蔵（必要に応じてゲストも参加）で分かりやすく特集！
5. `id: "daily_bousai"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null` — 暮らしに直結する防災チェック・自治体サービス案内
6. `id: "ending"` / `intro_jingle: "stinger"` / `bgm: "bgm_warm"` / `outro_jingle: "outro_jingle"` — 今日の「小春＆平蔵の防災ノート」まとめ＆【明日の予告】＆いってらっしゃい！"""
    else:
        segment_rules = f"""## 7. セグメント構成（全5コーナー構成を厳守）
1. `id: "opening"` / `intro_jingle: "opening_jingle"` / `bgm: "bgm_warm"` / `outro_jingle: null` — 朝7時の挨拶・小平市の今朝の天気＆直近地震・季節の小平トーク
2. `id: "kodaira_life"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null` — 小平が好きになる今日のまち・生活・防災トピック
3. `id: "guest_talk"` / `intro_jingle: "guest_jingle"` / `bgm: "{day_cfg['bgm_mood']}"` / `outro_jingle: null` — 本日のテーマ「{day_cfg['theme_name']}」専門家 {guest['name']} さんの深掘り解説＆3人の質疑応答・掛け合い
4. `id: "daily_bousai"` / `intro_jingle: "stinger"` / `bgm: "bgm_news"` / `outro_jingle: null` — 暮らしに直結する防災チェック・自治体サービスやイベント案内
5. `id: "ending"` / `intro_jingle: "stinger"` / `bgm: "bgm_warm"` / `outro_jingle: "outro_jingle"` — 今日の「小春＆平蔵の防災ノート」まとめ＆【明日の予告】＆いってらっしゃい！"""

    return f"""あなたは「{characters['program']['title']}」のメイン構成作家です。
以下の条件・設定・事実データをもとに、ラジオ番組1回分の完全台本JSONを生成してください。

## 1. 放送メタ条件
- 放送日: {target_date}（{day_plan['weekday_ja']}） / 第{ep_num}回
- 番組編成: {day_plan['edition_label']}（目標 {round(day_plan['target_duration_sec'] / 60)}分）
- **必須文字数目標**: 全セリフの `text` 合計文字数を **{day_plan['min_chars']}〜{day_plan['max_chars']}文字（目標 {day_plan['target_chars']}文字）** に収めること。
{holiday_instruction}
- **明日の予告（ending セグメントで必ず触れること）**:
  {tomorrow_preview['preview_hint']}

{editorial_block}

## 2. 登場人物（スピーカーIDは必ず `koharu`, `heizo`, `guest` のみ使用）
- `koharu`（小春）: {koharu['personality']}
- `heizo`（平蔵）: {heizo['personality']}
- `guest`（{guest['name']} / {guest['title']}）: {guest['personality']} 小平とのつながり: {guest['kodaira_connection']}
- 今回優先すべき未解説キーワード候補（この中から2〜4個を必ず噛み砕いて解説）: {fresh_kws_str}

### ★ 発言の信頼性・事実厳守ルール（超重要）
- **嘘・捏造ゼロ原則**: イベント日時（特に「{target_date[:4]}年」の正確な日程か）、小平市内の施設場所・開館情報・店舗情報、電話番号、防災数値は上記調査と公式データで確認できた事実のみを書くこと。不確かな具体日時や未確認イベントは絶対に書かない。
- **小春（`koharu`）の表現方針**: 防災初心者として「〜かも？」「〜なのかな？」とお茶目に予想・質問するのは大歓迎です。ただし、小春が迷ったり勘違いしそうなセリフを入れた場合は、**直後のターンで必ず平蔵または専門家ゲストが正しい事実をやさしく補足・訂正し、リスナーに誤認を残さない構成**にすること。また小春も、架空のイベント日時や実在しない店舗情報は絶対に口にしないこと。
- **平蔵（`heizo`）・専門家ゲスト（`guest`）の厳格信頼性**: 専門知識・数値（耐震基準年、応急手当の回数・手順、備蓄基準量、警戒レベル、法律・行政制度など）や小平市の施設・イベント日時・電話番号は **一切推測や誇張・脚色をせず、確認できた正確な事実のみ** を語ること。

## 3. 重複禁止ルール（厳守）
- **直近14日間の小平ローカル話題（同じネタ・場所の繰り返し禁止）**:
{dedup['recent_local_text']}
- **この専門家（{guest['name']}）が過去3か月（90日）間に解説済みの専門用語・テーマ（同ネタ禁止）**:
  既出: {covered_kws_str}
{dedup['expert_history_text']}
※ 連続成長として一言振り返るのは良いですが、本日のメイン話題や解説用語には**必ず上記と重ならない新しい内容**を選んでください。

## 4. 連続成長・過去の学び（自然な流れで振り返りや成長を取り入れる）
{recent_logs}

## 5. ライブ気象・地震・調査ブリーフィング（事実厳守）
小平市気象: {weather_json}
直近地震: {quakes_json}
調査ブリーフィング:
{research_summary}

利用可能な検証済み公式リンク候補:
{links_json}

## 6. Gemini 3.8 Flash TTS 表現力ルール（超重要）
- 各セリフは `speaker`, `text`, `tts_text`, `style`, `pause_after` を持つ。
- **`text`（画面表示用）**: `<laugh>` 等のタグは絶対に入れず、自然な日本語台本にする。
- **`tts_text`（Gemini 3.8 Flash TTS 読み上げ用）**:
  - 笑い・相槌・間合いを豊かにするため、半角英語の山括弧タグ `<laugh>`, `<chuckle>`, `<giggle>`, `<sigh>`, `<breath>`, `<short pause>` を会話の自然な位置にバランスよく入れる。
  - 演技のト書き（「明るく笑って：」など）は絶対に `tts_text` に書かないこと。
  - 難読の小平地名（小川町=おがわちょう、津田町=つだまち、御幸町=みゆきちょう、上水南町=じょうすいみなみちょう、狭山・境緑道=さやま・さかいりょくどう 等）や電話番号、英略語は `tts_text` 内でかな・カタカナ読みに開く。
- **`style`**: 各ターンごとの英語の短い演技ディレクション。
- **話者配列ルール**: 1つの会話ブロック内で自然に掛け合いできるよう、できるだけ `小春⇄ゲスト`、`平蔵⇄ゲスト`、`小春⇄平蔵` の2〜4往復ペアが連なる進行にすること。

{segment_rules}

## 8. 出力JSONスキーマ（厳密にこのキー構造のJSONのみ出力）
{{
  "subtitle": "第{ep_num}回・{target_date}（{day_plan['weekday_ja']}）朝7時号 ― テーマ要約サブタイトル",
  "keywords_featured": ["解説した専門用語1", "専門用語2", "専門用語3"],
  "kodaira_topics": ["今回取り上げた小平の施設・イベント・まちネタ1", "まちネタ2"],
  "kodaira_areas": ["今回登場した小平市内のエリア・駅・施設名1", "エリア2"],
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


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Parse JSON from model output, tolerating optional markdown code fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _format_usage(resp: Any) -> str:
    """Safely format token counts from response.usage_metadata for logs."""
    usage = getattr(resp, "usage_metadata", None)
    if not usage:
        return "usage=n/a"
    fields = (
        ("in", "prompt_token_count"),
        ("out", "candidates_token_count"),
        ("think", "thoughts_token_count"),
        ("total", "total_token_count"),
    )
    parts: list[str] = []
    for label, attr in fields:
        val = getattr(usage, attr, None)
        if val is not None:
            parts.append(f"{label}={val}")
    return ", ".join(parts) if parts else "usage=n/a"


def _assemble_and_validate_episode(
    raw_generated: dict[str, Any],
    target_date: str,
    ep_num: int,
    characters: dict[str, Any],
    day_plan: dict[str, Any],
    special_meta: dict[str, Any] | None,
    tomorrow_preview: dict[str, Any],
    live_bundle: dict[str, Any],
    fallback_links: list[dict[str, str]],
    research_model: str = DEFAULT_RESEARCH_MODEL,
    script_model: str = DEFAULT_SCRIPT_MODEL,
    factcheck_model: str = DEFAULT_FACTCHECK_MODEL,
) -> dict[str, Any]:
    """Wrap generated segments with full program metadata and validate every line."""
    day_cfg = day_plan["day_cfg"]
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
        lk
        for lk in raw_links
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
            or f"第{ep_num}回・{target_date}（{day_plan['weekday_ja']}）朝7時号 ― {day_cfg['theme_name']}",
            "episode_date": target_date,
            "episode_number": ep_num,
            "weekday": day_plan["day_key"],
            "weekday_ja": day_plan["weekday_ja"],
            "is_weekend": bool(day_plan["is_weekend"]),
            "is_holiday": bool(day_plan["is_holiday"]),
            "holiday_name": day_plan["holiday_name"],
            "edition_label": day_plan["edition_label"],
            "special_feature": special_meta,
            "tomorrow_preview": {
                "date": tomorrow_preview["date"],
                "edition_label": tomorrow_preview["edition_label"],
                "is_holiday": tomorrow_preview["is_holiday"],
                "holiday_name": tomorrow_preview["holiday_name"],
                "has_special": bool(tomorrow_preview.get("scheduled_special")),
            },
            "theme_name": day_cfg["theme_name"],
            "theme_badge": day_cfg["theme_badge"],
            "target_duration_sec": int(day_plan["target_duration_sec"]),
            "output_filename": f"kodaira_radio_{date_compact}.mp3",
            "kodaira_topics": [
                str(t).strip()
                for t in (raw_generated.get("kodaira_topics") or [])
                if str(t).strip()
            ],
            "kodaira_areas": [
                str(a).strip()
                for a in (raw_generated.get("kodaira_areas") or [])
                if str(a).strip()
            ],
            "models": {
                "research": research_model,
                "script": script_model,
                "factcheck": factcheck_model,
            },
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


def _format_episode_for_factcheck(episode: dict[str, Any]) -> str:
    """Render episode script, references, notes, and links with exact indices for auditing."""
    meta = episode.get("meta", {})
    out: list[str] = [f"[subtitle] {meta.get('subtitle', '')}", ""]

    out.append("## 台本セリフ一覧")
    for s_idx, seg in enumerate(episode.get("segments") or []):
        out.append(f"### Segment {s_idx}: {seg.get('id', '')} | {seg.get('title', '')}")
        for l_idx, line in enumerate(seg.get("lines") or []):
            out.append(
                f"[seg:{s_idx} line:{l_idx}] {line.get('speaker', '')} | {line.get('text', '')}"
            )
        out.append("")

    notes = episode.get("learned_notes") or {}
    out.append("## 防災ノート")
    for n_idx, pt in enumerate(notes.get("learned_points") or []):
        out.append(f"[learned_point:{n_idx}] {pt}")
    if notes.get("kodaira_discovery"):
        out.append(f"[kodaira_discovery] {notes['kodaira_discovery']}")

    refs = episode.get("references") or []
    if refs:
        out.append("\n## 防災メモ・連絡先")
        for r_idx, ref in enumerate(refs):
            out.append(
                f"[reference:{r_idx}] {ref.get('category', '')} | {ref.get('title', '')} | "
                f"{ref.get('detail', '')} | contact={ref.get('contact', '')}"
            )

    links = episode.get("links") or []
    if links:
        out.append("\n## 関連リンク")
        for l_idx, lk in enumerate(links):
            out.append(
                f"[link:{l_idx}] {lk.get('category', '')} | {lk.get('title', '')} | "
                f"{lk.get('url', '')} | {lk.get('note', '')}"
            )

    return "\n".join(out)


def build_factcheck_prompt(
    episode: dict[str, Any],
    live_bundle: dict[str, Any],
    research_summary: str,
) -> str:
    """Build Phase C fact-check and surgical correction prompt using Google Search grounding."""
    meta = episode.get("meta", {})
    guest = episode.get("guest", {})
    ep_date = str(meta.get("episode_date") or "")
    year_str = ep_date[:4] or str(datetime.now(JST).year)
    weekday_ja = str(meta.get("weekday_ja") or "")
    formatted_ep = _format_episode_for_factcheck(episode)
    weather_json = json.dumps(live_bundle.get("weather") or {}, ensure_ascii=False)
    quakes_json = json.dumps((live_bundle.get("earthquakes") or [])[:5], ensure_ascii=False)

    return f"""あなたは東京都小平市のラジオ番組「こだいら防災＆まちラジオ」の厳格なファクトチェッカー（校閲責任者）です。
Google検索ツールを使って、以下の放送台本・防災メモ・関連リンクに含まれる具体的な事実主張を徹底的に裏取りし、誤情報や根拠のない日付・数値があればピンポイントの修正案を出力してください。

対象放送日: {ep_date}（{weekday_ja} / {year_str}年）
担当専門家ゲスト: {guest.get('name', '')}（{guest.get('title', '')}）

## 監査の4つの観点（厳守）
1. **小平のイベント日程・開催年・施設情報の照合（最重要）**:
   - 台本・ノート内のイベント名、施設名、所在地・最寄駅、営業時間・開館日、開催日時をGoogle検索で実際に確認すること。
   - **特に「前年の開催日や曜日を {year_str}年（本日 {ep_date}）の開催と混同していないか」** を必ず検索して確認すること（例：昨年は11/23開催でも今年は11/22開催など）。本日開催と書いてあるイベントが別日開催や終了済みなら `severity: "critical"` とし、正しい日付へ修正するか、裏付けが取れない具体日時は削除・一般的な常設案内へ書き換えること。
2. **平蔵（`heizo`）・専門家（`guest`）の発言および防災ノートの厳格検証**:
   - 防災知識、数値基準、ガイドライン、法律・耐震基準年、応急手当の回数・手順（例：胸骨圧迫の回数、備蓄水・トイレ量、警戒レベル等）、小平市の公式窓口・電話番号に誤りがないかGoogle検索で裏取りすること。
   - 誤った数値・制度説明は必ず正しい公式情報へ修正すること。
3. **小春（`koharu`）のキャラクター配慮**:
   - 小春が防災初心者として「〜かも？」「〜なのかな？」とお茶目に予想・質問しているだけで、**直後のターン（次のセリフ等）で平蔵や専門家が正しく訂正・補足している場合は演出として許容し、修正不要**。
   - ただし、**誰も訂正しないまま放置された誤認識** や、**小春が根拠のない架空イベント日時・店名を言い切っている箇所** は `issues` として修正すること。
4. **気象・地震・リンクの整合性**:
   - 下記の公式気象・地震データと矛盾する天気・気温・地震情報、または無効・誤った参照情報がないか確認すること。
   - 問題が見つからない項目まで無理に粗探しして書き換えないこと（キャラクターの口調・`<laugh>`等の感情タグ・かな読みはできるだけ維持する）。

参考ライブ気象データ:
{weather_json}

参考直近地震データ:
{quakes_json}

参考Phase A調査メモ:
{research_summary}

## 検査対象の台本・付帯情報
{formatted_ep}

## 出力形式
最初に簡潔な監査メモを書いたあと、**必ず最後に以下の区切り行とJSONオブジェクトのみ**を出力してください。
問題がない場合は `"status": "passed"`、`"issues": []` としてください。修正が必要な場合は `"status": "patched"` として `issues` に該当箇所ごとの修正データを入れてください。

`issues` 内の各要素で使える `target_type`:
- `"line"`: `seg_index`(整数), `line_index`(整数), `fixed_text`(表示用・`<...>`タグ禁止), `fixed_tts_text`(読み上げ用・必要に応じタグ維持)
- `"subtitle"`: `fixed_value`
- `"learned_point"`: `index`(整数), `fixed_value`
- `"kodaira_discovery"`: `fixed_value`
- `"reference"`: `index`(整数), `action`(`"replace"` または `"remove"`), `fixed_title`, `fixed_detail`, `fixed_contact`
- `"link"`: `index`(整数), `action`(`"replace"` または `"remove"`), `fixed_url`(`https://...`), `fixed_title`, `fixed_note`

=== FACT_CHECK_JSON ===
{{
  "status": "passed",
  "checked_claims_count": 10,
  "issues": [
    {{
      "severity": "critical",
      "target_type": "line",
      "seg_index": 0,
      "line_index": 0,
      "claim": "問題のある主張の抜粋",
      "reason": "検索で確認した誤りの理由",
      "verified_fact": "確認できた正しい事実",
      "fixed_text": "自然な修正後の表示セリフ（タグなし）",
      "fixed_tts_text": "修正後のTTS読み上げセリフ"
    }}
  ],
  "summary": "全体のファクトチェック総評（1〜2文）"
}}"""


def _parse_fact_check_result(raw_text: str) -> dict[str, Any]:
    """Extract structured JSON from Phase C fact-check output safely."""
    marker = "=== FACT_CHECK_JSON ==="
    candidates: list[str] = []
    if marker in raw_text:
        candidates.append(raw_text.rsplit(marker, 1)[1])
    candidates.append(raw_text)

    decoder = json.JSONDecoder()
    for block in candidates:
        cleaned = block.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        for idx in (m.start() for m in re.finditer(r"\{", cleaned)):
            try:
                obj, _ = decoder.raw_decode(cleaned, idx)
                if isinstance(obj, dict) and ("issues" in obj or "status" in obj):
                    return obj
            except json.JSONDecodeError:
                continue

    return {
        "status": "parse_warning",
        "checked_claims_count": 0,
        "issues": [],
        "summary": "Fact-check JSON parse failed; kept original draft.",
    }


def _apply_fact_check_patches(
    episode: dict[str, Any],
    fc_result: dict[str, Any],
    factcheck_model: str,
) -> dict[str, Any]:
    """Apply validated Phase C surgical corrections to episode and record audit metadata."""
    issues = [it for it in (fc_result.get("issues") or []) if isinstance(it, dict)]
    segments = episode.get("segments") or []
    notes = episode.setdefault("learned_notes", {})
    learned_pts = notes.get("learned_points") or []
    refs = episode.get("references") or []
    links = episode.get("links") or []

    patches_applied = 0
    ref_removals: set[int] = set()
    link_removals: set[int] = set()

    for it in issues:
        t_type = str(it.get("target_type") or "").strip()
        if t_type == "line":
            try:
                s_idx = int(it["seg_index"])
                l_idx = int(it["line_index"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= s_idx < len(segments)):
                continue
            lines = segments[s_idx].get("lines") or []
            if not (0 <= l_idx < len(lines)):
                continue
            fixed_text = _strip_tags(str(it.get("fixed_text") or ""))
            if not fixed_text:
                continue
            fixed_tts = str(it.get("fixed_tts_text") or fixed_text).strip() or fixed_text
            lines[l_idx]["text"] = fixed_text
            lines[l_idx]["tts_text"] = fixed_tts
            patches_applied += 1
        elif t_type == "subtitle":
            val = _strip_tags(str(it.get("fixed_value") or ""))
            if val:
                episode["meta"]["subtitle"] = val
                patches_applied += 1
        elif t_type == "learned_point":
            try:
                idx = int(it["index"])
            except (KeyError, TypeError, ValueError):
                continue
            val = _strip_tags(str(it.get("fixed_value") or ""))
            if 0 <= idx < len(learned_pts) and val:
                learned_pts[idx] = val
                patches_applied += 1
        elif t_type == "kodaira_discovery":
            val = _strip_tags(str(it.get("fixed_value") or ""))
            if val:
                notes["kodaira_discovery"] = val
                patches_applied += 1
        elif t_type == "reference":
            try:
                idx = int(it["index"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= idx < len(refs)):
                continue
            action = str(it.get("action") or "replace").lower()
            if action == "remove":
                ref_removals.add(idx)
                patches_applied += 1
            else:
                if it.get("fixed_title"):
                    refs[idx]["title"] = _strip_tags(str(it["fixed_title"]))
                if it.get("fixed_detail"):
                    refs[idx]["detail"] = _strip_tags(str(it["fixed_detail"]))
                if "fixed_contact" in it and it["fixed_contact"] is not None:
                    refs[idx]["contact"] = _strip_tags(str(it["fixed_contact"]))
                patches_applied += 1
        elif t_type == "link":
            try:
                idx = int(it["index"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= idx < len(links)):
                continue
            action = str(it.get("action") or "replace").lower()
            if action == "remove":
                link_removals.add(idx)
                patches_applied += 1
            else:
                new_url = str(it.get("fixed_url") or "").strip()
                if new_url.startswith("https://"):
                    links[idx]["url"] = new_url
                if it.get("fixed_title"):
                    links[idx]["title"] = _strip_tags(str(it["fixed_title"]))
                if it.get("fixed_note"):
                    links[idx]["note"] = _strip_tags(str(it["fixed_note"]))
                patches_applied += 1

    for idx in sorted(ref_removals, reverse=True):
        if 0 <= idx < len(refs):
            refs.pop(idx)
    for idx in sorted(link_removals, reverse=True):
        if 0 <= idx < len(links) and len(links) > 1:
            links.pop(idx)

    raw_status = str(fc_result.get("status") or "").strip()
    if patches_applied > 0:
        final_status = "patched"
    elif raw_status:
        final_status = raw_status
    else:
        final_status = "passed"

    episode.setdefault("meta", {})["fact_check"] = {
        "model": factcheck_model,
        "status": final_status,
        "checked_claims_count": int(fc_result.get("checked_claims_count") or 0),
        "issues_found": len(issues),
        "patches_applied": patches_applied,
        "summary": str(fc_result.get("summary") or "").strip(),
        "issues": [
            {
                "severity": str(it.get("severity") or "warning"),
                "claim": str(it.get("claim") or "")[:160],
                "reason": str(it.get("reason") or "")[:240],
                "verified_fact": str(it.get("verified_fact") or "")[:240],
            }
            for it in issues[:12]
        ],
    }
    return episode


def run_fact_check(
    client: genai.Client,
    episode: dict[str, Any],
    live_bundle: dict[str, Any],
    research_summary: str,
    factcheck_model: str = DEFAULT_FACTCHECK_MODEL,
) -> dict[str, Any]:
    """Execute Phase C grounded fact-check audit and apply surgical patches before saving/TTS."""
    fc_prompt = build_factcheck_prompt(episode, live_bundle, research_summary)
    fc_cfg_kwargs: dict[str, Any] = {"tools": [{"google_search": {}}]}
    if factcheck_model.startswith("gemini-4"):
        fc_cfg_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MEDIUM,
        )

    print(f"Phase C: Auditing facts & dates via {factcheck_model} + Google Search...")
    fc_resp = client.models.generate_content(
        model=factcheck_model,
        contents=fc_prompt,
        config=types.GenerateContentConfig(**fc_cfg_kwargs),
    )
    print(f"Phase C usage   : {_format_usage(fc_resp)}")

    raw_fc = getattr(fc_resp, "text", "") or ""
    fc_result = _parse_fact_check_result(raw_fc)
    patched = _apply_fact_check_patches(episode, fc_result, factcheck_model)
    fc_meta = patched["meta"]["fact_check"]
    print(
        f"Phase C result  : status={fc_meta['status']} | claims={fc_meta['checked_claims_count']} | "
        f"issues={fc_meta['issues_found']} | patched={fc_meta['patches_applied']}"
    )
    if fc_meta["summary"]:
        print(f"Phase C summary : {fc_meta['summary']}")
    return patched


def _update_knowledge_log(episode: dict[str, Any]) -> None:
    """Append episode learned_notes into data/knowledge_log.json without duplicating dates."""
    log_path = DATA_DIR / "knowledge_log.json"
    data = _load_json(log_path) if log_path.exists() else {"entries": []}

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


def _update_topic_history(episode: dict[str, Any]) -> None:
    """Append episode topics, areas, and expert keywords into data/topic_history.json."""
    hist_path = DATA_DIR / "topic_history.json"
    data = _load_json(hist_path) if hist_path.exists() else {"entries": []}

    meta = episode["meta"]
    guest = episode.get("guest", {})
    ep_date = meta["episode_date"]
    sp = meta.get("special_feature")
    sp_title = sp.get("title") if isinstance(sp, dict) else None

    entries: list[dict[str, Any]] = [
        e for e in data.get("entries", []) if isinstance(e, dict) and e.get("date") != ep_date
    ]
    entries.append(
        {
            "date": ep_date,
            "weekday": meta.get("weekday_ja", ""),
            "day_key": meta.get("weekday", ""),
            "episode_number": meta.get("episode_number"),
            "theme": meta.get("theme_name", ""),
            "guest_id": guest.get("id", ""),
            "guest_name": guest.get("name", ""),
            "subtitle": meta.get("subtitle", ""),
            "kodaira_topics": meta.get("kodaira_topics") or [],
            "kodaira_areas": meta.get("kodaira_areas") or [],
            "keywords_featured": guest.get("keywords_featured") or [],
            "special_feature_title": sp_title,
        }
    )
    entries.sort(key=lambda e: e["date"])
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")


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
        "--research-model",
        default=DEFAULT_RESEARCH_MODEL,
        help="Gemini model for Phase A research & Google Search grounding",
    )
    parser.add_argument(
        "--script-model",
        default=DEFAULT_SCRIPT_MODEL,
        help="Gemini model for Phase B JSON script writing",
    )
    parser.add_argument(
        "--factcheck-model",
        default=DEFAULT_FACTCHECK_MODEL,
        help="Gemini model for Phase C grounded fact-check audit",
    )
    parser.add_argument(
        "--skip-factcheck",
        action="store_true",
        help="Skip Phase C grounded fact-check pass",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional single model override for Phase A, B, and C",
    )
    args = parser.parse_args()
    research_model = args.model or args.research_model
    script_model = args.model or args.script_model
    factcheck_model = args.model or args.factcheck_model

    load_dotenv(ROOT_DIR / ".env")
    target_date = args.date

    ep_dir = EPISODES_DIR / target_date
    ep_json_path = ep_dir / "episode.json"
    if ep_json_path.exists() and not args.force and not args.dry_run_prompt:
        print(f"Episode already exists at {ep_json_path}; skipping (use --force to regenerate).")
        return

    characters = _load_json(CONFIG_DIR / "characters.json")
    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    special_days = (
        _load_json(CONFIG_DIR / "special_days.json")
        if (CONFIG_DIR / "special_days.json").exists()
        else {"recurring": [], "dated_events": []}
    )
    knowledge_data = (
        _load_json(DATA_DIR / "knowledge_log.json")
        if (DATA_DIR / "knowledge_log.json").exists()
        else {"entries": []}
    )
    topic_history_data = (
        _load_json(DATA_DIR / "topic_history.json")
        if (DATA_DIR / "topic_history.json").exists()
        else {"entries": []}
    )
    editorial_plan = (
        _load_json(DATA_DIR / "editorial_plan.json")
        if (DATA_DIR / "editorial_plan.json").exists()
        else None
    )

    day_plan = resolve_day_plan(target_date, themes, special_days, editorial_plan=editorial_plan)
    tomorrow_preview = resolve_tomorrow_preview(
        target_date, themes, special_days, editorial_plan=editorial_plan
    )
    ep_num = _next_episode_number(target_date)
    dedup_ctx = build_dedup_context(
        target_date, day_plan, topic_history_data.get("entries", [])
    )

    print(
        f"Collecting live Kodaira feeds for {target_date} ({day_plan['weekday_ja']} / {day_plan['edition_label']})..."
    )
    live_bundle = collect_live_briefing()
    live_quake_special = _detect_live_quake_special(live_bundle["earthquakes"])
    research_prompt = build_research_prompt(
        target_date, day_plan, live_bundle, dedup_ctx=dedup_ctx
    )

    if args.dry_run_prompt:
        plan_preview, special_meta = _apply_breaking_extension(day_plan, live_quake_special)
        sample_script_prompt = build_script_prompt(
            target_date=target_date,
            ep_num=ep_num,
            characters=characters,
            day_plan=plan_preview,
            special_meta=special_meta,
            tomorrow_preview=tomorrow_preview,
            knowledge_entries=knowledge_data.get("entries", []),
            live_bundle=live_bundle,
            research_summary="[Dry-run: Phase A Google Search grounding output goes here]",
            grounded_links=live_bundle["verified_links"],
            dedup_ctx=dedup_ctx,
        )
        eg = plan_preview.get("editorial_guide") or {}
        eg_sp = eg.get("editorial_special") if isinstance(eg.get("editorial_special"), dict) else None
        eg_desc = (
            f"{eg.get('focus_area', '-')} | {eg.get('kodaira_angle', '-')}"
            + (f" [Special: {eg_sp.get('title')}]" if eg_sp and eg_sp.get("title") else "")
            if eg
            else "None"
        )
        print("\n=== DRY RUN CONFIG SUMMARY ===")
        print(f"Date            : {target_date} ({plan_preview['weekday_ja']}) | Episode #{ep_num}")
        fc_label = "SKIPPED" if args.skip_factcheck else factcheck_model
        print(f"Models          : research={research_model} | script={script_model} | factcheck={fc_label}")
        print(f"Edition         : {plan_preview['edition_label']}")
        print(f"Holiday         : {plan_preview['is_holiday']} ({plan_preview['holiday_name'] or '-'})")
        print(f"Target          : {plan_preview['target_duration_sec']}s / ~{plan_preview['target_chars']} chars ({plan_preview['min_chars']}~{plan_preview['max_chars']})")
        print(f"Theme / Guest   : {plan_preview['day_cfg']['theme_name']} / {plan_preview['day_cfg']['guest']['name']} ({plan_preview['day_cfg']['guest']['voice_name']})")
        print(f"Special Feature : {special_meta['title'] + ' [' + special_meta['phase_label'] + ']' if special_meta else 'None'}")
        print(f"Editorial Guide : {eg_desc}")
        print(f"Dedup 14d Local : {dedup_ctx['recent_local_count']} recent topic(s)")
        print(f"Dedup 90d Expert: {len(dedup_ctx['expert_covered_keywords'])} covered keyword(s) | Fresh candidates: {len(dedup_ctx['fresh_keywords'])}")
        print(f"Tomorrow Preview: {tomorrow_preview['preview_hint']}")
        print(f"Has special_feat: {'special_feature' in sample_script_prompt}")
        return

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        print(
            "ERROR: GEMINI_API_KEY is not set. Copy .env.example to .env and add your Gemini API key.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    research_cfg_kwargs: dict[str, Any] = {
        "tools": [{"google_search": {}}],
    }
    if research_model.startswith("gemini-4"):
        research_cfg_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MEDIUM,
        )
    print(f"Phase A: Researching latest Kodaira & disaster news via {research_model} + Google Search...")
    research_resp = client.models.generate_content(
        model=research_model,
        contents=research_prompt,
        config=types.GenerateContentConfig(**research_cfg_kwargs),
    )
    print(f"Phase A usage   : {_format_usage(research_resp)}")
    raw_research = getattr(research_resp, "text", "") or ""
    research_text, breaking_special = _parse_breaking_special(raw_research, live_quake_special)
    grounded_links = _extract_grounding_links(research_resp, live_bundle["verified_links"])

    final_plan, special_meta = _apply_breaking_extension(day_plan, breaking_special)
    print(
        f"Phase B: Generating script via {script_model} "
        f"({final_plan['edition_label']}, target ~{final_plan['target_chars']} chars)..."
    )

    script_prompt = build_script_prompt(
        target_date=target_date,
        ep_num=ep_num,
        characters=characters,
        day_plan=final_plan,
        special_meta=special_meta,
        tomorrow_preview=tomorrow_preview,
        knowledge_entries=knowledge_data.get("entries", []),
        live_bundle=live_bundle,
        research_summary=research_text,
        grounded_links=grounded_links,
        dedup_ctx=dedup_ctx,
    )
    script_resp = client.models.generate_content(
        model=script_model,
        contents=script_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    print(f"Phase B usage   : {_format_usage(script_resp)}")
    raw_json = _parse_json_response(getattr(script_resp, "text", "") or "")
    episode = _assemble_and_validate_episode(
        raw_generated=raw_json,
        target_date=target_date,
        ep_num=ep_num,
        characters=characters,
        day_plan=final_plan,
        special_meta=special_meta,
        tomorrow_preview=tomorrow_preview,
        live_bundle=live_bundle,
        fallback_links=grounded_links,
        research_model=research_model,
        script_model=script_model,
        factcheck_model="skipped" if args.skip_factcheck else factcheck_model,
    )

    if not args.skip_factcheck:
        episode = run_fact_check(
            client=client,
            episode=episode,
            live_bundle=live_bundle,
            research_summary=research_text,
            factcheck_model=factcheck_model,
        )

    ep_dir.mkdir(parents=True, exist_ok=True)
    ep_json_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_knowledge_log(episode)
    _update_topic_history(episode)

    total_lines = sum(len(s["lines"]) for s in episode["segments"])
    total_chars = sum(len(l["text"]) for s in episode["segments"] for l in s["lines"])
    print(f"Generated episode.json: {ep_json_path} ({total_lines} lines, {total_chars} chars)")


if __name__ == "__main__":
    main()
