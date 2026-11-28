"""Continuous primary-source field-reporting & dossier manager for Kodaira spots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

from generate_episode import (
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_RESEARCH_MODEL,
    JST,
    _format_usage,
    _load_json,
    _parse_json_response,
    _resolve_redirect_url,
)
from kodaira_spots import (
    LOW_TRUST_DOMAIN_BLOCKLIST,
    SPOT_REPORTS_DIR,
    VALID_OPERATING_STATUSES,
    compute_spot_usage,
    find_longitudinal_special_candidates,
    load_kodaira_spots,
    load_spot_reports,
    validate_report_entry,
)

DEFAULT_STALE_DAYS = 45
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def _parse_iso_date(raw: str | None) -> date | None:
    s = str(raw or "").strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _dedup_str_list(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = str(item or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _resolve_grounding_url(raw_url: str, timeout: float = 5.0) -> str:
    """Resolve vertexaisearch redirect URLs to final http(s):// canonical target URLs."""
    if not raw_url.startswith(("http://", "https://")):
        return ""
    if "vertexaisearch.cloud.google.com" not in raw_url:
        return raw_url
    direct = _resolve_redirect_url(raw_url, timeout=timeout)
    if direct:
        return direct
    try:
        import requests

        resp = requests.get(raw_url, allow_redirects=True, timeout=timeout, stream=True)
        final_url = resp.url or ""
        status_ok = resp.status_code < 400
        resp.close()
        if status_ok and final_url.startswith(("http://", "https://")) and "vertexaisearch.cloud.google.com" not in final_url:
            return final_url
    except Exception:  # noqa: BLE001
        pass
    return ""


