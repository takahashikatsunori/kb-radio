"""Render docs/listen.html: simplified listener-focused radio player & related links page."""

from __future__ import annotations

import html
from pathlib import Path
import re
from string import Template
from typing import Any, Callable

from site_share import (
    DEFAULT_HERO_ALT,
    DEFAULT_SITE_BASE_URL,
    build_episode_og_meta,
    clean_episode_headline,
    resolve_episode_image,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT_DIR / "docs"
DOCS_ASSETS_DIR = DOCS_DIR / "assets"
DOCS_CAST_ASSETS_DIR = DOCS_ASSETS_DIR / "cast"


def _resolve_hero_banner() -> str:
    """Return relative path to fixed cast group banner under docs/, with fallback."""
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".svg"):
        cand = DOCS_ASSETS_DIR / f"hero_cast_banner{ext}"
        if cand.exists() and cand.stat().st_size > 512:
            return f"assets/{cand.name}"
    if (DOCS_CAST_ASSETS_DIR / "koharu.jpg").exists():
        return "assets/cast/koharu.jpg"
    return ""


def _resolve_avatar(cast_id: str) -> str:
    """Return relative path to cast portrait under docs/ if available."""
    if not cast_id:
        return ""
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".svg"):
        cand = DOCS_CAST_ASSETS_DIR / f"{cast_id}{ext}"
        if cand.exists() and cand.stat().st_size > 256:
            return f"assets/cast/{cand.name}"
    return ""


def _format_date_labels(
    date_str: str,
    weekday_ja: str,
    is_latest: bool,
    is_spinoff: bool,
    spinoff_hint: str,
    latest_year: str,
) -> tuple[str, str]:
    """Return (display_date_label, select_option_label) in approachable Japanese."""
    w_short = (weekday_ja or "")[:1]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (date_str or "").strip())
    if m:
        yr, mo, dy = m.group(1), int(m.group(2)), int(m.group(3))
        base = f"{mo}月{dy}日（{w_short}）" if w_short else f"{mo}月{dy}日"
        if latest_year and yr != latest_year:
            base = f"{yr}年{base}"
    else:
        base = f"{date_str}（{w_short}）" if w_short else date_str

    if is_latest:
        select_label = f"{base} 最新"
    elif is_spinoff:
        suffix = f"：{spinoff_hint}" if spinoff_hint else ""
        select_label = f"{base} 特別編{suffix}"
    else:
        select_label = base

    return base, select_label


def _edition_tag(meta: dict[str, Any]) -> str:
    """Return a short human-friendly badge when the episode is a special edition."""
    if meta.get("is_spinoff"):
        return "特別編"
    if meta.get("is_holiday"):
        hname = str(meta.get("holiday_name") or "").strip()
        return f"{hname}15分版" if hname else "祝日15分版"
    if meta.get("special_feature"):
        return "特別拡大版"
    if meta.get("is_weekend"):
        return "週末15分版"
    return ""


def _spinoff_short_hint(theme_name: str) -> str:
    """Shorten spinoff theme name for compact <select> option display."""
    cleaned = re.sub(r"^スピンオフ特集[：:]\s*", "", (theme_name or "").strip())
    cleaned = re.sub(r"徹底ガイド$", "", cleaned).strip()
    return cleaned[:16]


def _build_listen_payload(
    bundles: list[dict[str, Any]],
    characters: dict[str, Any],
    themes: dict[str, Any],
    editorial_plan: dict[str, Any] | None = None,
    site_base_url: str = DEFAULT_SITE_BASE_URL,
    weekly_banners: dict[str, Any] | None = None,
    docs_dir: Path | None = None,
) -> dict[str, Any]:
    """Build compact episode + link payload ordered newest-first (latest regular episode at [0])."""
    ordered = list(reversed(bundles))
    latest_date = str(ordered[0]["episode"]["meta"].get("episode_date") or "") if ordered else ""
    latest_year = latest_date[:4] if len(latest_date) >= 4 else ""

    koharu_avatar = _resolve_avatar("koharu")
    heizo_avatar = _resolve_avatar("heizo")

    days_cfg = themes.get("days") or {}
    guest_ui_by_id: dict[str, dict[str, str]] = {}
    for cfg in days_cfg.values():
        g = cfg.get("guest") or {}
        if g.get("id") and g.get("ui"):
            guest_ui_by_id[str(g["id"])] = g["ui"]

    episodes_out: list[dict[str, Any]] = []
    for idx, b in enumerate(ordered):
        ep = b["episode"]
        mf = b["manifest"]
        meta = ep["meta"]
        mf_meta = mf["meta"]
        guest = ep.get("guest") or {}

        is_latest = idx == 0
        is_spinoff = bool(meta.get("is_spinoff"))
        theme_name = str(meta.get("theme_name") or "")
        date_str = str(meta.get("episode_date") or "")
        weekday_ja = str(meta.get("weekday_ja") or "")
        date_label, select_label = _format_date_labels(
            date_str=date_str,
            weekday_ja=weekday_ja,
            is_latest=is_latest,
            is_spinoff=is_spinoff,
            spinoff_hint=_spinoff_short_hint(theme_name),
            latest_year=latest_year,
        )

        guest_id = str(guest.get("id") or "")
        voice_guest_ui = (meta.get("voices") or {}).get("guest", {}).get("ui") or {}
        fallback_ui = guest_ui_by_id.get(guest_id) or {}
        accent_color = str(
            voice_guest_ui.get("color")
            or fallback_ui.get("color")
            or ("#1b5e3c" if is_spinoff else "#4338ca")
        )
        accent_bg = str(
            voice_guest_ui.get("bg_soft")
            or fallback_ui.get("bg_soft")
            or ("#e7f4ec" if is_spinoff else "#eef2ff")
        )

        segments_compact = [
            {
                "title": str(seg.get("title") or ""),
                "start_sec": float(seg.get("start_sec") or 0.0),
            }
            for seg in (mf.get("segments") or [])
        ]

        links_clean = [
            {
                "category": str(lk.get("category") or "関連ページ"),
                "title": str(lk.get("title") or lk.get("url") or ""),
                "url": str(lk.get("url") or ""),
                "note": str(lk.get("note") or ""),
            }
            for lk in (ep.get("links") or [])
            if lk.get("url")
        ]

        ep_img = resolve_episode_image(
            b,
            editorial_plan=editorial_plan,
            docs_dir=docs_dir,
            weekly_banners=weekly_banners,
        )

        episodes_out.append(
            {
                "slug": b["slug"],
                "date": date_str,
                "date_label": date_label,
                "select_label": select_label,
                "weekday_ja": weekday_ja,
                "weekday_short": (weekday_ja or "")[:1],
                "episode_label": str(meta.get("episode_label") or f"第{meta.get('episode_number', '')}回"),
                "is_latest": is_latest,
                "is_spinoff": is_spinoff,
                "edition_tag": _edition_tag(meta),
                "theme_name": theme_name,
                "headline": clean_episode_headline(str(meta.get("subtitle") or ""), fallback=theme_name),
                "guest_name": str(guest.get("name") or ""),
                "guest_title": str(guest.get("title") or ""),
                "guest_avatar": _resolve_avatar(guest_id),
                "koharu_avatar": koharu_avatar,
                "heizo_avatar": heizo_avatar,
                "accent_color": accent_color,
                "accent_bg": accent_bg,
                "hero_image": str(ep_img.get("rel_path") or ""),
                "hero_alt": str(ep_img.get("alt") or DEFAULT_HERO_ALT),
                "hero_spot_name": str(ep_img.get("spot_name") or ""),
                "hero_season_label": str(ep_img.get("season_label") or ""),
                "hero_caption": str(ep_img.get("caption") or ""),
                "share_rel_path": f"share/{b['slug']}/",
                "audio_src": f"audio/{meta['output_filename']}",
                "has_audio": bool(b["has_audio"]),
                "duration_sec": float(mf_meta.get("total_duration_sec") or 600.0),
                "duration_formatted": str(mf_meta.get("total_duration_formatted") or "10:00"),
                "detail_href": f"episodes/{b['slug']}/index.html",
                "segments": segments_compact,
                "links": links_clean,
            }
        )

    program = characters.get("program") or {}
    default_banner = _resolve_hero_banner()
    latest_ep = episodes_out[0] if episodes_out else {}
    latest_hero = str(latest_ep.get("hero_image") or "")
    return {
        "program_title": str(program.get("title") or "毎朝7時！こだいら防災＆まちラジオ"),
        "program_subtitle": "小春と平蔵、7人の専門家と聴く やさしい防災とまちの話題",
        "site_base_url": site_base_url,
        "default_banner": default_banner,
        "hero_banner": latest_hero or default_banner,
        "hero_alt": str(latest_ep.get("hero_alt") or DEFAULT_HERO_ALT),
        "hero_spot_name": str(latest_ep.get("hero_spot_name") or ""),
        "hero_caption": str(latest_ep.get("hero_caption") or ""),
        "episodes": episodes_out,
    }


