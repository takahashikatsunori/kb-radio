"""Weekly Chief Editor AI planner: investigates upcoming Kodaira events & builds data/editorial_plan.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from generate_episode import (
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_SCRIPT_MODEL,
    JST,
    _format_usage,
    _load_json,
    _parse_json_response,
    build_dedup_context,
)
from kodaira_spots import (
    SPOT_COOLDOWN_DAYS,
    audit_plan_spot_overlaps,
    compute_spot_usage,
    format_spot_candidates_block,
    format_spot_cooldown_block,
    load_kodaira_spots,
    match_spots_in_text,
    select_balanced_spot_candidates,
)
from schedule_calendar import resolve_day_plan

EDITORIAL_PLAN_PATH = DATA_DIR / "editorial_plan.json"


def _default_next_monday(
    now_jst: datetime,
    existing_plan: dict[str, Any] | None = None,
) -> date:
    """Return upcoming Monday in JST; if early Monday (<06:00 JST) & today is missing, target today."""
    if now_jst.weekday() == 0 and now_jst.hour < 6:
        existing_dates = {
            str(g.get("date"))
            for g in ((existing_plan or {}).get("daily_guides") or [])
            if isinstance(g, dict) and g.get("date")
        }
        if now_jst.date().isoformat() not in existing_dates:
            return now_jst.date()
    days_ahead = 7 - now_jst.weekday()
    return (now_jst + timedelta(days=days_ahead)).date()


def _build_week_skeleton(
    start_dt: date,
    num_days: int,
    themes: dict[str, Any],
    special_days: dict[str, Any],
    topic_history_entries: list[dict[str, Any]],
    program_schedule: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build day-by-day calendar, special-day lockouts, pre-planned expert schedule, and 90-day dedup data."""
    rows: list[dict[str, Any]] = []
    for offset in range(num_days):
        d_str = (start_dt + timedelta(days=offset)).isoformat()
        plan = resolve_day_plan(
            d_str,
            themes,
            special_days,
            editorial_plan=None,
            program_schedule=program_schedule,
        )
        dedup = build_dedup_context(d_str, plan, topic_history_entries)
        guest = plan["day_cfg"]["guest"]
        sp = plan.get("scheduled_special")
        ps = plan.get("program_schedule") or {}
        rows.append(
            {
                "date": d_str,
                "weekday_ja": plan["weekday_ja"],
                "day_key": plan["day_key"],
                "edition_label": plan["edition_label"],
                "is_holiday": plan["is_holiday"],
                "holiday_name": plan["holiday_name"],
                "theme_name": plan["day_cfg"]["theme_name"],
                "guest_id": guest["id"],
                "guest_name": guest["name"],
                "has_existing_special": sp is not None,
                "existing_special_desc": (
                    f"{sp['title']}（{sp['phase_label']}）" if sp else None
                ),
                "preplanned_expert_topics": ps.get("expert_topics") or [],
                "preplanned_expert_note": ps.get("expert_note") or "",
                "preplanned_kodaira_hint": ps.get("kodaira_hint") or "",
                "special_request": ps.get("special_request") or "",
                "schedule_locked": bool(ps.get("locked")),
                "expert_covered_90d": dedup["expert_covered_keywords"],
                "expert_fresh_candidates": dedup["fresh_keywords"][:5],
            }
        )
    return rows


