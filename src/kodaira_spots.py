"""Shared Kodaira City spot catalog loader, 90-day cooldown tracker, balanced selector, and overlap auditor."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SPOT_COOLDOWN_DAYS = 90
ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SPOTS_PATH = ROOT_DIR / "config" / "kodaira_spots.json"

MONTH_TO_SEASON: dict[int, str] = {
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
}


def load_kodaira_spots(path: Path = DEFAULT_SPOTS_PATH) -> dict[str, Any]:
    """Load config/kodaira_spots.json with a safe empty fallback if absent."""
    if not path.is_file():
        return {
            "version": 1,
            "default_cooldown_days": SPOT_COOLDOWN_DAYS,
            "categories": [],
            "spots": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_match_text(text: str) -> tuple[str, str]:
    """Return (space-collapsed NFKC lowercase, space-stripped NFKC lowercase)."""
    norm = unicodedata.normalize("NFKC", text or "").lower()
    collapsed = re.sub(r"\s+", " ", norm).strip()
    compact = re.sub(r"[\s・／/、。・「」『』]+", "", norm)
    return collapsed, compact


def _parse_iso_date(date_str: str) -> date | None:
    try:
        return datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def match_spots_in_text(text: str, spots_cfg: dict[str, Any]) -> list[str]:
    """Return unique spot IDs whose name or >=3-char aliases match inside text."""
    collapsed_hay, compact_hay = _normalize_match_text(text)
    if not collapsed_hay:
        return []

    matched: list[str] = []
    seen: set[str] = set()
    for spot in spots_cfg.get("spots") or []:
        if not isinstance(spot, dict) or not spot.get("id"):
            continue
        sid = str(spot["id"])
        candidates: list[str] = []
        if spot.get("name"):
            candidates.append(str(spot["name"]))
        for al in spot.get("aliases") or []:
            if al:
                candidates.append(str(al))

        hit = False
        for cand in candidates:
            c_col, c_comp = _normalize_match_text(cand)
            if len(c_col) < 3 or len(c_comp) < 3:
                continue
            if c_col in collapsed_hay or (len(c_comp) >= 4 and c_comp in compact_hay):
                hit = True
                break

        if hit and sid not in seen:
            seen.add(sid)
            matched.append(sid)
    return matched


def _extract_entry_text_for_history(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    if entry.get("subtitle"):
        parts.append(str(entry["subtitle"]))
    for key in ("kodaira_topics", "kodaira_areas"):
        for val in entry.get(key) or []:
            if val:
                parts.append(str(val))
    if entry.get("special_feature_title"):
        parts.append(str(entry["special_feature_title"]))
    return "\n".join(parts)


def _extract_guide_text(guide: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("focus_area", "kodaira_angle"):
        if guide.get(key):
            parts.append(str(guide[key]))
    for h in guide.get("search_hints") or []:
        if h:
            parts.append(str(h))
    ed_sp = guide.get("editorial_special")
    if isinstance(ed_sp, dict):
        if ed_sp.get("title"):
            parts.append(str(ed_sp["title"]))
        if ed_sp.get("theme_focus"):
            parts.append(str(ed_sp["theme_focus"]))
    return "\n".join(parts)


def _spot_ids_from_record(
    explicit_ids: Any,
    text: str,
    spots_cfg: dict[str, Any],
    valid_ids: set[str],
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(explicit_ids, list):
        for sid in explicit_ids:
            s = str(sid or "").strip()
            if s in valid_ids and s not in seen:
                seen.add(s)
                out.append(s)
    for sid in match_spots_in_text(text, spots_cfg):
        if sid in valid_ids and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def compute_spot_usage(
    spots_cfg: dict[str, Any],
    topic_history_entries: list[dict[str, Any]],
    editorial_plan: dict[str, Any] | None = None,
    program_schedule: dict[str, Any] | None = None,
    reference_date: str | date | None = None,
    exclude_date_range: tuple[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Track aired/planned dates and 90-day cooldown state for every catalog spot."""
    if isinstance(reference_date, date):
        ref_dt = reference_date
    elif isinstance(reference_date, str) and reference_date.strip():
        ref_dt = _parse_iso_date(reference_date) or date.today()
    else:
        ref_dt = date.today()

    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]
    valid_ids = {str(s["id"]) for s in spots}
    default_cd = int(spots_cfg.get("default_cooldown_days") or SPOT_COOLDOWN_DAYS)

    aired_map: dict[str, set[str]] = {sid: set() for sid in valid_ids}
    planned_map: dict[str, set[str]] = {sid: set() for sid in valid_ids}
    hint_map: dict[str, set[str]] = {sid: set() for sid in valid_ids}

    aired_dates_set: set[str] = set()
    for entry in topic_history_entries or []:
        if not isinstance(entry, dict) or not entry.get("date"):
            continue
        d_str = str(entry["date"]).strip()
        if exclude_date_range and exclude_date_range[0] <= d_str <= exclude_date_range[1]:
            continue
        aired_dates_set.add(d_str)
        sids = _spot_ids_from_record(
            entry.get("spot_ids"),
            _extract_entry_text_for_history(entry),
            spots_cfg,
            valid_ids,
        )
        for sid in sids:
            aired_map[sid].add(d_str)

    ed_dates_set: set[str] = set()
    if isinstance(editorial_plan, dict):
        for guide in editorial_plan.get("daily_guides") or []:
            if not isinstance(guide, dict) or not guide.get("date"):
                continue
            d_str = str(guide["date"]).strip()
            if exclude_date_range and exclude_date_range[0] <= d_str <= exclude_date_range[1]:
                continue
            if d_str in aired_dates_set:
                continue
            ed_dates_set.add(d_str)
            sids = _spot_ids_from_record(
                guide.get("spot_ids"),
                _extract_guide_text(guide),
                spots_cfg,
                valid_ids,
            )
            for sid in sids:
                planned_map[sid].add(d_str)

    if isinstance(program_schedule, dict):
        for entry in program_schedule.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("date"):
                continue
            d_str = str(entry["date"]).strip()
            if exclude_date_range and exclude_date_range[0] <= d_str <= exclude_date_range[1]:
                continue
            if d_str in aired_dates_set or d_str in ed_dates_set:
                continue
            txt = f"{entry.get('kodaira_hint') or ''}\n{entry.get('special_request') or ''}"
            sids = _spot_ids_from_record(entry.get("spot_ids"), txt, spots_cfg, valid_ids)
            for sid in sids:
                hint_map[sid].add(d_str)

    usage_out: dict[str, dict[str, Any]] = {}
    for spot in spots:
        sid = str(spot["id"])
        cd_days = int(spot.get("cooldown_days") or default_cd)
        aired_dates = sorted(aired_map[sid])
        planned_dates = sorted(planned_map[sid])
        hint_dates = sorted(hint_map[sid])

        # Aired + confirmed/editorial planned dates count toward cooldown checks
        active_dates = sorted(set(aired_dates) | set(planned_dates))
        in_cooldown = False
        cooldown_dates: list[str] = []
        for d_str in active_dates:
            dt = _parse_iso_date(d_str)
            if not dt:
                continue
            diff = (ref_dt - dt).days
            # Any appearance strictly before ref_dt within cooldown OR upcoming within cooldown
            if (0 < diff < cd_days) or (diff <= 0 and abs(diff) < cd_days and d_str != ref_dt.isoformat()):
                in_cooldown = True
                cooldown_dates.append(d_str)
            elif diff == 0 and d_str in aired_dates:
                # Already aired on ref_dt itself
                in_cooldown = True
                cooldown_dates.append(d_str)

        past_or_ref = [d for d in active_dates if d <= ref_dt.isoformat()]
        last_aired = aired_dates[-1] if aired_dates else None
        last_used = past_or_ref[-1] if past_or_ref else (active_dates[-1] if active_dates else None)
        days_since: int | None = None
        if past_or_ref:
            last_dt = _parse_iso_date(past_or_ref[-1])
            if last_dt:
                days_since = (ref_dt - last_dt).days

        if in_cooldown and aired_dates:
            status = "aired_cooldown"
        elif in_cooldown or planned_dates or hint_dates:
            status = "planned_upcoming"
        elif aired_dates:
            status = "aired_ready"
        else:
            status = "unfeatured"

        usage_out[sid] = {
            "spot_id": sid,
            "cooldown_days": cd_days,
            "aired_dates": aired_dates,
            "aired_count": len(aired_dates),
            "last_aired_date": last_aired,
            "planned_dates": planned_dates,
            "hint_dates": hint_dates,
            "cooldown_trigger_dates": sorted(cooldown_dates),
            "last_used_date": last_used,
            "days_since_last": days_since,
            "in_cooldown": in_cooldown,
            "status": status,
        }

    return usage_out