LISTEN_CSS = """
:root {
  --forest: #1b5e3c;
  --forest-dark: #124028;
  --forest-soft: #e7f4ec;
  --paper: #f6f4ee;
  --card: #ffffff;
  --ink: #1f2937;
  --muted: #5b6472;
  --border: #e2e6df;
  --amber: #d97706;
  --amber-soft: #fef3c7;
  --ep-accent: #1b5e3c;
  --ep-accent-soft: #e7f4ec;
  --shadow: 0 8px 24px rgba(18, 64, 40, 0.08);
}

* { box-sizing: border-box; }
html, body {
  overflow-x: clip;
  max-width: 100%;
}
body {
  margin: 0;
  font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", system-ui, -apple-system, sans-serif;
  background: var(--paper);
  color: var(--ink);
  line-height: 1.6;
  -webkit-tap-highlight-color: transparent;
}

.listen-wrap {
  max-width: 720px;
  margin: 0 auto;
  padding: 0.9rem 0.85rem 2.2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 1. Fixed Top Hero Banner */
.hero-card {
  background: var(--forest-dark);
  border-radius: 20px;
  overflow: hidden;
  box-shadow: var(--shadow);
  border: 1px solid rgba(18, 64, 40, 0.14);
}
.hero-img-wrap {
  position: relative;
  background: #dff0e6;
  aspect-ratio: 16 / 9;
  overflow: hidden;
}
.hero-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  display: block;
  transition: opacity 0.2s ease;
}
.hero-spot-badge {
  position: absolute;
  right: 0.65rem;
  bottom: 0.65rem;
  max-width: calc(100% - 1.3rem);
  padding: 0.24rem 0.68rem;
  border-radius: 999px;
  background: rgba(18, 64, 40, 0.82);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #ffffff;
  font-size: 0.74rem;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
}
.hero-spot-badge[hidden] {
  display: none;
}
.hero-plate {
  background: linear-gradient(135deg, var(--forest-dark) 0%, var(--forest) 68%, #266b47 100%);
  border-top: 3px solid var(--amber);
  color: #ffffff;
  padding: 0.95rem 1.15rem 1.05rem;
}
.hero-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.42rem;
}
.pill-morning {
  display: inline-flex;
  align-items: center;
  font-size: 0.74rem;
  font-weight: 800;
  padding: 0.16rem 0.6rem;
  border-radius: 999px;
  background: var(--amber);
  color: #ffffff;
  letter-spacing: 0.02em;
}
.pill-city {
  display: inline-flex;
  align-items: center;
  font-size: 0.74rem;
  font-weight: 700;
  padding: 0.16rem 0.58rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  color: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.24);
}
.hero-title {
  margin: 0;
  font-size: clamp(1.2rem, 4.8vw, 1.56rem);
  font-weight: 800;
  line-height: 1.28;
  letter-spacing: 0.01em;
}
.hero-sub {
  margin: 0.28rem 0 0;
  font-size: clamp(0.82rem, 3.2vw, 0.92rem);
  color: rgba(255, 255, 255, 0.9);
  line-height: 1.48;
}

/* Shared card */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  overflow: hidden;
}

/* 2. Middle Player Section */
.player-section {
  border-top: 4px solid var(--ep-accent);
  transition: border-color 0.2s ease;
}

.day-switcher-wrap {
  padding: 0.8rem 0.95rem 0.72rem;
  background: #fafaf7;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.day-switcher {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 0.45rem;
  align-items: center;
}
.day-nav-btn {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  min-height: 42px;
  padding: 0.45rem 0.78rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #ffffff;
  color: var(--ink);
  font-size: 0.82rem;
  font-weight: 700;
  white-space: nowrap;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.day-nav-btn:hover:not(:disabled) {
  background: var(--forest-soft);
  border-color: var(--forest);
  color: var(--forest-dark);
}
.day-nav-btn:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}
.day-select-wrap {
  position: relative;
  min-width: 0;
}
.day-select {
  appearance: none;
  -webkit-appearance: none;
  width: 100%;
  min-height: 42px;
  padding: 0.48rem 2.15rem 0.48rem 0.85rem;
  border-radius: 999px;
  border: 1.5px solid #cfd6ce;
  background-color: #ffffff;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%231b5e3c' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.78rem center;
  background-size: 16px 16px;
  font-family: inherit;
  font-size: 0.9rem;
  font-weight: 800;
  color: var(--forest-dark);
  text-overflow: ellipsis;
  cursor: pointer;
}
.day-select:focus {
  outline: 2px solid var(--forest);
  outline-offset: 1px;
  border-color: var(--forest);
}
.latest-jump-wrap {
  display: none;
  justify-content: center;
}
.latest-jump-wrap.is-visible {
  display: flex;
}
.btn-go-latest {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid rgba(27, 94, 60, 0.28);
  background: var(--forest-soft);
  color: var(--forest-dark);
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.28rem 0.8rem;
  border-radius: 999px;
}
.btn-go-latest:hover {
  background: #d3ebdc;
}

/* Selected Episode Concise Summary */
.ep-summary {
  padding: 0.9rem 1.05rem 0.55rem;
  display: flex;
  align-items: center;
  gap: 0.8rem;
}
.ep-avatar-box {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
}
.ep-avatar {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  object-fit: cover;
  object-position: center top;
  border: 2.5px solid var(--ep-accent);
  background: var(--ep-accent-soft);
  display: block;
}
.ep-avatar-pair {
  display: flex;
  align-items: center;
}
.ep-avatar-pair img {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  object-position: center top;
  border: 2px solid #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.14);
}
.ep-avatar-pair img + img {
  margin-left: -12px;
}
.ep-info {
  min-width: 0;
  flex: 1 1 auto;
}
.ep-meta-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.28rem;
}
.ep-theme-pill {
  display: inline-block;
  font-size: 0.74rem;
  font-weight: 800;
  padding: 0.14rem 0.56rem;
  border-radius: 999px;
  background: var(--ep-accent-soft);
  color: var(--ep-accent);
  max-width: 100%;
  overflow-wrap: anywhere;
}
.ep-guest-name {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--muted);
}
.ep-edition-pill {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.12rem 0.5rem;
  border-radius: 999px;
  background: var(--amber-soft);
  color: #92400e;
}
.ep-headline {
  margin: 0;
  font-size: clamp(1rem, 3.9vw, 1.18rem);
  font-weight: 800;
  line-height: 1.42;
  color: var(--ink);
  overflow-wrap: anywhere;
}

/* Player controls */
.player-body {
  padding: 0.45rem 1.05rem 1.05rem;
}
.audio-pending-banner {
  display: none;
  background: var(--amber-soft);
  border: 1px solid #f59e0b;
  color: #92400e;
  border-radius: 10px;
  padding: 0.55rem 0.75rem;
  font-size: 0.82rem;
  margin-bottom: 0.6rem;
}
.now-corner {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 0.25rem;
  min-height: 1.3em;
}
.now-corner.is-playing {
  color: var(--forest-dark);
}
.scrubber {
  width: 100%;
  accent-color: var(--forest);
  cursor: pointer;
  height: 28px;
  margin: 0;
  display: block;
}
.time-row {
  display: flex;
  justify-content: space-between;
  font-variant-numeric: tabular-nums;
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--muted);
  margin: 0.08rem 0 0.72rem;
}
.transport-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
}
.btn-seek {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  min-height: 46px;
  padding: 0.5rem 0.92rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #f9faf8;
  color: var(--ink);
  font-size: 0.86rem;
  font-weight: 700;
  white-space: nowrap;
  transition: background 0.15s, border-color 0.15s;
}
.btn-seek:hover:not(:disabled) {
  background: var(--forest-soft);
  border-color: var(--forest);
  color: var(--forest-dark);
}
.btn-play-main {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  min-height: 54px;
  min-width: 162px;
  padding: 0.68rem 1.45rem;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, var(--forest) 0%, var(--forest-dark) 100%);
  color: #ffffff;
  font-size: 1rem;
  font-weight: 800;
  box-shadow: 0 6px 16px rgba(27, 94, 60, 0.28);
  white-space: nowrap;
  transition: transform 0.1s ease, filter 0.15s ease;
}
.btn-play-main:hover:not(:disabled) {
  filter: brightness(1.06);
}
.btn-play-main:active:not(:disabled) {
  transform: scale(0.98);
}
.btn-seek:disabled,
.btn-play-main:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  box-shadow: none;
}
.speed-row {
  margin-top: 0.65rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.btn-speed {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid var(--border);
  background: #ffffff;
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.3rem 0.85rem;
  border-radius: 999px;
  min-height: 34px;
}
.btn-speed:hover {
  border-color: var(--forest);
  color: var(--forest-dark);
  background: var(--forest-soft);
}
.btn-share-trigger {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.36rem;
  border: 1px solid rgba(27, 94, 60, 0.34);
  background: var(--forest-soft);
  color: var(--forest-dark);
  font-size: 0.78rem;
  font-weight: 800;
  padding: 0.3rem 0.88rem;
  border-radius: 999px;
  min-height: 34px;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.btn-share-trigger:hover,
.btn-share-trigger[aria-expanded="true"] {
  background: var(--forest);
  border-color: var(--forest);
  color: #ffffff;
}
.share-icon {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
}
.share-panel {
  margin-top: 0.72rem;
  padding: 0.75rem 0.85rem;
  border-radius: 14px;
  border: 1px solid #d5e2d8;
  background: #f8faf7;
}
.share-panel[hidden] {
  display: none;
}
.share-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.55rem;
}
.share-panel-title {
  font-size: 0.82rem;
  font-weight: 800;
  color: var(--forest-dark);
  min-width: 0;
  overflow-wrap: anywhere;
}
.share-panel-close {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #ffffff;
  color: var(--muted);
  font-size: 1rem;
  font-weight: 700;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}
.share-panel-close:hover {
  border-color: var(--forest);
  color: var(--forest-dark);
}
.share-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.share-btn {
  appearance: none;
  font-family: inherit;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  min-height: 40px;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 800;
  white-space: nowrap;
  border: 1px solid transparent;
  transition: filter 0.15s, background 0.15s, border-color 0.15s;
}
.share-btn[hidden] {
  display: none;
}
.share-btn-native {
  background: var(--forest);
  color: #ffffff;
}
.share-btn-line {
  background: #06c755;
  color: #ffffff;
}
.share-btn-x {
  background: #111827;
  color: #ffffff;
}
.share-btn-copy {
  background: #ffffff;
  color: var(--forest-dark);
  border-color: rgba(27, 94, 60, 0.35);
}
.share-btn-native:hover,
.share-btn-line:hover,
.share-btn-x:hover {
  filter: brightness(1.07);
}
.share-btn-copy:hover {
  background: var(--forest-soft);
  border-color: var(--forest);
}
.share-feedback {
  margin-top: 0.45rem;
  min-height: 1.2em;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--forest-dark);
  text-align: center;
}
.share-feedback:empty {
  display: none;
}

/* 3. Bottom Related Pages Section */
.links-head {
  padding: 0.82rem 1.05rem;
  background: #fafaf7;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.links-head-title {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 800;
  color: var(--forest-dark);
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.links-count {
  font-size: 0.74rem;
  font-weight: 800;
  padding: 0.12rem 0.5rem;
  border-radius: 999px;
  background: var(--forest-soft);
  color: var(--forest-dark);
}
.links-hint {
  font-size: 0.76rem;
  color: var(--muted);
  white-space: nowrap;
}
.links-list {
  padding: 0.85rem 0.95rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.links-list.is-switching {
  animation: fadeSwap 0.24s ease;
}
@keyframes fadeSwap {
  from { opacity: 0.45; transform: translateY(3px); }
  to { opacity: 1; transform: translateY(0); }
}
.related-link {
  display: block;
  text-decoration: none;
  color: inherit;
  padding: 0.82rem 0.92rem;
  border-radius: 13px;
  border: 1px solid var(--border);
  background: #fcfcfa;
  transition: border-color 0.15s, background 0.15s, transform 0.12s;
}
.related-link:hover {
  border-color: var(--forest);
  background: var(--forest-soft);
  transform: translateY(-1px);
}
.link-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
  margin-bottom: 0.24rem;
}
.link-cat {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.12rem 0.52rem;
  border-radius: 999px;
  background: var(--forest-soft);
  color: var(--forest-dark);
}
.link-ext {
  font-size: 0.82rem;
  font-weight: 800;
  color: var(--forest);
  flex: 0 0 auto;
}
.link-title {
  font-size: 0.95rem;
  font-weight: 800;
  color: var(--forest-dark);
  line-height: 1.4;
  margin: 0 0 0.22rem;
  overflow-wrap: anywhere;
}
.link-note {
  font-size: 0.82rem;
  color: var(--muted);
  margin: 0;
  line-height: 1.52;
  overflow-wrap: anywhere;
}
.links-empty {
  margin: 0;
  padding: 0.8rem 0.4rem;
  text-align: center;
  font-size: 0.86rem;
  color: var(--muted);
}

/* 4. Detailed Homepage Exit Card */
.more-card {
  background: linear-gradient(135deg, #f2f8f4 0%, #ffffff 100%);
  border: 1px solid #cfe2d5;
  border-radius: 18px;
  padding: 1rem 1.05rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.65rem;
  box-shadow: 0 4px 14px rgba(18, 64, 40, 0.05);
}
.more-desc {
  margin: 0;
  font-size: 0.84rem;
  color: var(--ink);
  line-height: 1.58;
  max-width: 540px;
}
.more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  background: #ffffff;
  color: var(--forest-dark);
  border: 1.5px solid var(--forest);
  border-radius: 999px;
  padding: 0.56rem 1.25rem;
  font-size: 0.88rem;
  font-weight: 800;
  min-height: 42px;
  transition: background 0.15s, color 0.15s;
}
.more-btn:hover {
  background: var(--forest);
  color: #ffffff;
}
.ep-detail-link {
  display: none;
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--forest);
  text-decoration: none;
}
.ep-detail-link.is-visible {
  display: inline-block;
}
.ep-detail-link:hover {
  text-decoration: underline;
}

.listen-footer {
  text-align: center;
  font-size: 0.76rem;
  color: var(--muted);
  padding: 0.25rem 0 0.5rem;
}

@media (max-width: 480px) {
  .listen-wrap {
    padding: 0.65rem 0.65rem 1.8rem;
    gap: 0.82rem;
  }
  .hero-plate {
    padding: 0.82rem 0.95rem 0.9rem;
  }
  .day-switcher-wrap {
    padding: 0.68rem 0.72rem 0.62rem;
  }
  .day-switcher {
    gap: 0.34rem;
  }
  .day-nav-btn {
    padding: 0.42rem 0.56rem;
    font-size: 0.77rem;
  }
  .day-select {
    font-size: 0.84rem;
    padding: 0.44rem 1.85rem 0.44rem 0.68rem;
  }
  .ep-summary {
    padding: 0.78rem 0.85rem 0.48rem;
    gap: 0.68rem;
  }
  .ep-avatar {
    width: 46px;
    height: 46px;
  }
  .player-body {
    padding: 0.4rem 0.85rem 0.92rem;
  }
  .transport-row {
    gap: 0.48rem;
  }
  .btn-seek {
    padding: 0.46rem 0.76rem;
    font-size: 0.82rem;
  }
  .btn-play-main {
    min-width: 146px;
    padding: 0.62rem 1.2rem;
    font-size: 0.94rem;
  }
  .links-head {
    padding: 0.75rem 0.88rem;
  }
  .links-list {
    padding: 0.72rem 0.75rem 0.82rem;
  }
  .share-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
"""


