"""Render docs/calendar.html: broadcast content calendar (past aired + future specialist schedule)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from string import Template
from typing import Any

from generate_episode import _is_keyword_covered
from schedule_calendar import resolve_day_plan


def _parse_date(d_str: str) -> date:
    return datetime.strptime(d_str, "%Y-%m-%d").date()


def _build_calendar_payload(
    bundles: list[dict[str, Any]],
    themes: dict[str, Any],
    special_days: dict[str, Any],
    editorial_plan: dict[str, Any] | None,
    program_schedule: dict[str, Any] | None,
    topic_history: dict[str, Any] | None,
    today_jst_str: str,
) -> dict[str, Any]:
    """Assemble unified past + future broadcast calendar dataset."""
    bundles_by_date: dict[str, list[dict[str, Any]]] = {}
    all_bundle_dates: list[str] = []
    for b in bundles:
        ep = b["episode"]
        meta = ep["meta"]
        d_str = str(meta["episode_date"])
        bundles_by_date.setdefault(d_str, []).append(b)
        all_bundle_dates.append(d_str)

    # Sort multiple bundles on same date: regular episode first, spin-offs after
    for d_str, blist in bundles_by_date.items():
        blist.sort(key=lambda b: (1 if b["episode"]["meta"].get("is_spinoff") else 0, b["slug"]))

    sched_dates = [
        str(e["date"])
        for e in ((program_schedule or {}).get("entries") or [])
        if isinstance(e, dict) and e.get("date")
    ]
    ed_dates = [
        str(g["date"])
        for g in ((editorial_plan or {}).get("daily_guides") or [])
        if isinstance(g, dict) and g.get("date")
    ]

    min_date_str = min(all_bundle_dates + [today_jst_str])
    max_candidates = all_bundle_dates + sched_dates + ed_dates + [today_jst_str]
    max_date_str = max(max_candidates)
    start_dt = _parse_date(min_date_str)
    end_dt = _parse_date(max_date_str)

    # Build weeks metadata from editorial_plan
    weeks_meta: dict[str, dict[str, Any]] = {}
    if editorial_plan:
        raw_weeks = editorial_plan.get("weeks") or []
        if not raw_weeks and editorial_plan.get("week_start") and editorial_plan.get("weekly_arc"):
            raw_weeks = [
                {
                    "week_start": editorial_plan["week_start"],
                    "week_end": editorial_plan.get("week_end", editorial_plan["week_start"]),
                    "weekly_arc": editorial_plan["weekly_arc"],
                    "upcoming_ideas": editorial_plan.get("upcoming_ideas", []),
                }
            ]
        for wk in raw_weeks:
            ws = str(wk.get("week_start") or "")
            if ws:
                arc = wk.get("weekly_arc") or {}
                weeks_meta[ws] = {
                    "week_start": ws,
                    "week_end": str(wk.get("week_end") or ""),
                    "arc_title": str(arc.get("title") or ""),
                    "arc_concept": str(arc.get("concept") or ""),
                }

    days_out: list[dict[str, Any]] = []
    # Track per-guest covered and planned topics
    guest_covered: dict[str, list[dict[str, Any]]] = {}
    guest_planned: dict[str, list[dict[str, Any]]] = {}

    cur = start_dt
    while cur <= end_dt:
        d_str = cur.isoformat()
        plan = resolve_day_plan(
            d_str,
            themes,
            special_days,
            editorial_plan=editorial_plan,
            program_schedule=program_schedule,
        )
        day_cfg = plan["day_cfg"]
        guest = day_cfg["guest"]
        guest_ui = guest.get("ui") or {}
        ps = plan.get("program_schedule") or {}
        eg = plan.get("editorial_guide") or {}
        sp = plan.get("scheduled_special")

        week_mon = cur - timedelta(days=cur.weekday())
        week_sun = week_mon + timedelta(days=6)
        ws_str = week_mon.isoformat()
        we_str = week_sun.isoformat()

        day_bundles = bundles_by_date.get(d_str, [])
        regular_bundles = [b for b in day_bundles if not b["episode"]["meta"].get("is_spinoff")]
        is_aired = len(day_bundles) > 0
        primary_bundle = regular_bundles[0] if regular_bundles else (day_bundles[0] if day_bundles else None)

        aired_cards: list[dict[str, Any]] = []
        for b in day_bundles:
            ep = b["episode"]
            mf = b["manifest"]
            meta = ep["meta"]
            ep_guest = ep.get("guest") or {}
            sp_feat = meta.get("special_feature")
            aired_cards.append(
                {
                    "slug": b["slug"],
                    "episode_label": meta.get("episode_label") or f"第{meta.get('episode_number', '')}回",
                    "subtitle": meta.get("subtitle", ""),
                    "theme_name": meta.get("theme_name", ""),
                    "edition_label": meta.get("edition_label", ""),
                    "duration": mf["meta"].get("total_duration_formatted", ""),
                    "has_audio": b["has_audio"],
                    "is_spinoff": bool(meta.get("is_spinoff")),
                    "special_title": sp_feat.get("title", "") if isinstance(sp_feat, dict) else "",
                    "keywords": list(ep_guest.get("keywords_featured") or []),
                    "kodaira_topics": list(meta.get("kodaira_topics") or []),
                    "href": f"episodes/{b['slug']}/index.html",
                }
            )

        # Special / holiday badge
        special_badges: list[str] = []
        special_title = ""
        if plan["is_holiday"] and plan["holiday_name"]:
            special_badges.append(f"祝日: {plan['holiday_name']}")
        if sp:
            special_title = str(sp.get("title") or "")
            phase = str(sp.get("phase_label") or "特別特集")
            special_badges.append(f"{phase}: {special_title}")

        # Determine expert topics & note
        if primary_bundle and not primary_bundle["episode"]["meta"].get("is_spinoff"):
            p_ep = primary_bundle["episode"]
            p_meta = p_ep["meta"]
            p_guest = p_ep.get("guest") or {}
            expert_topics = list(p_guest.get("keywords_featured") or ps.get("expert_topics") or [])
            expert_note = str(
                (p_ep.get("learned_notes") or {}).get("kodaira_discovery")
                or ps.get("expert_note")
                or ""
            )
            kodaira_topics = list(p_meta.get("kodaira_topics") or [])
            focus_area = ", ".join(p_meta.get("kodaira_areas") or []) or str(eg.get("focus_area") or "")
            edition_label = str(p_meta.get("edition_label") or plan["edition_label"])
            p_sp = p_meta.get("special_feature")
            if isinstance(p_sp, dict) and p_sp.get("title") and not special_title:
                special_title = str(p_sp["title"])
                special_badges.append(str(p_sp.get("phase_label") or "特別特集") + ": " + special_title)
            sched_status = "aired"
        else:
            expert_topics = list(ps.get("expert_topics") or [])
            expert_note = str(ps.get("expert_note") or eg.get("expert_angle") or "").strip()
            kodaira_angle = str(eg.get("kodaira_angle") or "").strip()
            kodaira_hint = str(ps.get("kodaira_hint") or "").strip()
            kodaira_topics = [x for x in ([kodaira_angle] if kodaira_angle else ([kodaira_hint] if kodaira_hint else [])) if x]
            focus_area = str(eg.get("focus_area") or "")
            edition_label = plan["edition_label"]
            sched_status = str(ps.get("status") or "proposed")

        is_special = bool(
            plan["is_holiday"]
            or sp is not None
            or any(c["is_spinoff"] or c["special_title"] for c in aired_cards)
        )

        # Accumulate specialist roadmap
        gid = guest["id"]
        if is_aired and primary_bundle and not primary_bundle["episode"]["meta"].get("is_spinoff"):
            guest_covered.setdefault(gid, []).append(
                {
                    "date": d_str,
                    "weekday_short": plan["weekday_ja"][:1],
                    "topics": expert_topics,
                    "href": f"episodes/{primary_bundle['slug']}/index.html",
                }
            )
        else:
            guest_planned.setdefault(gid, []).append(
                {
                    "date": d_str,
                    "weekday_short": plan["weekday_ja"][:1],
                    "is_holiday": plan["is_holiday"],
                    "holiday_name": plan["holiday_name"],
                    "is_special": is_special,
                    "special_badge": " ／ ".join(special_badges),
                    "topics": expert_topics,
                    "expert_note": expert_note,
                    "status": sched_status,
                    "locked": bool(ps.get("locked")),
                    "special_request": str(ps.get("special_request") or ""),
                }
            )

        days_out.append(
            {
                "date": d_str,
                "month": d_str[:7],
                "day": cur.day,
                "weekday": plan["day_key"],
                "weekday_idx": cur.weekday(),
                "weekday_ja": plan["weekday_ja"],
                "weekday_short": plan["weekday_ja"][:1],
                "week_start": ws_str,
                "week_end": we_str,
                "status": "aired" if is_aired else "planned",
                "schedule_status": sched_status,
                "locked": bool(ps.get("locked")),
                "special_request": str(ps.get("special_request") or ""),
                "is_today": d_str == today_jst_str,
                "is_weekend": plan["is_weekend"],
                "is_holiday": plan["is_holiday"],
                "holiday_name": plan["holiday_name"],
                "is_special": is_special,
                "special_badges": special_badges,
                "special_title": special_title,
                "edition_label": edition_label,
                "target_minutes": round(plan["target_duration_sec"] / 60),
                "theme_name": day_cfg["theme_name"],
                "guest_id": gid,
                "guest_name": guest["name"],
                "guest_title": guest["title"],
                "guest_color": guest_ui.get("color", "#1b5e3c"),
                "guest_bg": guest_ui.get("bg_soft", "#f0f9ff"),
                "expert_topics": expert_topics,
                "expert_note": expert_note,
                "kodaira_topics": kodaira_topics,
                "focus_area": focus_area,
                "aired_episodes": aired_cards,
            }
        )
        cur += timedelta(days=1)

    # Also ensure any topic_history entries earlier than min_date are reflected in covered history
    for entry in (topic_history or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        gid = entry.get("guest_id")
        d_str = str(entry.get("date") or "")
        if gid and d_str and all(x["date"] != d_str for x in guest_covered.get(gid, [])):
            guest_covered.setdefault(gid, []).append(
                {
                    "date": d_str,
                    "weekday_short": str(entry.get("weekday") or "")[:1],
                    "topics": list(entry.get("keywords_featured") or []),
                    "href": "",
                }
            )

    specialists_out: list[dict[str, Any]] = []
    for day_key, day_cfg in themes.get("days", {}).items():
        g = day_cfg["guest"]
        gid = g["id"]
        g_ui = g.get("ui") or {}
        cov = sorted(guest_covered.get(gid, []), key=lambda x: x["date"])
        pln = sorted(guest_planned.get(gid, []), key=lambda x: x["date"])
        all_assigned = [t for item in cov + pln for t in item["topics"]]
        remaining = [
            kw for kw in g.get("keywords_bank", []) if not _is_keyword_covered(kw, all_assigned)
        ]
        specialists_out.append(
            {
                "day_key": day_key,
                "weekday_ja": day_cfg["weekday_ja"],
                "weekday_short": day_cfg["weekday_ja"][:1],
                "theme_name": day_cfg["theme_name"],
                "id": gid,
                "name": g["name"],
                "title": g["title"],
                "color": g_ui.get("color", "#1b5e3c"),
                "bg_soft": g_ui.get("bg_soft", "#f0f9ff"),
                "cast_href": f"cast.html#{gid}",
                "covered": cov,
                "planned": pln,
                "remaining_bank": remaining,
            }
        )

    months = sorted({d["month"] for d in days_out})
    return {
        "today_jst": today_jst_str,
        "horizon_end": max_date_str,
        "months": months,
        "weeks_meta": weeks_meta,
        "upcoming_ideas": (editorial_plan or {}).get("upcoming_ideas", []),
        "days": days_out,
        "specialists": specialists_out,
        "counts": {
            "total_days": len(days_out),
            "aired_days": sum(1 for d in days_out if d["status"] == "aired"),
            "aired_episodes": sum(len(d["aired_episodes"]) for d in days_out),
            "planned_days": sum(1 for d in days_out if d["status"] == "planned"),
            "special_days": sum(1 for d in days_out if d["is_special"]),
        },
    }


CALENDAR_CSS = """
.cal-banner {
  padding: 0.95rem 1.05rem;
  border-left: 4px solid var(--amber);
  background: linear-gradient(180deg, #fffdf8 0%, #ffffff 100%);
}
.cal-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.6rem;
}
.cal-stat-pill {
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.22rem 0.65rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #fff;
}
.cal-stat-pill.is-aired { background: var(--forest-soft); color: var(--forest-dark); border-color: #a7d7bc; }
.cal-stat-pill.is-planned { background: var(--heizo-soft); color: var(--heizo); border-color: #bfdbfe; }
.cal-stat-pill.is-special { background: var(--amber-soft); color: #92400e; border-color: #fcd34d; }
.cal-guide-box {
  font-size: 0.86rem;
  line-height: 1.65;
  color: var(--ink);
  background: #fcfcfa;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  padding: 0.68rem 0.85rem;
}
.cal-filter-card {
  padding: 0.82rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.62rem;
}
.cal-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}
.cal-filter-label {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--muted);
  margin-right: 0.2rem;
}
.cal-pill-btn {
  font-size: 0.78rem;
  padding: 0.3rem 0.62rem;
  min-height: 32px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--ink);
  font-weight: 700;
}
.cal-pill-btn.active {
  background: var(--forest);
  color: #fff;
  border-color: var(--forest);
}
.cal-search {
  width: 100%;
  padding: 0.48rem 0.78rem;
  border-radius: 9px;
  border: 1px solid var(--border);
  font-size: 16px;
  font-family: inherit;
}