def select_balanced_spot_candidates(
    spots_cfg: dict[str, Any],
    usage_map: dict[str, dict[str, Any]],
    target_dt: date | str,
    count: int = 18,
    include_hinted: bool = True,
) -> list[dict[str, Any]]:
    """Pick a diverse, non-cooldown candidate list across categories & Kodaira areas."""
    if isinstance(target_dt, str):
        dt = _parse_iso_date(target_dt) or date.today()
    else:
        dt = target_dt

    season = MONTH_TO_SEASON.get(dt.month, "all")
    categories = [c["id"] for c in (spots_cfg.get("categories") or []) if isinstance(c, dict) and c.get("id")]
    cat_labels = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in (spots_cfg.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }

    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]
    eligible: list[dict[str, Any]] = []
    for s in spots:
        sid = str(s["id"])
        u = usage_map.get(sid) or {}
        if u.get("in_cooldown"):
            continue
        if not include_hinted and (u.get("hint_dates") or []):
            continue
        # Avoid suggesting spots explicitly known to be mid-renovation closed on target date
        if sid == "osama_hanakoganei" and date(2026, 4, 1) <= dt < date(2026, 12, 9):
            continue
        eligible.append(s)

    def _spot_sort_key(s: dict[str, Any]) -> tuple[int, int, int, int, str, str]:
        sid = str(s["id"])
        u = usage_map.get(sid) or {}
        priority = 0 if s.get("user_request_priority") else 1
        never_aired = 0 if (u.get("aired_count", 0) == 0 and not u.get("planned_dates")) else 1
        no_hint = 0 if not u.get("hint_dates") else 1
        seasons = s.get("best_seasons") or ["all"]
        season_rank = 0 if season in seasons else (1 if "all" in seasons else 2)
        last_used = str(u.get("last_aired_date") or "0000-00-00")
        return (priority, never_aired, no_hint, season_rank, last_used, sid)

    by_cat: dict[str, list[dict[str, Any]]] = {cid: [] for cid in categories}
    for s in sorted(eligible, key=_spot_sort_key):
        cat = str(s.get("category") or "")
        by_cat.setdefault(cat, []).append(s)

    # Rotate starting category offset deterministically by week so weekly pools naturally rotate
    rot = dt.isocalendar().week % max(1, len(categories))
    ordered_cats = categories[rot:] + categories[:rot]

    picked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    used_areas: dict[str, int] = {}
    round_idx = 0

    while len(picked) < count:
        added_this_round = False
        for cid in ordered_cats:
            bucket = by_cat.get(cid) or []
            # Pick best not-yet-picked spot in bucket, preferring an area seen fewer times
            avail = [s for s in bucket if str(s["id"]) not in seen_ids]
            if not avail:
                continue
            avail.sort(
                key=lambda s: (
                    used_areas.get(str(s.get("area") or ""), 0),
                    _spot_sort_key(s),
                )
            )
            chosen = avail[0]
            sid = str(chosen["id"])
            seen_ids.add(sid)
            area = str(chosen.get("area") or "")
            used_areas[area] = used_areas.get(area, 0) + 1
            enriched = dict(chosen)
            enriched["category_label"] = cat_labels.get(cid, cid)
            picked.append(enriched)
            added_this_round = True
            if len(picked) >= count:
                break
        round_idx += 1
        if not added_this_round or round_idx > 12:
            break

    return picked


