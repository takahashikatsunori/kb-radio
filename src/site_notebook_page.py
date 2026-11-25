"""Render docs/characters.html: tactile handwritten diary notebook for Kodaira Bousai Radio."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_CAST_ASSETS_DIR = ROOT_DIR / "docs" / "assets" / "cast"

WEEKDAY_SHORT = {
    "monday": "月",
    "tuesday": "火",
    "wednesday": "水",
    "thursday": "木",
    "friday": "金",
    "saturday": "土",
    "sunday": "日",
}

WEEKDAY_SHORT_LABEL = {
    "monday": "月・地震",
    "tuesday": "火・水害",
    "wednesday": "水・火災",
    "thursday": "木・医療",
    "friday": "金・備蓄",
    "saturday": "土・地域",
    "sunday": "日・テック",
}


def _weather_emoji(weather_desc: str) -> str:
    """Map Japanese weather phrase to a compact diary weather icon."""
    w = weather_desc or ""
    if "雪" in w:
        return "❄️"
    if "雷" in w:
        return "⛈️"
    if "雨" in w:
        return "☔"
    if "快晴" in w:
        return "☀️"
    if "晴" in w:
        return "🌤️"
    if "曇" in w or "霧" in w:
        return "☁️"
    return "🌤️"


def _format_weather_badge(weather_summary: dict[str, Any] | None) -> tuple[str, str]:
    """Build concise (icon, text) weather summary from episode weather_summary."""
    if not isinstance(weather_summary, dict) or not weather_summary.get("ok"):
        return ("", "")
    cur = weather_summary.get("current") or {}
    daily = weather_summary.get("daily") or []
    d0 = daily[0] if daily and isinstance(daily[0], dict) else {}

    cur_w = str(cur.get("weather") or "").strip()
    cur_t = cur.get("temperature_c")
    day_w = str(d0.get("weather") or "").strip()
    t_max = d0.get("temp_max_c")
    t_min = d0.get("temp_min_c")

    icon = _weather_emoji(cur_w or day_w)
    parts: list[str] = []
    if cur_w:
        parts.append(cur_w)
    if cur_t is not None:
        parts.append(f"{cur_t}℃")
    main_str = " ".join(parts)

    extra_parts: list[str] = []
    if day_w and day_w != cur_w:
        extra_parts.append(f"日中は{day_w}")
    if t_max is not None and t_min is not None:
        extra_parts.append(f"{t_max}°/{t_min}°")
    if extra_parts:
        main_str = f"{main_str}（{' '.join(extra_parts)}）" if main_str else " ".join(extra_parts)
    return (icon, main_str)


def _cast_asset_src(cast_id: str) -> str:
    """Return relative portrait path under docs/ if raster portrait asset exists."""
    if not cast_id:
        return ""
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if (DOCS_CAST_ASSETS_DIR / f"{cast_id}{ext}").exists():
            return f"assets/cast/{cast_id}{ext}"
    return ""


def _build_notebook_payload(
    knowledge_log: dict[str, Any],
    bundles: list[dict[str, Any]],
    characters: dict[str, Any],
    themes: dict[str, Any],
) -> dict[str, Any]:
    """Combine knowledge_log entries with episode audio/weather/cast metadata for diary rendering."""
    # Prefer regular (non-spinoff) episodes when multiple exist on the same date
    bundles_by_date: dict[str, dict[str, Any]] = {}
    sorted_bundles = sorted(
        bundles,
        key=lambda b: (1 if b["episode"]["meta"].get("is_spinoff") else 0, b["slug"]),
    )
    for b in sorted_bundles:
        d_str = str(b["episode"]["meta"].get("episode_date") or "")
        if d_str and d_str not in bundles_by_date:
            bundles_by_date[d_str] = b

    days_cfg = themes.get("days") or {}
    by_weekday_ja: dict[str, dict[str, Any]] = {}
    by_guest_id: dict[str, dict[str, Any]] = {}
    by_guest_name: dict[str, dict[str, Any]] = {}

    for day_key, cfg in days_cfg.items():
        guest = cfg.get("guest") or {}
        g_id = str(guest.get("id") or "")
        g_name = str(guest.get("name") or "")
        g_ui = guest.get("ui") or {}
        info = {
            "day_key": day_key,
            "weekday_ja": str(cfg.get("weekday_ja") or ""),
            "weekday_short": WEEKDAY_SHORT.get(day_key, ""),
            "tab_label": WEEKDAY_SHORT_LABEL.get(day_key, day_key),
            "theme_name": str(cfg.get("theme_name") or ""),
            "guest_id": g_id,
            "guest_name": g_name,
            "guest_title": str(guest.get("title") or ""),
            "guest_portrait": _cast_asset_src(g_id),
            "accent_color": str(g_ui.get("color") or "#1b5e3c"),
            "bg_soft": str(g_ui.get("bg_soft") or "#f0fdf4"),
        }
        if info["weekday_ja"]:
            by_weekday_ja[info["weekday_ja"]] = info
        if g_id:
            by_guest_id[g_id] = info
        if g_name:
            by_guest_name[g_name] = info

    entries_out: list[dict[str, Any]] = []
    guest_visit_counts: dict[str, int] = {}
    total_points = 0

    for raw_entry in reversed(knowledge_log.get("entries") or []):
        if not isinstance(raw_entry, dict):
            continue
        d_str = str(raw_entry.get("date") or "")
        w_ja = str(raw_entry.get("weekday") or "")
        g_name = str(raw_entry.get("guest_name") or "")
        b = bundles_by_date.get(d_str)

        ep_meta = (b["episode"].get("meta") or {}) if b else {}
        mf_meta = (b["manifest"].get("meta") or {}) if b else {}
        ep_guest = (b["episode"].get("guest") or {}) if b else {}

        ep_guest_id = str(ep_guest.get("id") or "")
        day_meta = (
            by_guest_id.get(ep_guest_id)
            or by_guest_name.get(g_name)
            or by_weekday_ja.get(w_ja)
            or {}
        )

        g_id = ep_guest_id or day_meta.get("guest_id", "")
        if g_id:
            guest_visit_counts[g_id] = guest_visit_counts.get(g_id, 0) + 1

        weather_icon, weather_text = _format_weather_badge(
            b["episode"].get("weather_summary") if b else None
        )
        learned_pts = [str(p).strip() for p in (raw_entry.get("learned_points") or []) if str(p).strip()]
        total_points += len(learned_pts)

        entries_out.append(
            {
                "date": d_str,
                "weekday": w_ja,
                "day_key": str(ep_meta.get("weekday") or day_meta.get("day_key") or ""),
                "weekday_short": day_meta.get("weekday_short") or (w_ja[:1] if w_ja else ""),
                "theme": str(raw_entry.get("theme") or day_meta.get("theme_name") or ""),
                "guest_name": g_name or day_meta.get("guest_name", ""),
                "guest_id": g_id,
                "guest_title": str(ep_guest.get("title") or day_meta.get("guest_title") or ""),
                "guest_portrait": _cast_asset_src(g_id),
                "accent_color": day_meta.get("accent_color") or "#1b5e3c",
                "bg_soft": day_meta.get("bg_soft") or "#f0fdf4",
                "episode_number": ep_meta.get("episode_number"),
                "subtitle": str(ep_meta.get("subtitle") or ""),
                "edition_label": str(ep_meta.get("edition_label") or ""),
                "episode_href": f"episodes/{b['slug']}/index.html" if b else "",
                "duration_formatted": str(mf_meta.get("total_duration_formatted") or ""),
                "has_audio": bool(b and b.get("has_audio")),
                "keywords_featured": list(ep_guest.get("keywords_featured") or []),
                "weather_icon": weather_icon,
                "weather_text": weather_text,
                "learned_points": learned_pts,
                "kodaira_discovery": str(raw_entry.get("kodaira_discovery") or "").strip(),
            }
        )

    hosts_cfg = (characters.get("hosts") or {})
    koharu_cfg = hosts_cfg.get("koharu") or {}
    heizo_cfg = hosts_cfg.get("heizo") or {}
    hosts_out = {
        "koharu": {
            "name": str(koharu_cfg.get("name") or "小春"),
            "role": str(koharu_cfg.get("role") or "メインパーソナリティ"),
            "portrait": _cast_asset_src("koharu"),
        },
        "heizo": {
            "name": str(heizo_cfg.get("name") or "平蔵"),
            "role": str(heizo_cfg.get("role") or "パートナーキャスター"),
            "portrait": _cast_asset_src("heizo"),
        },
    }

    weekday_order = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    all_guests: list[dict[str, Any]] = []
    for dk in weekday_order:
        cfg = days_cfg.get(dk)
        if not cfg:
            continue
        g = cfg.get("guest") or {}
        gid = str(g.get("id") or "")
        info = by_guest_id.get(gid) or {}
        visits = guest_visit_counts.get(gid, 0)
        all_guests.append(
            {
                "day_key": dk,
                "weekday_short": WEEKDAY_SHORT.get(dk, ""),
                "tab_label": WEEKDAY_SHORT_LABEL.get(dk, dk),
                "id": gid,
                "name": str(g.get("name") or ""),
                "theme_name": str(cfg.get("theme_name") or ""),
                "accent_color": info.get("accent_color") or "#1b5e3c",
                "bg_soft": info.get("bg_soft") or "#f0fdf4",
                "portrait_src": info.get("portrait_src") or _cast_asset_src(gid),
                "met": visits > 0,
                "visit_count": visits,
            }
        )

    return {
        "entries": entries_out,
        "hosts": hosts_out,
        "all_guests": all_guests,
        "stats": {
            "days": len(entries_out),
            "points": total_points,
            "met_guests": sum(1 for g in all_guests if g["met"]),
            "total_guests": len(all_guests),
        },
    }


NOTEBOOK_CSS = r"""
/* Handwritten diary desk & notebook aesthetic */
body {
  background-color: #efe7d8;
  background-image:
    radial-gradient(rgba(130, 108, 78, 0.14) 1px, transparent 1px),
    linear-gradient(180deg, #f3ecdf 0%, #eae0cd 100%);
  background-size: 20px 20px, 100% 100%;
  overflow-x: clip;
}
.nb-wrap {
  width: 100%;
  max-width: 980px;
  min-width: 0;
  margin: 0 auto;
  padding: 1.15rem 1rem 2.2rem;
}
.nb-hand {
  font-family: "Klee One", "Yomogi", "Hiragino Maru Gothic ProN", "Yu Mincho", "BIZ UDPMincho", serif;
}

/* Notebook Cover Card */
.nb-cover {
  position: relative;
  min-width: 0;
  max-width: 100%;
  background:
    linear-gradient(135deg, #fbf4e4 0%, #f5ead2 100%);
  border: 2px solid #d5c5a5;
  border-radius: 16px;
  padding: 1.35rem 1.35rem 1.2rem;
  margin-bottom: 1.15rem;
  box-shadow:
    0 10px 24px rgba(72, 52, 24, 0.11),
    0 2px 0 #e0d2b6;
}
.nb-cover::before {
  content: "";
  position: absolute;
  inset: 7px;
  border: 1.5px dashed rgba(155, 130, 92, 0.38);
  border-radius: 11px;
  pointer-events: none;
}
.nb-cover-top {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) auto;
  gap: 1.1rem;
  align-items: center;
}
.nb-cover-top > * {
  min-width: 0;
  max-width: 100%;
}
.nb-cover-kicker {
  display: inline-block;
  font-size: 0.74rem;
  font-weight: 700;
  color: #8c3f23;
  background: rgba(255, 243, 214, 0.9);
  border: 1px solid #e2c89c;
  border-radius: 999px;
  padding: 0.14rem 0.65rem;
  margin-bottom: 0.4rem;
}
.nb-cover-title {
  margin: 0 0 0.35rem;
  font-size: clamp(0.98rem, 4.4vw, 1.72rem);
  font-weight: 600;
  line-height: 1.35;
  color: #2f261c;
  text-wrap: balance;
}
.nb-title-underline {
  background: linear-gradient(transparent 68%, rgba(225, 29, 72, 0.22) 68%);
  padding: 0 0.15rem;
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
}
.nb-title-chunk {
  display: inline-block;
  white-space: nowrap;
}
.nb-cover-desc {
  margin: 0 0 0.75rem;
  font-size: 0.88rem;
  color: #5b4d3c;
  line-height: 1.65;
}

/* Stamp-style stats row */
.nb-stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.nb-stamp-stat {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  min-width: 82px;
  padding: 0.36rem 0.68rem;
  border: 1.5px solid rgba(180, 74, 52, 0.45);
  border-radius: 10px;
  background: rgba(255, 253, 246, 0.85);
  box-shadow: 0 1px 3px rgba(72, 52, 24, 0.08);
}
.nb-stamp-stat .val {
  font-family: "Klee One", "Yomogi", serif;
  font-size: 1.04rem;
  font-weight: 600;
  color: #b43b2a;
  line-height: 1.2;
}
.nb-stamp-stat .lbl {
  font-size: 0.68rem;
  color: #6b5a45;
  font-weight: 700;
}
.nb-cast-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.44rem 0.82rem;
  border-radius: 10px;
  background: #fff8c8;
  border: 1.5px solid #dfc96a;
  color: #533e10;
  font-size: 0.82rem;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 2px 3px 0 rgba(130, 102, 34, 0.14);
  transition: transform 0.15s ease;
}
.nb-cast-btn:hover {
  transform: translateY(-1px);
  background: #fff4ae;
}

