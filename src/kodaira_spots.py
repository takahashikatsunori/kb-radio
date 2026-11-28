"""Shared Kodaira City spot catalog loader, 90-day cooldown tracker, balanced selector, and overlap auditor."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SPOT_COOLDOWN_DAYS = 90
ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SPOTS_PATH = ROOT_DIR / "config" / "kodaira_spots.json"
SPOT_REPORTS_DIR = ROOT_DIR / "data" / "spot_reports"
LOW_TRUST_DOMAIN_BLOCKLIST = (
    "ezua.com",
)
VALID_OPERATING_STATUSES = ("open", "seasonal", "limited", "renovation", "closed")

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
    reports_map: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Format balanced unfeatured spot candidates across diverse genres & areas for prompts."""
    if not candidates:
        return "（候補資料なし）"
    cat_labels = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in (spots_cfg.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }
    reports = reports_map or {}
    lines: list[str] = []
    for sp in candidates:
        cid = str(sp.get("category") or "")
        cat_lbl = str(sp.get("category_label") or cat_labels.get(cid, cid))
        angles = "／".join(sp.get("disaster_angles") or [])
        prio = " ★優先リクエスト" if sp.get("user_request_priority") else ""
        note_extra = f" ※{sp['verify_note']}" if sp.get("verify_note") and "改装" in sp["verify_note"] else ""
        dossier = reports.get(str(sp.get("id") or ""))
        dossier_extra = ""
        if isinstance(dossier, dict):
            entries = dossier.get("entries") or []
            if entries:
                latest = entries[-1] if isinstance(entries[-1], dict) else {}
                hl = str(latest.get("headline") or "").strip()
                if hl:
                    dossier_extra = f" ［取材ストック{len(entries)}件: {hl}］"
                else:
                    dossier_extra = f" ［取材ストック{len(entries)}件あり］"
        lines.append(
            f"- [{cat_lbl}] **{sp['name']}**（{sp.get('area', '')}／最寄: {sp.get('station', '')}）{prio}: "
            f"{sp.get('summary', '')}"
            + (f" 〔防災接続例: {angles}〕" if angles else "")
            + note_extra
            + dossier_extra
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


def load_spot_reports(reports_dir: Path = SPOT_REPORTS_DIR) -> dict[str, dict[str, Any]]:
    """Load accumulated primary-source spot dossiers keyed by spot_id."""
    if not reports_dir.exists() or not reports_dir.is_dir():
        return {}
    reports: dict[str, dict[str, Any]] = {}
    for p in sorted(reports_dir.glob("*.json")):
        if p.name.startswith("_") or p.name.startswith("."):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("spot_id") or p.stem).strip()
        if not sid:
            continue
        entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        entries.sort(key=lambda e: str(e.get("researched_at") or e.get("date") or ""))
        data["spot_id"] = sid
        data["entries"] = entries
        reports[sid] = data
    return reports