def format_spot_cooldown_block(
    spots_cfg: dict[str, Any],
    usage_map: dict[str, dict[str, Any]],
    target_dt: date | str | None = None,
) -> str:
    """Format a concise prompt block listing spots currently in their 90-day cooldown."""
    del target_dt  # reserved for future per-date note customization
    spots_by_id = {
        str(s["id"]): s
        for s in (spots_cfg.get("spots") or [])
        if isinstance(s, dict) and s.get("id")
    }
    cat_labels = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in (spots_cfg.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }

    cooldown_items: list[tuple[str, str, str, list[str]]] = []
    for sid, u in usage_map.items():
        if not u.get("in_cooldown"):
            continue
        sp = spots_by_id.get(sid)
        if not sp:
            continue
        dates = u.get("cooldown_trigger_dates") or []
        latest = dates[-1] if dates else (u.get("last_used_date") or "")
        cat_lbl = cat_labels.get(str(sp.get("category") or ""), "")
        cooldown_items.append((latest, str(sp["name"]), cat_lbl, dates))

    if not cooldown_items:
        return "（過去90日以内に紹介・予定済みの小平スポットはありません）"

    cooldown_items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    lines = [
        f"- **{name}**（{cat_lbl}／対象日: {', '.join(dates)}）"
        for _, name, cat_lbl, dates in cooldown_items
    ]
    return "\n".join(lines)