LISTEN_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>毎朝7時！こだいら防災＆まちラジオ（リスナー向けプレーヤー）</title>
  $OG_META_HTML
  <style>
    $LISTEN_CSS
  </style>
</head>
<body>
  <main class="listen-wrap">
    <!-- 1. Fixed Main Title Banner -->
    <header class="hero-card">
      $HERO_IMAGE_HTML
      <div class="hero-plate">
        <div class="hero-pills">
          <span class="pill-morning">毎朝7時放送</span>
          <span class="pill-city">東京都小平市</span>
        </div>
        <h1 class="hero-title">$PROGRAM_TITLE</h1>
        <p class="hero-sub">$PROGRAM_SUBTITLE</p>
      </div>
    </header>

    <!-- 2. Day Switcher & Radio Player -->
    <section class="card player-section" id="player-section" aria-label="放送プレーヤー">
      <div class="day-switcher-wrap">
        <div class="day-switcher">
          <button type="button" class="day-nav-btn" id="btn-prev-ep" aria-label="前の日の放送へ">‹ 前の回</button>
          <div class="day-select-wrap">
            <select class="day-select" id="episode-select" aria-label="聴く放送日を選ぶ"></select>
          </div>
          <button type="button" class="day-nav-btn" id="btn-next-ep" aria-label="次の日の放送へ">次の回 ›</button>
        </div>
        <div class="latest-jump-wrap" id="latest-jump-wrap">
          <button type="button" class="btn-go-latest" id="btn-go-latest">最新の放送に戻る</button>
        </div>
      </div>

      <div class="ep-summary">
        <div class="ep-avatar-box" id="ep-avatar-box"></div>
        <div class="ep-info">
          <div class="ep-meta-pills">
            <span class="ep-theme-pill" id="ep-theme-pill"></span>
            <span class="ep-guest-name" id="ep-guest-name"></span>
            <span class="ep-edition-pill" id="ep-edition-pill" style="display:none;"></span>
          </div>
          <h2 class="ep-headline" id="ep-headline"></h2>
        </div>
      </div>

      <div class="player-body">
        <div id="audio-pending" class="audio-pending-banner">
          この回の音声ファイルはまだ準備中です。下の関連ページはそのままご覧いただけます。
        </div>
        <audio id="radio-audio" preload="metadata"></audio>
        <div class="now-corner" id="now-corner" aria-live="polite">ボタンを押してお聴きください</div>
        <input type="range" class="scrubber" id="scrubber" min="0" max="100" step="0.1" value="0" aria-label="再生位置" />
        <div class="time-row">
          <span id="time-current">00:00</span>
          <span id="time-total">00:00</span>
        </div>
        <div class="transport-row">
          <button type="button" class="btn-seek" id="btn-back" aria-label="15秒戻る">-15秒</button>
          <button type="button" class="btn-play-main" id="btn-play">▶ 放送を聴く</button>
          <button type="button" class="btn-seek" id="btn-fwd" aria-label="15秒進む">+15秒</button>
        </div>
        <div class="speed-row">
          <button type="button" class="btn-speed" id="btn-speed">再生速度 1.0x</button>
          <button type="button" class="btn-share-trigger" id="btn-share-toggle" aria-expanded="false" aria-controls="share-panel">
            <svg class="share-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
            <span>この回をシェア</span>
          </button>
        </div>
        <div class="share-panel" id="share-panel" hidden>
          <div class="share-panel-head">
            <span class="share-panel-title" id="share-panel-title">この回をシェア</span>
            <button type="button" class="share-panel-close" id="btn-share-close" aria-label="シェアメニューを閉じる">×</button>
          </div>
          <div class="share-actions">
            <button type="button" class="share-btn share-btn-native" id="btn-share-native" hidden>他のアプリで共有</button>
            <a class="share-btn share-btn-line" id="btn-share-line" href="#" target="_blank" rel="noopener noreferrer">LINEで送る</a>
            <a class="share-btn share-btn-x" id="btn-share-x" href="#" target="_blank" rel="noopener noreferrer">Xでシェア</a>
            <button type="button" class="share-btn share-btn-copy" id="btn-share-copy">URLをコピー</button>
          </div>
          <div class="share-feedback" id="share-feedback" aria-live="polite"></div>
        </div>
      </div>
    </section>

    <!-- 3. Related Pages for Selected Day -->
    <section class="card links-section" aria-label="関連ページ">
      <div class="links-head">
        <h2 class="links-head-title">
          <span>この日の関連ページ</span>
          <span class="links-count" id="links-count">0件</span>
        </h2>
        <span class="links-hint">タップで外部サイトへ</span>
      </div>
      <div class="links-list" id="links-list"></div>
    </section>

    <!-- 4. Link to Detailed Homepage -->
    <section class="more-card" aria-label="詳しいホームページへの案内">
      <p class="more-desc">
        文字起こし台本・防災ノート・出演者紹介・放送カレンダー・番組のしくみなど、もっと詳しく知りたい方はこちら
      </p>
      <a class="more-btn" href="index.html">くわしいホームページを見る →</a>
      <a class="ep-detail-link" id="ep-detail-link" href="index.html"></a>
    </section>

    <footer class="listen-footer">
      毎朝7時！こだいら防災＆まちラジオ（東京都小平市）
    </footer>
  </main>

  <script type="application/json" id="listen-data">$PAYLOAD_JSON</script>
  <script>
    (function () {
      const payload = JSON.parse(document.getElementById("listen-data").textContent);
      const episodes = payload.episodes || [];
      if (episodes.length === 0) return;

      const rootEl = document.documentElement;
      const heroImg = document.getElementById("hero-img");
      const heroSpotBadge = document.getElementById("hero-spot-badge");
      if (heroImg) {
        heroImg.addEventListener("error", () => {
          const fallback = payload.default_banner || "";
          const curAttr = heroImg.getAttribute("src") || "";
          if (fallback && curAttr !== fallback && heroImg.dataset.fallbackTried !== fallback) {
            heroImg.dataset.fallbackTried = fallback;
            heroImg.setAttribute("src", fallback);
          }
        });
      }
      const audio = document.getElementById("radio-audio");
      const btnPrev = document.getElementById("btn-prev-ep");
      const btnNext = document.getElementById("btn-next-ep");
      const epSelect = document.getElementById("episode-select");
      const latestJumpWrap = document.getElementById("latest-jump-wrap");
      const btnGoLatest = document.getElementById("btn-go-latest");

      const avatarBox = document.getElementById("ep-avatar-box");
      const themePill = document.getElementById("ep-theme-pill");
      const guestNameEl = document.getElementById("ep-guest-name");
      const editionPill = document.getElementById("ep-edition-pill");
      const headlineEl = document.getElementById("ep-headline");

      const audioPending = document.getElementById("audio-pending");
      const nowCorner = document.getElementById("now-corner");
      const scrubber = document.getElementById("scrubber");
      const timeCurrent = document.getElementById("time-current");
      const timeTotal = document.getElementById("time-total");
      const btnPlay = document.getElementById("btn-play");
      const btnBack = document.getElementById("btn-back");
      const btnFwd = document.getElementById("btn-fwd");
      const btnSpeed = document.getElementById("btn-speed");
      const btnShareToggle = document.getElementById("btn-share-toggle");
      const sharePanel = document.getElementById("share-panel");
      const sharePanelTitle = document.getElementById("share-panel-title");
      const btnShareClose = document.getElementById("btn-share-close");
      const btnShareNative = document.getElementById("btn-share-native");
      const btnShareLine = document.getElementById("btn-share-line");
      const btnShareX = document.getElementById("btn-share-x");
      const btnShareCopy = document.getElementById("btn-share-copy");
      const shareFeedback = document.getElementById("share-feedback");

      const linksCount = document.getElementById("links-count");
      const linksList = document.getElementById("links-list");
      const epDetailLink = document.getElementById("ep-detail-link");

      const SPEED_RATES = [1.0, 1.25, 1.5, 0.9];
      const SPEED_STORAGE_KEY = "kb_radio_listen_speed";
      let speedIdx = 0;
      let currentIdx = 0;
      let isScrubbing = false;
      let copyTimer = null;

      if (btnShareNative && typeof navigator.share === "function") {
        btnShareNative.hidden = false;
      }

      function buildShareInfo(ep) {
        const relPath = ep.share_rel_path || ("share/" + ep.slug + "/");
        let shareUrl = "";
        if (window.location.protocol === "http:" || window.location.protocol === "https:") {
          try {
            shareUrl = new URL(relPath, window.location.href).toString();
          } catch (_) {}
        }
        if (!shareUrl) {
          let cleanBase = payload.site_base_url || "";
          while (cleanBase.endsWith("/")) cleanBase = cleanBase.slice(0, -1);
          let cleanRel = relPath;
          while (cleanRel.startsWith("/")) cleanRel = cleanRel.slice(1);
          shareUrl = cleanBase ? (cleanBase + "/" + cleanRel) : relPath;
        }
        const prefix = ep.is_spinoff ? ("特別編・" + ep.date_label) : ep.date_label;
        const rawHeadline = ep.headline || ep.theme_name || "";
        const shortHeadline = rawHeadline.length > 72 ? (rawHeadline.slice(0, 71) + "…") : rawHeadline;
        const shareText = "【" + prefix + "】" + shortHeadline + "｜" + (payload.program_title || "毎朝7時！こだいら防災＆まちラジオ");
        const shareTitle = "【" + prefix + "】" + rawHeadline;
        return {
          url: shareUrl,
          text: shareText,
          title: shareTitle,
          label: prefix + "の回をシェア"
        };
      }

      function copyToClipboard(text) {
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
          return navigator.clipboard.writeText(text);
        }
        return new Promise((resolve, reject) => {
          try {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.top = "-9999px";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            const ok = document.execCommand("copy");
            document.body.removeChild(ta);
            if (ok) resolve();
            else reject(new Error("copy failed"));
          } catch (err) {
            reject(err);
          }
        });
      }

      function setShareFeedback(msg) {
        if (shareFeedback) shareFeedback.textContent = msg || "";
      }

      function closeSharePanel() {
        if (!sharePanel || !btnShareToggle) return;
        sharePanel.hidden = true;
        btnShareToggle.setAttribute("aria-expanded", "false");
      }

      function updateShareUI(ep) {
        if (!ep) return;
        const info = buildShareInfo(ep);
        if (sharePanelTitle) sharePanelTitle.textContent = info.label;
        if (btnShareLine) {
          btnShareLine.href = "https://social-plugins.line.me/lineit/share?url=" + encodeURIComponent(info.url) + "&text=" + encodeURIComponent(info.text);
        }
        if (btnShareX) {
          btnShareX.href = "https://x.com/intent/tweet?text=" + encodeURIComponent(info.text) + "&url=" + encodeURIComponent(info.url);
        }
        if (copyTimer) {
          clearTimeout(copyTimer);
          copyTimer = null;
        }
        if (btnShareCopy) btnShareCopy.textContent = "URLをコピー";
        setShareFeedback("");
      }

      try {
        const saved = parseFloat(localStorage.getItem(SPEED_STORAGE_KEY) || "");
        const found = SPEED_RATES.indexOf(saved);
        if (found >= 0) speedIdx = found;
      } catch (_) {}

      function fmtTime(sec) {
        const s = Math.max(0, Math.floor(sec || 0));
        return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
      }

      function applySpeed(rate) {
        audio.playbackRate = rate;
        btnSpeed.textContent = "再生速度 " + rate + "x";
        try {
          localStorage.setItem(SPEED_STORAGE_KEY, String(rate));
        } catch (_) {}
      }

      function populateSelect() {
        epSelect.innerHTML = "";
        episodes.forEach((ep, idx) => {
          const opt = document.createElement("option");
          opt.value = String(idx);
          opt.textContent = ep.select_label;
          epSelect.appendChild(opt);
        });
      }

      function renderAvatars(ep) {
        avatarBox.innerHTML = "";
        if (!ep.is_spinoff && ep.guest_avatar) {
          const img = document.createElement("img");
          img.className = "ep-avatar";
          img.src = ep.guest_avatar;
          img.alt = ep.guest_name || "出演者";
          avatarBox.appendChild(img);
          return;
        }
        if (ep.koharu_avatar || ep.heizo_avatar) {
          const pair = document.createElement("div");
          pair.className = "ep-avatar-pair";
          if (ep.koharu_avatar) {
            const k = document.createElement("img");
            k.src = ep.koharu_avatar;
            k.alt = "小春";
            pair.appendChild(k);
          }
          if (ep.heizo_avatar) {
            const h = document.createElement("img");
            h.src = ep.heizo_avatar;
            h.alt = "平蔵";
            pair.appendChild(h);
          }
          avatarBox.appendChild(pair);
        }
      }

      function renderLinks(ep, animate) {
        const links = ep.links || [];
        linksCount.textContent = links.length + "件";
        linksList.innerHTML = "";

        if (animate) {
          linksList.classList.remove("is-switching");
          void linksList.offsetWidth;
          linksList.classList.add("is-switching");
        }

        if (links.length === 0) {
          const p = document.createElement("p");
          p.className = "links-empty";
          p.textContent = "この回の関連ページはありません。";
          linksList.appendChild(p);
          return;
        }

        links.forEach((lk) => {
          const a = document.createElement("a");
          a.className = "related-link";
          a.href = lk.url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";

          const top = document.createElement("div");
          top.className = "link-top";
          const cat = document.createElement("span");
          cat.className = "link-cat";
          cat.textContent = lk.category || "関連ページ";
          const ext = document.createElement("span");
          ext.className = "link-ext";
          ext.setAttribute("aria-hidden", "true");
          ext.textContent = "↗";
          top.appendChild(cat);
          top.appendChild(ext);

          const title = document.createElement("h3");
          title.className = "link-title";
          title.textContent = lk.title || lk.url;

          a.appendChild(top);
          a.appendChild(title);

          if (lk.note) {
            const note = document.createElement("p");
            note.className = "link-note";
            note.textContent = lk.note;
            a.appendChild(note);
          }
          linksList.appendChild(a);
        });
      }

      function resolveAbsoluteAssetUrl(relPath) {
        if (!relPath) return "";
        try {
          return new URL(relPath, window.location.href).toString();
        } catch (_) {
          let base = String(payload.site_base_url || "");
          while (base.endsWith("/")) base = base.slice(0, -1);
          let rel = String(relPath);
          while (rel.startsWith("/")) rel = rel.slice(1);
          return base ? (base + "/" + rel) : rel;
        }
      }

      function updateMediaSession(ep) {
        if (!("mediaSession" in navigator)) return;
        try {
          const artRel = ep.hero_image || payload.default_banner || payload.hero_banner || "";
          const artUrl = resolveAbsoluteAssetUrl(artRel);
          const metaInit = {
            title: ep.headline || ep.theme_name,
            artist: payload.program_title || "こだいら防災＆まちラジオ",
            album: ep.date_label
          };
          if (artUrl) {
            const artType = artRel.endsWith(".png")
              ? "image/png"
              : (artRel.endsWith(".webp") ? "image/webp" : "image/jpeg");
            metaInit.artwork = [{ src: artUrl, sizes: "1376x768", type: artType }];
          }
          navigator.mediaSession.metadata = new MediaMetadata(metaInit);
        } catch (_) {}
      }

      function updateCornerAndTime() {
        const ep = episodes[currentIdx];
        const estTotal = ep.duration_sec || 600;
        const total = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : estTotal;
        const cur = audio.currentTime || 0;

        if (!isScrubbing) {
          scrubber.max = String(total);
          scrubber.value = String(cur);
        }
        timeCurrent.textContent = fmtTime(cur);
        timeTotal.textContent = fmtTime(total);

        const segs = ep.segments || [];
        if ((!audio.paused || cur > 0.5) && segs.length > 0) {
          let active = segs[0];
          for (let i = 0; i < segs.length; i++) {
            if (cur >= segs[i].start_sec) active = segs[i];
          }
          nowCorner.textContent = "♪ " + active.title;
          nowCorner.classList.add("is-playing");
        } else {
          nowCorner.textContent = ep.has_audio ? "ボタンを押してお聴きください" : "音声準備中です";
          nowCorner.classList.remove("is-playing");
        }
      }

      function selectEpisode(idx, opts) {
        const options = opts || {};
        if (idx < 0 || idx >= episodes.length) return;
        currentIdx = idx;
        const ep = episodes[idx];

        audio.pause();
        isScrubbing = false;

        rootEl.style.setProperty("--ep-accent", ep.accent_color || "#1b5e3c");
        rootEl.style.setProperty("--ep-accent-soft", ep.accent_bg || "#e7f4ec");

        epSelect.value = String(idx);
        btnPrev.disabled = idx >= episodes.length - 1;
        btnNext.disabled = idx <= 0;
        latestJumpWrap.classList.toggle("is-visible", idx > 0);

        renderAvatars(ep);
        themePill.textContent = ep.theme_name;
        guestNameEl.textContent = ep.guest_name ? ("ゲスト: " + ep.guest_name) : "小春＆平蔵";
        if (ep.edition_tag) {
          editionPill.textContent = ep.edition_tag;
          editionPill.style.display = "inline-block";
        } else {
          editionPill.style.display = "none";
        }
        headlineEl.textContent = ep.headline;

        if (ep.has_audio) {
          audioPending.style.display = "none";
          audio.src = ep.audio_src;
          audio.currentTime = 0;
          btnPlay.disabled = false;
          btnBack.disabled = false;
          btnFwd.disabled = false;
          scrubber.disabled = false;
          btnPlay.textContent = "▶ 放送を聴く";
        } else {
          audioPending.style.display = "block";
          audio.removeAttribute("src");
          audio.load();
          btnPlay.disabled = true;
          btnBack.disabled = true;
          btnFwd.disabled = true;
          scrubber.disabled = true;
          btnPlay.textContent = "音声準備中";
        }

        scrubber.max = String(ep.duration_sec || 600);
        scrubber.value = "0";
        timeCurrent.textContent = "00:00";
        timeTotal.textContent = fmtTime(ep.duration_sec || 600);
        nowCorner.textContent = ep.has_audio ? "ボタンを押してお聴きください" : "音声準備中です";
        nowCorner.classList.remove("is-playing");

        applySpeed(SPEED_RATES[speedIdx]);
        renderLinks(ep, Boolean(options.animate));

        if (!ep.is_latest && ep.detail_href) {
          epDetailLink.href = ep.detail_href;
          epDetailLink.textContent = "この日（" + ep.date_label + "）の台本・詳細ページを見る →";
          epDetailLink.classList.add("is-visible");
        } else {
          epDetailLink.classList.remove("is-visible");
        }

        updateMediaSession(ep);
        if (heroImg) {
          const nextImg = ep.hero_image || payload.default_banner || payload.hero_banner || "";
          if (nextImg && heroImg.getAttribute("src") !== nextImg) {
            heroImg.dataset.fallbackTried = "";
            heroImg.setAttribute("src", nextImg);
          }
          if (ep.hero_alt) {
            heroImg.setAttribute("alt", ep.hero_alt);
          }
        }
        if (heroSpotBadge) {
          const spotText = (ep.hero_caption || ep.hero_spot_name || "").trim();
          if (spotText) {
            heroSpotBadge.textContent = "📍 " + spotText;
            heroSpotBadge.hidden = false;
          } else {
            heroSpotBadge.textContent = "";
            heroSpotBadge.hidden = true;
          }
        }
        document.title = ep.date_label + " " + (ep.headline || ep.theme_name) + " | " + (payload.program_title || "毎朝7時！こだいら防災＆まちラジオ");
        updateShareUI(ep);

        if (options.updateUrl) {
          try {
            const url = new URL(window.location.href);
            if (idx === 0) {
              url.searchParams.delete("ep");
            } else {
              url.searchParams.set("ep", ep.slug);
            }
            window.history.replaceState(null, "", url.toString());
          } catch (_) {}
        }
      }

      btnPrev.addEventListener("click", () => {
        if (currentIdx < episodes.length - 1) {
          selectEpisode(currentIdx + 1, { animate: true, updateUrl: true });
        }
      });
      btnNext.addEventListener("click", () => {
        if (currentIdx > 0) {
          selectEpisode(currentIdx - 1, { animate: true, updateUrl: true });
        }
      });
      epSelect.addEventListener("change", () => {
        const idx = parseInt(epSelect.value, 10);
        if (!Number.isNaN(idx)) {
          selectEpisode(idx, { animate: true, updateUrl: true });
        }
      });
      btnGoLatest.addEventListener("click", () => {
        selectEpisode(0, { animate: true, updateUrl: true });
      });

      btnPlay.addEventListener("click", () => {
        const ep = episodes[currentIdx];
        if (!ep || !ep.has_audio) return;
        if (audio.paused) {
          audio.playbackRate = SPEED_RATES[speedIdx];
          audio.play().catch(() => {});
        } else {
          audio.pause();
        }
      });
      btnBack.addEventListener("click", () => {
        const ep = episodes[currentIdx];
        if (!ep || !ep.has_audio) return;
        audio.currentTime = Math.max(0, audio.currentTime - 15);
        updateCornerAndTime();
      });
      btnFwd.addEventListener("click", () => {
        const ep = episodes[currentIdx];
        if (!ep || !ep.has_audio) return;
        const total = Number.isFinite(audio.duration) ? audio.duration : (ep.duration_sec || 600);
        audio.currentTime = Math.min(total, audio.currentTime + 15);
        updateCornerAndTime();
      });
      btnSpeed.addEventListener("click", () => {
        speedIdx = (speedIdx + 1) % SPEED_RATES.length;
        applySpeed(SPEED_RATES[speedIdx]);
      });

      if (btnShareToggle && sharePanel) {
        btnShareToggle.addEventListener("click", () => {
          const nextHidden = !sharePanel.hidden;
          sharePanel.hidden = nextHidden;
          btnShareToggle.setAttribute("aria-expanded", nextHidden ? "false" : "true");
        });
      }
      if (btnShareClose) {
        btnShareClose.addEventListener("click", closeSharePanel);
      }
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && sharePanel && !sharePanel.hidden) {
          closeSharePanel();
        }
      });
      if (btnShareCopy) {
        btnShareCopy.addEventListener("click", () => {
          const ep = episodes[currentIdx];
          if (!ep) return;
          const info = buildShareInfo(ep);
          copyToClipboard(info.url).then(() => {
            btnShareCopy.textContent = "✓ コピーしました";
            setShareFeedback("この回のURLをコピーしました");
            if (copyTimer) clearTimeout(copyTimer);
            copyTimer = setTimeout(() => {
              btnShareCopy.textContent = "URLをコピー";
            }, 2200);
          }).catch(() => {
            setShareFeedback("コピーできませんでした。URL欄から直接コピーしてください");
          });
        });
      }
      if (btnShareNative) {
        btnShareNative.addEventListener("click", () => {
          const ep = episodes[currentIdx];
          if (!ep || typeof navigator.share !== "function") return;
          const info = buildShareInfo(ep);
          navigator.share({
            title: info.title,
            text: info.text,
            url: info.url
          }).catch((err) => {
            if (err && err.name === "AbortError") return;
            copyToClipboard(info.url).then(() => {
              setShareFeedback("共有画面を開けなかったため、URLをコピーしました");
            }).catch(() => {
              setShareFeedback("共有画面を開けませんでした");
            });
          });
        });
      }

      scrubber.addEventListener("input", () => {
        const ep = episodes[currentIdx];
        if (!ep) return;
        isScrubbing = true;
        timeCurrent.textContent = fmtTime(Number(scrubber.value));
      });
      scrubber.addEventListener("change", () => {
        audio.currentTime = Number(scrubber.value);
        isScrubbing = false;
        updateCornerAndTime();
      });

      audio.addEventListener("play", () => {
        audio.playbackRate = SPEED_RATES[speedIdx];
        btnPlay.textContent = "❚❚ 一時停止";
        updateCornerAndTime();
      });
      audio.addEventListener("pause", () => {
        if (!audio.ended) {
          btnPlay.textContent = "▶ 放送を聴く";
        }
        updateCornerAndTime();
      });
      audio.addEventListener("ended", () => {
        btnPlay.textContent = "▶ もう一度聴く";
        updateCornerAndTime();
      });
      audio.addEventListener("timeupdate", updateCornerAndTime);
      audio.addEventListener("loadedmetadata", () => {
        audio.playbackRate = SPEED_RATES[speedIdx];
        updateCornerAndTime();
      });

      if ("mediaSession" in navigator) {
        try {
          navigator.mediaSession.setActionHandler("play", () => {
            if (episodes[currentIdx] && episodes[currentIdx].has_audio) {
              audio.play().catch(() => {});
            }
          });
          navigator.mediaSession.setActionHandler("pause", () => audio.pause());
          navigator.mediaSession.setActionHandler("seekbackward", () => btnBack.click());
          navigator.mediaSession.setActionHandler("seekforward", () => btnFwd.click());
          navigator.mediaSession.setActionHandler("previoustrack", () => {
            if (currentIdx < episodes.length - 1) {
              selectEpisode(currentIdx + 1, { animate: true, updateUrl: true });
            }
          });
          navigator.mediaSession.setActionHandler("nexttrack", () => {
            if (currentIdx > 0) {
              selectEpisode(currentIdx - 1, { animate: true, updateUrl: true });
            }
          });
        } catch (_) {}
      }

      populateSelect();
      let startIdx = 0;
      try {
        const params = new URLSearchParams(window.location.search);
        const requested = params.get("ep") || window.location.hash.replace(/^#/, "");
        if (requested) {
          const foundIdx = episodes.findIndex((ep) => ep.slug === requested || ep.date === requested);
          if (foundIdx >= 0) startIdx = foundIdx;
        }
      } catch (_) {}
      selectEpisode(startIdx, { animate: false, updateUrl: false });
    })();
  </script>
