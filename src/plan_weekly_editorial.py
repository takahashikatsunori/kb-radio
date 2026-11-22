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
    RECENT_LOCAL_DEDUP_DAYS,
    _format_usage,
    _load_json,
    _parse_json_response,
    build_dedup_context,
)
from schedule_calendar import resolve_day_plan

EDITORIAL_PLAN_PATH = DATA_DIR / "editorial_plan.json"


def _default_next_monday(now_jst: datetime) -> date:
    """Return upcoming Monday in JST (Sunday -> tomorrow Monday)."""
    days_ahead = 7 - now_jst.weekday()
    return (now_jst + timedelta(days=days_ahead)).date()


def _build_week_skeleton(
    start_dt: date,
    num_days: int,
    themes: dict[str, Any],
    special_days: dict[str, Any],
    topic_history_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build day-by-day calendar, special-day lockouts, and 90-day expert dedup data."""
    rows: list[dict[str, Any]] = []
    for offset in range(num_days):
        d_str = (start_dt + timedelta(days=offset)).isoformat()
        plan = resolve_day_plan(d_str, themes, special_days, editorial_plan=None)
        dedup = build_dedup_context(d_str, plan, topic_history_entries)
        guest = plan["day_cfg"]["guest"]
        sp = plan.get("scheduled_special")
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
                "expert_covered_90d": dedup["expert_covered_keywords"],
                "expert_fresh_candidates": dedup["fresh_keywords"][:5],
            }
        )
    return rows


def _format_recent_history(
    start_dt: date,
    topic_history_entries: list[dict[str, Any]],
) -> str:
    """Format recent 14-day broadcast topics/areas to help avoid repetition."""
    lines: list[str] = []
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
        if 0 <= (start_dt - e_dt).days <= RECENT_LOCAL_DEDUP_DAYS + 7:
            areas = ", ".join(e.get("kodaira_areas") or [])
            topics = "; ".join(e.get("kodaira_topics") or [])
            kws = ", ".join(e.get("keywords_featured") or [])
            lines.append(
                f"- {e['date']}（{e.get('weekday', '')}・{e.get('guest_name', '')}）: "
                f"エリア=[{areas}] / 話題=[{topics}] / 専門用語=[{kws}]"
            )
    return "\n".join(lines) if lines else "（直近の放送記録なし）"


def build_editorial_research_prompt(
    start_dt: date,
    end_dt: date,
    recent_history_text: str,
) -> str:
    """Build Phase 1 prompt for researching upcoming Kodaira events and seasonal life topics."""
    lookahead_end = (start_dt + timedelta(days=13)).isoformat()
    return f"""あなたは東京都小平市の朝7時番組「こだいら防災＆まちラジオ」の編集長付きリサーチャーです。
対象編成週: {start_dt.isoformat()} 〜 {end_dt.isoformat()}
先行リサーチ期間: {start_dt.isoformat()} 〜 {lookahead_end}（向こう2週間）

【直近で放送済みの話題・エリア（重複回避の参考）】
{recent_history_text}

Google検索を使い、この季節の東京都小平市に関する実在の最新情報・地域の魅力を調査してください。
1. 【小平市の行事・イベント・公民館/図書館/地域企画】向こう2週間に小平市内（花小金井、小平駅周辺、一橋学園、鷹の台、新小平、小川、鈴木町、大沼町など）で予定されている公開イベント・展示・講座・地域マーケット等。
2. 【季節の自然・食・まち歩きネタ】この時期の小平で楽しめる紅葉や散策コース（玉川上水、狭山・境緑道、野火止用水、平櫛田中彫刻美術館周辺、ふれあい下水道館、ガスミュージアム等）、旬の地元農産物（冬野菜、キウイ・柿、ブルーベリー加工品、小平うどん・地元パン屋等）。
3. 【防災・生活の季節トピック】初冬〜年末に向けて東京・小平の暮らしで今チェックしておきたい備え（暖房器具・火災予防、凍結や寒波への備え、大掃除ついでの耐震・通電点検、年末年始の救急・防災確認など）。

※【開催年の厳密確認】イベント日程を挙げる際は必ず {start_dt.year}年（令和{start_dt.year - 2018}年）の開催であることを確認してください。前年（{start_dt.year - 1}年以前）の開催日・曜日を今年の日程と混同して記載することは厳禁です。開催年が確認できない単発イベントは候補から外してください。
※確認できた事実・場所名・日付のみ挙げ、推測で架空のイベント日時を作らないでください。"""


def build_editorial_plan_prompt(
    start_dt: date,
    end_dt: date,
    skeleton: list[dict[str, Any]],
    recent_history_text: str,
    research_briefing: str,
) -> str:
    """Build Phase 2 prompt for Gemini 4 Neon Chief Editor to structure 7-day weekly plan JSON."""
    skeleton_json = json.dumps(skeleton, ensure_ascii=False, indent=2)
    return f"""あなたは「毎朝7時！こだいら防災＆まちラジオ」の編集長（チーフプロデューサー）です。
小平市民が「小平っていいな」「この町をもっと知りたい、歩きたい！」と毎朝ワクワクしながら、自然に防災力も高まる来週7日間の週間編成プランを作成してください。

## 1. 編成対象期間
{start_dt.isoformat()} 〜 {end_dt.isoformat()}（7日間）

## 2. カレンダー枠・曜日専門家・90日未解説キーワード情報
※ `has_existing_special: true` の日はすでに年間記念日/イベントのカウントダウン特集が組まれているため、その日の `editorial_special` は必ず `null` にしてください。
{skeleton_json}

## 3. 直近の放送履歴（重複禁止）
{recent_history_text}

## 4. 最新リサーチ結果（小平の季節・イベント・まちネタ）
{research_briefing}

## 5. 編集長としての編成ルール（重要）
1. **週間テーマ軸 (`weekly_arc`)**: 今週1週間を通じたワクワクする番組の縦糸・特集コンセプトを1つ設定してください。
2. **7日間の地理・ジャンルの多様性**:
   - 月〜日で同じ駅・施設ばかりに偏らないよう、`focus_area`（小川／花小金井／一橋学園／鷹の台／小平駅南・北口／津田・野火止／鈴木・大沼など）を毎日変えてください。
   - `kodaira_angle` にはリスナーが小平をもっと好きになる具体的なまち・暮らしの切り口（直近履歴と非重複）を記載してください。
   - `expert_angle` には各日の `expert_fresh_candidates` を活用し、過去90日と被らない深掘り切り口を指定してください。
3. **編集長ワクワク特集コーナー (`editorial_special`)**:
   - `has_existing_special` が `false` の日の中から、**週に1〜2日だけ** ワクワクする特別特集（+2〜3分拡大コーナー）を企画してください（その他の日は必ず `null`）。
   - 単なる災害恐怖ではなく、「小平のまち歩き・季節の楽しみ・地域文化」と「暮らしの安心・防災」が楽しくつながる企画にしてください。
   - 前日のエンディングで自然に予告できる、魅力的なタイトルにしてください。
4. **先のワクワク予告 (`upcoming_ideas`)**: 向こう2〜3週間先に育てたい特集企画アイデアを2〜3個挙げてください。
5. **事実厳守・開催年の徹底確認**: 検索結果にないイベント開催日時を創作しないでください。単発イベントや企画展を書く場合は **必ず {start_dt.year}年（令和{start_dt.year - 2018}年）の開催日・期間がリサーチ結果で裏付けられたものだけ** を採用し、前年以前の日程を流用しないこと（確認できないものは常設施設や季節散歩の企画にする）。

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
) -> dict[str, Any]:
    """Validate dates, avoid stacking specials on countdown days, and cap editorial specials."""
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
        normalized_guides.append(
            {
                "date": d_str,
                "weekday_ja": row["weekday_ja"],
                "theme_name": row["theme_name"],
                "guest_name": row["guest_name"],
                "focus_area": str(rg.get("focus_area") or "小平市内エリア散策").strip(),
                "kodaira_angle": str(
                    rg.get("kodaira_angle") or f"{row['theme_name']}と小平の季節の暮らし"
                ).strip(),
                "search_hints": hints[:4],
                "expert_angle": str(
                    rg.get("expert_angle")
                    or (
                        f"未解説キーワード（{', '.join(row['expert_fresh_candidates'][:2])}）を小平向けに解説"
                        if row["expert_fresh_candidates"]
                        else f"{row['theme_name']}の実践知識"
                    )
                ).strip(),
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


def main() -> None:
    now_jst = datetime.now(JST)
    default_start = _default_next_monday(now_jst).isoformat()

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

    load_dotenv(CONFIG_DIR.parent / ".env")
    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    special_days = (
        _load_json(CONFIG_DIR / "special_days.json")
        if (CONFIG_DIR / "special_days.json").exists()
        else {"recurring": [], "dated_events": []}
    )
    topic_history_data = (
        _load_json(DATA_DIR / "topic_history.json")
        if (DATA_DIR / "topic_history.json").exists()
        else {"entries": []}
    )
    topic_entries = topic_history_data.get("entries", [])

    skeleton = _build_week_skeleton(start_dt, args.days, themes, special_days, topic_entries)
    recent_text = _format_recent_history(start_dt, topic_entries)
    research_prompt = build_editorial_research_prompt(start_dt, end_dt, recent_text)

    if args.dry_run:
        print(f"=== DRY RUN WEEKLY EDITORIAL PLAN ({start_dt} ~ {end_dt}) ===")
        print(f"Models: research={research_model} | planner={planner_model}")
        for r in skeleton:
            print(
                f"  {r['date']} ({r['weekday_ja']}) | {r['edition_label']} | "
                f"ExistingSpecial={r['existing_special_desc'] or 'None'} | "
                f"90dCovered={len(r['expert_covered_90d'])}"
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
    )
    print(f"Phase 2: Drafting weekly editorial plan via {planner_model}...")
    p_resp = client.models.generate_content(
        model=planner_model,
        contents=plan_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    print(f"Phase 2 usage   : {_format_usage(p_resp)}")
    raw_plan = _parse_json_response(getattr(p_resp, "text", "") or "")
    final_plan = _normalize_editorial_plan(raw_plan, skeleton, research_model, planner_model)

    EDITORIAL_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDITORIAL_PLAN_PATH.write_text(
        json.dumps(final_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved weekly editorial plan: {EDITORIAL_PLAN_PATH}")


if __name__ == "__main__":
    main()