/* Polaroid snapshots for Koharu & Heizo */
.nb-polaroids {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  padding: 0.35rem 0.2rem;
}
.nb-polaroid {
  position: relative;
  display: block;
  width: 96px;
  padding: 6px 6px 18px;
  background: #ffffff;
  border: 1px solid #ded5c3;
  border-radius: 4px;
  box-shadow: 0 6px 14px rgba(56, 40, 20, 0.16);
  text-decoration: none;
  color: #3a2e21;
  transition: transform 0.18s ease;
}
.nb-polaroid.koharu { transform: rotate(-2.8deg); }
.nb-polaroid.heizo { transform: rotate(2.4deg); }
.nb-polaroid:hover { transform: rotate(0deg) scale(1.03); z-index: 2; }
.nb-polaroid::before {
  content: "";
  position: absolute;
  top: -7px;
  left: 50%;
  transform: translateX(-50%) rotate(-3deg);
  width: 44px;
  height: 14px;
  background: rgba(245, 195, 105, 0.65);
  border-left: 1px dashed rgba(180, 130, 45, 0.3);
  border-right: 1px dashed rgba(180, 130, 45, 0.3);
}
.nb-polaroid.heizo::before {
  background: rgba(130, 185, 232, 0.6);
  transform: translateX(-50%) rotate(4deg);
}
.nb-polaroid img {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
  border-radius: 2px;
  background: #f3ece0;
}
.nb-polaroid .cap {
  display: block;
  margin-top: 4px;
  text-align: center;
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.72rem;
  font-weight: 600;
  line-height: 1.15;
}