def format_spot_candidates_block(
    spots_cfg: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    """Format balanced unfeatured spot candidates across diverse genres & areas for prompts."""
    if not candidates:
        return "（候補資料なし）"
    cat_labels = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in (spots_cfg.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }
    lines: list[str] = []
    for sp in candidates:
        cid = str(sp.get("category") or "")
        cat_lbl = str(sp.get("category_label") or cat_labels.get(cid, cid))
        angles = "／".join(sp.get("disaster_angles") or [])
        prio = " ★優先リクエスト" if sp.get("user_request_priority") else ""
        note_extra = f" ※{sp['verify_note']}" if sp.get("verify_note") and "改装" in sp["verify_note"] else ""
        lines.append(
            f"- [{cat_lbl}] **{sp['name']}**（{sp.get('area', '')}／最寄: {sp.get('station', '')}）{prio}: "
            f"{sp.get('summary', '')}"
            + (f" 〔防災接続例: {angles}〕" if angles else "")
            + note_extra
        )
    return "\n".join(lines)


def audit_plan_spot_overlaps(
    spots_cfg: dict[str, Any],
    topic_history_entries: list[dict[str, Any]],
    editorial_plan: dict[str, Any] | None,
    program_schedule: dict[str, Any] | None = None,
    include_exceptions: bool = False,
) -> list[dict[str, Any]]:
    """Return list of spot appearances falling within cooldown_days across aired + planned timelines."""
    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]
    spots_by_id = {str(s["id"]): s for s in spots}
    valid_ids = set(spots_by_id.keys())
    default_cd = int(spots_cfg.get("default_cooldown_days") or SPOT_COOLDOWN_DAYS)

    # One authoritative record per date (topic_history > editorial_plan > program_schedule)
    by_date: dict[str, tuple[str, list[str], dict[str, str]]] = {}

    if isinstance(program_schedule, dict):
        for entry in program_schedule.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("date"):
                continue
            d_str = str(entry["date"]).strip()
            txt = f"{entry.get('kodaira_hint') or ''}\n{entry.get('special_request') or ''}"
            sids = _spot_ids_from_record(entry.get("spot_ids"), txt, spots_cfg, valid_ids)
            exc = entry.get("exception_spots") if isinstance(entry.get("exception_spots"), dict) else {}
            by_date[d_str] = ("program_schedule", sids, {str(k): str(v) for k, v in exc.items()})

    if isinstance(editorial_plan, dict):
        for guide in editorial_plan.get("daily_guides") or []:
            if not isinstance(guide, dict) or not guide.get("date"):
                continue
            d_str = str(guide["date"]).strip()
            sids = _spot_ids_from_record(
                guide.get("spot_ids"),
                _extract_guide_text(guide),
                spots_cfg,
                valid_ids,
            )
            exc = guide.get("exception_spots") if isinstance(guide.get("exception_spots"), dict) else {}
            by_date[d_str] = ("editorial_plan", sids, {str(k): str(v) for k, v in exc.items()})

    for entry in topic_history_entries or []:
        if not isinstance(entry, dict) or not entry.get("date"):
            continue
        d_str = str(entry["date"]).strip()
        sids = _spot_ids_from_record(
            entry.get("spot_ids"),
            _extract_entry_text_for_history(entry),
            spots_cfg,
            valid_ids,
        )
        exc = entry.get("exception_spots") if isinstance(entry.get("exception_spots"), dict) else {}
        by_date[d_str] = ("topic_history", sids, {str(k): str(v) for k, v in exc.items()})

    occurrences: dict[str, list[tuple[date, str, str, str]]] = {}
    for d_str in sorted(by_date):
        dt = _parse_iso_date(d_str)
        if not dt:
            continue
        src, sids, exc = by_date[d_str]
        for sid in sids:
            occurrences.setdefault(sid, []).append((dt, d_str, src, exc.get(sid, "")))

    overlaps: list[dict[str, Any]] = []
    for sid, occs in sorted(occurrences.items()):
        sp = spots_by_id[sid]
        cd_days = int(sp.get("cooldown_days") or default_cd)
        for i in range(1, len(occs)):
            dt_a, str_a, src_a, _ = occs[i - 1]
            dt_b, str_b, src_b, exc_reason = occs[i]
            gap = (dt_b - dt_a).days
            if 0 < gap < cd_days:
                if exc_reason and not include_exceptions:
                    continue
                overlaps.append(
                    {
                        "spot_id": sid,
                        "spot_name": str(sp["name"]),
                        "category": str(sp.get("category") or ""),
                        "date_a": str_a,
                        "source_a": src_a,
                        "date_b": str_b,
                        "source_b": src_b,
                        "gap_days": gap,
                        "cooldown_days": cd_days,
                        "exception_reason": exc_reason,
                    }
                )
    return overlaps