/* Monthly calendar grid */
.cal-months-wrap {
  padding: 0.85rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 1.15rem;
}
.cal-month-title {
  margin: 0 0 0.55rem;
  font-size: 1rem;
  color: var(--forest-dark);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.cal-dow-head {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.35rem;
  margin-bottom: 0.35rem;
}
.cal-dow-cell {
  text-align: center;
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--muted);
  padding: 0.2rem;
  background: #f3f5f2;
  border-radius: 6px;
}
.cal-month-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.35rem;
}
.cal-grid-empty {
  background: #fafaf7;
  border: 1px dashed #e5e7eb;
  border-radius: 10px;
  min-height: 82px;
}
.cal-cell {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  text-decoration: none;
  color: inherit;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.42rem 0.48rem;
  background: #fff;
  min-height: 92px;
  min-width: 0;
  overflow: hidden;
  transition: transform 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.cal-cell:hover {
  border-color: var(--forest);
  box-shadow: 0 4px 12px rgba(18, 64, 40, 0.10);
  transform: translateY(-1px);
}
.cal-cell.is-aired {
  background: #f4fbf6;
  border-color: #b7e1c7;
}
.cal-cell.is-today {
  border: 2px solid var(--amber);
  box-shadow: 0 0 0 2px rgba(217, 119, 6, 0.14);
}
.cal-cell.is-dimmed {
  opacity: 0.32;
}
.cal-cell-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem;
}
.cal-cell-num {
  font-size: 0.82rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}