def _format_recent_history(
    start_dt: date,
    topic_history_entries: list[dict[str, Any]],
    existing_plan: dict[str, Any] | None = None,
) -> str:
    """Format recent aired & already-planned broadcast topics/areas (90-day window) to avoid repetition."""
    lines: list[str] = []
    seen_dates: set[str] = set()
    sorted_entries = sorted(
        (e for e in topic_history_entries if isinstance(e, dict) and e.get("date")),
        key=lambda e: e["date"],
        reverse=True,
    )
    for e in sorted_entries:
        try:
            e_dt = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (start_dt - e_dt).days <= SPOT_COOLDOWN_DAYS:
            seen_dates.add(str(e["date"]))
            areas = ", ".join(e.get("kodaira_areas") or [])
            topics = "; ".join(e.get("kodaira_topics") or [])
            kws = ", ".join(e.get("keywords_featured") or [])
            lines.append(
                f"- {e['date']} [放送済]（{e.get('weekday', '')}・{e.get('guest_name', '')}）: "
                f"エリア=[{areas}] / 話題=[{topics}] / 専門用語=[{kws}]"
            )

    if isinstance(existing_plan, dict):
        prior_guides = sorted(
            (
                g
                for g in (existing_plan.get("daily_guides") or [])
                if isinstance(g, dict) and g.get("date")
            ),
            key=lambda g: str(g["date"]),
            reverse=True,
        )
        for g in prior_guides:
            d_str = str(g["date"])
            if d_str in seen_dates:
                continue
            try:
                g_dt = datetime.strptime(d_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if 0 < (start_dt - g_dt).days <= SPOT_COOLDOWN_DAYS:
                lines.append(
                    f"- {d_str} [直前週予定]（{g.get('weekday_ja', '')}・{g.get('guest_name', '')}）: "
                    f"エリア=[{g.get('focus_area', '')}] / 話題=[{g.get('kodaira_angle', '')}]"
                )

    return "\n".join(lines) if lines else "（直近の放送・編成記録なし）"


def build_editorial_research_prompt(
    start_dt: date,
    end_dt: date,
    recent_history_text: str,
    spot_cooldown_text: str = "",
    spot_candidates_text: str = "",
) -> str:
    """Build Phase 1 prompt for researching upcoming Kodaira events and diverse seasonal life topics."""
    lookahead_end = (start_dt + timedelta(days=13)).isoformat()
    cooldown_section = (
        f"\n【重複禁止①：90日クールダウン中の紹介済み／直近予定スポット（原則再登場NG）】\n{spot_cooldown_text}\n"
        "※上記スポットは原則約3か月（90日）間は再登場させないでください（ただし大規模リニューアル・新装開店・開催当日の耳より大型イベントがある場合のみ例外）。\n"
        if spot_cooldown_text
        else ""
    )
    candidates_section = (
        f"\n【小平市スポット題材ネタ帳：未紹介・季節適合候補（ジャンル分散の参考プール）】\n{spot_candidates_text}\n"
        "※ネタ帳に縛られすぎず、新鮮な最新ニュース・季節の行事・開花/紅葉状況等があれば臨機応変に優先してください。\n"
        if spot_candidates_text
        else ""
    )
    return f"""あなたは東京都小平市の朝7時番組「こだいら防災＆まちラジオ」の編集長付きリサーチャーです。
対象編成週: {start_dt.isoformat()} 〜 {end_dt.isoformat()}
先行リサーチ期間: {start_dt.isoformat()} 〜 {lookahead_end}（向こう2週間）

【直近90日間に放送済み・予定済みの話題・エリア（重複回避）】
{recent_history_text}
{cooldown_section}{candidates_section}
Google検索を使い、この季節の東京都小平市に関する実在の最新情報・多彩な地域の魅力を調査してください。
1. 【小平市の行事・イベント・公共機関・コミュニティ拠点】向こう2週間に小平市内（市役所・消防署・警察署・郵便局・公民館・地域センター・図書館・文化会館・各駅周辺など）で予定されている公開イベント・展示・講座・地域マーケットや新規/リニューアル情報。
2. 【多彩なジャンルの地元愛されスポット＆食・自然】直近90日と被らない新ネタを中心に、植物園・美術館/博物館・温浴/足湯・工場/企業/研究機関・商店街/ショッピング施設・カフェ/パン屋/小平うどん・書店/雑貨/ペット・大小の公園や水辺・桜/紅葉・大学/専門学校・モニュメント/社寺・農産物直売所・レジャー施設など幅広い分野から旬の地元情報を調査してください。
3. 【防災・生活の季節トピック】その季節に東京・小平の暮らしで今チェックしておきたい備え（暖房器具・火災予防、凍結・寒波や台風/豪雨への備え、大掃除・耐震・通電点検、季節の体調管理・救急確認など）。

※【開催年・事実・営業状況の厳密確認】イベント日程を挙げる際は必ず {start_dt.year}年（令和{start_dt.year - 2018}年）の開催であること、また店舗・施設が現在営業・開館中であることを確認し、前年以前の日程や閉店・長期休館中施設を誤って記載しないでください。開催年・事実が確認できない単発イベントは候補から外してください。
※確認できた事実・場所名・日付のみ挙げ、推測で架空のイベント日時を作らないでください。"""


def build_editorial_plan_prompt(
    start_dt: date,
    end_dt: date,
    skeleton: list[dict[str, Any]],
    recent_history_text: str,
    research_briefing: str,
    spot_cooldown_text: str = "",
    spot_candidates_text: str = "",
) -> str:
    """Build Phase 2 prompt for Gemini 4 Neon Chief Editor to structure 7-day weekly plan JSON."""
    skeleton_json = json.dumps(skeleton, ensure_ascii=False, indent=2)
    cooldown_section = (
        f"\n### ② クールダウン中スポット一覧（原則90日間は再登場禁止）\n{spot_cooldown_text}\n"
        "※ただし「大規模リニューアルオープン」「耳よりの当日大型イベント」など明確なニュース価値がある場合のみ例外として採用可。\n"
        if spot_cooldown_text
        else ""
    )
    candidates_section = (
        f"\n## 4.5 小平市スポット題材ネタ帳（未紹介・バランス候補プール）\n{spot_candidates_text}\n"
        if spot_candidates_text
        else ""
    )
    return f"""あなたは「毎朝7時！こだいら防災＆まちラジオ」の編集長（チーフプロデューサー）です。
小平市民が「小平っていいな」「地元にこんな素敵な場所があったんだ！」と毎朝ワクワクしながら、自然に防災力も高まる来週7日間の週間編成プランを作成してください。

## 1. 編成対象期間
{start_dt.isoformat()} 〜 {end_dt.isoformat()}（7日間）

## 2. カレンダー枠・曜日専門家・90日未解説キーワード情報
※ `has_existing_special: true` の日はすでに年間記念日/イベントのカウントダウン特集が組まれているため、その日の `editorial_special` は必ず `null` にしてください。
{skeleton_json}

## 3. 直近の放送・予定履歴（重複禁止）
{recent_history_text}
{cooldown_section}
## 4. 最新リサーチ結果（小平の季節・イベント・まちネタ）
{research_briefing}
{candidates_section}
## 5. 編集長としての編成ルール（重要）
1. **週間テーマ軸 (`weekly_arc`)**: 今週1週間を通じたワクワクする番組の縦糸・特集コンセプトを1つ設定してください。
2. **7日間の地理・ジャンルの多様性 ＆ 重複禁止・鮮度重視**:
   - 月〜日で同じ駅・エリアばかりに偏らないよう、`focus_area`（小川／花小金井／一橋学園／鷹の台／小平駅南・北口／中島・栄町／鈴木・大沼・天神町など）を毎日変えてください。
   - **ジャンル重複・スポット重複の排除**: クールダウン中スポットの使い回しは厳禁とし、公共機関・公民館/図書館・駅・スポーツ・美術館/植物園・温浴/足湯・企業/工場・商業・カフェ/パン/うどん・本/雑貨/ペット・公園/水辺・花/紅葉・大学/専門学校・モニュメント/社寺・直売所・レジャーの多彩なジャンルを日替わりで組み合わせてください（連続した日に同じジャンルが重ならないように）。
   - **鮮度の確保**: ネタ帳の候補を活かしつつ、今週ならではの最新オープン・季節の花や旬の味・地域イベントなど鮮度の高い話題が見つかった場合は柔軟に優先採用してください。`preplanned_kodaira_hint` がある日は方向性の参考にしてください（同一・既出スポットなら未紹介ネタへ差し替えて構いません。ただし `schedule_locked: true` と `special_request` は最優先遵守）。
   - **`preplanned_expert_topics` が指定されている日は、必ずそのテーマを `expert_angle` の主軸として採用してください**（空欄の日のみ `expert_fresh_candidates` を活用）。
   - **`schedule_locked: true` または `special_request` がある日は、そのリクエスト内容を最優先で `kodaira_angle` や `expert_angle`（必要に応じて `editorial_special`）に忠実に反映し、勝手に別テーマへ変更しないでください**。
3. **編集長ワクワク特集コーナー (`editorial_special`)**:
   - `has_existing_special` が `false` の日の中から、**週に1〜2日だけ** ワクワクする特別特集（+2〜3分拡大コーナー）を企画してください（その他の日は必ず `null`）。
   - 単なる災害恐怖ではなく、「小平のまち歩き・季節の楽しみ・地域文化」と「暮らしの安心・防災」が楽しくつながる企画にしてください。
   - 前日のエンディングで自然に予告できる、魅力的なタイトルにしてください。
4. **先のワクワク予告 (`upcoming_ideas`)**: 向こう2〜3週間先に育てたい特集企画アイデアを2〜3個挙げてください。
5. **事実厳守・開催年の徹底確認**: 検索結果にないイベント開催日時を創作しないでください。単発イベントや企画展を書く場合は **必ず {start_dt.year}年（令和{start_dt.year - 2018}年）の開催日・期間がリサーチ結果で裏付けられたものだけ** を採用し、前年以前の日程や閉店・改装休館中店舗を流用しないこと（確認できないものは営業中の常設施設や季節散歩の企画にする）。

## 6. 出力JSONスキーマ（厳密にこのJSON構造のみ出力）
{{
  "weekly_arc": {{
    "title": "今週の番組キャッチタイトル",
    "concept": "今週の編集方針（1〜2文）"
  }},
  "daily_guides": [
    {{
      "date": "YYYY-MM-DD",
      "focus_area": "小平市内の重点エリア・路線周辺",
      "kodaira_angle": "その日のワクワクする小平まち・暮らしネタ切り口",
      "search_hints": ["当日朝に検索する具体キーワード1", "キーワード2"],
      "expert_angle": "専門家ゲストの未解説テーマと小平を絡める切り口",
      "editorial_special": {{
        "title": "特集タイトル",
        "phase_label": "編集長ワクワク特集",
        "extra_minutes": 3,
        "theme_focus": "小春・平蔵で掘り下げる具体的企画内容"
      }}
    }}
  ],
  "upcoming_ideas": [
    "来週〜再来週に向けた小平ワクワク特集企画アイデア1",
    "アイデア2",
    "アイデア3"
  ]
}}"""


def _normalize_editorial_plan(
    raw_plan: dict[str, Any],
    skeleton: list[dict[str, Any]],
    research_model: str,
    planner_model: str,
    spots_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate dates, avoid stacking specials on countdown days, cap specials, and tag spot_ids."""
    spots_data = spots_cfg or load_kodaira_spots()
    raw_guides = {
        str(g.get("date")): g
        for g in (raw_plan.get("daily_guides") or [])
        if isinstance(g, dict) and g.get("date")
    }

    normalized_guides: list[dict[str, Any]] = []
    special_count = 0

    for row in skeleton:
        d_str = row["date"]
        rg = raw_guides.get(d_str, {})
        ed_sp = rg.get("editorial_special")
        cleaned_sp: dict[str, Any] | None = None

        if (
            isinstance(ed_sp, dict)
            and str(ed_sp.get("title", "")).strip()
            and not row["has_existing_special"]
            and special_count < 2
        ):
            extra_min = max(2, min(4, int(ed_sp.get("extra_minutes", 3))))
            cleaned_sp = {
                "title": str(ed_sp["title"]).strip(),
                "phase_label": str(ed_sp.get("phase_label") or "編集長ワクワク特集").strip(),
                "extra_minutes": extra_min,
                "theme_focus": str(ed_sp.get("theme_focus") or "").strip(),
            }
            special_count += 1

        hints = [str(h).strip() for h in (rg.get("search_hints") or []) if str(h).strip()]
        focus_area = str(rg.get("focus_area") or "小平市内エリア散策").strip()
        kodaira_angle = str(
            rg.get("kodaira_angle") or f"{row['theme_name']}と小平の季節の暮らし"
        ).strip()
        expert_angle = str(
            rg.get("expert_angle")
            or (
                f"{row['guest_name']}さんとともに事前編成テーマ（{'／'.join(row['preplanned_expert_topics'])}）を小平向けに解説。{row['preplanned_expert_note']}".strip()
                if row.get("preplanned_expert_topics")
                else (
                    f"未解説キーワード（{', '.join(row['expert_fresh_candidates'][:2])}）を小平向けに解説"
                    if row["expert_fresh_candidates"]
                    else f"{row['theme_name']}の実践知識"
                )
            )
        ).strip()

        spot_text = "\n".join(
            [
                focus_area,
                kodaira_angle,
                " ".join(hints),
                cleaned_sp["title"] if cleaned_sp else "",
            ]
        )
        matched_ids = match_spots_in_text(spot_text, spots_data)
        for exp_sid in rg.get("spot_ids") or []:
            sid_clean = str(exp_sid or "").strip()
            if sid_clean and sid_clean not in matched_ids:
                matched_ids.append(sid_clean)

        normalized_guides.append(
            {
                "date": d_str,
                "weekday_ja": row["weekday_ja"],
                "theme_name": row["theme_name"],
                "guest_name": row["guest_name"],
                "focus_area": focus_area,
                "kodaira_angle": kodaira_angle,
                "spot_ids": matched_ids,
                "search_hints": hints[:4],
                "expert_angle": expert_angle,
                "editorial_special": cleaned_sp,
            }
        )

    arc = raw_plan.get("weekly_arc") or {}
    return {
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "week_start": skeleton[0]["date"],
        "week_end": skeleton[-1]["date"],
        "models": {
            "research": research_model,
            "planner": planner_model,
        },
        "weekly_arc": {
            "title": str(arc.get("title") or "今週の小平・暮らしと安心発見ウィーク").strip(),
            "concept": str(
                arc.get("concept") or "小平のまちの魅力と毎日の防災を楽しく結びつける7日間。"
            ).strip(),
        },
        "daily_guides": normalized_guides,
        "upcoming_ideas": [
            str(x).strip()
            for x in (raw_plan.get("upcoming_ideas") or [])
            if str(x).strip()
        ][:4],
    }


def merge_editorial_plans(
    existing_plan: dict[str, Any] | None,
    new_week_plan: dict[str, Any],
    now_jst: datetime,
) -> dict[str, Any]:
    """Merge a newly planned week into existing multi-week editorial_plan.json without clobbering active/other weeks."""
    cutoff_str = (now_jst.date() - timedelta(days=60)).isoformat()
    today_str = now_jst.date().isoformat()

    guides_by_date: dict[str, dict[str, Any]] = {}
    weeks_by_start: dict[str, dict[str, Any]] = {}

    if existing_plan:
        for g in existing_plan.get("daily_guides") or []:
            if isinstance(g, dict) and g.get("date") and str(g["date"]) >= cutoff_str:
                guides_by_date[str(g["date"])] = g

        existing_weeks = existing_plan.get("weeks") or []
        if not existing_weeks and existing_plan.get("week_start") and existing_plan.get("weekly_arc"):
            existing_weeks = [
                {
                    "week_start": existing_plan["week_start"],
                    "week_end": existing_plan.get("week_end", existing_plan["week_start"]),
                    "generated_at": existing_plan.get("generated_at", ""),
                    "weekly_arc": existing_plan["weekly_arc"],
                    "upcoming_ideas": existing_plan.get("upcoming_ideas", []),
                }
            ]
        for wk in existing_weeks:
            ws = str(wk.get("week_start") or "")
            we = str(wk.get("week_end") or ws)
            if ws and we >= cutoff_str:
                weeks_by_start[ws] = wk

    for g in new_week_plan.get("daily_guides") or []:
        if isinstance(g, dict) and g.get("date"):
            guides_by_date[str(g["date"])] = g

    new_ws = new_week_plan["week_start"]
    prev_wk = weeks_by_start.get(new_ws) or {}
    merged_week_entry = {
        "week_start": new_ws,
        "week_end": new_week_plan["week_end"],
        "generated_at": new_week_plan["generated_at"],
        "weekly_arc": new_week_plan["weekly_arc"],
        "upcoming_ideas": new_week_plan.get("upcoming_ideas", []),
    }
    for banner_key in ("banner_image", "hero_image", "og_image"):
        banner_val = new_week_plan.get(banner_key) or prev_wk.get(banner_key)
        if banner_val:
            merged_week_entry[banner_key] = banner_val
    weeks_by_start[new_ws] = merged_week_entry

    sorted_guides = [guides_by_date[d] for d in sorted(guides_by_date)]
    sorted_weeks = [weeks_by_start[ws] for ws in sorted(weeks_by_start)]

    active_arc = new_week_plan["weekly_arc"]
    for wk in sorted_weeks:
        if wk["week_start"] <= today_str <= wk["week_end"]:
            active_arc = wk["weekly_arc"]
            break

    return {
        "generated_at": new_week_plan["generated_at"],
        "week_start": sorted_guides[0]["date"] if sorted_guides else new_ws,
        "week_end": sorted_guides[-1]["date"] if sorted_guides else new_week_plan["week_end"],
        "models": new_week_plan["models"],
        "weekly_arc": active_arc,
        "weeks": sorted_weeks,
        "daily_guides": sorted_guides,
        "upcoming_ideas": new_week_plan.get("upcoming_ideas", []),
    }


def main() -> None:
    load_dotenv(CONFIG_DIR.parent / ".env")
    now_jst = datetime.now(JST)
    existing_plan = (
        _load_json(EDITORIAL_PLAN_PATH) if EDITORIAL_PLAN_PATH.exists() else None
    )
    default_start = _default_next_monday(now_jst, existing_plan=existing_plan).isoformat()

    parser = argparse.ArgumentParser(description="Generate weekly Kodaira radio editorial plan")
    parser.add_argument(
        "--start-date",
        default=default_start,
        help="Week start YYYY-MM-DD in JST (default: upcoming Monday JST)",
    )
    parser.add_argument("--days", type=int, default=7, help="Number of days to plan (default: 7)")
    parser.add_argument(
        "--research-model",
        default=DEFAULT_RESEARCH_MODEL,
        help="Gemini model for Phase 1 Kodaira seasonal/event research",
    )
    parser.add_argument(
        "--planner-model",
        default=DEFAULT_SCRIPT_MODEL,
        help="Gemini model for Phase 2 Chief Editor planning",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional single model override for both Phase 1 and Phase 2",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print calendar skeleton and prompts without calling Gemini API",
    )
    args = parser.parse_args()

    research_model = args.model or args.research_model
    planner_model = args.model or args.planner_model
    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_dt = start_dt + timedelta(days=args.days - 1)

    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    special_days = (
        _load_json(CONFIG_DIR / "special_days.json")
        if (CONFIG_DIR / "special_days.json").exists()
        else {"recurring": [], "dated_events": []}
    )
    program_schedule = (
        _load_json(CONFIG_DIR / "program_schedule.json")
        if (CONFIG_DIR / "program_schedule.json").exists()
        else None
    )
    topic_history_data = (
        _load_json(DATA_DIR / "topic_history.json")
        if (DATA_DIR / "topic_history.json").exists()
        else {"entries": []}
    )
    topic_entries = topic_history_data.get("entries", [])
    spots_cfg = load_kodaira_spots()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_entries,
        editorial_plan=existing_plan,
        reference_date=start_dt,
        exclude_date_range=(start_dt.isoformat(), end_dt.isoformat()),
    )
    fresh_candidates = select_balanced_spot_candidates(
        spots_cfg,
        usage_map,
        start_dt,
        count=20,
    )
    spot_cooldown_text = format_spot_cooldown_block(spots_cfg, usage_map, start_dt)
    spot_candidates_text = format_spot_candidates_block(spots_cfg, fresh_candidates)

    skeleton = _build_week_skeleton(
        start_dt,
        args.days,
        themes,
        special_days,
        topic_entries,
        program_schedule=program_schedule,
    )
    recent_text = _format_recent_history(start_dt, topic_entries, existing_plan=existing_plan)
    research_prompt = build_editorial_research_prompt(
        start_dt,
        end_dt,
        recent_text,
        spot_cooldown_text=spot_cooldown_text,
        spot_candidates_text=spot_candidates_text,
    )

    if args.dry_run:
        cooldown_count = sum(1 for u in usage_map.values() if u.get("in_cooldown"))
        print(f"=== DRY RUN WEEKLY EDITORIAL PLAN ({start_dt} ~ {end_dt}) ===")
        print(f"Models: research={research_model} | planner={planner_model}")
        print(
            f"Spot Catalog: total={len(spots_cfg.get('spots', []))} | "
            f"cooldown_90d={cooldown_count} | fresh_candidates={len(fresh_candidates)}"
        )
        for r in skeleton:
            sched_str = " / ".join(r["preplanned_expert_topics"]) or "Auto"
            lock_str = " [LOCKED]" if r["schedule_locked"] else ""
            print(
                f"  {r['date']} ({r['weekday_ja']}) | {r['edition_label']} | "
                f"ExistingSpecial={r['existing_special_desc'] or 'None'} | "
                f"Preplanned=[{sched_str}]{lock_str} | 90dCovered={len(r['expert_covered_90d'])}"
            )
        return

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        print("ERROR: GEMINI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    r_cfg_kwargs: dict[str, Any] = {"tools": [{"google_search": {}}]}
    if research_model.startswith("gemini-4"):
        r_cfg_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MEDIUM,
        )
    print(f"Phase 1: Researching 2-week Kodaira seasonal/event outlook via {research_model}...")
    r_resp = client.models.generate_content(
        model=research_model,
        contents=research_prompt,
        config=types.GenerateContentConfig(**r_cfg_kwargs),
    )
    print(f"Phase 1 usage   : {_format_usage(r_resp)}")
    research_brief = getattr(r_resp, "text", "") or ""

    plan_prompt = build_editorial_plan_prompt(
        start_dt=start_dt,
        end_dt=end_dt,
        skeleton=skeleton,
        recent_history_text=recent_text,
        research_briefing=research_brief,
        spot_cooldown_text=spot_cooldown_text,
        spot_candidates_text=spot_candidates_text,
    )
    print(f"Phase 2: Drafting weekly editorial plan via {planner_model}...")
    p_resp = client.models.generate_content(
        model=planner_model,
        contents=plan_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    print(f"Phase 2 usage   : {_format_usage(p_resp)}")
    raw_plan = _parse_json_response(getattr(p_resp, "text", "") or "")
    new_week_plan = _normalize_editorial_plan(
        raw_plan,
        skeleton,
        research_model,
        planner_model,
        spots_cfg=spots_cfg,
    )
    merged_plan = merge_editorial_plans(existing_plan, new_week_plan, now_jst)

    EDITORIAL_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDITORIAL_PLAN_PATH.write_text(
        json.dumps(merged_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    overlaps = audit_plan_spot_overlaps(spots_cfg, topic_entries, merged_plan)
    if overlaps:
        print(f"WARNING: Detected {len(overlaps)} 90-day spot overlap(s) across editorial timeline:")
        for ov in overlaps:
            print(
                f"  - {ov['spot_name']}: {ov['date_a']} ({ov['source_a']}) -> "
                f"{ov['date_b']} ({ov['source_b']}) [gap={ov['gap_days']}d < {ov['cooldown_days']}d]"
            )
    print(
        f"Saved weekly editorial plan: {EDITORIAL_PLAN_PATH} "
        f"(total {len(merged_plan['daily_guides'])} days across {len(merged_plan['weeks'])} week(s))"
    )


if __name__ == "__main__":
    main()