def validate_report_entry(entry: dict[str, Any], *, spot_id: str = "") -> list[str]:
    """Validate one spot report entry against primary-source fact-checking rules."""
    errors: list[str] = []
    prefix = f"[{spot_id}] " if spot_id else ""
    if not isinstance(entry, dict):
        return [f"{prefix}entry must be a JSON object"]

    if not str(entry.get("headline") or "").strip():
        errors.append(f"{prefix}headline must be a non-empty string")

    discoveries = entry.get("discoveries")
    if not isinstance(discoveries, list) or not [d for d in discoveries if isinstance(d, str) and d.strip()]:
        errors.append(f"{prefix}discoveries must be a non-empty list of strings")

    op_status = str(entry.get("operating_status") or "").strip()
    if op_status and op_status not in VALID_OPERATING_STATUSES:
        errors.append(f"{prefix}operating_status '{op_status}' must be one of {VALID_OPERATING_STATUSES}")

    fc = entry.get("fact_check")
    if not isinstance(fc, dict):
        errors.append(f"{prefix}fact_check object is required")
    else:
        if fc.get("status") != "verified_primary":
            errors.append(f"{prefix}fact_check.status must equal 'verified_primary'")
        if not str(fc.get("checked_at") or "").strip():
            errors.append(f"{prefix}fact_check.checked_at must be non-empty")

    sources = entry.get("primary_sources")
    if not isinstance(sources, list) or not sources:
        errors.append(f"{prefix}primary_sources must be a non-empty list")
    else:
        for idx, src in enumerate(sources):
            if not isinstance(src, dict):
                errors.append(f"{prefix}primary_sources[{idx}] must be an object")
                continue
            title = str(src.get("title") or "").strip()
            url = str(src.get("url") or "").strip()
            if not title:
                errors.append(f"{prefix}primary_sources[{idx}].title must be non-empty")
            if not (url.startswith("http://") or url.startswith("https://")):
                errors.append(f"{prefix}primary_sources[{idx}].url must start with http:// or https://")
                continue
            host = urlparse(url).netloc.lower().split(":")[0]
            if not host:
                errors.append(f"{prefix}primary_sources[{idx}].url has empty host")
                continue
            for blocked in LOW_TRUST_DOMAIN_BLOCKLIST:
                if host == blocked or host.endswith("." + blocked):
                    errors.append(
                        f"{prefix}primary_sources[{idx}].url domain '{host}' is in LOW_TRUST_DOMAIN_BLOCKLIST"
                    )

    return errors


_OPERATING_STATUS_JA: dict[str, str] = {
    "open": "営業・公開中",
    "seasonal": "季節営業・開園",
    "limited": "事前予約・限定公開",
    "renovation": "改修・リニューアル予定/中",
    "closed": "閉業・閉鎖確認済",
}