</body>
</html>
""")


def render_listen_page(
    bundles: list[dict[str, Any]],
    characters: dict[str, Any],
    themes: dict[str, Any],
    safe_json_fn: Callable[[Any], str],
    editorial_plan: dict[str, Any] | None = None,
    site_base_url: str = DEFAULT_SITE_BASE_URL,
    weekly_banners: dict[str, Any] | None = None,
    docs_dir: Path | None = None,
) -> str:
    """Render simplified listener-focused docs/listen.html page."""
    payload = _build_listen_payload(
        bundles,
        characters,
        themes,
        editorial_plan=editorial_plan,
        site_base_url=site_base_url,
        weekly_banners=weekly_banners,
        docs_dir=docs_dir,
    )
    hero_src = payload.get("hero_banner") or ""
    hero_alt = str(payload.get("hero_alt") or DEFAULT_HERO_ALT)
    spot_text = str(payload.get("hero_caption") or payload.get("hero_spot_name") or "").strip()
    if spot_text:
        badge_html = f'<div class="hero-spot-badge" id="hero-spot-badge">📍 {html.escape(spot_text)}</div>'
    else:
        badge_html = '<div class="hero-spot-badge" id="hero-spot-badge" hidden></div>'

    if hero_src:
        hero_img_html = (
            '<div class="hero-img-wrap">'
            f'<img class="hero-img" id="hero-img" src="{html.escape(hero_src)}" '
            f'alt="{html.escape(hero_alt, quote=True)}" />'
            f"{badge_html}"
            "</div>"
        )
    else:
        hero_img_html = ""

    og_meta_html = (
        build_episode_og_meta(
            bundles[-1],
            page_rel_url="listen.html",
            site_base_url=site_base_url,
            editorial_plan=editorial_plan,
            program_title=payload["program_title"],
            og_type="website",
            docs_dir=docs_dir,
            weekly_banners=weekly_banners,
        )
        if bundles
        else ""
    )

    return LISTEN_TEMPLATE.substitute(
        LISTEN_CSS=LISTEN_CSS,
        OG_META_HTML=og_meta_html,
        HERO_IMAGE_HTML=hero_img_html,
        PROGRAM_TITLE=html.escape(payload["program_title"]),
        PROGRAM_SUBTITLE=html.escape(payload["program_subtitle"]),
        PAYLOAD_JSON=safe_json_fn(payload),
    )
