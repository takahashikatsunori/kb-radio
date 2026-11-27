"""Shared helpers for episode share links, OGP metadata, and weekly/episode image resolution."""

from __future__ import annotations

from datetime import date, timedelta
import html
import json
import os
from pathlib import Path
import re
import struct
from typing import Any
from urllib.parse import quote

DEFAULT_SITE_BASE_URL = "https://takahashikatsunori.github.io/kb-radio/"
DEFAULT_HERO_ALT = "小春・平蔵と7人の防災専門家ゲスト集合イラスト"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
WEEKLY_BANNERS_PATH = DATA_DIR / "weekly_banners.json"
DOCS_DIR = ROOT_DIR / "docs"
DOCS_ASSETS_DIR = DOCS_DIR / "assets"
DOCS_WEEKLY_ASSETS_DIR = DOCS_ASSETS_DIR / "weekly"
DOCS_EPISODE_ASSETS_DIR = DOCS_ASSETS_DIR / "episodes"
DOCS_CAST_ASSETS_DIR = DOCS_ASSETS_DIR / "cast"


def load_weekly_banners(path: Path = WEEKLY_BANNERS_PATH) -> dict[str, Any] | None:
    """Safely load data/weekly_banners.json if present and valid."""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def resolve_site_base_url(characters: dict[str, Any] | None = None) -> str:
    """Resolve canonical public base URL ending with '/' for OGP and file:// sharing."""
    env_url = os.environ.get("SITE_BASE_URL", "").strip()
    cfg_url = str(((characters or {}).get("program") or {}).get("site_url") or "").strip()
    raw = env_url or cfg_url or DEFAULT_SITE_BASE_URL
    return raw if raw.endswith("/") else f"{raw}/"


def clean_episode_headline(subtitle: str, fallback: str = "") -> str:
    """Strip leading episode/date prefix before ' ― ' or ' — ' for clean display."""
    raw = (subtitle or "").strip()
    for sep in (" ― ", " — ", " - "):
        if sep in raw:
            right = raw.split(sep, 1)[1].strip()
            if right:
                return right
    return raw or fallback


def format_short_date_ja(date_str: str, weekday_ja: str) -> str:
    """Format '2026-11-27' + '金曜日' into '11月27日（金）'."""
    w_short = (weekday_ja or "").strip()[:1]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (date_str or "").strip())
    if m:
        base = f"{int(m.group(2))}月{int(m.group(3))}日"
    else:
        base = (date_str or "").strip()
    if base and w_short:
        return f"{base}（{w_short}）"
    return base or w_short


def _read_jpeg_dimensions(fh: Any) -> tuple[int, int] | None:
    """Read (width, height) from JPEG SOF0/SOF1/SOF2 frame header."""
    while True:
        byte = fh.read(1)
        if not byte:
            return None
        if byte != b"\xff":
            continue
        while byte == b"\xff":
            byte = fh.read(1)
            if not byte:
                return None
        marker = byte[0]
        if marker in (0x00, 0x01) or (0xD0 <= marker <= 0xD8):
            continue
        if marker in (0xD9, 0xDA):
            return None
        seg_len_bytes = fh.read(2)
        if len(seg_len_bytes) < 2:
            return None
        seg_len = struct.unpack(">H", seg_len_bytes)[0]
        if seg_len < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2):
            frame = fh.read(5)
            if len(frame) < 5:
                return None
            height, width = struct.unpack(">HH", frame[1:5])
            return (width, height) if width > 0 and height > 0 else None
        fh.seek(seg_len - 2, 1)