def format_spot_reports_context(
    spot_ids: list[str],
    reports_map: dict[str, dict[str, Any]],
    spots_cfg: dict[str, Any] | None = None,
    *,
    max_entries_per_spot: int = 3,
) -> str:
    """Format accumulated verified spot dossiers for the requested spot_ids."""
    if not spot_ids or not reports_map:
        return ""
    spots_by_id = {
        str(s["id"]): s
        for s in ((spots_cfg or {}).get("spots") or [])
        if isinstance(s, dict) and s.get("id")
    }
    seen: set[str] = set()
    blocks: list[str] = []
    for raw_sid in spot_ids:
        sid = str(raw_sid or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        dossier = reports_map.get(sid)
        if not isinstance(dossier, dict):
            continue
        entries = [e for e in (dossier.get("entries") or []) if isinstance(e, dict)]
        sp_meta = spots_by_id.get(sid) or {}
        name = str(dossier.get("spot_name") or sp_meta.get("name") or sid)
        op_code = str(dossier.get("operating_status") or "open")
        op_ja = _OPERATING_STATUS_JA.get(op_code, op_code)
        op_note = str(dossier.get("operating_status_note") or "").strip()
        official_urls = [str(u) for u in (dossier.get("official_urls") or []) if str(u).strip()]

        lines = [
            f"### 📂 {name}（ID: `{sid}`｜蓄積取材 {len(entries)}件｜一次確認状況: {op_ja}"
            + (f" — {op_note}" if op_note else "")
            + "）"
        ]
        if official_urls:
            lines.append(f"- **公式一次URL**: {' / '.join(official_urls)}")
        highlights = [str(x) for x in (dossier.get("curated_highlights") or []) if str(x).strip()]
        if highlights:
            lines.append(f"- **深掘り見どころ**: {' ／ '.join(highlights)}")
        angles = [str(x) for x in (dossier.get("story_angles") or []) if str(x).strip()]
        if angles:
            lines.append(f"- **放送切り口メモ**: {' ／ '.join(angles)}")
        essay = dossier.get("editorial_essay")
        if isinstance(essay, dict) and str(essay.get("lead") or "").strip():
            lines.append(f"- **取材ストーリー要約**: {str(essay['lead']).strip()}")
        conns = [c for c in (dossier.get("connections") or []) if isinstance(c, dict) and c.get("spot_id")]
        if conns:
            conn_parts = []
            for c in conns[:4]:
                rel_sid = str(c["spot_id"])
                rel_name = str((spots_by_id.get(rel_sid) or {}).get("name") or rel_sid)
                rel_lbl = str(c.get("relation") or "関連").strip()
                rel_note = str(c.get("note") or "").strip()
                conn_parts.append(f"{rel_name}［{rel_lbl}］" + (f"({rel_note})" if rel_note else ""))
            lines.append(f"- **周辺・関連スポットのつながり**: {' ／ '.join(conn_parts)}")
        leads = [str(x).strip() for x in (dossier.get("next_research_leads") or []) if str(x).strip()]
        if leads:
            lines.append(f"- **次期取材リード**: {' ／ '.join(leads[:3])}")
        sfp = dossier.get("special_feature_potential")
        if isinstance(sfp, dict) and (sfp.get("ready") or sfp.get("theme_idea")):
            ready_lbl = "特集化OK" if sfp.get("ready") else "特集の種"
            theme = str(sfp.get("theme_idea") or "").strip()
            reason = str(sfp.get("reason") or "").strip()
            lines.append(f"- **長期特集ポテンシャル（{ready_lbl}）**: {theme}" + (f"（理由: {reason}）" if reason else ""))

        for e in reversed(entries[-max_entries_per_spot:]):
            rdate = str(e.get("researched_at") or e.get("date") or "")
            hl = str(e.get("headline") or "").strip()
            lines.append(f"- **[{rdate}] {hl}**")
            for d in (e.get("discoveries") or []):
                if str(d).strip():
                    lines.append(f"  - 発見: {str(d).strip()}")
            if e.get("seasonal_note"):
                lines.append(f"  - 季節メモ: {str(e['seasonal_note']).strip()}")
            if e.get("disaster_tie_in"):
                lines.append(f"  - 防災・備え接続: {str(e['disaster_tie_in']).strip()}")
            excluded = [str(x).strip() for x in (e.get("excluded_unverified_claims") or []) if str(x).strip()]
            if excluded:
                lines.append(f"  - ※未確認・否定事項（放送禁止）: {' / '.join(excluded)}")
            srcs = [
                f"{str(s.get('title') or '').strip()} ({str(s.get('url') or '').strip()})"
                for s in (e.get("primary_sources") or [])
                if isinstance(s, dict) and str(s.get("url") or "").strip()
            ]
            if srcs:
                lines.append(f"  - 一次ソース: {' ｜ '.join(srcs)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def find_longitudinal_special_candidates(
    spots_cfg: dict[str, Any],
    reports_map: dict[str, dict[str, Any]],
    *,
    min_entries: int = 2,
) -> list[dict[str, Any]]:
    """Identify spots whose accumulated dossiers support a deep-dive special episode."""
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
    results: list[dict[str, Any]] = []
    for sid, dossier in reports_map.items():
        if not isinstance(dossier, dict):
            continue
        entries = [e for e in (dossier.get("entries") or []) if isinstance(e, dict)]
        sfp = dossier.get("special_feature_potential") if isinstance(dossier.get("special_feature_potential"), dict) else {}
        ready = bool(sfp.get("ready"))
        if not ready and len(entries) < min_entries:
            continue
        sp = spots_by_id.get(sid) or {}
        cid = str(dossier.get("category") or sp.get("category") or "")
        latest = entries[-1] if entries else {}
        results.append(
            {
                "spot_id": sid,
                "spot_name": str(dossier.get("spot_name") or sp.get("name") or sid),
                "category": cid,
                "category_label": cat_labels.get(cid, cid),
                "entry_count": len(entries),
                "ready": ready,
                "theme_idea": str(sfp.get("theme_idea") or "").strip(),
                "reason": str(sfp.get("reason") or "").strip(),
                "latest_headline": str(latest.get("headline") or "").strip(),
                "operating_status": str(dossier.get("operating_status") or "open"),
                "last_researched_at": str(dossier.get("last_researched_at") or latest.get("researched_at") or ""),
            }
        )
    results.sort(key=lambda item: (not item["ready"], -item["entry_count"], item["spot_name"]))
    return results


def render_spots_catalog_markdown(
    spots_cfg: dict[str, Any],
    usage_map: dict[str, dict[str, Any]],
    today_jst_str: str,
    reports_map: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Render browsable Markdown catalog of all researched Kodaira spots by category."""
    cats = spots_cfg.get("categories") or []
    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]
    reports = reports_map if reports_map is not None else load_spot_reports()

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
        "reported_spots": sum(1 for s in spots if (reports.get(str(s["id"])) or {}).get("entries")),
        "report_entries": sum(len((reports.get(str(s["id"])) or {}).get("entries") or []) for s in spots),
    }

    lines = [
        f"# 小平市スポット題材ネタ帳（{len(cats)}ジャンル網羅・重複防止マスタ）",
        "",
        f"> 更新基準日: {today_jst_str}（JST）／ 元データ: `config/kodaira_spots.json` + `data/spot_reports/*.json`（全{counts['total']}スポット・{len(cats)}ジャンル）",
        "",
        "## 運用ルール（重複防止 × 鮮度優先 × 一次ソース継続取材）",
        f"- **原則90日クールダウン**: 一度紹介した小平スポットは原則として**約3か月（90日間）再登場させず**、{len(cats)}ジャンル・市内各エリアからバランスよく選定します。",
        "- **例外（耳よりニュース）**: 大規模リニューアル（例：おふろの王様 花小金井店 2026年12月9日リニューアルオープン）、新店オープン、開催当日の大型地域イベント（例：12月5日 ウクライナのクリスマス）等がある場合は鮮度を優先して取り上げます。",
        "- **継続取材と一次ソース検証（取材手帳）**: 公式サイト・自治体・団体発表など一次情報のみをもとに各スポットの取材レポートを蓄積し、最新状況の把握と長期特集（深い掘り下げ）に活かします。",
        "- **週次・当日の臨機応変さ**: このネタ帳はあくまで重複防止とジャンル充実のための候補プールです。最終的な配信内容は日曜の編集長AI編成および当日の朝リサーチ・天候・最新市報に応じて柔軟に差し替えます。",
        "- **リクエスト歓迎**: 追加したいお店・公園・施設や優先取り上げ希望はいつでもお知らせください（Web版は [calendar.html#spot-catalog](calendar.html#spot-catalog) でも絞り込み閲覧できます）。",
        "",
        (
            f"- 集計: **総スポット数 {counts['total']}** ／ 未紹介 **{counts['unfeatured']}** ／ 予定あり **{counts['planned']}** ／ "
            f"放送済み **{counts['aired']}** ／ 取材レポート蓄積 **{counts['reported_spots']}スポット（計{counts['report_entries']}件）**"
        ),
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

            dossier = reports.get(sid)
            entries = (dossier.get("entries") or []) if isinstance(dossier, dict) else []
            if entries:
                badges.append(f"取材ストック: {len(entries)}件")

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
            if entries:
                latest = entries[-1]
                op_code = str(dossier.get("operating_status") or "open")
                op_ja = _OPERATING_STATUS_JA.get(op_code, op_code)
                op_note = str(dossier.get("operating_status_note") or "").strip()
                checked = str((latest.get("fact_check") or {}).get("checked_at") or dossier.get("last_researched_at") or "")
                lines.append(
                    f"- **最新取材ノート**（確認状況: {op_ja}"
                    + (f"・{op_note}" if op_note else "")
                    + f"｜確認日: {checked}）: **{latest.get('headline', '')}**"
                )
                for disc in (latest.get("discoveries") or [])[:3]:
                    if str(disc).strip():
                        lines.append(f"  - {str(disc).strip()}")
                srcs = [
                    f"[{str(s.get('title') or '一次情報').strip()}]({str(s.get('url') or '').strip()})"
                    for s in (latest.get("primary_sources") or [])
                    if isinstance(s, dict) and str(s.get("url") or "").strip()
                ]
                if srcs:
                    lines.append(f"  - 一次ソース: {' / '.join(srcs)}")
                sfp = dossier.get("special_feature_potential")
                if isinstance(sfp, dict) and sfp.get("theme_idea"):
                    lines.append(f"  - 特集案: {sfp['theme_idea']}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