/* 7-guest stamp rally strip */
.nb-rally {
  position: relative;
  min-width: 0;
  max-width: 100%;
  margin-top: 0.95rem;
  padding-top: 0.78rem;
  border-top: 1px dashed rgba(155, 130, 92, 0.45);
}
.nb-rally-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem 0.5rem;
  margin-bottom: 0.5rem;
  font-size: 0.78rem;
  font-weight: 700;
  color: #5b4d3c;
}
.nb-rally-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.45rem;
}
.nb-rally-item {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 0.38rem 0.22rem;
  border-radius: 10px;
  background: rgba(255, 253, 248, 0.78);
  border: 1px solid #e1d4ba;
  cursor: pointer;
  transition: transform 0.14s ease, box-shadow 0.14s ease;
  font-family: inherit;
  color: inherit;
}
.nb-rally-item.met:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(56, 40, 20, 0.12);
}
.nb-rally-item.unmet {
  opacity: 0.62;
  background: rgba(250, 245, 234, 0.55);
  border-style: dashed;
  cursor: default;
}
.nb-rally-avatar {
  position: relative;
  width: 42px;
  height: 42px;
  border-radius: 999px;
  padding: 2px;
  border: 2px solid var(--g-color, #1b5e3c);
  background: #fff;
  margin-bottom: 0.24rem;
}
.nb-rally-item.unmet .nb-rally-avatar {
  border-style: dashed;
  filter: grayscale(85%);
}
.nb-rally-avatar img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 999px;
}
.nb-rally-mark {
  position: absolute;
  right: -4px;
  bottom: -3px;
  font-size: 0.56rem;
  font-weight: 800;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 999px;
  background: #c83e37;
  color: #fff;
  border: 1.5px solid #fffdf7;
}
.nb-rally-day {
  font-size: 0.64rem;
  font-weight: 800;
  color: var(--g-color, #1b5e3c);
}
.nb-rally-name {
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.7rem;
  font-weight: 600;
  color: #362b1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

/* Controls: Index sticky tabs + Search + Sort */
.nb-controls {
  min-width: 0;
  max-width: 100%;
  background: rgba(255, 252, 243, 0.9);
  border: 1px solid #dbceb2;
  border-radius: 14px;
  padding: 0.72rem 0.85rem;
  margin-bottom: 1.15rem;
  box-shadow: 0 4px 12px rgba(72, 52, 24, 0.06);
}
.nb-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
  margin-bottom: 0.62rem;
}
.nb-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  min-height: 0;
  padding: 0.3rem 0.64rem;
  border-radius: 8px 8px 3px 3px;
  border: 1px solid #d6c8ab;
  border-top: 3px solid var(--tab-color, #1b5e3c);
  background: #fffcf4;
  color: #493c2e;
  font-size: 0.75rem;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.12s ease, background 0.12s ease;
}
.nb-tab:hover {
  transform: translateY(-1px);
  background: #fff7de;
}
.nb-tab.active {
  background: var(--tab-color, #1b5e3c);
  color: #ffffff;
  border-color: var(--tab-color, #1b5e3c);
}
.nb-tab .cnt {
  font-size: 0.68rem;
  opacity: 0.85;
}
.nb-search-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  min-width: 0;
}
.nb-search-box {
  flex: 1 1 180px;
  min-width: 0;
  max-width: 100%;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: #fffdf8;
  border: 1.5px solid #d7c9ab;
  border-radius: 10px;
  padding: 0.32rem 0.68rem;
}
.nb-search-box input {
  width: 100%;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.86rem;
  color: #2f261c;
  font-family: inherit;
}
.nb-sort-btn {
  flex: 0 0 auto;
  min-height: 0;
  padding: 0.42rem 0.78rem;
  border-radius: 10px;
  border: 1.5px solid #cbbba0;
  background: #faf3e4;
  color: #4a3c2c;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
}
.nb-sort-btn:hover {
  background: #f2e5cb;
}

/* 1-Day-1-Page Ruled Notebook Sheet */
.nb-pages {
  display: flex;
  flex-direction: column;
  gap: 1.45rem;
  min-width: 0;
  max-width: 100%;
}
.nb-page {
  position: relative;
  min-width: 0;
  max-width: 100%;
  background-color: #fffdf6;
  background-image:
    linear-gradient(90deg, transparent 0, transparent 48px, rgba(214, 92, 92, 0.28) 48px, rgba(214, 92, 92, 0.28) 49.5px, transparent 49.5px);
  border: 1px solid #d9ccb0;
  border-radius: 14px;
  padding: 1.25rem 1.45rem 1.15rem 4.15rem;
  box-shadow:
    0 10px 26px rgba(68, 48, 22, 0.1),
    3px 3px 0 #ede4d1,
    6px 6px 0 #e4d9c2;
}

/* Desktop left spiral binding rings */
.nb-rings-left {
  position: absolute;
  top: 22px;
  bottom: 22px;
  left: 11px;
  width: 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}
.nb-ring {
  position: relative;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: #d8ccb4;
  box-shadow: inset 0 2px 3px rgba(60, 42, 18, 0.35);
}
.nb-ring::before {
  content: "";
  position: absolute;
  left: -13px;
  top: 3px;
  width: 21px;
  height: 8px;
  border-radius: 999px;
  border: 2.5px solid #8c867c;
  border-right-color: transparent;
  background: linear-gradient(180deg, #e5dfd5 0%, #9b958b 100%);
  opacity: 0.72;
}

/* Washi masking tape on diary corners (kept strictly inside card bounds) */
.nb-tape {
  position: absolute;
  top: -8px;
  right: 22px;
  width: 92px;
  height: 22px;
  background: var(--tape-bg, rgba(245, 195, 105, 0.58));
  border-left: 2px dotted rgba(255, 255, 255, 0.75);
  border-right: 2px dotted rgba(255, 255, 255, 0.75);
  transform: rotate(2.4deg);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
  pointer-events: none;
}

/* Page header: date, weather, hanko stamp, guest mini-polaroid */
.nb-page-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  padding-bottom: 0.75rem;
  border-bottom: 3px double #cabfa5;
  margin-bottom: 0;
}
.nb-head-left {
  min-width: 0;
  flex: 1 1 280px;
}
.nb-date-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.36rem;
}
.nb-date-text {
  font-family: "Klee One", "Yomogi", serif;
  font-size: clamp(1.12rem, 2.8vw, 1.38rem);
  font-weight: 600;
  color: #292018;
  letter-spacing: 0.02em;
}
.nb-hanko {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.14rem 0.52rem;
  border: 2px solid #c83e37;
  border-radius: 999px;
  color: #c83e37;
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.74rem;
  font-weight: 600;
  transform: rotate(-5deg);
  background: rgba(255, 248, 246, 0.9);
  box-shadow: inset 0 0 0 1px rgba(200, 62, 55, 0.25);
}
.nb-weather-box {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.18rem 0.6rem;
  border-radius: 10px;
  border: 1.5px solid #d5c7aa;
  background: rgba(246, 249, 255, 0.82);
  font-size: 0.76rem;
  color: #3f4b5b;
  margin-bottom: 0.42rem;
}
.nb-theme-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}
.nb-theme-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.18rem 0.62rem;
  border-radius: 999px;
  background: var(--page-soft, #f0fdf4);
  color: var(--page-accent, #1b5e3c);
  border: 1px solid color-mix(in srgb, var(--page-accent, #1b5e3c) 30%, transparent);
  font-size: 0.76rem;
  font-weight: 700;
}
.nb-ep-subtitle {
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.86rem;
  color: #5b4d3c;
  margin-top: 0.34rem;
  line-height: 1.45;
}

/* Guest Mini-Polaroid */
.nb-guest-card {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.4rem 0.62rem;
  background: #ffffff;
  border: 1px solid #dfd4bd;
  border-radius: 10px;
  box-shadow: 0 3px 8px rgba(68, 48, 22, 0.09);
  transform: rotate(1.1deg);
  max-width: 260px;
}
.nb-guest-card img {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  object-fit: cover;
  flex: 0 0 auto;
  border: 1.5px solid var(--page-accent, #1b5e3c);
}
.nb-guest-meta {
  min-width: 0;
}
.nb-guest-lbl {
  font-size: 0.64rem;
  font-weight: 800;
  color: var(--page-accent, #1b5e3c);
}
.nb-guest-name {
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.88rem;
  font-weight: 600;
  color: #2b2218;
  line-height: 1.25;
}
.nb-guest-role {
  font-size: 0.68rem;
  color: #6b5d4c;
  line-height: 1.3;
}

/* Pixel-locked ruled writing sheet */
.nb-ruled-body {
  --nb-line: 32px;
  --nb-baseline-shift: 3px;
  position: relative;
  margin: 0;
  padding: var(--nb-baseline-shift) 0 calc(var(--nb-line) - var(--nb-baseline-shift));
  background-image: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent calc(var(--nb-line) - 1px),
    #ddd4bc calc(var(--nb-line) - 1px),
    #ddd4bc var(--nb-line)
  );
  background-size: 100% var(--nb-line);
  background-position: 0 0;
  background-origin: border-box;
}

/* Section subheadings inside page */
.nb-sec-title {
  display: block;
  margin: 0;
  padding: 0;
  min-height: var(--nb-line);
  line-height: var(--nb-line);
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.96rem;
  font-weight: 600;
  color: #2c2319;
}
.nb-sec-title .bar {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: var(--page-accent, #1b5e3c);
  margin-right: 0.42rem;
  vertical-align: 0.05em;
}

/* Interactive Checkable Learned Points */
.nb-memo-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--nb-line);
}
.nb-memo-item {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  margin: 0;
  padding: 0 0.25rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.14s ease;
}
.nb-memo-item:hover {
  background: rgba(252, 242, 207, 0.45);
}
.nb-chk-btn {
  flex: 0 0 auto;
  box-sizing: border-box;
  width: 20px;
  height: 20px;
  min-height: 20px;
  margin-top: calc((var(--nb-line) - 20px) / 2);
  padding: 0;
  border: 2px solid #7d6d58;
  border-radius: 5px;
  background: #fffdf8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #c83e37;
}
.nb-chk-btn svg {
  width: 14px;
  height: 14px;
  display: block;
}
.nb-memo-item.checked .nb-chk-btn {
  border-color: #c83e37;
  background: #fff5f3;
}
.nb-memo-text {
  display: block;
  flex: 1 1 auto;
  min-width: 0;
  font-family: "Klee One", "Yomogi", serif;
  font-size: 15.5px;
  line-height: var(--nb-line);
  color: #2a2219;
  overflow-wrap: anywhere;
}
.nb-memo-item.checked .nb-memo-text {
  color: #6b5f50;
}
.nb-done-chip {
  display: inline-block;
  margin-left: 0.42rem;
  padding: 0.05rem 0.36rem;
  font-size: 0.68rem;
  line-height: 1.3;
  font-family: sans-serif;
  font-weight: 800;
  color: #c83e37;
  border: 1px solid rgba(200, 62, 55, 0.55);
  border-radius: 4px;
  vertical-align: 0.12em;
}
.nb-hl {
  background: linear-gradient(transparent 56%, rgba(254, 240, 138, 0.82) 56%, rgba(254, 240, 138, 0.82) 94%, transparent 94%);
  padding: 0 0.1rem;
  border-radius: 2px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

/* Koharu's Kodaira Discovery Sticky Note */
.nb-sticky {
  position: relative;
  margin: 0.85rem 0 0.95rem;
  padding: 0.8rem 0.95rem 0.85rem;
  background: linear-gradient(160deg, #fff9c9 0%, #fff2a6 100%);
  border: 1px solid #ead87d;
  border-radius: 6px 6px 14px 6px;
  box-shadow: 2px 5px 12px rgba(96, 78, 22, 0.14);
  transform: rotate(-0.65deg);
}
.nb-sticky::after {
  content: "";
  position: absolute;
  right: 0;
  bottom: 0;
  width: 18px;
  height: 18px;
  background: linear-gradient(135deg, rgba(224, 200, 96, 0.55) 50%, transparent 50%);
  border-top-left-radius: 6px;
  pointer-events: none;
}
.nb-sticky-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.32rem;
}
.nb-sticky-avatar {
  width: 26px;
  height: 26px;
  border-radius: 999px;
  object-fit: cover;
  border: 1.5px solid #e11d48;
  background: #fff;
}
.nb-sticky-title {
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.86rem;
  font-weight: 600;
  color: #9f1239;
}
.nb-sticky-body {
  font-family: "Klee One", "Yomogi", serif;
  font-size: 0.93rem;
  line-height: 1.78;
  color: #3b2f13;
}

/* Page footer: keywords + doodle + listen bookmark */
.nb-page-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.65rem;
  padding-top: 0.65rem;
  border-top: 1px dashed rgba(130, 108, 78, 0.35);
}
.nb-kw-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  flex: 1 1 240px;
}
.nb-kw-chip {
  display: inline-block;
  padding: 0.14rem 0.5rem;
  border-radius: 6px;
  border: 1px dashed rgba(91, 77, 60, 0.4);
  background: rgba(255, 253, 248, 0.85);
  font-size: 0.72rem;
  color: #554736;
}
.nb-foot-right {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}
.nb-doodle {
  width: 34px;
  height: 34px;
  opacity: 0.7;
  color: var(--page-accent, #1b5e3c);
}
.nb-listen-link {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  padding: 0.36rem 0.72rem;
  border-radius: 999px;
  background: var(--page-accent, #1b5e3c);
  color: #ffffff;
  text-decoration: none;
  font-size: 0.76rem;
  font-weight: 700;
  white-space: nowrap;
}
.nb-listen-link:hover {
  filter: brightness(1.08);
}

.nb-empty {
  text-align: center;
  padding: 2rem 1rem;
  background: #fffdf6;
  border: 1.5px dashed #d3c4a4;
  border-radius: 14px;
  color: #5b4d3c;
}
.nb-reset-btn {
  margin-top: 0.7rem;
  padding: 0.4rem 0.85rem;
  border-radius: 999px;
  border: 1px solid #1b5e3c;
  background: #ffffff;
  color: #1b5e3c;
  font-weight: 700;
  cursor: pointer;
}

@media (max-width: 720px) {
  .nb-cover-top {
    grid-template-columns: minmax(0, 1fr);
  }
  .nb-polaroids {
    justify-content: flex-start;
  }
  .nb-rally-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.34rem;
  }
}

@media (max-width: 680px) {
  .nb-wrap {
    padding: 0.85rem 0.65rem 1.8rem;
  }
  .nb-cover {
    padding: 1rem 0.9rem 0.95rem;
  }
  .nb-rally-name {
    font-size: 0.64rem;
  }
  .nb-controls {
    padding: 0.65rem 0.72rem;
  }
  .nb-search-row {
    gap: 0.42rem;
  }
  .nb-search-box {
    flex: 1 1 100%;
  }
  .nb-sort-btn {
    width: 100%;
  }
  .nb-page {
    background-image: none;
    padding: 2.05rem 0.95rem 1rem 0.95rem;
  }
  .nb-ruled-body {
    --nb-line: 30px;
    --nb-baseline-shift: 3px;
  }
  .nb-sec-title {
    font-size: 0.88rem;
  }
  .nb-head-left {
    flex: 1 1 100%;
  }
  .nb-listen-link {
    max-width: 100%;
    white-space: normal;
  }
  /* Move spiral ring holes to the top edge on mobile for generous text width */
  .nb-rings-left {
    top: 9px;
    bottom: auto;
    left: 18px;
    right: 18px;
    width: auto;
    height: 14px;
    flex-direction: row;
  }
  .nb-ring {
    width: 11px;
    height: 11px;
  }
  .nb-ring::before {
    left: 2px;
    top: -11px;
    width: 7px;
    height: 16px;
    border: 2px solid #8c867c;
    border-bottom-color: transparent;
  }
  .nb-tape {
    width: 68px;
    height: 17px;
    right: 14px;
    top: -6px;
  }
  .nb-guest-card {
    max-width: 100%;
    transform: none;
  }
  .nb-sticky {
    transform: none;
  }
  .nb-memo-text {
    font-size: 14.5px;
    line-height: var(--nb-line);
  }
}
"""


NOTEBOOK_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>防災ノート | 毎朝7時！こだいら防災＆まちラジオ</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Klee+One:wght@400;600&family=Yomogi&display=swap" rel="stylesheet" />
  <style>$COMMON_CSS
$NOTEBOOK_CSS</style>
</head>
<body>
  <header>
    <div class="header-inner">
      $NAV_HTML
    </div>
  </header>

  <main class="nb-wrap">
    <section class="nb-cover" aria-label="防災ノートの表紙">
      <div class="nb-cover-top">
        <div>
          <span class="nb-cover-kicker">毎朝の学びを綴るコミュニティ日記</span>
          <h2 class="nb-cover-title nb-hand"><span class="nb-title-underline"><span class="nb-title-chunk">小春＆平蔵の</span> <span class="nb-title-chunk">防災・こだいら発見ノート</span></span></h2>
          <p class="nb-cover-desc">
            毎朝7時の放送で専門家から教わった防災の知恵と、小平のまちの魅力を1日1ページずつ手書き風に記録しています。メモの四角（□）をタップすると、おうち点検の「確認済み」チェックも残せます。
          </p>
          <div class="nb-stats-row">
            <div class="nb-stamp-stat">
              <span class="val" id="stat-days">-</span>
              <span class="lbl">記録日数</span>
            </div>
            <div class="nb-stamp-stat">
              <span class="val" id="stat-points">-</span>
              <span class="lbl">防災メモ</span>
            </div>
            <div class="nb-stamp-stat">
              <span class="val" id="stat-checked">0 / 0</span>
              <span class="lbl">確認済み</span>
            </div>
            <div class="nb-stamp-stat">
              <span class="val" id="stat-guests">-</span>
              <span class="lbl">会えた先生</span>
            </div>
            <a class="nb-cast-btn" href="cast.html">出演者紹介・声を聴く →</a>
          </div>
        </div>

        <div class="nb-polaroids" id="host-polaroids"></div>
      </div>

      <div class="nb-rally">
        <div class="nb-rally-head">
          <span>曜日別 専門家スタンプラリー（タップで絞り込み）</span>
          <span id="rally-progress-text" style="color:#b43b2a;"></span>
        </div>
        <div class="nb-rally-grid" id="guest-rally"></div>
      </div>
    </section>

    <section class="nb-controls" aria-label="ノートの絞り込みと並び替え">
      <div class="nb-tabs" id="day-tabs"></div>
      <div class="nb-search-row">
        <label class="nb-search-box" aria-label="ノート内検索">
          <span aria-hidden="true">🔍</span>
          <input id="nb-search" type="search" placeholder="キーワード検索（例：XRAIN、キウイ、耐震、下水道館…）" />
        </label>
        <button type="button" class="nb-sort-btn" id="nb-sort-btn">新しい順 ↓</button>
      </div>
    </section>

    <section class="nb-pages" id="notebook-pages" aria-label="日別の防災ノート一覧"></section>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ <a href="cast.html">出演者紹介へ →</a></footer>

  <script type="application/json" id="notebook-data">$PAYLOAD_JSON</script>
  <script>
    (function () {
      const STORAGE_KEY = "kb_radio_bousai_checks_v1";
      const data = JSON.parse(document.getElementById("notebook-data").textContent);
      const entries = data.entries || [];
      const hosts = data.hosts || {};
      const allGuests = data.all_guests || [];

      let activeDay = "all";
      let searchQuery = "";
      let sortNewestFirst = true;

      function loadChecks() {
        try {
          const raw = localStorage.getItem(STORAGE_KEY);
          const parsed = raw ? JSON.parse(raw) : {};
          return parsed && typeof parsed === "object" ? parsed : {};
        } catch (e) {
          return {};
        }
      }

      function saveChecks(map) {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
        } catch (e) {
          /* ignore storage quota errors */
        }
      }

      let checksMap = loadChecks();

      function createSvg(paths, viewBox, className) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", viewBox || "0 0 24 24");
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "1.9");
        svg.setAttribute("stroke-linecap", "round");
        svg.setAttribute("stroke-linejoin", "round");
        svg.setAttribute("aria-hidden", "true");
        if (className) svg.setAttribute("class", className);
        paths.forEach(function (d) {
          const p = document.createElementNS(ns, "path");
          p.setAttribute("d", d);
          svg.appendChild(p);
        });
        return svg;
      }

      function doodlePathsForDay(dayKey) {
        switch (dayKey) {
          case "monday":
            return ["M3 20 L12 4 L21 20 Z", "M9 20 L9 14 L15 14 L15 20"];
          case "tuesday":
            return ["M6 15 A4 4 0 0 1 8 8 A5 5 0 0 1 18 9 A3.5 3.5 0 0 1 18 15 Z", "M8 18 L7 21", "M12 18 L11 21", "M16 18 L15 21"];
          case "wednesday":
            return ["M12 3 C14 7 17 9 17 14 A5 5 0 0 1 7 14 C7 11 9 8 10 6 C11 8 12 8 12 3 Z"];
          case "thursday":
            return ["M12 20 C6 15 4 11 4 8 A4 4 0 0 1 12 7 A4 4 0 0 1 20 8 C20 11 18 15 12 20 Z"];
          case "friday":
            return ["M6 8 L18 8 L17 20 L7 20 Z", "M9 8 L9 5 L15 5 L15 8", "M9 14 L15 14"];
          case "saturday":
            return ["M3 11 L12 4 L21 11", "M5 10 V20 H19 V10", "M10 20 V14 H14 V20"];
          case "sunday":
            return ["M12 3 L12 7", "M4 12 H8", "M16 12 H20", "M7 17 A5 5 0 0 1 17 17", "M12 12 m-2 0 a2 2 0 1 0 4 0 a2 2 0 1 0 -4 0"];
          default:
            return ["M12 4 L14 10 L20 10 L15 14 L17 20 L12 16 L7 20 L9 14 L4 10 L10 10 Z"];
        }
      }

      function appendHighlightedText(parent, text) {
        const str = String(text || "");
        const re = /([「『][^」』]{1,36}[」』])/g;
        let lastIdx = 0;
        let match;
        while ((match = re.exec(str)) !== null) {
          if (match.index > lastIdx) {
            parent.appendChild(document.createTextNode(str.slice(lastIdx, match.index)));
          }
          const span = document.createElement("span");
          span.className = "nb-hl";
          span.textContent = match[1];
          parent.appendChild(span);
          lastIdx = match.index + match[1].length;
        }
        if (lastIdx < str.length) {
          parent.appendChild(document.createTextNode(str.slice(lastIdx)));
        }
      }

      function formatJpDate(dateStr, weekdayShort) {
        const parts = String(dateStr || "").split("-");
        if (parts.length !== 3) return dateStr + (weekdayShort ? "（" + weekdayShort + "）" : "");
        const y = parts[0];
        const mo = parseInt(parts[1], 10);
        const da = parseInt(parts[2], 10);
        if (isNaN(mo) || isNaN(da)) return dateStr + (weekdayShort ? "（" + weekdayShort + "）" : "");
        return y + "年 " + mo + "月 " + da + "日" + (weekdayShort ? "（" + weekdayShort + "）" : "");
      }

      function updateStats() {
        const stats = data.stats || { days: entries.length, points: 0, met_guests: 0, total_guests: 7 };
        let checkedCount = 0;
        entries.forEach(function (e) {
          (e.learned_points || []).forEach(function (_, idx) {
            if (checksMap[e.date + "#" + idx]) checkedCount += 1;
          });
        });
        document.getElementById("stat-days").textContent = stats.days + "日分";
        document.getElementById("stat-points").textContent = stats.points + "個";
        document.getElementById("stat-checked").textContent = checkedCount + " / " + stats.points;
        document.getElementById("stat-guests").textContent = stats.met_guests + " / " + stats.total_guests + "名";
        document.getElementById("rally-progress-text").textContent =
          "現在 " + stats.met_guests + " / " + stats.total_guests + " 名の先生が登場済み";
      }

      function renderPolaroids() {
        const container = document.getElementById("host-polaroids");
        container.textContent = "";
        [["koharu", "小春メモ"], ["heizo", "平蔵メモ"]].forEach(function (pair) {
          const key = pair[0];
          const label = pair[1];
          const h = hosts[key] || {};
          const a = document.createElement("a");
          a.className = "nb-polaroid " + key;
          a.href = "cast.html#" + key;
          if (h.portrait) {
            const img = document.createElement("img");
            img.src = h.portrait;
            img.alt = (h.name || key) + "のポートレート";
            img.loading = "lazy";
            a.appendChild(img);
          }
          const cap = document.createElement("span");
          cap.className = "cap";
          cap.textContent = label;
          a.appendChild(cap);
          container.appendChild(a);
        });
      }

      function renderGuestRally() {
        const grid = document.getElementById("guest-rally");
        grid.textContent = "";
        allGuests.forEach(function (g) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "nb-rally-item " + (g.met ? "met" : "unmet");
          btn.style.setProperty("--g-color", g.accent_color || "#1b5e3c");
          btn.title = g.met
            ? g.name + "（" + g.theme_name + "）のページで絞り込む"
            : g.name + "（" + g.weekday_short + "曜・これから登場予定）";

          const av = document.createElement("div");
          av.className = "nb-rally-avatar";
          if (g.portrait_src) {
            const img = document.createElement("img");
            img.src = g.portrait_src;
            img.alt = g.name;
            img.loading = "lazy";
            av.appendChild(img);
          }
          if (g.met) {
            const mark = document.createElement("span");
            mark.className = "nb-rally-mark";
            mark.textContent = "済";
            av.appendChild(mark);
          }
          btn.appendChild(av);

          const dayEl = document.createElement("span");
          dayEl.className = "nb-rally-day";
          dayEl.textContent = g.weekday_short + "曜";
          btn.appendChild(dayEl);

          const nameEl = document.createElement("span");
          nameEl.className = "nb-rally-name";
          nameEl.textContent = g.name;
          btn.appendChild(nameEl);

          if (g.met) {
            btn.addEventListener("click", function () {
              activeDay = activeDay === g.day_key ? "all" : g.day_key;
              renderTabs();
              renderPages();
            });
          }
          grid.appendChild(btn);
        });
      }

      function renderTabs() {
        const tabsEl = document.getElementById("day-tabs");
        tabsEl.textContent = "";
        const counts = { all: entries.length };
        entries.forEach(function (e) {
          if (e.day_key) counts[e.day_key] = (counts[e.day_key] || 0) + 1;
        });

        const tabDefs = [{ key: "all", label: "すべて", color: "#1b5e3c" }].concat(
          allGuests.map(function (g) {
            return { key: g.day_key, label: g.tab_label, color: g.accent_color };
          })
        );

        tabDefs.forEach(function (td) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "nb-tab" + (activeDay === td.key ? " active" : "");
          btn.style.setProperty("--tab-color", td.color || "#1b5e3c");
          const lblSpan = document.createElement("span");
          lblSpan.textContent = td.label;
          const cntSpan = document.createElement("span");
          cntSpan.className = "cnt";
          cntSpan.textContent = "(" + (counts[td.key] || 0) + ")";
          btn.appendChild(lblSpan);
          btn.appendChild(cntSpan);
          btn.addEventListener("click", function () {
            activeDay = td.key;
            renderTabs();
            renderPages();
          });
          tabsEl.appendChild(btn);
        });
      }

      function matchesFilters(e) {
        if (activeDay !== "all" && e.day_key !== activeDay) return false;
        if (!searchQuery) return true;
        const haystack = [
          e.date,
          e.weekday,
          e.theme,
          e.guest_name,
          e.subtitle,
          e.kodaira_discovery,
          (e.learned_points || []).join(" "),
          (e.keywords_featured || []).join(" "),
        ]
          .join(" ")
          .toLowerCase();
        return haystack.indexOf(searchQuery.toLowerCase()) !== -1;
      }

      function renderPages() {
        const listEl = document.getElementById("notebook-pages");
        listEl.textContent = "";

        let filtered = entries.filter(matchesFilters);
        if (!sortNewestFirst) {
          filtered = filtered.slice().reverse();
        }

        if (filtered.length === 0) {
          const empty = document.createElement("div");
          empty.className = "nb-empty";
          const msg = document.createElement("div");
          msg.className = "nb-hand";
          msg.textContent = "条件に合うノートページが見つかりませんでした。";
          empty.appendChild(msg);
          const resetBtn = document.createElement("button");
          resetBtn.type = "button";
          resetBtn.className = "nb-reset-btn";
          resetBtn.textContent = "絞り込みをリセットする";
          resetBtn.addEventListener("click", function () {
            activeDay = "all";
            searchQuery = "";
            document.getElementById("nb-search").value = "";
            renderTabs();
            renderPages();
          });
          empty.appendChild(resetBtn);
          listEl.appendChild(empty);
          return;
        }

        filtered.forEach(function (e, pageIdx) {
          const article = document.createElement("article");
          article.className = "nb-page";
          article.style.setProperty("--page-accent", e.accent_color || "#1b5e3c");
          article.style.setProperty("--page-soft", e.bg_soft || "#f0fdf4");
          article.style.setProperty("--tape-bg", pageIdx % 2 === 0 ? "rgba(245, 195, 105, 0.56)" : "rgba(130, 185, 232, 0.52)");

          // Spiral binding holes
          const rings = document.createElement("div");
          rings.className = "nb-rings-left";
          rings.setAttribute("aria-hidden", "true");
          for (let r = 0; r < 10; r += 1) {
            const ring = document.createElement("span");
            ring.className = "nb-ring";
            rings.appendChild(ring);
          }
          article.appendChild(rings);

          // Decorative masking tape
          const tape = document.createElement("div");
          tape.className = "nb-tape";
          tape.setAttribute("aria-hidden", "true");
          article.appendChild(tape);

          // Header
          const head = document.createElement("div");
          head.className = "nb-page-head";

          const headLeft = document.createElement("div");
          headLeft.className = "nb-head-left";

          const dateRow = document.createElement("div");
          dateRow.className = "nb-date-row";
          const dateSpan = document.createElement("span");
          dateSpan.className = "nb-date-text";
          dateSpan.textContent = formatJpDate(e.date, e.weekday_short);
          dateRow.appendChild(dateSpan);

          if (e.episode_number) {
            const hanko = document.createElement("span");
            hanko.className = "nb-hanko";
            hanko.textContent = "第" + e.episode_number + "回";
            dateRow.appendChild(hanko);
          }
          headLeft.appendChild(dateRow);

          if (e.weather_text) {
            const wBox = document.createElement("div");
            wBox.className = "nb-weather-box";
            wBox.textContent = "お天気: " + (e.weather_icon ? e.weather_icon + " " : "") + e.weather_text;
            headLeft.appendChild(wBox);
          }

          const themeRow = document.createElement("div");
          themeRow.className = "nb-theme-row";
          const themeBadge = document.createElement("span");
          themeBadge.className = "nb-theme-badge";
          themeBadge.textContent = (e.weekday_short ? e.weekday_short + "曜テーマ: " : "") + e.theme;
          themeRow.appendChild(themeBadge);
          headLeft.appendChild(themeRow);

          if (e.subtitle) {
            const sub = document.createElement("div");
            sub.className = "nb-ep-subtitle";
            sub.textContent = e.subtitle;
            headLeft.appendChild(sub);
          }
          head.appendChild(headLeft);

          // Guest mini-polaroid
          if (e.guest_name) {
            const gCard = document.createElement("div");
            gCard.className = "nb-guest-card";
            if (e.guest_portrait) {
              const gImg = document.createElement("img");
              gImg.src = e.guest_portrait;
              gImg.alt = e.guest_name;
              gImg.loading = "lazy";
              gCard.appendChild(gImg);
            }
            const gMeta = document.createElement("div");
            gMeta.className = "nb-guest-meta";
            const gLbl = document.createElement("div");
            gLbl.className = "nb-guest-lbl";
            gLbl.textContent = "本日の先生";
            const gName = document.createElement("div");
            gName.className = "nb-guest-name";
            gName.textContent = e.guest_name + " 先生";
            gMeta.appendChild(gLbl);
            gMeta.appendChild(gName);
            if (e.guest_title) {
              const gRole = document.createElement("div");
              gRole.className = "nb-guest-role";
              gRole.textContent = e.guest_title.replace(/（[^）]*架空ゲスト）/g, "");
              gMeta.appendChild(gRole);
            }
            gCard.appendChild(gMeta);
            head.appendChild(gCard);
          }
          article.appendChild(head);

          // Learned points section (ruled writing sheet)
          const ruledBody = document.createElement("div");
          ruledBody.className = "nb-ruled-body";

          const secTitle = document.createElement("h3");
          secTitle.className = "nb-sec-title";
          const bar = document.createElement("span");
          bar.className = "bar";
          secTitle.appendChild(bar);
          secTitle.appendChild(document.createTextNode("今日の防災メモ（クリックで点検チェック）"));
          ruledBody.appendChild(secTitle);

          const ul = document.createElement("ul");
          ul.className = "nb-memo-list";
          (e.learned_points || []).forEach(function (pt, idx) {
            const chkKey = e.date + "#" + idx;
            const li = document.createElement("li");
            li.className = "nb-memo-item" + (checksMap[chkKey] ? " checked" : "");

            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "nb-chk-btn";
            btn.setAttribute("aria-pressed", checksMap[chkKey] ? "true" : "false");
            btn.setAttribute("aria-label", "防災メモを確認済みにする");

            function syncCheckVisual() {
              const isChecked = !!checksMap[chkKey];
              li.className = "nb-memo-item" + (isChecked ? " checked" : "");
              btn.setAttribute("aria-pressed", isChecked ? "true" : "false");
              btn.textContent = "";
              if (isChecked) {
                btn.appendChild(createSvg(["M4 12 L9.5 17.5 L20 6"], "0 0 24 24", ""));
              }
              doneChip.style.display = isChecked ? "inline-block" : "none";
            }

            const textSpan = document.createElement("span");
            textSpan.className = "nb-memo-text";
            appendHighlightedText(textSpan, pt);

            const doneChip = document.createElement("span");
            doneChip.className = "nb-done-chip";
            doneChip.textContent = "確認済";
            textSpan.appendChild(doneChip);

            syncCheckVisual();

            li.addEventListener("click", function () {
              if (checksMap[chkKey]) {
                delete checksMap[chkKey];
              } else {
                checksMap[chkKey] = true;
              }
              saveChecks(checksMap);
              syncCheckVisual();
              updateStats();
            });

            li.appendChild(btn);
            li.appendChild(textSpan);
            ul.appendChild(li);
          });
          ruledBody.appendChild(ul);
          article.appendChild(ruledBody);

          // Koharu's Kodaira discovery sticky note
          if (e.kodaira_discovery) {
            const sticky = document.createElement("div");
            sticky.className = "nb-sticky";
            const sHead = document.createElement("div");
            sHead.className = "nb-sticky-head";
            if (hosts.koharu && hosts.koharu.portrait) {
              const kImg = document.createElement("img");
              kImg.className = "nb-sticky-avatar";
              kImg.src = hosts.koharu.portrait;
              kImg.alt = hosts.koharu.name || "小春";
              kImg.loading = "lazy";
              sHead.appendChild(kImg);
            }
            const sTitle = document.createElement("span");
            sTitle.className = "nb-sticky-title";
            sTitle.textContent = "小春のこだいら発見メモ♪";
            sHead.appendChild(sTitle);
            sticky.appendChild(sHead);

            const sBody = document.createElement("div");
            sBody.className = "nb-sticky-body";
            appendHighlightedText(sBody, e.kodaira_discovery);
            sticky.appendChild(sBody);
            article.appendChild(sticky);
          }

          // Footer: keywords + doodle + episode link
          const foot = document.createElement("div");
          foot.className = "nb-page-foot";

          const kwWrap = document.createElement("div");
          kwWrap.className = "nb-kw-list";
          (e.keywords_featured || []).forEach(function (kw) {
            const chip = document.createElement("span");
            chip.className = "nb-kw-chip";
            chip.textContent = "# " + kw;
            kwWrap.appendChild(chip);
          });
          foot.appendChild(kwWrap);

          const footRight = document.createElement("div");
          footRight.className = "nb-foot-right";
          footRight.appendChild(createSvg(doodlePathsForDay(e.day_key), "0 0 24 24", "nb-doodle"));
          if (e.episode_href) {
            const link = document.createElement("a");
            link.className = "nb-listen-link";
            link.href = e.episode_href;
            link.textContent = "🎧 この回のラジオを聴く" + (e.duration_formatted ? "（" + e.duration_formatted + "）" : "") + " →";
            footRight.appendChild(link);
          }
          foot.appendChild(footRight);

          article.appendChild(foot);
          listEl.appendChild(article);
        });
      }

      document.getElementById("nb-search").addEventListener("input", function (ev) {
        searchQuery = ev.target.value.trim();
        renderPages();
      });

      const sortBtn = document.getElementById("nb-sort-btn");
      sortBtn.addEventListener("click", function () {
        sortNewestFirst = !sortNewestFirst;
        sortBtn.textContent = sortNewestFirst ? "新しい順 ↓" : "第1回から読む ↑";
        renderPages();
      });

      updateStats();
      renderPolaroids();
      renderGuestRally();
      renderTabs();
      renderPages();
    })();
  </script>
</body>
</html>
""")


def render_notebook_page(
    knowledge_log: dict[str, Any],
    bundles: list[dict[str, Any]],
    characters: dict[str, Any],
    themes: dict[str, Any],
    common_css: str,
    nav_html: str,
    safe_json_fn: Callable[[Any], str],
) -> str:
    """Render handwritten diary-style 防災ノート HTML page."""
    payload = _build_notebook_payload(knowledge_log, bundles, characters, themes)
    return NOTEBOOK_TEMPLATE.substitute(
        COMMON_CSS=common_css,
        NOTEBOOK_CSS=NOTEBOOK_CSS,
        NAV_HTML=nav_html,
        PAYLOAD_JSON=safe_json_fn(payload),
    )