def _read_webp_dimensions(header: bytes) -> tuple[int, int] | None:
    """Read (width, height) from RIFF/WEBP VP8, VP8L, or VP8X header bytes."""
    if len(header) < 30 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
        return None
    chunk_id = header[12:16]
    if chunk_id == b"VP8 " and header[23:26] == b"\x9d\x01\x2a":
        width = struct.unpack_from("<H", header, 26)[0] & 0x3FFF
        height = struct.unpack_from("<H", header, 28)[0] & 0x3FFF
        return (width, height) if width > 0 and height > 0 else None
    if chunk_id == b"VP8L" and header[20] == 0x2F:
        bits = struct.unpack_from("<I", header, 21)[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return (width, height) if width > 0 and height > 0 else None
    if chunk_id == b"VP8X":
        width = int.from_bytes(header[24:27], "little") + 1
        height = int.from_bytes(header[27:30], "little") + 1
        return (width, height) if width > 0 and height > 0 else None
    return None


def read_image_dimensions(path: Path) -> tuple[int, int] | None:
    """Read (width, height) from PNG, JPEG, or WebP headers without external dependencies."""
    try:
        with path.open("rb") as fh:
            head = fh.read(32)
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                width, height = struct.unpack(">II", head[16:24])
                return (width, height) if width > 0 and height > 0 else None
            if len(head) >= 2 and head[:2] == b"\xff\xd8":
                fh.seek(2)
                return _read_jpeg_dimensions(fh)
            if len(head) >= 30 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return _read_webp_dimensions(head)
    except OSError:
        return None
    return None


def _parse_iso_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _validate_asset(rel_path: Any, docs_dir: Path) -> tuple[str, Path] | None:
    """Normalize a relative asset path under docs_dir and confirm it exists cleanly."""
    if not isinstance(rel_path, str):
        return None
    cleaned = rel_path.strip().replace("\\", "/").lstrip("/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned:
        return None
    docs_root = docs_dir.resolve()
    try:
        cand = (docs_root / cleaned).resolve()
    except OSError:
        return None
    if not cand.is_relative_to(docs_root):
        return None
    if cand.is_file() and cand.stat().st_size > 256:
        return cleaned, cand
    return None


def _find_matching_week(
    ep_dt: date | None,
    editorial_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not ep_dt or not isinstance(editorial_plan, dict):
        return None
    for wk in editorial_plan.get("weeks") or []:
        if not isinstance(wk, dict):
            continue
        w_start = _parse_iso_date(wk.get("week_start"))
        w_end = _parse_iso_date(wk.get("week_end"))
        if w_start and w_end and w_start <= ep_dt <= w_end:
            return wk
    return None


def _find_matching_banner_entry(
    ep_dt: date | None,
    weekly_banners: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not ep_dt or not isinstance(weekly_banners, dict):
        return None
    for entry in weekly_banners.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        w_start = _parse_iso_date(entry.get("week_start"))
        w_end = _parse_iso_date(entry.get("week_end")) or (
            w_start + timedelta(days=6) if w_start else None
        )
        if w_start and w_end and w_start <= ep_dt <= w_end:
            return entry
    return None


def _normalize_rel_key(rel_path: Any) -> str:
    if not isinstance(rel_path, str):
        return ""
    cleaned = rel_path.strip().replace("\\", "/").lstrip("/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _find_banner_entry_by_rel_path(
    rel_path: str,
    weekly_banners: dict[str, Any] | None,
) -> dict[str, Any] | None:
    target = _normalize_rel_key(rel_path)
    if not target or not isinstance(weekly_banners, dict):
        return None
    for entry in weekly_banners.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if _normalize_rel_key(entry.get("rel_path") or entry.get("banner_path")) == target:
            return entry
    default_cfg = weekly_banners.get("default_banner")
    if isinstance(default_cfg, dict) and _normalize_rel_key(default_cfg.get("rel_path")) == target:
        return default_cfg
    return None


def _extract_banner_meta(
    entry: dict[str, Any] | None,
    default_alt: str = DEFAULT_HERO_ALT,
    week_start_override: str = "",
) -> dict[str, str]:
    e = entry if isinstance(entry, dict) else {}
    spot_name = str(e.get("spot_name") or "").strip()
    season_label = str(e.get("season_label") or "").strip()
    caption = str(e.get("caption") or "").strip()
    alt = str(e.get("alt") or "").strip()
    if not alt:
        alt = f"{spot_name}（小春・平蔵と専門家ゲスト）" if spot_name else default_alt
    week_start = str(e.get("week_start") or week_start_override or "").strip()
    return {
        "alt": alt,
        "caption": caption,
        "spot_name": spot_name,
        "season_label": season_label,
        "week_start": week_start,
    }


def _build_image_result(
    rel_path: str,
    file_path: Path | None,
    source: str,
    banner_meta: dict[str, str] | None = None,
    default_alt: str = DEFAULT_HERO_ALT,
) -> dict[str, Any]:
    dims = read_image_dimensions(file_path) if file_path else None
    bm = banner_meta or {}
    return {
        "rel_path": rel_path,
        "width": dims[0] if dims else None,
        "height": dims[1] if dims else None,
        "source": source,
        "alt": str(bm.get("alt") or default_alt),
        "caption": str(bm.get("caption") or ""),
        "spot_name": str(bm.get("spot_name") or ""),
        "season_label": str(bm.get("season_label") or ""),
        "week_start": str(bm.get("week_start") or ""),
    }


def resolve_episode_image(
    bundle: dict[str, Any],
    editorial_plan: dict[str, Any] | None = None,
    docs_dir: Path | None = None,
    weekly_banners: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the hero/OGP image tile for an episode (episode -> weekly_banners -> editorial -> weekly file -> default)."""
    target_docs_dir = docs_dir if docs_dir is not None else DOCS_DIR
    if weekly_banners is None and target_docs_dir.resolve() == DOCS_DIR.resolve():
        weekly_banners = load_weekly_banners()

    default_cfg = (
        weekly_banners.get("default_banner")
        if isinstance(weekly_banners, dict) and isinstance(weekly_banners.get("default_banner"), dict)
        else {}
    )
    default_alt = str(default_cfg.get("alt") or DEFAULT_HERO_ALT).strip() or DEFAULT_HERO_ALT

    meta = (bundle.get("episode") or {}).get("meta") or {}
    slug = str(bundle.get("slug") or meta.get("episode_slug") or meta.get("episode_date") or "").strip()
    ep_date_str = str(meta.get("episode_date") or "").strip()
    ep_dt = _parse_iso_date(ep_date_str)

    # 1. Explicit episode.json metadata
    for key in ("og_image", "banner_image", "hero_image"):
        found = _validate_asset(meta.get(key), target_docs_dir)
        if found:
            matched = _find_banner_entry_by_rel_path(found[0], weekly_banners)
            return _build_image_result(
                found[0],
                found[1],
                "episode_meta",
                _extract_banner_meta(matched, default_alt=default_alt),
                default_alt=default_alt,
            )

    # 2. Per-episode file under docs/assets/episodes/
    ep_stems = [s for s in (slug, ep_date_str) if s]
    for stem in dict.fromkeys(ep_stems):
        for ext in IMAGE_EXTS:
            found = _validate_asset(f"assets/episodes/{stem}{ext}", target_docs_dir)
            if found:
                matched = _find_banner_entry_by_rel_path(found[0], weekly_banners)
                return _build_image_result(
                    found[0],
                    found[1],
                    "episode_file",
                    _extract_banner_meta(matched, default_alt=default_alt),
                    default_alt=default_alt,
                )

    # 3. weekly_banners.json exact week match
    matched_banner = _find_matching_banner_entry(ep_dt, weekly_banners)
    if matched_banner:
        found = _validate_asset(
            matched_banner.get("rel_path") or matched_banner.get("banner_path"),
            target_docs_dir,
        )
        if found:
            return _build_image_result(
                found[0],
                found[1],
                "weekly_banners",
                _extract_banner_meta(matched_banner, default_alt=default_alt),
                default_alt=default_alt,
            )

    # 4. Explicit editorial_plan.json weeks[] entry
    matched_week = _find_matching_week(ep_dt, editorial_plan)
    if matched_week:
        for key in ("og_image", "banner_image", "hero_image"):
            found = _validate_asset(matched_week.get(key), target_docs_dir)
            if found:
                entry_meta = (
                    _find_banner_entry_by_rel_path(found[0], weekly_banners)
                    or matched_banner
                )
                return _build_image_result(
                    found[0],
                    found[1],
                    "editorial_plan",
                    _extract_banner_meta(
                        entry_meta,
                        default_alt=default_alt,
                        week_start_override=str(matched_week.get("week_start") or ""),
                    ),
                    default_alt=default_alt,
                )

    # 5. Exact weekly file under docs/assets/weekly/
    if ep_dt:
        week_monday = (ep_dt - timedelta(days=ep_dt.weekday())).isoformat()
        iso_year, iso_week, _ = ep_dt.isocalendar()
        iso_week_str = f"{iso_year}-W{iso_week:02d}"
        ed_week_start = str((matched_week or {}).get("week_start") or "").strip()
        weekly_stems = [s for s in (week_monday, ed_week_start, iso_week_str) if s]
        for stem in dict.fromkeys(weekly_stems):
            for ext in IMAGE_EXTS:
                found = _validate_asset(f"assets/weekly/{stem}{ext}", target_docs_dir)
                if found:
                    entry_meta = (
                        _find_banner_entry_by_rel_path(found[0], weekly_banners)
                        or matched_banner
                    )
                    return _build_image_result(
                        found[0],
                        found[1],
                        "weekly_exact",
                        _extract_banner_meta(
                            entry_meta,
                            default_alt=default_alt,
                            week_start_override=ed_week_start or week_monday,
                        ),
                        default_alt=default_alt,
                    )

        # 6. Effective-from weekly file: latest YYYY-MM-DD.<ext> with file_date <= ep_dt
        weekly_dir = target_docs_dir / "assets" / "weekly"
        if weekly_dir.is_dir():
            ext_rank = {ext: idx for idx, ext in enumerate(IMAGE_EXTS)}
            candidates: list[tuple[date, int, str, Path]] = []
            for p in weekly_dir.iterdir():
                if not p.is_file():
                    continue
                suffix_lower = p.suffix.lower()
                if suffix_lower not in ext_rank:
                    continue
                file_dt = _parse_iso_date(p.stem)
                if not file_dt or file_dt > ep_dt:
                    continue
                validated = _validate_asset(f"assets/weekly/{p.name}", target_docs_dir)
                if validated:
                    candidates.append((file_dt, -ext_rank[suffix_lower], validated[0], validated[1]))
            if candidates:
                candidates.sort(reverse=True)
                file_dt, _, rel_path, file_path = candidates[0]
                entry_meta = (
                    _find_banner_entry_by_rel_path(rel_path, weekly_banners)
                    or _find_matching_banner_entry(file_dt, weekly_banners)
                )
                return _build_image_result(
                    rel_path,
                    file_path,
                    "weekly_effective",
                    _extract_banner_meta(
                        entry_meta,
                        default_alt=default_alt,
                        week_start_override=file_dt.isoformat(),
                    ),
                    default_alt=default_alt,
                )

    # 7. Default program banner fallback, then cast portrait fallback
    def_rel = default_cfg.get("rel_path")
    if def_rel:
        found_def = _validate_asset(def_rel, target_docs_dir)
        if found_def:
            return _build_image_result(
                found_def[0],
                found_def[1],
                "default_banner",
                _extract_banner_meta(default_cfg, default_alt=default_alt),
                default_alt=default_alt,
            )

    for ext in IMAGE_EXTS:
        found = _validate_asset(f"assets/hero_cast_banner{ext}", target_docs_dir)
        if found:
            return _build_image_result(
                found[0],
                found[1],
                "default_banner",
                _extract_banner_meta(default_cfg, default_alt=default_alt),
                default_alt=default_alt,
            )

    found_cast = _validate_asset("assets/cast/koharu.jpg", target_docs_dir)
    if found_cast:
        return _build_image_result(found_cast[0], found_cast[1], "cast_fallback", default_alt=default_alt)

    return _build_image_result("", None, "none", default_alt=default_alt)


def _truncate_text(text: str, limit: int = 140) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _compose_og_texts(
    bundle: dict[str, Any],
    program_title: str,
) -> dict[str, str]:
    episode = bundle.get("episode") or {}
    manifest = bundle.get("manifest") or {}
    meta = episode.get("meta") or {}
    mf_meta = manifest.get("meta") or {}
    guest = episode.get("guest") or {}

    date_ja = format_short_date_ja(str(meta.get("episode_date") or ""), str(meta.get("weekday_ja") or ""))
    theme_name = str(meta.get("theme_name") or "").strip()
    headline = clean_episode_headline(str(meta.get("subtitle") or ""), fallback=theme_name)
    is_spinoff = bool(meta.get("is_spinoff"))
    prefix = f"特別編・{date_ja}" if (is_spinoff and date_ja) else (date_ja or ("特別編" if is_spinoff else ""))

    og_title = f"【{prefix}】{headline}｜{program_title}" if prefix else f"{headline}｜{program_title}"
    guest_name = str(guest.get("name") or "").strip()
    guest_or_hosts = f"ゲスト: {guest_name}" if guest_name else "小春＆平蔵"
    duration = str(mf_meta.get("total_duration_formatted") or "").strip()
    detail = f"{guest_or_hosts}・{duration}" if duration else guest_or_hosts
    raw_desc = f"{theme_name}（{detail}）{headline}" if theme_name else f"（{detail}）{headline}"

    return {
        "date_ja": date_ja,
        "prefix": prefix,
        "theme_name": theme_name,
        "headline": headline,
        "guest_or_hosts": guest_or_hosts,
        "duration": duration,
        "og_title": og_title,
        "og_desc": _truncate_text(raw_desc, limit=140),
    }


def build_episode_og_meta(
    bundle: dict[str, Any],
    page_rel_url: str,
    site_base_url: str,
    editorial_plan: dict[str, Any] | None = None,
    program_title: str = "毎朝7時！こだいら防災＆まちラジオ",
    og_type: str = "article",
    docs_dir: Path | None = None,
    weekly_banners: dict[str, Any] | None = None,
) -> str:
    """Render description, canonical link, Open Graph, and Twitter Card meta tags."""
    target_docs_dir = docs_dir if docs_dir is not None else DOCS_DIR
    base = site_base_url if site_base_url.endswith("/") else f"{site_base_url}/"
    page_abs_url = base + page_rel_url.lstrip("/")
    texts = _compose_og_texts(bundle, program_title)
    img_info = resolve_episode_image(
        bundle,
        editorial_plan=editorial_plan,
        docs_dir=target_docs_dir,
        weekly_banners=weekly_banners,
    )
    img_rel = str(img_info.get("rel_path") or "")
    img_abs_url = (base + img_rel.lstrip("/")) if img_rel else ""

    esc = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    lines = [
        f'<meta name="description" content="{esc(texts["og_desc"])}" />',
        f'<link rel="canonical" href="{esc(page_abs_url)}" />',
        f'<meta property="og:type" content="{esc(og_type)}" />',
        '<meta property="og:locale" content="ja_JP" />',
        f'<meta property="og:site_name" content="{esc(program_title)}" />',
        f'<meta property="og:title" content="{esc(texts["og_title"])}" />',
        f'<meta property="og:description" content="{esc(texts["og_desc"])}" />',
        f'<meta property="og:url" content="{esc(page_abs_url)}" />',
    ]

    if img_abs_url:
        alt_text = str(img_info.get("alt") or "").strip() or f"{program_title} {texts['prefix']} 番組イメージ".strip()
        lines.append(f'<meta property="og:image" content="{esc(img_abs_url)}" />')
        lines.append(f'<meta property="og:image:alt" content="{esc(alt_text)}" />')
        if img_info.get("width") and img_info.get("height"):
            lines.append(f'<meta property="og:image:width" content="{img_info["width"]}" />')
            lines.append(f'<meta property="og:image:height" content="{img_info["height"]}" />')
        lines.append('<meta name="twitter:card" content="summary_large_image" />')
    else:
        lines.append('<meta name="twitter:card" content="summary" />')

    lines.append(f'<meta name="twitter:title" content="{esc(texts["og_title"])}" />')
    lines.append(f'<meta name="twitter:description" content="{esc(texts["og_desc"])}" />')
    if img_abs_url:
        lines.append(f'<meta name="twitter:image" content="{esc(img_abs_url)}" />')

    return "\n  ".join(lines)


def render_share_redirect_page(
    bundle: dict[str, Any],
    site_base_url: str,
    editorial_plan: dict[str, Any] | None = None,
    program_title: str = "毎朝7時！こだいら防災＆まちラジオ",
    docs_dir: Path | None = None,
    weekly_banners: dict[str, Any] | None = None,
) -> str:
    """Render docs/share/<slug>/index.html with episode OGP tags and JS redirect to listen.html."""
    target_docs_dir = docs_dir if docs_dir is not None else DOCS_DIR
    meta = (bundle.get("episode") or {}).get("meta") or {}
    slug = str(bundle.get("slug") or meta.get("episode_slug") or meta.get("episode_date") or "").strip()
    safe_slug = quote(slug, safe="-_")
    target_rel = f"../../listen.html?ep={safe_slug}"
    texts = _compose_og_texts(bundle, program_title)
    og_meta_html = build_episode_og_meta(
        bundle,
        page_rel_url=f"share/{safe_slug}/",
        site_base_url=site_base_url,
        editorial_plan=editorial_plan,
        program_title=program_title,
        og_type="article",
        docs_dir=target_docs_dir,
        weekly_banners=weekly_banners,
    )
    img_info = resolve_episode_image(
        bundle,
        editorial_plan=editorial_plan,
        docs_dir=target_docs_dir,
        weekly_banners=weekly_banners,
    )
    img_rel = str(img_info.get("rel_path") or "")
    share_alt = str(img_info.get("alt") or "").strip() or program_title
    slug_json = json.dumps(slug, ensure_ascii=False).replace("</", "<\\/")

    banner_html = ""
    if img_rel:
        banner_html = (
            '<div class="share-card-media">'
            f'<img src="../../{html.escape(img_rel, quote=True)}" '
            f'alt="{html.escape(share_alt, quote=True)}" />'
            "</div>"
        )

    sub_parts = [p for p in (texts["theme_name"], texts["guest_or_hosts"], texts["duration"]) if p]
    sub_line = " ／ ".join(sub_parts)
    pill_label = texts["prefix"] or "放送回"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(texts["og_title"])}</title>
  <meta name="robots" content="noindex" />
  {og_meta_html}
  <script>
    window.location.replace("../../listen.html?ep=" + encodeURIComponent({slug_json}));
  </script>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.25rem;
      background: #f6f4ee;
      color: #1f2937;
      font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", system-ui, -apple-system, sans-serif;
      line-height: 1.6;
    }}
    .share-card {{
      width: 100%;
      max-width: 520px;
      background: #ffffff;
      border: 1px solid #e2e6df;
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 8px 24px rgba(18, 64, 40, 0.08);
    }}
    .share-card-media {{
      background: #dff0e6;
      aspect-ratio: 16 / 9;
      overflow: hidden;
    }}
    .share-card-media img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .share-card-body {{
      padding: 1.15rem 1.25rem 1.35rem;
    }}
    .share-prog {{
      font-size: 0.78rem;
      font-weight: 800;
      color: #1b5e3c;
      margin: 0 0 0.45rem;
    }}
    .share-date-pill {{
      display: inline-block;
      font-size: 0.76rem;
      font-weight: 800;
      padding: 0.16rem 0.62rem;
      border-radius: 999px;
      background: #e7f4ec;
      color: #124028;
      margin-bottom: 0.5rem;
    }}
    .share-title {{
      margin: 0 0 0.45rem;
      font-size: 1.12rem;
      font-weight: 800;
      line-height: 1.42;
      color: #1f2937;
    }}
    .share-meta {{
      margin: 0 0 1rem;
      font-size: 0.82rem;
      color: #5b6472;
    }}
    .cta-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-height: 48px;
      padding: 0.65rem 1.2rem;
      border-radius: 999px;
      background: linear-gradient(135deg, #1b5e3c 0%, #124028 100%);
      color: #ffffff;
      text-decoration: none;
      font-size: 0.96rem;
      font-weight: 800;
      box-shadow: 0 6px 16px rgba(27, 94, 60, 0.24);
    }}
    .cta-btn:hover {{
      filter: brightness(1.06);
    }}
  </style>
</head>
<body>
  <main class="share-card">
    {banner_html}
    <div class="share-card-body">
      <p class="share-prog">{html.escape(program_title)}</p>
      <span class="share-date-pill">{html.escape(pill_label)}</span>
      <h1 class="share-title">{html.escape(texts["headline"])}</h1>
      <p class="share-meta">{html.escape(sub_line)}</p>
      <a class="cta-btn" href="{html.escape(target_rel, quote=True)}">▶ この回をプレーヤーで聴く</a>
    </div>
  </main>
</body>
</html>
"""