.cal-cell-dow-inline {
  display: none;
  font-size: 0.7rem;
  color: var(--muted);
  font-weight: 700;
}
.cal-cell-badge {
  font-size: 0.64rem;
  font-weight: 700;
  padding: 0.06rem 0.35rem;
  border-radius: 999px;
  white-space: nowrap;
}
.cal-cell-badge.aired { background: var(--forest); color: #fff; }
.cal-cell-badge.holiday { background: var(--amber); color: #fff; }
.cal-cell-badge.special { background: #7c3aed; color: #fff; }
.cal-cell-badge.planned { background: #e2e8f0; color: #334155; }
.cal-cell-guest {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.7rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cal-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex: 0 0 auto;
}
.cal-cell-topic {
  font-size: 0.69rem;
  line-height: 1.35;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Week-grouped detail cards */
.week-group {
  margin-bottom: 1.15rem;
}
.week-arc-banner {
  padding: 0.78rem 1rem;
  background: linear-gradient(135deg, #f0f9f4 0%, #fcfcfa 100%);
  border-bottom: 1px solid var(--border);
  border-left: 4px solid var(--forest);
}
.week-arc-range {
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--forest);
}
.week-arc-title {
  margin: 0.12rem 0 0.2rem;
  font-size: 1rem;
  color: var(--forest-dark);
}
.week-arc-concept {
  margin: 0;
  font-size: 0.82rem;
  color: var(--muted);
}
.day-list {
  padding: 0.85rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.75rem;
}
.day-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.85rem 0.95rem;
  background: #fff;
  scroll-margin-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
  min-width: 0;
  overflow-wrap: anywhere;
}
.day-card.is-aired {
  border-left: 4px solid var(--forest);
  background: #fbfefb;
}
.day-card.is-planned {
  border-left: 4px solid var(--guest-accent, #2563eb);
}
.day-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
}
.day-date-title {
  font-size: 0.98rem;
  font-weight: 800;
  color: var(--ink);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.status-chip {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.14rem 0.55rem;
  border-radius: 999px;
}
.status-chip.aired { background: var(--forest); color: #fff; }
.status-chip.proposed { background: #e0f2fe; color: #0369a1; }
.status-chip.confirmed { background: #ede9fe; color: #6d28d9; }
.day-expert-box {
  border-radius: 10px;
  padding: 0.62rem 0.78rem;
  border: 1px solid var(--border);
}
.day-expert-label {
  font-size: 0.74rem;
  font-weight: 800;
  margin-bottom: 0.28rem;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.day-expert-note {
  margin: 0.35rem 0 0;
  font-size: 0.82rem;
  color: var(--ink);
  line-height: 1.55;
}
.day-local-row {
  font-size: 0.82rem;
  color: var(--muted);
  line-height: 1.55;
}
.day-local-row strong {
  color: var(--ink);
}
.day-aired-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.15rem;
}

/* Specialist roadmap grid */
.spec-grid {
  padding: 0.85rem;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
}
.spec-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.85rem 0.95rem;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-width: 0;
}
.spec-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.spec-timeline {
  display: flex;
  flex-direction: column;
  gap: 0.42rem;
}
.spec-row {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.45rem 0.6rem;
  font-size: 0.8rem;
  background: #fcfcfa;
}
.spec-row.aired {
  background: #f0fdf4;
  border-color: #bbf7d0;
}
.spec-row-date {
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  margin-right: 0.35rem;
}

@media (max-width: 760px) {
  .cal-dow-head { display: none; }
  .cal-grid-empty { display: none; }
  .cal-month-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.4rem;
  }
  .cal-cell {
    min-height: 76px;
  }
  .cal-cell-dow-inline { display: inline; }
  .spec-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
"""

CALENDAR_HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>放送内容カレンダー | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>
$COMMON_CSS
$CALENDAR_CSS
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      $NAV_HTML
    </div>
  </header>

  <main class="container single">
    <div class="card cal-banner">
      <div class="cal-stats" id="cal-stats"></div>
      <div class="cal-guide-box">
        <strong>💡 専門家テーマの変更リクエスト・ネタの追加はいつでも大歓迎です！</strong><br />
        このカレンダーは、過去の放送実績と <strong>$HORIZON_END までの専門家解説テーマ事前予定</strong> をまとめた編成表です（編集元：<code>config/program_schedule.json</code>）。
        「この日にこのテーマを扱ってほしい」「最近思いついたこの小平ネタを入れてほしい」と随時リクエストいただければ、該当日の予定を更新し、前後の重複を避けながら今後の放送予定全体を見直します。
      </div>
    </div>

    <div class="card cal-filter-card">
      <input type="search" id="cal-search" class="cal-search" placeholder="テーマ・専門家・小平のスポットを検索（例：耐震、キウイ、トラッキング、小川パレット…）" />
      <div class="cal-filter-row" id="month-filters">
        <span class="cal-filter-label">月別:</span>
      </div>
      <div class="cal-filter-row" id="status-filters">
        <span class="cal-filter-label">状態:</span>
        <button type="button" class="cal-pill-btn active" data-status="all">すべて</button>
        <button type="button" class="cal-pill-btn" data-status="aired">放送済み</button>
        <button type="button" class="cal-pill-btn" data-status="planned">今後の予定</button>
        <button type="button" class="cal-pill-btn" data-status="special">祝日・特別拡大版</button>
      </div>
      <div class="cal-filter-row" id="day-filters">
        <span class="cal-filter-label">曜日・専門:</span>
        <button type="button" class="cal-pill-btn active" data-day="all">全曜日</button>
        <button type="button" class="cal-pill-btn" data-day="monday">月・地震</button>
        <button type="button" class="cal-pill-btn" data-day="tuesday">火・気象</button>
        <button type="button" class="cal-pill-btn" data-day="wednesday">水・火災</button>
        <button type="button" class="cal-pill-btn" data-day="thursday">木・医療</button>
        <button type="button" class="cal-pill-btn" data-day="friday">金・食備蓄</button>
        <button type="button" class="cal-pill-btn" data-day="saturday">土・地域</button>
        <button type="button" class="cal-pill-btn" data-day="sunday">日・テック</button>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>月間放送カレンダー（タップで詳細へジャンプ）</h2>
        <span class="hint">緑=放送済み ／ 橙枠=本日</span>
      </div>
      <div class="cal-months-wrap" id="cal-months-wrap"></div>
    </div>

    <div id="weeks-container"></div>

    <div class="card">
      <div class="section-head">
        <h2>7人の専門家別・今後の解説テーマ予定表</h2>
        <span class="hint">過去90日重複防止ルール連動</span>
      </div>
      <div class="spec-grid" id="spec-grid"></div>
    </div>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ <a href="tech.html">番組の技術解説・対談音声へ →</a></footer>

  <script type="application/json" id="calendar-data">$PAYLOAD_JSON</script>
  <script>
    (function () {
      const data = JSON.parse(document.getElementById("calendar-data").textContent);
      const statsEl = document.getElementById("cal-stats");
      const monthFiltersEl = document.getElementById("month-filters");
      const statusButtons = Array.from(document.querySelectorAll("#status-filters button"));
      const dayButtons = Array.from(document.querySelectorAll("#day-filters button"));
      const searchInput = document.getElementById("cal-search");
      const monthsWrap = document.getElementById("cal-months-wrap");
      const weeksContainer = document.getElementById("weeks-container");
      const specGrid = document.getElementById("spec-grid");

      let selectedMonth = "all";
      let selectedStatus = "all";
      let selectedDay = "all";

      function addStatPill(cls, text) {
        const span = document.createElement("span");
        span.className = "cal-stat-pill " + cls;
        span.textContent = text;
        statsEl.appendChild(span);
      }
      addStatPill("is-aired", "放送済み: " + data.counts.aired_days + "日（" + data.counts.aired_episodes + "本）");
      addStatPill("is-planned", "今後の予定: " + data.counts.planned_days + "日分（〜" + data.horizon_end + "）");
      addStatPill("is-special", "祝日・特別拡大版: " + data.counts.special_days + "日");

      // Build month filter buttons
      const allMBtn = document.createElement("button");
      allMBtn.type = "button";
      allMBtn.className = "cal-pill-btn active";
      allMBtn.dataset.month = "all";
      allMBtn.textContent = "すべて";
      monthFiltersEl.appendChild(allMBtn);

      data.months.forEach((ym) => {
        const parts = ym.split("-");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cal-pill-btn";
        btn.dataset.month = ym;
        btn.textContent = parts[0] + "年" + parseInt(parts[1], 10) + "月";
        monthFiltersEl.appendChild(btn);
      });

      const monthButtons = Array.from(monthFiltersEl.querySelectorAll("button"));
      monthButtons.forEach((b) => {
        b.addEventListener("click", () => {
          selectedMonth = b.dataset.month || "all";
          monthButtons.forEach((x) => x.classList.toggle("active", x === b));
          renderAll();
        });
      });

      statusButtons.forEach((b) => {
        b.addEventListener("click", () => {
          selectedStatus = b.dataset.status || "all";
          statusButtons.forEach((x) => x.classList.toggle("active", x === b));
          renderAll();
        });
      });

      dayButtons.forEach((b) => {
        b.addEventListener("click", () => {
          selectedDay = b.dataset.day || "all";
          dayButtons.forEach((x) => x.classList.toggle("active", x === b));
          renderAll();
        });
      });

      searchInput.addEventListener("input", renderAll);

      function matchesFilters(d) {
        if (selectedMonth !== "all" && d.month !== selectedMonth) return false;
        if (selectedStatus === "aired" && d.status !== "aired") return false;
        if (selectedStatus === "planned" && d.status !== "planned") return false;
        if (selectedStatus === "special" && !d.is_special) return false;
        if (selectedDay !== "all" && d.weekday !== selectedDay) return false;
        const q = (searchInput.value || "").trim().toLowerCase();
        if (!q) return true;
        const hay = [
          d.date, d.weekday_ja, d.theme_name, d.guest_name, d.edition_label,
          d.holiday_name, d.special_title, d.expert_note, d.focus_area, d.special_request,
          ...(d.expert_topics || []), ...(d.kodaira_topics || []),
          ...(d.aired_episodes || []).map((e) => e.subtitle + " " + e.special_title)
        ].join(" ").toLowerCase();
        return hay.includes(q);
      }

      function renderMonthGrid(filteredSet) {
        monthsWrap.innerHTML = "";
        const monthsToShow = selectedMonth === "all" ? data.months : [selectedMonth];

        monthsToShow.forEach((ym) => {
          const monthDays = data.days.filter((d) => d.month === ym);
          if (monthDays.length === 0) return;

          const parts = ym.split("-");
          const sec = document.createElement("section");
          const h3 = document.createElement("h3");
          h3.className = "cal-month-title";
          h3.textContent = parts[0] + "年" + parseInt(parts[1], 10) + "月";
          sec.appendChild(h3);

          const dowHead = document.createElement("div");
          dowHead.className = "cal-dow-head";
          ["月", "火", "水", "木", "金", "土", "日"].forEach((lbl) => {
            const c = document.createElement("div");
            c.className = "cal-dow-cell";
            c.textContent = lbl;
            dowHead.appendChild(c);
          });
          sec.appendChild(dowHead);

          const grid = document.createElement("div");
          grid.className = "cal-month-grid";

          // Leading empty padding up to the first visible day's weekday (Monday=0)
          const firstIdx = monthDays[0].weekday_idx;
          for (let i = 0; i < firstIdx; i++) {
            const emp = document.createElement("div");
            emp.className = "cal-grid-empty";
            grid.appendChild(emp);
          }

          monthDays.forEach((d) => {
            const isMatch = filteredSet.has(d.date);
            const cell = document.createElement("a");
            cell.className = "cal-cell"
              + (d.status === "aired" ? " is-aired" : "")
              + (d.is_today ? " is-today" : "")
              + (!isMatch ? " is-dimmed" : "");
            cell.href = "#day-" + d.date;

            const top = document.createElement("div");
            top.className = "cal-cell-top";
            const num = document.createElement("span");
            num.className = "cal-cell-num";
            num.textContent = String(d.day) + "日";
            const dowInline = document.createElement("span");
            dowInline.className = "cal-cell-dow-inline";
            dowInline.textContent = "(" + d.weekday_short + ")";
            num.appendChild(dowInline);

            const badge = document.createElement("span");
            if (d.status === "aired") {
              badge.className = "cal-cell-badge aired";
              badge.textContent = "放送済";
            } else if (d.is_holiday) {
              badge.className = "cal-cell-badge holiday";
              badge.textContent = "祝15m";
            } else if (d.is_special) {
              badge.className = "cal-cell-badge special";
              badge.textContent = "特集";
            } else if (d.is_weekend) {
              badge.className = "cal-cell-badge planned";
              badge.textContent = "15m";
            } else {
              badge.className = "cal-cell-badge planned";
              badge.textContent = "予定";
            }

            top.appendChild(num);
            top.appendChild(badge);
            cell.appendChild(top);

            const gRow = document.createElement("div");
            gRow.className = "cal-cell-guest";
            const dot = document.createElement("span");
            dot.className = "cal-dot";
            dot.style.background = d.guest_color;
            gRow.appendChild(dot);
            gRow.appendChild(document.createTextNode(d.guest_name));
            cell.appendChild(gRow);

            const topic = document.createElement("div");
            topic.className = "cal-cell-topic";
            topic.textContent = (d.expert_topics && d.expert_topics.length > 0)
              ? d.expert_topics.join("／")
              : d.theme_name;
            cell.appendChild(topic);

            grid.appendChild(cell);
          });

          sec.appendChild(grid);
          monthsWrap.appendChild(sec);
        });
      }

      function renderWeekCards(filteredDays) {
        weeksContainer.innerHTML = "";
        if (filteredDays.length === 0) {
          const emptyCard = document.createElement("div");
          emptyCard.className = "card";
          const p = document.createElement("p");
          p.style.padding = "1rem";
          p.style.color = "var(--muted)";
          p.textContent = "指定した条件に一致する放送予定・履歴が見つかりませんでした。";
          emptyCard.appendChild(p);
          weeksContainer.appendChild(emptyCard);
          return;
        }

        const groups = new Map();
        filteredDays.forEach((d) => {
          if (!groups.has(d.week_start)) {
            groups.set(d.week_start, []);
          }
          groups.get(d.week_start).push(d);
        });

        groups.forEach((days, ws) => {
          const card = document.createElement("div");
          card.className = "card week-group";

          const wm = data.weeks_meta[ws];
          const arcHead = document.createElement("div");
          arcHead.className = "week-arc-banner";
          const range = document.createElement("div");
          range.className = "week-arc-range";
          const we = (wm && wm.week_end) || days[days.length - 1].week_end;
          range.textContent = "週別編成: " + ws + " 〜 " + we;
          const h2 = document.createElement("h2");
          h2.className = "week-arc-title";
          h2.textContent = (wm && wm.arc_title)
            ? wm.arc_title
            : "事前編成：専門家解説テーマ提案ウィーク（編集長AIが日曜に地元企画を肉付け予定）";
          const concept = document.createElement("p");
          concept.className = "week-arc-concept";
          concept.textContent = (wm && wm.arc_concept)
            ? wm.arc_concept
            : "季節やイベントに合わせた小平の話題は、放送直前の日曜12:17頃に編集長AIが最新検索して編成します。ご希望のテーマ変更はいつでもお知らせください。";
          arcHead.appendChild(range);
          arcHead.appendChild(h2);
          arcHead.appendChild(concept);
          card.appendChild(arcHead);

          const list = document.createElement("div");
          list.className = "day-list";

          days.forEach((d) => {
            const dc = document.createElement("article");
            dc.id = "day-" + d.date;
            dc.className = "day-card " + (d.status === "aired" ? "is-aired" : "is-planned");
            dc.style.setProperty("--guest-accent", d.guest_color);

            const head = document.createElement("div");
            head.className = "day-card-head";

            const titleWrap = document.createElement("div");
            titleWrap.className = "day-date-title";
            const dtText = document.createElement("span");
            dtText.textContent = d.date + "（" + d.weekday_short + "）";
            titleWrap.appendChild(dtText);

            if (d.is_today) {
              const tp = document.createElement("span");
              tp.className = "edition-pill";
              tp.textContent = "本日";
              titleWrap.appendChild(tp);
            }

            const edPill = document.createElement("span");
            edPill.className = "edition-pill";
            edPill.textContent = d.edition_label;
            titleWrap.appendChild(edPill);

            const gPill = document.createElement("span");
            gPill.className = "theme-pill";
            gPill.style.background = d.guest_bg;
            gPill.style.color = d.guest_color;
            gPill.textContent = d.theme_name + " ／ " + d.guest_name;
            titleWrap.appendChild(gPill);

            const stChip = document.createElement("span");
            if (d.status === "aired") {
              stChip.className = "status-chip aired";
              stChip.textContent = "放送済み";
            } else if (d.schedule_status === "confirmed" || d.locked) {
              stChip.className = "status-chip confirmed";
              stChip.textContent = d.locked ? "リクエスト固定" : "確定";
            } else {
              stChip.className = "status-chip proposed";
              stChip.textContent = "テーマ提案中（変更可）";
            }

            head.appendChild(titleWrap);
            head.appendChild(stChip);
            dc.appendChild(head);

            if (d.special_badges && d.special_badges.length > 0) {
              const spRow = document.createElement("div");
              spRow.style.display = "flex";
              spRow.style.flexWrap = "wrap";
              spRow.style.gap = "0.35rem";
              d.special_badges.forEach((sb) => {
                const sp = document.createElement("span");
                sp.className = "pill-tag";
                sp.style.background = "#fef3c7";
                sp.style.color = "#92400e";
                sp.textContent = "★ " + sb;
                spRow.appendChild(sp);
              });
              dc.appendChild(spRow);
            }

            // Expert topic box
            const expBox = document.createElement("div");
            expBox.className = "day-expert-box";
            expBox.style.background = d.guest_bg;

            const expLbl = document.createElement("div");
            expLbl.className = "day-expert-label";
            expLbl.style.color = d.guest_color;
            expLbl.textContent = d.status === "aired"
              ? "解説した専門キーワード（" + d.guest_name + "）"
              : "専門家による解説テーマ予定（" + d.guest_name + "）";
            expBox.appendChild(expLbl);

            if (d.expert_topics && d.expert_topics.length > 0) {
              const kwWrap = document.createElement("div");
              kwWrap.className = "kw-wrap";
              kwWrap.style.marginTop = "0";
              d.expert_topics.forEach((kw) => {
                const chip = document.createElement("span");
                chip.className = "kw-chip";
                chip.textContent = kw;
                kwWrap.appendChild(chip);
              });
              expBox.appendChild(kwWrap);
            }

            if (d.expert_note) {
              const noteP = document.createElement("p");
              noteP.className = "day-expert-note";
              noteP.textContent = d.expert_note;
              expBox.appendChild(noteP);
            }
            dc.appendChild(expBox);

            // Kodaira angle
            if (d.focus_area || (d.kodaira_topics && d.kodaira_topics.length > 0)) {
              const loc = document.createElement("div");
              loc.className = "day-local-row";
              const st = document.createElement("strong");
              st.textContent = "小平のまち・エリア予定: ";
              loc.appendChild(st);
              const pieces = [];
              if (d.focus_area) pieces.push("[" + d.focus_area + "]");
              if (d.kodaira_topics && d.kodaira_topics.length > 0) {
                pieces.push(d.kodaira_topics.join(" ／ "));
              }
              loc.appendChild(document.createTextNode(pieces.join(" ")));
              dc.appendChild(loc);
            }

            if (d.special_request) {
              const req = document.createElement("div");
              req.className = "day-local-row";
              const st = document.createElement("strong");
              st.textContent = "反映済みリクエスト: ";
              req.appendChild(st);
              req.appendChild(document.createTextNode(d.special_request));
              dc.appendChild(req);
            }

            if (d.aired_episodes && d.aired_episodes.length > 0) {
              const act = document.createElement("div");
              act.className = "day-aired-actions";
              d.aired_episodes.forEach((ep) => {
                const a = document.createElement("a");
                a.className = "btn-link";
                a.href = ep.href;
                a.textContent = ep.episode_label + "（" + ep.duration + "）を聴く・読む →";
                act.appendChild(a);
              });
              dc.appendChild(act);
            }

            list.appendChild(dc);
          });

          card.appendChild(list);
          weeksContainer.appendChild(card);
        });
      }

      function renderSpecialists() {
        specGrid.innerHTML = "";
        data.specialists.forEach((s) => {
          const card = document.createElement("article");
          card.className = "spec-card";
          card.style.borderTop = "4px solid " + s.color;

          const head = document.createElement("div");
          head.className = "spec-head";
          const h3 = document.createElement("h3");
          h3.style.margin = "0";
          h3.style.fontSize = "1rem";
          h3.textContent = s.weekday_ja + "｜" + s.name;
          const link = document.createElement("a");
          link.href = s.cast_href;
          link.style.fontSize = "0.78rem";
          link.style.fontWeight = "700";
          link.textContent = "紹介・ボイス →";
          head.appendChild(h3);
          head.appendChild(link);
          card.appendChild(head);

          const th = document.createElement("div");
          th.style.fontSize = "0.8rem";
          th.style.color = s.color;
          th.style.fontWeight = "700";
          th.textContent = s.theme_name + "（" + s.title + "）";
          card.appendChild(th);

          const tl = document.createElement("div");
          tl.className = "spec-timeline";

          s.covered.forEach((item) => {
            const row = document.createElement("div");
            row.className = "spec-row aired";
            const dt = document.createElement("span");
            dt.className = "spec-row-date";
            dt.textContent = item.date + " [放送済]";
            row.appendChild(dt);
            row.appendChild(document.createTextNode(item.topics.join(" ／ ")));
            tl.appendChild(row);
          });

          s.planned.forEach((item) => {
            const row = document.createElement("div");
            row.className = "spec-row";
            const dt = document.createElement("span");
            dt.className = "spec-row-date";
            dt.textContent = item.date + (item.is_holiday ? " [祝15m]" : (item.is_special ? " [特集]" : ""));
            row.appendChild(dt);
            row.appendChild(document.createTextNode(item.topics.join(" ／ ")));
            tl.appendChild(row);
          });
          card.appendChild(tl);

          if (s.remaining_bank && s.remaining_bank.length > 0) {
            const rem = document.createElement("div");
            rem.style.fontSize = "0.75rem";
            rem.style.color = "var(--muted)";
            rem.textContent = "今後の追加候補ストック: " + s.remaining_bank.join(" ／ ");
            card.appendChild(rem);
          }

          specGrid.appendChild(card);
        });
      }

      function renderAll() {
        const filtered = data.days.filter(matchesFilters);
        const filteredSet = new Set(filtered.map((d) => d.date));
        renderMonthGrid(filteredSet);
        renderWeekCards(filtered);
      }

      renderAll();
      renderSpecialists();
    })();
  </script>
</body>
</html>
""")


def render_calendar_page(
    bundles: list[dict[str, Any]],
    themes: dict[str, Any],
    special_days: dict[str, Any],
    editorial_plan: dict[str, Any] | None,
    program_schedule: dict[str, Any] | None,
    topic_history: dict[str, Any] | None,
    today_jst_str: str,
    common_css: str,
    nav_html: str,
    safe_json_fn: Any,
) -> str:
    """Render docs/calendar.html using build_site.py common styling and navigation."""
    payload = _build_calendar_payload(
        bundles=bundles,
        themes=themes,
        special_days=special_days,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        topic_history=topic_history,
        today_jst_str=today_jst_str,
    )
    return CALENDAR_HTML_TEMPLATE.substitute(
        COMMON_CSS=common_css,
        CALENDAR_CSS=CALENDAR_CSS,
        NAV_HTML=nav_html,
        HORIZON_END=payload["horizon_end"],
        PAYLOAD_JSON=safe_json_fn(payload),
    )