def _clean_primary_sources(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for src in sources:
        if not isinstance(src, dict):
            continue
        title = str(src.get("title") or "").strip()
        raw_url = str(src.get("url") or "").strip()
        url = _resolve_grounding_url(raw_url) if "vertexaisearch.cloud.google.com" in raw_url else raw_url
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        cleaned.append({"title": title or "一次情報ソース", "url": url})
    return cleaned


def _load_schedule_context() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    spots_cfg = load_kodaira_spots()
    reports_map = load_spot_reports(SPOT_REPORTS_DIR)
    th_path = DATA_DIR / "topic_history.json"
    ep_path = DATA_DIR / "editorial_plan.json"
    ps_path = CONFIG_DIR / "program_schedule.json"
    topic_history = (_load_json(th_path) if th_path.exists() else {}).get("entries") or []
    editorial_plan = _load_json(ep_path) if ep_path.exists() else None
    program_schedule = _load_json(ps_path) if ps_path.exists() else None
    return spots_cfg, reports_map, topic_history, editorial_plan or {}, program_schedule or {}


def select_target_spots(
    spots_cfg: dict[str, Any],
    reports_map: dict[str, dict[str, Any]],
    usage_map: dict[str, dict[str, Any]],
    *,
    today_dt: date,
    spot_ids: list[str] | None = None,
    category: str | None = None,
    count: int = 5,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> list[dict[str, Any]]:
    """Select priority spots for ongoing primary-source field research."""
    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]
    spots_by_id = {str(s["id"]): s for s in spots}
    cat_labels = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in (spots_cfg.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }

    if spot_ids:
        selected: list[dict[str, Any]] = []
        missing: list[str] = []
        for raw_sid in spot_ids:
            sid = str(raw_sid).strip()
            if sid in spots_by_id:
                sp = dict(spots_by_id[sid])
                sp["category_label"] = cat_labels.get(str(sp.get("category") or ""), "")
                sp["_reason"] = "明示指定 (--spot-id)"
                selected.append(sp)
            else:
                missing.append(sid)
        if missing:
            raise ValueError(f"Unknown spot_id(s): {', '.join(missing)}")
        return selected

    cat_report_counts: dict[str, int] = {cid: 0 for cid in cat_labels}
    for sp in spots:
        sid = str(sp["id"])
        if (reports_map.get(sid) or {}).get("entries"):
            cid = str(sp.get("category") or "")
            cat_report_counts[cid] = cat_report_counts.get(cid, 0) + 1

    from kodaira_spots import MONTH_TO_SEASON

    cur_season = MONTH_TO_SEASON.get(today_dt.month, "all")
    horizon_end = today_dt + timedelta(days=14)
    pool: list[tuple[int, dict[str, Any]]] = []

    for sp in spots:
        sid = str(sp["id"])
        cid = str(sp.get("category") or "")
        if category and cid != category:
            continue

        dossier = reports_map.get(sid) or {}
        last_dt = _parse_iso_date(dossier.get("last_researched_at"))
        days_stale = (today_dt - last_dt).days if last_dt else None
        is_stale = days_stale is None or days_stale >= stale_days
        if not is_stale:
            continue

        usage = usage_map.get(sid) or {}
        upcoming = False
        for d_str in list(usage.get("planned_dates") or []) + list(usage.get("hint_dates") or []):
            dt = _parse_iso_date(d_str)
            if dt and today_dt <= dt <= horizon_end:
                upcoming = True
                break

        score = 0
        reasons: list[str] = []
        if upcoming:
            score += 100
            reasons.append("直近2週間の放送予定・仮予定")
        if sp.get("user_request_priority"):
            score += 50
            reasons.append("優先リクエスト対象")
        if days_stale is None:
            score += 40
            reasons.append("未取材（新規開拓）")
        else:
            score += 25 + min(30, max(0, days_stale - stale_days))
            reasons.append(f"前回取材から{days_stale}日経過")

        c_count = cat_report_counts.get(cid, 0)
        if c_count == 0:
            score += 30
            reasons.append("取材レポート0件のジャンル")
        elif c_count < 3:
            score += max(0, 15 - c_count * 5)

        seasons = sp.get("best_seasons") or ["all"]
        if cur_season in seasons:
            score += 15
            reasons.append(f"旬の季節({cur_season})")
        elif "all" in seasons:
            score += 5

        item = dict(sp)
        item["category_label"] = cat_labels.get(cid, cid)
        item["_score"] = score
        item["_reason"] = " / ".join(reasons)
        pool.append((score, item))

    pool.sort(key=lambda pair: (-pair[0], str(pair[1].get("name") or "")))

    chosen: list[dict[str, Any]] = []
    chosen_cats: set[str] = set()
    deferred: list[dict[str, Any]] = []
    for _, sp in pool:
        cid = str(sp.get("category") or "")
        if cid not in chosen_cats or category:
            chosen.append(sp)
            chosen_cats.add(cid)
        else:
            deferred.append(sp)
        if len(chosen) >= count:
            return chosen[:count]

    for sp in deferred:
        chosen.append(sp)
        if len(chosen) >= count:
            break
    return chosen[:count]


def _validate_primary_sources_list(sources: Any, *, spot_id: str = "") -> list[str]:
    """Validate primary_sources URL list against HTTP(S) and low-trust domain blocklist."""
    prefix = f"[{spot_id}] " if spot_id else ""
    if not isinstance(sources, list) or not sources:
        return [f"{prefix}primary_sources must be a non-empty list"]
    errors: list[str] = []
    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            errors.append(f"{prefix}primary_sources[{idx}] must be an object")
            continue
        if not str(src.get("title") or "").strip():
            errors.append(f"{prefix}primary_sources[{idx}].title must be non-empty")
        url = str(src.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
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


def select_patrol_batch(
    spots_cfg: dict[str, Any],
    reports_map: dict[str, dict[str, Any]],
    usage_map: dict[str, dict[str, Any]],
    *,
    today_dt: date,
    high_count: int = 10,
    low_count: int = 5,
    high_stale_days: int = 4,
    low_stale_days: int = 14,
) -> dict[str, list[dict[str, Any]]]:
    """Select daily high-tier and low-tier patrol targets with same-day skip & round-robin FIFO fairness."""
    from kodaira_spots import MONTH_TO_SEASON

    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]
    cat_labels = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in (spots_cfg.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }
    cat_report_counts: dict[str, int] = {cid: 0 for cid in cat_labels}
    for sp in spots:
        sid = str(sp["id"])
        if (reports_map.get(sid) or {}).get("entries"):
            cid = str(sp.get("category") or "")
            cat_report_counts[cid] = cat_report_counts.get(cid, 0) + 1

    cur_season = MONTH_TO_SEASON.get(today_dt.month, "all")
    horizon_end = today_dt + timedelta(days=14)
    tier_cfg = (
        ("high", high_count, high_stale_days, "高頻度"),
        ("low", low_count, low_stale_days, "低頻度"),
    )
    selected_by_tier: dict[str, list[dict[str, Any]]] = {"high": [], "low": []}

    for tier_name, quota, stale_threshold, tier_ja in tier_cfg:
        if quota <= 0:
            continue
        unresearched: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        previously_checked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        for sp in spots:
            sp_tier = str(sp.get("patrol_tier") or "low").strip()
            if sp_tier != tier_name:
                continue
            sid = str(sp["id"])
            cid = str(sp.get("category") or "")
            dossier = reports_map.get(sid) or {}
            last_checked_raw = str(dossier.get("last_checked_at") or dossier.get("last_researched_at") or "").strip()
            last_dt = _parse_iso_date(last_checked_raw)
            days_since = (today_dt - last_dt).days if last_dt else None

            # Idempotency: skip spots already checked today
            if days_since is not None and days_since <= 0:
                continue

            usage = usage_map.get(sid) or {}
            upcoming = False
            for d_str in list(usage.get("planned_dates") or []) + list(usage.get("hint_dates") or []):
                dt = _parse_iso_date(d_str)
                if dt and today_dt <= dt <= horizon_end:
                    upcoming = True
                    break

            seasons = sp.get("best_seasons") or ["all"]
            season_rank = 0 if cur_season in seasons else (1 if "all" in seasons else 2)
            c_count = cat_report_counts.get(cid, 0)
            cat_scarcity = 0 if c_count == 0 else (1 if c_count < 3 else 2)
            item = dict(sp)
            item["patrol_tier"] = tier_name
            item["category_label"] = cat_labels.get(cid, cid)
            item["last_checked_at"] = last_dt.isoformat() if last_dt else ""
            item["last_researched_at"] = str(dossier.get("last_researched_at") or "")
            item["days_since_check"] = days_since

            reasons = [f"{tier_ja}(目安{stale_threshold}日)"]
            if upcoming:
                reasons.append("直近2週間予定")
            if sp.get("user_request_priority"):
                reasons.append("優先リクエスト")

            if last_dt is None:
                reasons.append("未取材(新規)")
                if season_rank == 0:
                    reasons.append(f"旬({cur_season})")
                item["_reason"] = " / ".join(reasons)
                key = (
                    0 if upcoming else 1,
                    0 if sp.get("user_request_priority") else 1,
                    cat_scarcity,
                    season_rank,
                    str(sp.get("name") or ""),
                )
                unresearched.append((key, item))
            else:
                is_stale = days_since is not None and days_since >= stale_threshold
                if is_stale:
                    reasons.append(f"要再確認({days_since}日経過)")
                else:
                    reasons.append(f"最終確認 {last_dt.isoformat()} ({days_since}日前)")
                item["_reason"] = " / ".join(reasons)
                if upcoming and is_stale:
                    bucket = 0
                elif is_stale:
                    bucket = 1
                elif upcoming:
                    bucket = 2
                else:
                    bucket = 3
                key = (
                    bucket,
                    last_dt.isoformat(),
                    0 if sp.get("user_request_priority") else 1,
                    season_rank,
                    str(sp.get("name") or ""),
                )
                previously_checked.append((key, item))

        unresearched.sort(key=lambda pair: pair[0])
        previously_checked.sort(key=lambda pair: pair[0])

        chosen: list[dict[str, Any]] = []
        seen_cats: set[str] = set()
        deferred_unresearched: list[dict[str, Any]] = []

        # Soft category diversity across unresearched spots first
        for _, sp in unresearched:
            cid = str(sp.get("category") or "")
            if cid not in seen_cats:
                chosen.append(sp)
                seen_cats.add(cid)
            else:
                deferred_unresearched.append(sp)
            if len(chosen) >= quota:
                break

        for sp in deferred_unresearched:
            if len(chosen) >= quota:
                break
            chosen.append(sp)

        for _, sp in previously_checked:
            if len(chosen) >= quota:
                break
            chosen.append(sp)

        selected_by_tier[tier_name] = chosen[:quota]

    return selected_by_tier


def _merge_editorial_essay(existing_raw: Any, incoming_raw: Any) -> dict[str, Any]:
    ex = existing_raw if isinstance(existing_raw, dict) else {}
    inc = incoming_raw if isinstance(incoming_raw, dict) else {}
    lead = str(inc.get("lead") or ex.get("lead") or "").strip()
    inc_paras = [str(p).strip() for p in (inc.get("paragraphs") or []) if str(p).strip()]
    ex_paras = [str(p).strip() for p in (ex.get("paragraphs") or []) if str(p).strip()]
    paragraphs = inc_paras if inc_paras else ex_paras
    editor_note = str(inc.get("editor_note") or ex.get("editor_note") or "").strip()
    if not (lead or paragraphs or editor_note):
        return {}
    return {
        "lead": lead,
        "paragraphs": paragraphs,
        "editor_note": editor_note,
    }


def _merge_illustrations(existing_raw: Any, incoming_raw: Any, *, default_date: str = "") -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for raw in list(existing_raw or []) + list(incoming_raw or []):
        if not isinstance(raw, dict):
            continue
        art_id = str(raw.get("id") or "").strip()
        src = str(raw.get("src") or "").strip()
        if not art_id or not src:
            continue
        prev = merged.get(art_id) or {}
        entry = {
            "id": art_id,
            "kind": str(raw.get("kind") or prev.get("kind") or "scene").strip(),
            "title": str(raw.get("title") or prev.get("title") or "").strip(),
            "caption": str(raw.get("caption") or prev.get("caption") or "").strip(),
            "src": src,
            "based_on": str(raw.get("based_on") or prev.get("based_on") or "").strip(),
            "added_at": str(raw.get("added_at") or prev.get("added_at") or default_date).strip(),
        }
        if art_id not in merged:
            order.append(art_id)
        merged[art_id] = entry
    return [merged[k] for k in order]


def _merge_connections(
    existing_raw: Any,
    incoming_raw: Any,
    *,
    self_spot_id: str = "",
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for raw in list(existing_raw or []) + list(incoming_raw or []):
        if not isinstance(raw, dict):
            continue
        rel_id = str(raw.get("spot_id") or "").strip()
        if not rel_id or rel_id == self_spot_id:
            continue
        prev = merged.get(rel_id) or {}
        entry = {
            "spot_id": rel_id,
            "relation": str(raw.get("relation") or prev.get("relation") or "関連").strip(),
            "note": str(raw.get("note") or prev.get("note") or "").strip(),
        }
        if rel_id not in merged:
            order.append(rel_id)
        merged[rel_id] = entry
    return [merged[k] for k in order]


def _merge_location(existing_raw: Any, incoming_raw: Any) -> dict[str, Any]:
    existing = dict(existing_raw) if isinstance(existing_raw, dict) else {}
    incoming = dict(incoming_raw) if isinstance(incoming_raw, dict) else {}
    if not existing and not incoming:
        return {}
    merged = dict(existing)
    for k, v in incoming.items():
        if k == "maps" and isinstance(v, dict):
            prev_maps = dict(existing.get("maps") or {}) if isinstance(existing.get("maps"), dict) else {}
            prev_maps.update(v)
            merged["maps"] = prev_maps
        elif v is not None and v != "":
            merged[k] = v
    return merged


def _normalize_draft_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("reports"), list):
            return [x for x in payload["reports"] if isinstance(x, dict)]
        if isinstance(payload.get("spots"), list):
            return [x for x in payload["spots"] if isinstance(x, dict)]
        if payload.get("spot_id"):
            return [payload]
    raise ValueError("Draft JSON must be an object with 'reports'/'spots' list, a spot list, or a single report object.")


def ingest_draft_payload(
    payload: Any,
    *,
    reports_dir: Path = SPOT_REPORTS_DIR,
    spots_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate and merge verified dossier entries into data/spot_reports/<spot_id>.json."""
    cfg = spots_cfg or load_kodaira_spots()
    spots_by_id = {str(s["id"]): s for s in (cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")}
    items = _normalize_draft_items(payload)
    if not items:
        raise ValueError("Draft contains zero spot report items.")

    reports_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for item in items:
        sid = str(item.get("spot_id") or "").strip()
        if sid not in spots_by_id:
            raise ValueError(f"Unknown spot_id '{sid}' not found in config/kodaira_spots.json")
        sp_meta = spots_by_id[sid]

        out_path = reports_dir / f"{sid}.json"
        existing: dict[str, Any] = {}
        if out_path.exists():
            try:
                loaded = _load_json(out_path)
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}

        existing_entries: list[dict[str, Any]] = [
            e for e in (existing.get("entries") or []) if isinstance(e, dict)
        ]
        is_no_change = bool(item.get("no_change") is True or item.get("change_detected") is False)
        if is_no_change and existing_entries:
            fc_obj = item.get("fact_check") if isinstance(item.get("fact_check"), dict) else {}
            checked_at = str(
                item.get("checked_at")
                or item.get("researched_at")
                or fc_obj.get("checked_at")
                or ""
            ).strip()
            if _parse_iso_date(checked_at) is None:
                raise ValueError(f"[{sid}] checked_at (YYYY-MM-DD) is required for no-change check-in")

            raw_sources = item.get("primary_sources")
            if raw_sources is None and isinstance(item.get("entry"), dict):
                raw_sources = item["entry"].get("primary_sources")
            clean_sources = _clean_primary_sources(raw_sources) if isinstance(raw_sources, list) else []
            src_errs = _validate_primary_sources_list(clean_sources, spot_id=sid)
            if src_errs:
                raise ValueError("Primary-source check-in validation failed: " + " ; ".join(src_errs))

            top_op = str(item.get("operating_status") or "").strip()
            if top_op and top_op not in VALID_OPERATING_STATUSES:
                raise ValueError(f"[{sid}] Invalid operating_status '{top_op}'")

            new_urls = (
                list(existing.get("official_urls") or [])
                + list(item.get("official_urls") or [])
                + [s["url"] for s in clean_sources if s.get("url")]
            )
            prev_checked = str(existing.get("last_checked_at") or existing.get("last_researched_at") or "")
            merged_checked = max(checked_at, prev_checked)
            merged_essay = _merge_editorial_essay(existing.get("editorial_essay"), item.get("editorial_essay"))
            merged_illustrations = _merge_illustrations(
                existing.get("illustrations"),
                item.get("illustrations"),
                default_date=merged_checked,
            )
            merged_connections = _merge_connections(
                existing.get("connections"),
                item.get("connections"),
                self_spot_id=sid,
            )
            merged_leads = _dedup_str_list(
                list(existing.get("next_research_leads") or []) + list(item.get("next_research_leads") or [])
            )
            merged_location = _merge_location(existing.get("location"), item.get("location"))
            dossier = {
                "spot_id": sid,
                "spot_name": str(item.get("spot_name") or existing.get("spot_name") or sp_meta["name"]),
                "category": str(sp_meta.get("category") or existing.get("category") or ""),
                "patrol_tier": str(sp_meta.get("patrol_tier") or existing.get("patrol_tier") or "low"),
                "last_researched_at": str(existing.get("last_researched_at") or existing_entries[-1].get("researched_at") or ""),
                "last_checked_at": merged_checked,
                "last_check_note": str(
                    item.get("check_note") or item.get("last_check_note") or "一次ソース再確認・前回より変更なし"
                ).strip(),
                "operating_status": top_op or str(existing.get("operating_status") or "open"),
                "operating_status_note": str(
                    item.get("operating_status_note")
                    or existing.get("operating_status_note")
                    or ""
                ).strip(),
                "official_urls": _dedup_str_list(new_urls),
                "curated_highlights": _dedup_str_list(
                    list(existing.get("curated_highlights") or []) + list(item.get("curated_highlights") or [])
                ),
                "story_angles": _dedup_str_list(
                    list(existing.get("story_angles") or []) + list(item.get("story_angles") or [])
                ),
                "special_feature_potential": existing.get("special_feature_potential")
                or {"ready": False, "theme_idea": "", "reason": ""},
                **({"editorial_essay": merged_essay} if merged_essay else {}),
                **({"illustrations": merged_illustrations} if merged_illustrations else {}),
                **({"connections": merged_connections} if merged_connections else {}),
                **({"next_research_leads": merged_leads} if merged_leads else {}),
                **({"location": merged_location} if merged_location else {}),
                "entries": existing_entries,
            }
            out_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append(
                {
                    "spot_id": sid,
                    "spot_name": dossier["spot_name"],
                    "status": "checked_no_change",
                    "total_entries": len(existing_entries),
                    "added_entries": 0,
                    "checked_at": dossier["last_checked_at"],
                    "path": str(out_path),
                }
            )
            continue

        raw_entries: list[dict[str, Any]] = []
        if isinstance(item.get("entries"), list):
            raw_entries = [dict(e) for e in item["entries"] if isinstance(e, dict)]
        elif isinstance(item.get("entry"), dict):
            raw_entries = [dict(item["entry"])]
        else:
            raw_entries = [dict(item)]

        if not raw_entries:
            raise ValueError(f"[{sid}] No entries provided in draft item")

        validated_entries: list[dict[str, Any]] = []
        for entry in raw_entries:
            if isinstance(entry.get("primary_sources"), list):
                entry["primary_sources"] = _clean_primary_sources(entry["primary_sources"])
            if not entry.get("researched_at"):
                entry["researched_at"] = str((entry.get("fact_check") or {}).get("checked_at") or datetime.now(JST).date().isoformat())
            errs = validate_report_entry(entry, spot_id=sid)
            if errs:
                raise ValueError("Primary-source validation failed: " + " ; ".join(errs))
            validated_entries.append(entry)

        top_op = str(item.get("operating_status") or validated_entries[-1].get("operating_status") or "").strip()
        if top_op and top_op not in VALID_OPERATING_STATUSES:
            raise ValueError(f"[{sid}] Invalid operating_status '{top_op}'")

        merged_entries: list[dict[str, Any]] = list(existing_entries)
        seen_keys = {
            (str(e.get("researched_at") or ""), str(e.get("headline") or "").strip())
            for e in merged_entries
        }
        added_count = 0
        for ve in validated_entries:
            k = (str(ve.get("researched_at") or ""), str(ve.get("headline") or "").strip())
            if k in seen_keys:
                merged_entries = [
                    ve if (str(e.get("researched_at") or ""), str(e.get("headline") or "").strip()) == k else e
                    for e in merged_entries
                ]
            else:
                merged_entries.append(ve)
                seen_keys.add(k)
                added_count += 1

        merged_entries.sort(key=lambda e: str(e.get("researched_at") or e.get("date") or ""))
        latest_entry = merged_entries[-1]

        new_urls = list(existing.get("official_urls") or []) + list(item.get("official_urls") or [])
        for src in latest_entry.get("primary_sources") or []:
            if isinstance(src, dict) and src.get("url"):
                new_urls.append(src["url"])

        merged_sfp = dict(existing.get("special_feature_potential") or {})
        if isinstance(item.get("special_feature_potential"), dict):
            sfp_in = item["special_feature_potential"]
            merged_sfp = {
                "ready": bool(sfp_in.get("ready", merged_sfp.get("ready", False))),
                "theme_idea": str(sfp_in.get("theme_idea") or merged_sfp.get("theme_idea") or "").strip(),
                "reason": str(sfp_in.get("reason") or merged_sfp.get("reason") or "").strip(),
            }

        latest_checked = str(
            (latest_entry.get("fact_check") or {}).get("checked_at")
            or latest_entry.get("researched_at")
            or ""
        ).strip()
        prev_checked = str(existing.get("last_checked_at") or "")
        merged_checked = max(latest_checked, prev_checked)
        merged_essay = _merge_editorial_essay(existing.get("editorial_essay"), item.get("editorial_essay"))
        merged_illustrations = _merge_illustrations(
            existing.get("illustrations"),
            item.get("illustrations"),
            default_date=merged_checked,
        )
        merged_connections = _merge_connections(
            existing.get("connections"),
            item.get("connections"),
            self_spot_id=sid,
        )
        merged_leads = _dedup_str_list(
            list(existing.get("next_research_leads") or []) + list(item.get("next_research_leads") or [])
        )
        merged_location = _merge_location(existing.get("location"), item.get("location"))
        dossier = {
            "spot_id": sid,
            "spot_name": str(item.get("spot_name") or existing.get("spot_name") or sp_meta["name"]),
            "category": str(sp_meta.get("category") or existing.get("category") or ""),
            "patrol_tier": str(sp_meta.get("patrol_tier") or existing.get("patrol_tier") or "low"),
            "last_researched_at": str(latest_entry.get("researched_at") or ""),
            "last_checked_at": merged_checked,
            "last_check_note": str(item.get("check_note") or latest_entry.get("headline") or "").strip(),
            "operating_status": top_op or str(existing.get("operating_status") or "open"),
            "operating_status_note": str(
                item.get("operating_status_note")
                or existing.get("operating_status_note")
                or ""
            ).strip(),
            "official_urls": _dedup_str_list(new_urls),
            "curated_highlights": _dedup_str_list(
                list(existing.get("curated_highlights") or []) + list(item.get("curated_highlights") or [])
            ),
            "story_angles": _dedup_str_list(
                list(existing.get("story_angles") or []) + list(item.get("story_angles") or [])
            ),
            "special_feature_potential": merged_sfp
            or {"ready": False, "theme_idea": "", "reason": ""},
            **({"editorial_essay": merged_essay} if merged_essay else {}),
            **({"illustrations": merged_illustrations} if merged_illustrations else {}),
            **({"connections": merged_connections} if merged_connections else {}),
            **({"next_research_leads": merged_leads} if merged_leads else {}),
            **({"location": merged_location} if merged_location else {}),
            "entries": merged_entries,
        }

        out_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(
            {
                "spot_id": sid,
                "spot_name": dossier["spot_name"],
                "status": "updated",
                "total_entries": len(merged_entries),
                "added_entries": added_count,
                "checked_at": dossier["last_checked_at"],
                "path": str(out_path),
            }
        )
    return results


def _build_research_briefing_md(
    targets: list[dict[str, Any]],
    reports_map: dict[str, dict[str, Any]],
    today_str: str,
) -> str:
    lines = [
        f"# 小平スポット継続取材・一次情報ファクトチェック指示書（{today_str}）",
        "",
        "## 取材方針（愛情 × 厳格な一次ソース検証）",
        "- 目的: 放送日だけでなく普段から小平の各地に目を配り、最新の営業状況・季節の変化・イベント・歴史豆知識・防災の接点を蓄積し、日々の放送や将来の長期特集に活かすこと。",
        "- **一次情報のみ採用**: 公式サイト、小平市役所公式、都水道局・一部事務組合公式、農園・神社・団体の公式発表・公式SNS・PR TIMES一次リリースのみを根拠とすること。",
        f"- **禁止事項**: まとめブログ・アフィリエイト系個人ブログ（例: {', '.join(LOW_TRUST_DOMAIN_BLOCKLIST)}）の記述だけで閉店・移転・休業・数値等を断定してはならない。未確認情報は `excluded_unverified_claims` に分離すること。",
        "",
        "## 対象スポットと既存取材履歴",
    ]
    for sp in targets:
        sid = str(sp["id"])
        existing = reports_map.get(sid) or {}
        e_count = len(existing.get("entries") or [])
        last_dt = existing.get("last_researched_at") or "なし"
        lines.append(
            f"- **{sp['name']}** (`{sid}`) ｜ {sp.get('category_label', sp.get('category'))} ｜ {sp.get('area', '')} ({sp.get('address_hint', '')})"
        )
        lines.append(f"  - 選定理由: {sp.get('_reason', '')} ｜ 既存レポート: {e_count}件（最終: {last_dt}）")
        if sp.get("verify_note"):
            lines.append(f"  - 注意・確認メモ: {sp['verify_note']}")

    lines.extend(
        [
            "",
            "## --ingest-draft 用 出力JSONフォーマット",
            "```json",
            json.dumps(
                {
                    "reports": [
                        {
                            "spot_id": "<spot_id>",
                            "operating_status": "open | seasonal | limited | renovation | closed",
                            "operating_status_note": "例: 通常営業中（営業時間・定休日）",
                            "official_urls": ["https://..."],
                            "curated_highlights": ["スポット固有の魅力・豆知識"],
                            "story_angles": ["ラジオでの切り口・防災とのつなぎ"],
                            "special_feature_potential": {
                                "ready": False,
                                "theme_idea": "複数回取材や周年・リニューアルを見据えた特集タイトル案",
                                "reason": "特集化できる根拠",
                            },
                            "entry": {
                                "researched_at": today_str,
                                "researcher": "local_verified",
                                "operating_status": "open",
                                "headline": "一次情報に基づく最新見出し",
                                "discoveries": ["一次確認できた具体事実1", "具体事実2"],
                                "seasonal_note": "季節の話題・見頃など",
                                "disaster_tie_in": "防災・減災・暮らしの備えへの自然なつなぎ",
                                "excluded_unverified_claims": ["一次確認できず除外した噂やブログ情報があれば記載"],
                                "fact_check": {
                                    "status": "verified_primary",
                                    "checked_at": today_str,
                                    "method": "公式HP直接確認 / Google検索一次情報照合",
                                    "notes": "確認日時・応答・照合根拠",
                                },
                                "primary_sources": [
                                    {"title": "公式サイト等タイトル", "url": "https://..."}
                                ],
                            },
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_api_research_for_spot(
    client: genai.Client,
    model: str,
    sp: dict[str, Any],
    existing_dossier: dict[str, Any] | None,
    today_str: str,
) -> dict[str, Any]:
    """2-pass grounded spot reporter + strict primary-source fact-checker."""
    from google.genai import types

    sid = str(sp["id"])
    prior_entries = (existing_dossier or {}).get("entries") or []
    prior_summary = (
        "\n".join(f"- [{e.get('researched_at')}] {e.get('headline')}" for e in prior_entries[-3:])
        if prior_entries
        else "（まだ取材履歴なし）"
    )
    existing_urls = ", ".join((existing_dossier or {}).get("official_urls") or []) or "（未登録）"

    pass1_prompt = f"""あなたは『こだいら防災＆まちラジオ』の専属フィールド記者です。
対象スポットの最新状況と魅力を、**一次情報（公式ホームページ・小平市役所公式・東京都等公的機関・運営企業や団体の公式SNS/プレスリリース）のみ**を使って深く取材してください。

基準日: {today_str}（JST）
スポットID: {sid}
スポット名: {sp['name']}
ジャンル: {sp.get('category_label', sp.get('category'))}
エリア・住所ヒント: {sp.get('area', '')} / {sp.get('address_hint', '')}（最寄: {sp.get('station', '')}）
既存メモ: {sp.get('summary', '')}
確認上の注意: {sp.get('verify_note', 'なし')}
既知の公式URL候補: {existing_urls}
これまでの取材ストック:
{prior_summary}

【厳守事項】
1. 営業状況（営業中・季節営業・事前予約制・改修中・閉業）は必ず一次情報で最新確認すること。
2. まとめサイトや個人ブログ（{', '.join(LOW_TRUST_DOMAIN_BLOCKLIST)} 等）だけを根拠に閉業・休業・イベント日付を書かないこと。未確認の噂やブログ記述を見つけた場合は事実扱いせず `excluded_unverified_claims` に記録すること。
3. 小平市と隣接市（立川市・東村山市・東久留米市・国分寺市など）の境界にある施設は、正確な所在地自治体を明記すること。

JSONのみを出力してください（コードブロックなしでも可）:
{{
  "spot_id": "{sid}",
  "operating_status": "open | seasonal | limited | renovation | closed",
  "operating_status_note": "確認した営業時間・定休日・注意など",
  "official_urls": ["https://..."],
  "curated_highlights": ["地元の人が喜ぶ具体魅力1", "豆知識2"],
  "story_angles": ["ラジオ放送や防災へのつなぎ例1"],
  "special_feature_potential": {{
    "ready": false,
    "theme_idea": "長期特集テーマ案（あれば）",
    "reason": "特集にできる理由"
  }},
  "entry": {{
    "researched_at": "{today_str}",
    "researcher": "api_grounded",
    "operating_status": "open",
    "headline": "今回の取材でわかった最重要トピック見出し",
    "discoveries": ["一次情報で確認した具体事実1", "具体事実2"],
    "seasonal_note": "季節の見どころ・限定メニュー等",
    "disaster_tie_in": "防災・暮らしの備えへの自然なつなぎ",
    "excluded_unverified_claims": [],
    "primary_sources": [
      {{"title": "一次情報ページ名", "url": "https://..."}}
    ]
  }}
}}"""

    resp1 = client.models.generate_content(
        model=model,
        contents=pass1_prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    print(f"  [Pass1 Reporter] {sid}: {_format_usage(resp1)}")
    draft1 = _parse_json_response(resp1.text or "{}")

    pass2_prompt = f"""あなたは『こだいら防災＆まちラジオ』の厳格な**一次情報ファクトチェックデスク**です。
記者が提出した下記ドラフトJSONのすべての主張（特に営業状況・閉業/改修の有無・住所/所在地自治体・日時・数値・URL）を、Google検索で一次ソースと再照合して最終確定版JSONを返してください。

基準日: {today_str}
ブロック対象ドメイン（primary_sources に入れず、これらのみ根拠の主張は削除して excluded_unverified_claims へ移す）: {', '.join(LOW_TRUST_DOMAIN_BLOCKLIST)}

提出ドラフト:
{json.dumps(draft1, ensure_ascii=False, indent=2)}

最終出力は下記を厳守:
- `entry.fact_check` を必ず {{"status": "verified_primary", "checked_at": "{today_str}", "method": "Gemini Google検索一次ソース二段階照合", "notes": "<何を一次ソースで検証したか>"}} として追加すること。
- `entry.primary_sources` には実際に一次情報が確認できた http:// または https:// URL を1件以上残すこと。
- 純粋なJSONオブジェクトのみ出力してください。"""

    resp2 = client.models.generate_content(
        model=model,
        contents=pass2_prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
        ),
    )
    print(f"  [Pass2 FactCheck] {sid}: {_format_usage(resp2)}")
    verified = _parse_json_response(resp2.text or "{}")
    if not isinstance(verified, dict):
        raise ValueError(f"[{sid}] Fact-check response was not a JSON object")
    verified["spot_id"] = sid
    return verified


def cmd_status(args: argparse.Namespace) -> int:
    spots_cfg, reports_map, topic_history, editorial_plan, program_schedule = _load_schedule_context()
    today_dt = datetime.now(JST).date()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_history,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        reference_date=today_dt,
    )
    cats = spots_cfg.get("categories") or []
    spots = [s for s in (spots_cfg.get("spots") or []) if isinstance(s, dict) and s.get("id")]

    total_entries = 0
    reported_spots = 0
    stale_spots = 0
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for sp in spots:
        by_cat.setdefault(str(sp.get("category") or ""), []).append(sp)

    print(f"=== Kodaira Spot Dossiers Status (base date: {today_dt.isoformat()}, stale >= {args.stale_days}d) ===")
    for cat in cats:
        cid = str(cat["id"])
        lbl = str(cat.get("label") or cid)
        icon = str(cat.get("icon") or "")
        cat_spots = by_cat.get(cid) or []
        cat_with_rep = 0
        cat_entries = 0
        for sp in cat_spots:
            dossier = reports_map.get(str(sp["id"])) or {}
            entries = dossier.get("entries") or []
            if entries:
                cat_with_rep += 1
                reported_spots += 1
                cat_entries += len(entries)
                total_entries += len(entries)
                last_dt = _parse_iso_date(dossier.get("last_researched_at"))
                if not last_dt or (today_dt - last_dt).days >= args.stale_days:
                    stale_spots += 1
            else:
                stale_spots += 1
        print(f"  {icon} {lbl:<20} | spots: {len(cat_spots):>2} | dossiers: {cat_with_rep:>2} | entries: {cat_entries:>2}")

    high_total = sum(1 for sp in spots if (sp.get("patrol_tier") or "low") == "high")
    high_reported = sum(
        1
        for sp in spots
        if (sp.get("patrol_tier") or "low") == "high" and (reports_map.get(str(sp["id"])) or {}).get("entries")
    )
    low_total = sum(1 for sp in spots if (sp.get("patrol_tier") or "low") != "high")
    low_reported = sum(
        1
        for sp in spots
        if (sp.get("patrol_tier") or "low") != "high" and (reports_map.get(str(sp["id"])) or {}).get("entries")
    )

    print(
        f"\nSummary: total_spots={len(spots)}, categories={len(cats)}, "
        f"spots_with_dossiers={reported_spots}, total_entries={total_entries}, stale_or_unresearched={stale_spots}"
    )
    print(f"Patrol Tiers: high={high_reported}/{high_total} covered | low={low_reported}/{low_total} covered")
    specials = find_longitudinal_special_candidates(spots_cfg, reports_map, min_entries=2)
    if specials:
        print(f"\nSpecial Feature Candidates ({len(specials)}):")
        for sp in specials:
            flag = "READY" if sp["ready"] else "SEED"
            print(f"  [{flag}] {sp['spot_name']} ({sp['spot_id']}, {sp['entry_count']} entries): {sp['theme_idea']}")

    batch = select_target_spots(
        spots_cfg,
        reports_map,
        usage_map,
        today_dt=today_dt,
        category=args.category,
        count=5,
        stale_days=args.stale_days,
    )
    if batch:
        print("\nTop 5 Suggested Next Targets:")
        for sp in batch:
            print(f"  - {sp['id']} | {sp['name']} ({sp['category_label']}) | {sp['_reason']}")
    return 0


def cmd_select_batch(args: argparse.Namespace) -> int:
    spots_cfg, reports_map, topic_history, editorial_plan, program_schedule = _load_schedule_context()
    today_dt = datetime.now(JST).date()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_history,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        reference_date=today_dt,
    )
    targets = select_target_spots(
        spots_cfg,
        reports_map,
        usage_map,
        today_dt=today_dt,
        spot_ids=args.spot_id,
        category=args.category,
        count=args.select_batch,
        stale_days=args.stale_days,
    )
    print(f"Selected {len(targets)} target spot(s) (date={today_dt.isoformat()}):")
    for idx, sp in enumerate(targets, start=1):
        print(
            f"  {idx}. {sp['id']} — {sp['name']} [{sp.get('category_label')}] ({sp.get('area')}) | {sp.get('_reason')}"
        )
    return 0


def cmd_prepare_local(args: argparse.Namespace) -> int:
    spots_cfg, reports_map, topic_history, editorial_plan, program_schedule = _load_schedule_context()
    today_dt = datetime.now(JST).date()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_history,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        reference_date=today_dt,
    )
    count = args.select_batch or args.max_spots or 5
    targets = select_target_spots(
        spots_cfg,
        reports_map,
        usage_map,
        today_dt=today_dt,
        spot_ids=args.spot_id,
        category=args.category,
        count=count,
        stale_days=args.stale_days,
    )
    md = _build_research_briefing_md(targets, reports_map, today_dt.isoformat())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"spot_research_{today_dt.isoformat()}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote local spot research briefing ({len(targets)} spot(s)): {out_path}")
    print(md)
    return 0


def cmd_ingest_draft(args: argparse.Namespace) -> int:
    draft_path = Path(args.ingest_draft)
    if not draft_path.exists():
        print(f"ERROR: Draft file not found: {draft_path}", file=sys.stderr)
        return 1
    payload = _load_json(draft_path)
    spots_cfg = load_kodaira_spots()
    results = ingest_draft_payload(payload, reports_dir=SPOT_REPORTS_DIR, spots_cfg=spots_cfg)
    print(f"Ingested {len(results)} verified spot dossier(s) into {SPOT_REPORTS_DIR}:")
    for r in results:
        print(f"  - {r['spot_id']} ({r['spot_name']}): +{r['added_entries']} new, total={r['total_entries']}")
    if args.rebuild_site:
        import build_site

        build_site.main()
    return 0


def cmd_run_api(args: argparse.Namespace) -> int:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set. Put it in .env or pass drafts via --ingest-draft.", file=sys.stderr)
        return 1
    from google import genai

    spots_cfg, reports_map, topic_history, editorial_plan, program_schedule = _load_schedule_context()
    today_dt = datetime.now(JST).date()
    today_str = today_dt.isoformat()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_history,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        reference_date=today_dt,
    )
    count = args.select_batch or args.max_spots
    targets = select_target_spots(
        spots_cfg,
        reports_map,
        usage_map,
        today_dt=today_dt,
        spot_ids=args.spot_id,
        category=args.category,
        count=count,
        stale_days=args.stale_days,
    )
    if not targets:
        print("No stale/matching target spots found.")
        return 0

    client = genai.Client(api_key=api_key)
    verified_items: list[dict[str, Any]] = []
    print(f"Running 2-pass grounded spot research via {args.model} for {len(targets)} spot(s)...")
    for sp in targets:
        sid = str(sp["id"])
        item = _run_api_research_for_spot(client, args.model, sp, reports_map.get(sid), today_str)
        verified_items.append(item)

    results = ingest_draft_payload({"reports": verified_items}, reports_dir=SPOT_REPORTS_DIR, spots_cfg=spots_cfg)
    print(f"Saved {len(results)} API-verified spot dossier(s):")
    for r in results:
        print(f"  - {r['spot_id']} ({r['spot_name']}): +{r['added_entries']} new, total={r['total_entries']}")

    if args.rebuild_site:
        import build_site

        build_site.main()
    return 0


def cmd_check_specials(args: argparse.Namespace) -> int:
    spots_cfg = load_kodaira_spots()
    reports_map = load_spot_reports(SPOT_REPORTS_DIR)
    specials = find_longitudinal_special_candidates(spots_cfg, reports_map, min_entries=2)
    print(f"Found {len(specials)} longitudinal special feature candidate(s):")
    for sp in specials:
        status = "特集化OK (ready=True)" if sp["ready"] else "蓄積進行中"
        print(
            f"- [{status}] {sp['spot_name']} ({sp['spot_id']} / {sp['category_label']} / {sp['entry_count']}件)"
        )
        if sp["theme_idea"]:
            print(f"    特集テーマ案: {sp['theme_idea']}")
        if sp["reason"]:
            print(f"    根拠: {sp['reason']}")
        if sp["latest_headline"]:
            print(f"    最新見出し ({sp['last_researched_at']}): {sp['latest_headline']}")
    return 0


def cmd_patrol_batch(args: argparse.Namespace) -> int:
    spots_cfg, reports_map, topic_history, editorial_plan, program_schedule = _load_schedule_context()
    today_dt = datetime.now(JST).date()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_history,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        reference_date=today_dt,
    )
    policy = spots_cfg.get("patrol_policy") or {}
    high_stale = int(policy.get("high_stale_days") or 4)
    low_stale = int(policy.get("low_stale_days") or 14)
    batched = select_patrol_batch(
        spots_cfg,
        reports_map,
        usage_map,
        today_dt=today_dt,
        high_count=args.high_count,
        low_count=args.low_count,
        high_stale_days=high_stale,
        low_stale_days=low_stale,
    )
    high_list = batched["high"]
    low_list = batched["low"]
    print(
        f"Patrol Batch (date={today_dt.isoformat()} | high={len(high_list)}/{args.high_count}, "
        f"low={len(low_list)}/{args.low_count}, total={len(high_list) + len(low_list)}):"
    )
    print("\n[HIGH TIER — 1日10件・高頻度巡回]")
    for idx, sp in enumerate(high_list, start=1):
        print(
            f"  {idx:>2}. {sp['id']} — {sp['name']} [{sp.get('category_label')}] ({sp.get('area')}) | {sp.get('_reason')}"
        )
    print("\n[LOW TIER — 1日5件・低頻度巡回]")
    for idx, sp in enumerate(low_list, start=1):
        print(
            f"  {idx:>2}. {sp['id']} — {sp['name']} [{sp.get('category_label')}] ({sp.get('area')}) | {sp.get('_reason')}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kodaira spot continuous primary-source research & dossier manager.")
    p.add_argument("--status", action="store_true", help="Show dossier coverage across all categories.")
    p.add_argument("--select-batch", type=int, default=0, help="Select N priority spots to research next.")
    p.add_argument("--patrol-batch", action="store_true", help="Preview tiered daily patrol targets (high + low).")
    p.add_argument("--high-count", type=int, default=10, help="Daily high-tier quota (default: 10).")
    p.add_argument("--low-count", type=int, default=5, help="Daily low-tier quota (default: 5).")
    p.add_argument("--spot-id", action="append", default=[], help="Target specific spot_id (repeatable).")
    p.add_argument("--category", default=None, help="Filter target selection by category id.")
    p.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS, help="Staleness threshold in days (default: 45).")
    p.add_argument("--prepare-local", action="store_true", help="Generate local spot-research & fact-check briefing.")
    p.add_argument("--ingest-draft", default=None, help="Validate & merge a local/agent-researched draft JSON.")
    p.add_argument("--rebuild-site", action="store_true", help="Rebuild docs/ HTML & Markdown catalog after ingest/run.")
    p.add_argument("--run-api", action="store_true", help="Run 2-pass Gemini grounded spot research & ingest.")
    p.add_argument("--model", default=DEFAULT_RESEARCH_MODEL, help=f"Gemini model for --run-api (default: {DEFAULT_RESEARCH_MODEL}).")
    p.add_argument("--max-spots", type=int, default=5, help="Max spots for --run-api when --select-batch is unset.")
    p.add_argument("--check-specials", action="store_true", help="List longitudinal special feature candidates.")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.ingest_draft:
        return cmd_ingest_draft(args)
    if args.run_api:
        return cmd_run_api(args)
    if args.prepare_local:
        return cmd_prepare_local(args)
    if args.patrol_batch:
        return cmd_patrol_batch(args)
    if args.select_batch > 0 and not args.status:
        return cmd_select_batch(args)
    if args.check_specials:
        return cmd_check_specials(args)
    return cmd_status(args)


if __name__ == "__main__":
    raise SystemExit(main())