def render_spots_catalog_markdown(
    spots_cfg: dict[str, Any],
    usage_map: dict[str, dict[str, Any]],
    today_jst_str: str,
) -> str:
    """Render browsable Markdown catalog of all researched Kodaira spots by category."""
    cats = spots_cfg.get("categories") or []
    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]

    counts = {
        "total": len(spots),
        "unfeatured": sum(1 for s in spots if (usage_map.get(str(s["id"])) or {}).get("status") == "unfeatured"),
        "planned": sum(
            1
            for s in spots
            if (usage_map.get(str(s["id"])) or {}).get("planned_dates")
            or (usage_map.get(str(s["id"])) or {}).get("hint_dates")
        ),
        "aired": sum(1 for s in spots if (usage_map.get(str(s["id"])) or {}).get("aired_count", 0) > 0),
    }

    lines = [
        "# 小平市スポット題材ネタ帳（16ジャンル網羅・重複防止マスタ）",
        "",
        f"> 更新基準日: {today_jst_str}（JST）／ 元データ: `config/kodaira_spots.json`（全{counts['total']}スポット・{len(cats)}ジャンル）",
        "",
        "## 運用ルール（重複防止 × 鮮度優先）",
        "- **原則90日クールダウン**: 一度紹介した小平スポットは原則として**約3か月（90日間）再登場させず**、16ジャンル・市内各エリアからバランスよく選定します。",
        "- **例外（耳よりニュース）**: 大規模リニューアル（例：おふろの王様 花小金井店 2026年12月9日リニューアルオープン）、新店オープン、開催当日の大型地域イベント（例：12月5日 ウクライナのクリスマス）等がある場合は鮮度を優先して取り上げます。",
        "- **週次・当日の臨機応変さ**: このネタ帳はあくまで重複防止とジャンル充実のための候補プールです。最終的な配信内容は日曜の編集長AI編成および当日の朝リサーチ・天候・最新市報に応じて柔軟に差し替えます。",
        "- **リクエスト歓迎**: 追加したいお店・公園・施設や優先取り上げ希望はいつでもお知らせください（Web版は [calendar.html#spot-catalog](calendar.html#spot-catalog) でも絞り込み閲覧できます）。",
        "",
        f"- 集計: **総スポット数 {counts['total']}** ／ 未紹介 **{counts['unfeatured']}** ／ 予定あり **{counts['planned']}** ／ 放送済み **{counts['aired']}**",
        "",
    ]

    season_labels = {
        "spring": "春",
        "summer": "夏",
        "autumn": "秋",
        "winter": "冬",
        "all": "通年",
    }

    for cat in cats:
        cid = str(cat.get("id") or "")
        icon = str(cat.get("icon") or "📍")
        label = str(cat.get("label") or cid)
        cat_spots = [s for s in spots if s.get("category") == cid]
        lines.append(f"## {icon} {label}（{len(cat_spots)}件）")
        lines.append("")
        for sp in cat_spots:
            sid = str(sp["id"])
            u = usage_map.get(sid) or {}
            badges: list[str] = []
            if u.get("aired_dates"):
                badges.append(f"放送済: {', '.join(u['aired_dates'])}")
            if u.get("planned_dates"):
                badges.append(f"週間予定: {', '.join(u['planned_dates'])}")
            elif u.get("hint_dates"):
                badges.append(f"仮予定ヒント: {', '.join(u['hint_dates'])}")
            if not badges:
                badges.append("未紹介")

            s_tags = "・".join(season_labels.get(x, x) for x in (sp.get("best_seasons") or ["all"]))
            angles = " ／ ".join(sp.get("disaster_angles") or [])
            lines.append(f"### {sp['name']} 〔{' / '.join(badges)}〕")
            lines.append(
                f"- **エリア・最寄**: {sp.get('area', '')}（最寄: {sp.get('station', '')} ／ {sp.get('address_hint', '')}）｜ **おすすめ季節**: {s_tags}"
            )
            lines.append(f"- **魅力**: {sp.get('summary', '')}")
            if angles:
                lines.append(f"- **防災のつなぎ方例**: {angles}")
            if sp.get("verify_note"):
                lines.append(f"- **確認メモ**: {sp['verify_note']}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
