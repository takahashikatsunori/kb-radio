"""Holiday, special disaster-preparedness day countdown, and tomorrow-preview resolver."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import jpholiday

WEEKDAY_KEYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

MAX_TARGET_DURATION_SEC = 1260  # 21-minute cap keeps Gemini TTS requests comfortably under RPD limit
CHARS_PER_MINUTE = 320


def _match_special_day(dt: date, special_days: dict[str, Any]) -> dict[str, Any] | None:
    """Find the most urgent active or upcoming special disaster day / event for date dt."""
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []

    for item in special_days.get("recurring", []):
        sm, sd = map(int, item["start_mm_dd"].split("-"))
        em, ed = map(int, item["end_mm_dd"].split("-"))
        cd_before = int(item.get("countdown_days_before", 3))
        extra_min = int(item.get("extra_minutes", 3))

        for yr in (dt.year - 1, dt.year, dt.year + 1):
            start_d = date(yr, sm, sd)
            end_year = yr + 1 if (em, ed) < (sm, sd) else yr
            end_d = date(end_year, em, ed)
            if start_d <= dt <= end_d:
                days_until = 0
                phase = "当日" if start_d == end_d else "期間中"
            elif 0 < (start_d - dt).days <= cd_before:
                days_until = (start_d - dt).days
                phase = f"あと{days_until}日"
            else:
                continue

            candidates.append(
                (
                    days_until,
                    1,
                    -extra_min,
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "target_date": start_d.isoformat(),
                        "days_until": days_until,
                        "phase_label": phase,
                        "extra_minutes": extra_min,
                        "theme_focus": item["theme_focus"],
                        "source_type": "recurring",
                    },
                )
            )

    for ev in special_days.get("dated_events", []):
        ev_d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        cd_before = int(ev.get("countdown_days_before", 3))
        extra_min = int(ev.get("extra_minutes", 3))
        diff = (ev_d - dt).days
        if diff == 0:
            phase = "当日"
        elif 0 < diff <= cd_before:
            phase = f"あと{diff}日"
        else:
            continue

        candidates.append(
            (
                diff,
                0,
                -extra_min,
                {
                    "id": ev["id"],
                    "title": ev["title"],
                    "target_date": ev_d.isoformat(),
                    "days_until": diff,
                    "phase_label": phase,
                    "extra_minutes": extra_min,
                    "theme_focus": ev["theme_focus"],
                    "source_type": "dated_event",
                },
            )
        )

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return candidates[0][3]


def resolve_day_plan(
    target_date_str: str,
    themes: dict[str, Any],
    special_days: dict[str, Any],
) -> dict[str, Any]:
    """Compute weekday/holiday rules, target duration/chars, and active special countdown."""
    dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    day_key = WEEKDAY_KEYS[dt.weekday()]
    day_cfg = themes["days"][day_key]

    holiday_name = jpholiday.is_holiday_name(dt)
    is_holiday = bool(holiday_name)
    is_weekend = bool(day_cfg["is_weekend"])
    is_expanded_base = is_weekend or is_holiday

    rule_key = "weekend" if is_expanded_base else "weekday"
    base_rule = themes["schedule_rules"][rule_key]
    base_dur = int(base_rule["target_duration_sec"])
    base_chars = int(base_rule["target_chars"])
    base_min = int(base_rule["min_chars"])
    base_max = int(base_rule["max_chars"])

    if is_holiday and not is_weekend:
        base_edition = f"祝日15分拡大版（{holiday_name}）"
    elif is_holiday and is_weekend:
        base_edition = f"土日祝15分特集（{holiday_name}）"
    elif is_weekend:
        base_edition = "土日15分特集版"
    else:
        base_edition = "平日レギュラー版（約10分）"

    scheduled_special = _match_special_day(dt, special_days)
    if scheduled_special:
        extra_sec = int(scheduled_special["extra_minutes"]) * 60
        target_dur = min(MAX_TARGET_DURATION_SEC, base_dur + extra_sec)
        actual_added_sec = max(0, target_dur - base_dur)
        added_chars = round((actual_added_sec / 60.0) * CHARS_PER_MINUTE)
        target_chars = base_chars + added_chars
        min_chars = base_min + round(added_chars * 0.85)
        max_chars = base_max + round(added_chars * 1.15)
        total_min = round(target_dur / 60)

        if is_holiday:
            edition_label = f"祝日15分＋特別特集拡大版（{holiday_name}・約{total_min}分）"
        elif is_weekend:
            edition_label = f"土日15分＋特別特集拡大版（約{total_min}分）"
        else:
            edition_label = f"特別コーナー拡大版（約{total_min}分）"
    else:
        target_dur = base_dur
        target_chars = base_chars
        min_chars = base_min
        max_chars = base_max
        edition_label = base_edition

    return {
        "date": target_date_str,
        "day_key": day_key,
        "weekday_ja": day_cfg["weekday_ja"],
        "day_cfg": day_cfg,
        "is_weekend": is_weekend,
        "is_holiday": is_holiday,
        "holiday_name": holiday_name or "",
        "is_expanded_base": is_expanded_base,
        "base_duration_sec": base_dur,
        "base_chars": base_chars,
        "base_min_chars": base_min,
        "base_max_chars": base_max,
        "target_duration_sec": target_dur,
        "target_chars": target_chars,
        "min_chars": min_chars,
        "max_chars": max_chars,
        "edition_label": edition_label,
        "scheduled_special": scheduled_special,
    }


def resolve_tomorrow_preview(
    target_date_str: str,
    themes: dict[str, Any],
    special_days: dict[str, Any],
) -> dict[str, Any]:
    """Resolve tomorrow's broadcast plan to generate an accurate ending preview cue."""
    dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    tmr_str = (dt + timedelta(days=1)).isoformat()
    tmr = resolve_day_plan(tmr_str, themes, special_days)
    guest_name = tmr["day_cfg"]["guest"]["name"]
    theme_name = tmr["day_cfg"]["theme_name"]
    total_min = round(tmr["target_duration_sec"] / 60)

    highlights: list[str] = []
    if tmr["is_holiday"]:
        highlights.append(f"明日は祝日「{tmr['holiday_name']}」のため15分拡大版")
    elif tmr["is_weekend"]:
        highlights.append(f"明日は{tmr['weekday_ja']}の15分特集版")

    sp = tmr["scheduled_special"]
    if sp:
        if sp["days_until"] == 0:
            highlights.append(f"「{sp['title']}」当日の特別コーナーを追加した約{total_min}分拡大版")
        else:
            highlights.append(
                f"「{sp['title']}」（{sp['phase_label']}）に向けたカウントダウン特別コーナーを追加した約{total_min}分拡大版"
            )

    if highlights:
        note_text = "／".join(highlights)
        hint = (
            f"明日（{tmr_str}・{tmr['weekday_ja']}）の予告：テーマは「{theme_name}」、"
            f"ゲストは{guest_name}さん。さらに【{note_text}】でお届けすることを小春と平蔵が必ず予告してください！"
        )
    else:
        hint = (
            f"明日（{tmr_str}・{tmr['weekday_ja']}）の予告：朝7時からの平日10分レギュラー版、"
            f"テーマは「{theme_name}」、ゲストは{guest_name}さんであることを予告してください。"
        )

    return {
        "date": tmr_str,
        "weekday_ja": tmr["weekday_ja"],
        "theme_name": theme_name,
        "guest_name": guest_name,
        "edition_label": tmr["edition_label"],
        "target_duration_sec": tmr["target_duration_sec"],
        "is_holiday": tmr["is_holiday"],
        "holiday_name": tmr["holiday_name"],
        "scheduled_special": sp,
        "preview_hint": hint,
    }


if __name__ == "__main__":
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    themes_cfg = json.loads((root / "config" / "weekly_themes.json").read_text(encoding="utf-8"))
    special_cfg = json.loads((root / "config" / "special_days.json").read_text(encoding="utf-8"))

    for d in ["2026-11-22", "2026-11-23", "2026-11-24", "2026-11-25", "2026-08-29"]:
        plan = resolve_day_plan(d, themes_cfg, special_cfg)
        tmr = resolve_tomorrow_preview(d, themes_cfg, special_cfg)
        print(f"=== {d} ({plan['weekday_ja']}) ===")
        print(f"  Edition : {plan['edition_label']}")
        print(f"  Target  : {plan['target_duration_sec']}s / ~{plan['target_chars']} chars ({plan['min_chars']}~{plan['max_chars']})")
        print(f"  Guest   : {plan['day_cfg']['guest']['name']} ({plan['day_cfg']['theme_name']})")
        print(f"  Special : {plan['scheduled_special']['title'] + ' [' + plan['scheduled_special']['phase_label'] + ']' if plan['scheduled_special'] else 'None'}")
        print(f"  Preview : {tmr['preview_hint']}")
