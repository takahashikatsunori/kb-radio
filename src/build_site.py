"""Build GitHub Pages and local file:// compatible mobile-first portal in docs/ plus script.md."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import json
import re
from pathlib import Path
from typing import Any

from kodaira_spots import (
    load_kodaira_spots,
    load_spot_reports,
)
from site_calendar_page import render_calendar_page
from site_listen_page import render_listen_page
from site_notebook_page import render_notebook_page
from site_share import (
    DEFAULT_HERO_ALT,
    DEFAULT_SITE_BASE_URL,
    build_episode_og_meta,
    clean_episode_headline,
    format_short_date_ja,
    load_weekly_banners,
    render_share_redirect_page,
    resolve_episode_image,
    resolve_site_base_url,
)
from site_spots_page import (
    build_spot_dossier_context,
    render_spot_detail_page,
    render_spots_index_page,
)
from site_tech_page import render_tech_page

JST = timezone(timedelta(hours=9))
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
TECH_TALK_DIR = DATA_DIR / "tech_talk"
EPISODES_DIR = ROOT_DIR / "episodes"
DOCS_DIR = ROOT_DIR / "docs"
DOCS_AUDIO_DIR = DOCS_DIR / "audio"
DOCS_CAST_ASSETS_DIR = DOCS_DIR / "assets" / "cast"
DOCS_INTROS_AUDIO_DIR = DOCS_AUDIO_DIR / "intros"

BGM_LABELS = {
    "bgm_warm": "温かいアコースティック風トークBGM（bgm_warm）",
    "bgm_news": "軽快なニュース解説BGM（bgm_news）",
    "bgm_feature": "落ち着いた深掘り特集BGM（bgm_feature）",
}

JINGLE_LABELS = {
    "opening_jingle": "オープニングジングル（朝7時FMテーマ）",
    "stinger": "コーナー切替チャイム",
    "guest_jingle": "ゲスト登場ファンファーレ（guest_jingle）",
    "outro_jingle": "エンディングテーマ",
}


def fmt_tc(seconds: float) -> str:
    total = max(0, int(seconds))
    mins, secs = divmod(total, 60)
    return f"{mins:02d}:{secs:02d}"


def _safe_json_for_html(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_tts_tag_hints(text: str) -> str:
    """Remove parenthetical technical TTS markup (e.g. '（<laugh> / <chuckle>）') for display."""
    cleaned = re.sub(r"[（(][^）)]*<[^>]+>[^）)]*[）)]", "", text)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _write_placeholder_svg(
    svg_path: Path,
    name: str,
    accent_color: str,
    bg_soft: str,
    badge_label: str,
) -> None:
    """Write a crisp 1:1 512x512 SVG bust-up placeholder harmonizing with Concept A."""
    initial = html.escape((name or "?")[:1])
    color_esc = html.escape(accent_color or "#1b5e3c")
    soft_esc = html.escape(bg_soft or "#eef2ff")
    badge_esc = html.escape(badge_label or "")
    grad_id = html.escape(svg_path.stem)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="{html.escape(name)} イラスト準備中">
  <defs>
    <linearGradient id="bg_{grad_id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#fffdf8"/>
      <stop offset="55%" stop-color="{soft_esc}"/>
      <stop offset="100%" stop-color="#e7f4ec"/>
    </linearGradient>
    <clipPath id="clip_{grad_id}">
      <rect x="0" y="0" width="512" height="512" rx="36"/>
    </clipPath>
  </defs>
  <g clip-path="url(#clip_{grad_id})">
    <rect width="512" height="512" fill="url(#bg_{grad_id})"/>
    <!-- Sunny morning studio window motif -->
    <rect x="38" y="34" width="436" height="290" rx="18" fill="#ffffff" fill-opacity="0.58" stroke="#cbd5e1" stroke-width="3"/>
    <line x1="256" y1="34" x2="256" y2="324" stroke="#e2e8f0" stroke-width="2.5"/>
    <circle cx="408" cy="102" r="36" fill="#fde68a" fill-opacity="0.55"/>
    <!-- Bust-up silhouette with studio headphones -->
    <path d="M98 512 C104 374, 174 334, 256 334 C338 334, 408 374, 414 512 Z" fill="{color_esc}" fill-opacity="0.22"/>
    <path d="M126 512 C132 394, 188 358, 256 358 C324 358, 380 394, 386 512 Z" fill="#ffffff" stroke="{color_esc}" stroke-width="5"/>
    <path d="M214 358 L256 410 L298 358" fill="none" stroke="{color_esc}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
    <!-- Head & headphones -->
    <path d="M168 228 A88 88 0 0 1 344 228" fill="none" stroke="#334155" stroke-width="14" stroke-linecap="round"/>
    <rect x="148" y="204" width="28" height="62" rx="14" fill="{color_esc}"/>
    <rect x="336" y="204" width="28" height="62" rx="14" fill="{color_esc}"/>
    <circle cx="256" cy="232" r="76" fill="#ffffff" stroke="{color_esc}" stroke-width="5"/>
    <text x="256" y="256" text-anchor="middle" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="76" font-weight="800" fill="{color_esc}">{initial}</text>
    <!-- Role & status pills -->
    <rect x="128" y="38" width="256" height="32" rx="16" fill="{color_esc}" fill-opacity="0.14"/>
    <text x="256" y="60" text-anchor="middle" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="16" font-weight="700" fill="{color_esc}">{badge_esc}</text>
    <rect x="146" y="446" width="220" height="38" rx="19" fill="#1f2937" fill-opacity="0.78"/>
    <text x="256" y="471" text-anchor="middle" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="17" font-weight="700" fill="#ffffff">イラスト準備中</text>
  </g>
</svg>
"""
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg, encoding="utf-8")


def _resolve_cast_portrait(
    cast_id: str,
    name: str,
    accent_color: str,
    bg_soft: str,
    badge_label: str,
) -> dict[str, Any]:
    """Return portrait asset metadata; use real raster file if present else write SVG placeholder."""
    DOCS_CAST_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        cand = DOCS_CAST_ASSETS_DIR / f"{cast_id}{ext}"
        if cand.exists() and cand.stat().st_size > 512:
            return {
                "src": f"assets/cast/{cand.name}",
                "is_placeholder": False,
            }
    svg_path = DOCS_CAST_ASSETS_DIR / f"{cast_id}.svg"
    _write_placeholder_svg(svg_path, name, accent_color, bg_soft, badge_label)
    return {
        "src": f"assets/cast/{svg_path.name}",
        "is_placeholder": True,
    }


def _build_estimated_manifest(episode: dict[str, Any]) -> dict[str, Any]:
    """Estimate timeline timestamps from text length when manifest.json is not built yet."""
    meta = episode["meta"]
    voices = meta["voices"]
    cursor = 0.0
    global_idx = 0
    segs_out: list[dict[str, Any]] = []

    for seg in episode["segments"]:
        seg_start = cursor
        intro = seg.get("intro_jingle")
        if intro == "opening_jingle":
            cursor += 5.0
        elif intro == "guest_jingle":
            cursor += 2.5
        elif intro:
            cursor += 2.2

        lines_out: list[dict[str, Any]] = []
        for idx, line in enumerate(seg["lines"]):
            sp = line["speaker"]
            dur = max(1.8, len(line["text"]) / 5.7)
            l_start = round(cursor, 2)
            l_end = round(cursor + dur, 2)
            cursor = l_end + float(line.get("pause_after", 0.32))
            lines_out.append(
                {
                    "index": idx,
                    "global_index": global_idx,
                    "speaker": sp,
                    "speaker_name": voices[sp]["name"],
                    "text": line["text"],
                    "start_sec": l_start,
                    "end_sec": l_end,
                    "duration_sec": round(dur, 2),
                }
            )
            global_idx += 1

        if seg.get("outro_jingle"):
            cursor += 6.5

        segs_out.append(
            {
                "id": seg["id"],
                "title": seg["title"],
                "bgm": seg.get("bgm"),
                "intro_jingle": intro,
                "outro_jingle": seg.get("outro_jingle"),
                "start_sec": round(seg_start, 2),
                "end_sec": round(cursor, 2),
                "duration_sec": round(cursor - seg_start, 2),
                "lines": lines_out,
            }
        )

    return {
        "meta": {
            "title": meta["title"],
            "subtitle": meta["subtitle"],
            "episode_date": meta["episode_date"],
            "episode_number": meta["episode_number"],
            "output_filename": meta["output_filename"],
            "total_duration_sec": round(cursor, 2),
            "total_duration_formatted": fmt_tc(cursor),
            "line_count": global_idx,
            "estimated": True,
        },
        "segments": segs_out,
    }


def _load_episode_bundle(ep_dir: Path) -> dict[str, Any]:
    episode = _load_json(ep_dir / "episode.json")
    manifest_path = ep_dir / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        manifest["meta"]["estimated"] = False
    else:
        manifest = _build_estimated_manifest(episode)

    mp3_name = episode["meta"]["output_filename"]
    mp3_path = DOCS_AUDIO_DIR / mp3_name
    has_audio = mp3_path.exists() and mp3_path.stat().st_size > 1024
    return {
        "dir": ep_dir,
        "slug": episode["meta"].get("episode_slug") or ep_dir.name,
        "episode": episode,
        "manifest": manifest,
        "has_audio": has_audio,
    }


def generate_script_md(bundle: dict[str, Any]) -> None:
    """Write complete broadcast script.md inside the episode directory."""
    episode = bundle["episode"]
    manifest = bundle["manifest"]
    meta = episode["meta"]
    mf_meta = manifest["meta"]
    guest = episode.get("guest", {})
    ep_dir: Path = bundle["dir"]
    est_label = "（推定尺・音声未生成）" if mf_meta.get("estimated") else ""
    ep_label = meta.get("episode_label") or f"第{meta['episode_number']}回"
    guest_desc = (
        f"{guest['name']}（{guest.get('title', '')}）"
        if guest.get("name")
        else "なし（小春＆平蔵スピンオフ特別回）"
    )

    lines_out: list[str] = [
        f"# {meta['title']}",
        "",
        f"**{meta['subtitle']}**",
        "",
        f"- **放送日**: {meta['episode_date']}（{meta.get('weekday_ja', '')}・{ep_label}）",
        f"- **テーマ**: {meta.get('theme_name', '')}",
        f"- **想定/収録時間**: {mf_meta['total_duration_formatted']}（{mf_meta['total_duration_sec']:.1f}秒）{est_label}",
        "- **レギュラー出演**: 小春（メインパーソナリティ）／ 平蔵（パートナーキャスター）",
        f"- **本日の専門家ゲスト**: {guest_desc}",
        f"- **音声ファイル**: `docs/audio/{meta['output_filename']}`",
        "",
        "## チャプター目次",
        "",
    ]

    for idx, seg in enumerate(manifest["segments"], start=1):
        lines_out.append(
            f"{idx}. **[{fmt_tc(seg['start_sec'])} - {fmt_tc(seg['end_sec'])}]** "
            f"{seg['title']}（{len(seg['lines'])}セリフ / {fmt_tc(seg['duration_sec'])}）"
        )

    lines_out.extend(["", "---", "", "## 本編完全台本", ""])
    for idx, seg in enumerate(manifest["segments"], start=1):
        lines_out.append(f"### {idx}. [{fmt_tc(seg['start_sec'])}] {seg['title']}")
        lines_out.append("")
        cues = []
        if seg.get("intro_jingle"):
            cues.append(f"ジングル: {JINGLE_LABELS.get(seg['intro_jingle'], seg['intro_jingle'])}")
        if seg.get("bgm"):
            cues.append(f"BGM: {BGM_LABELS.get(seg['bgm'], seg['bgm'])}")
        if cues:
            lines_out.append(f"> ♪ {' ／ '.join(cues)}")
            lines_out.append("")
        for item in seg["lines"]:
            lines_out.append(f"- **[{fmt_tc(item['start_sec'])}] {item['speaker_name']}**：{item['text']}")
        if seg.get("outro_jingle"):
            lines_out.extend(["", f"> ♪ エンディング: {JINGLE_LABELS.get(seg['outro_jingle'], seg['outro_jingle'])}"])
        lines_out.append("")

    notes = episode.get("learned_notes") or {}
    if notes.get("learned_points"):
        lines_out.extend(["---", "", "## 今日の小春＆平蔵 防災ノート", ""])
        for pt in notes["learned_points"]:
            lines_out.append(f"- {pt}")
        if notes.get("kodaira_discovery"):
            lines_out.append(f"- **今日の小平発見**: {notes['kodaira_discovery']}")
        lines_out.append("")

    links = episode.get("links") or []
    if links:
        lines_out.extend(["---", "", "## 関連リンク", ""])
        for lk in links:
            lines_out.append(f"- **[{lk['category']}] [{lk['title']}]({lk['url']})** — {lk.get('note', '')}")
        lines_out.append("")

    (ep_dir / "script.md").write_text("\n".join(lines_out), encoding="utf-8")


COMMON_CSS = """
:root {
  --forest: #1b5e3c;
  --forest-dark: #124028;
  --forest-soft: #e7f4ec;
  --paper: #f8f7f3;
  --card: #ffffff;
  --ink: #1f2937;
  --muted: #5b6472;
  --border: #dfe4de;
  --amber: #d97706;
  --amber-soft: #fef3c7;
  --koharu: #e11d48;
  --koharu-soft: #fff1f2;
  --heizo: #2563eb;
  --heizo-soft: #eff6ff;
  --guest: var(--guest-color, #4338ca);
  --guest-soft: var(--guest-bg, #eef2ff);
  --shadow: 0 6px 20px rgba(18, 64, 40, 0.08);
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
  line-height: 1.65;
  -webkit-tap-highlight-color: transparent;
}
a { color: var(--forest); }

/* Compact app-style header */
header {
  background: linear-gradient(135deg, var(--forest-dark) 0%, var(--forest) 65%, #2b7a50 100%);
  color: #ffffff;
  border-bottom: 3px solid var(--amber);
}
.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0.65rem 1rem 0.75rem;
}
.brand-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.55rem;
}
.brand {
  font-weight: 800;
  font-size: clamp(0.98rem, 4vw, 1.22rem);
  color: #fff;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.01em;
}
.time-pill {
  flex: 0 0 auto;
  white-space: nowrap;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.16rem 0.55rem;
  border-radius: 999px;
  background: var(--amber);
  color: #fff;
}
.nav-links {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.32rem;
}
.nav-links a {
  color: rgba(255, 255, 255, 0.94);
  text-decoration: none;
  font-size: 0.76rem;
  font-weight: 700;
  padding: 0.34rem 0.2rem;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.12);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.15s;
}
.nav-links a:hover, .nav-links a.active {
  background: #ffffff;
  color: var(--forest-dark);
  border-color: #ffffff;
}
.page-subhead {
  margin: 0.55rem 0 0;
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.9);
}
.page-h1 {
  margin: 0.45rem 0 0;
  font-size: clamp(1.08rem, 4vw, 1.45rem);
  line-height: 1.3;
}

/* Main layout */
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem 1.25rem;
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(310px, 0.95fr);
  gap: 1.25rem;
  align-items: start;
}
.container.single {
  grid-template-columns: minmax(0, 1fr);
}
.col-main, .col-side, .card, .now-playing, .section-head, .seg-divider, .mobile-tabs {
  min-width: 0;
  max-width: 100%;
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow);
  overflow: hidden;
  margin-bottom: 1rem;
}
.ep-hero {
  padding: 0.78rem 1rem;
  border-left: 4px solid var(--amber);
}
.ep-hero-media {
  position: relative;
  aspect-ratio: 16 / 9;
  max-height: 290px;
  width: 100%;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 0.65rem;
  background: #dff0e6;
}
.ep-hero-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ep-hero-spot-badge,
.archive-spot-badge {
  position: absolute;
  right: 0.5rem;
  bottom: 0.5rem;
  max-width: calc(100% - 1rem);
  padding: 0.2rem 0.58rem;
  border-radius: 999px;
  background: rgba(18, 64, 40, 0.82);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #ffffff;
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
}
.ep-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.76rem;
  color: var(--muted);
}
.theme-pill {
  display: inline-block;
  padding: 0.14rem 0.55rem;
  border-radius: 999px;
  background: var(--guest-soft);
  color: var(--guest);
  font-weight: 700;
}
.edition-pill {
  display: inline-block;
  padding: 0.14rem 0.55rem;
  border-radius: 999px;
  background: var(--amber-soft);
  color: #92400e;
  font-weight: 700;
}
.ep-title {
  margin: 0.35rem 0 0;
  font-size: clamp(0.98rem, 3.6vw, 1.22rem);
  line-height: 1.38;
  color: var(--forest-dark);
  overflow-wrap: anywhere;
}
.section-head {
  padding: 0.75rem 1rem;
  background: #fcfcfa;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.3rem 0.6rem;
}
.section-head h2 {
  margin: 0;
  font-size: 0.96rem;
  color: var(--forest-dark);
  flex: 1 1 180px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.hint {
  font-size: 0.76rem;
  color: var(--muted);
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

/* Slim sticky player */
.player-card {
  position: sticky;
  top: 0;
  z-index: 30;
  padding: 0.72rem 1rem;
  border-top: 3px solid var(--forest);
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(8px);
}
.audio-pending-banner {
  background: var(--amber-soft);
  border: 1px solid #f59e0b;
  color: #92400e;
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  font-size: 0.8rem;
  margin-bottom: 0.55rem;
}
.now-playing {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}
.now-chapter {
  flex: 1 1 auto;
  font-size: 0.88rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.time-readout {
  font-variant-numeric: tabular-nums;
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--heizo);
  white-space: nowrap;
  flex: 0 0 auto;
}
.scrubber {
  width: 100%;
  accent-color: var(--forest);
  cursor: pointer;
  height: 22px;
  margin: 0.2rem 0 0.35rem;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
}
.btn-group {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
button {
  font-family: inherit;
  cursor: pointer;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--ink);
  padding: 0.4rem 0.65rem;
  font-size: 0.82rem;
  font-weight: 700;
  min-height: 36px;
  white-space: nowrap;
}
button:hover:not(:disabled) {
  background: var(--forest-soft);
  border-color: var(--forest);
}
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.primary {
  background: var(--forest);
  border-color: var(--forest);
  color: #fff;
  padding: 0.42rem 0.95rem;
}
button.primary:hover:not(:disabled) { background: var(--forest-dark); }
button.active-toggle {
  background: var(--heizo-soft);
  border-color: var(--heizo);
  color: var(--heizo);
}
.speed-group button.is-selected {
  background: var(--forest);
  color: #fff;
  border-color: var(--forest);
}
.speed-cycle-btn {
  display: none;
}
.share-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: var(--forest-soft);
  border-color: rgba(27, 94, 60, 0.35);
  color: var(--forest-dark);
}
.share-toggle-btn[aria-expanded="true"] {
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
  margin-top: 0.55rem;
  padding: 0.65rem 0.75rem;
  border-radius: 12px;
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
  margin-bottom: 0.45rem;
}
.share-panel-title {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--forest-dark);
  min-width: 0;
  overflow-wrap: anywhere;
}
button.share-panel-close {
  min-height: 28px;
  width: 28px;
  padding: 0;
  border-radius: 999px;
  color: var(--muted);
  font-size: 0.95rem;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}
.share-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.share-btn {
  font-family: inherit;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  min-height: 36px;
  padding: 0.36rem 0.75rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  white-space: nowrap;
  border: 1px solid transparent;
  transition: filter 0.15s, background 0.15s, border-color 0.15s;
}
.share-btn[hidden] {
  display: none;
}
.share-btn-native {
  background: var(--forest);
  border-color: var(--forest);
  color: #ffffff;
}
.share-btn-native:hover {
  background: var(--forest-dark);
  border-color: var(--forest-dark);
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
.share-btn-line:hover,
.share-btn-x:hover {
  filter: brightness(1.07);
}
.share-btn-copy:hover {
  background: var(--forest-soft);
  border-color: var(--forest);
}
.share-feedback {
  margin-top: 0.38rem;
  min-height: 1.15em;
  font-size: 0.76rem;
  font-weight: 700;
  color: var(--forest-dark);
}
.share-feedback:empty {
  display: none;
}

/* Mobile 3-tab bar */
.mobile-tabs {
  display: none;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.35rem;
  margin-bottom: 0.75rem;
  background: #ecefe9;
  padding: 0.3rem;
  border-radius: 12px;
}
.mobile-tabs button {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 0.8rem;
  min-height: 36px;
  padding: 0.35rem 0.25rem;
  border-radius: 9px;
}
.mobile-tabs button.active {
  background: #ffffff;
  color: var(--forest-dark);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

/* Chapters accordion */
.chapter-summary {
  list-style: none;
  cursor: pointer;
  user-select: none;
  flex-wrap: nowrap;
  align-items: center;
}
.chapter-summary h2 {
  flex: 1 1 auto;
}
.chapter-summary .hint {
  flex: 0 0 auto;
  white-space: nowrap;
}
.chapter-summary::-webkit-details-marker {
  display: none;
}
.chapter-summary .hint::after {
  content: " ▼";
  font-size: 0.7rem;
}
.chapter-details[open] .chapter-summary .hint::after {
  content: " ▲";
}
.chapter-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 0.45rem;
  padding: 0.75rem 0.95rem;
}
.chapter-btn {
  text-align: left;
  padding: 0.5rem 0.65rem;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 0.14rem;
  white-space: normal;
  min-height: auto;
}
.chapter-btn.active {
  background: var(--forest-soft);
  border-color: var(--forest);
  box-shadow: inset 3px 0 0 var(--forest);
}
.chapter-tc {
  font-size: 0.74rem;
  font-variant-numeric: tabular-nums;
  color: var(--heizo);
  font-weight: 700;
  flex: 0 0 auto;
}
.chapter-title {
  font-size: 0.82rem;
  line-height: 1.35;
  min-width: 0;
  overflow-wrap: anywhere;
}

/* Transcript */
.transcript-body {
  padding: 0.8rem 0.95rem 1.25rem;
  max-height: 68vh;
  overflow-y: auto;
}
.seg-divider {
  margin: 1rem 0 0.55rem;
  padding: 0.42rem 0.7rem;
  background: var(--forest-soft);
  border-left: 4px solid var(--forest);
  border-radius: 6px;
  font-weight: 700;
  font-size: 0.88rem;
  color: var(--forest-dark);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.4rem;
  scroll-margin-top: 150px;
}
.seg-divider > span:first-child {
  min-width: 0;
  overflow-wrap: anywhere;
}
.seg-divider:first-child { margin-top: 0; }
.line-item {
  display: grid;
  grid-template-columns: 48px 86px minmax(0, 1fr);
  grid-template-areas: "tc speaker text";
  gap: 0.5rem;
  padding: 0.52rem 0.6rem;
  border-radius: 10px;
  cursor: pointer;
  border: 1px solid transparent;
  align-items: baseline;
  scroll-margin-top: 150px;
}
.line-item:hover { background: #f3f5f2; }
.line-item.active {
  background: var(--amber-soft);
  border-color: #f59e0b;
}
.line-tc {
  grid-area: tc;
  font-variant-numeric: tabular-nums;
  font-size: 0.76rem;
  color: var(--muted);
  font-weight: 600;
}
.speaker-pill {
  grid-area: speaker;
  font-size: 0.74rem;
  font-weight: 700;
  text-align: center;
  padding: 0.14rem 0.48rem;
  border-radius: 999px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.speaker-koharu { background: var(--koharu-soft); color: var(--koharu); }
.speaker-heizo { background: var(--heizo-soft); color: var(--heizo); }
.speaker-guest { background: var(--guest-soft); color: var(--guest); }
.line-text {
  grid-area: text;
  font-size: 0.94rem;
  overflow-wrap: anywhere;
}

/* Right panels & cards */
.panel-body {
  padding: 0.8rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.link-card {
  display: block;
  text-decoration: none;
  color: inherit;
  padding: 0.72rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fcfcfa;
  transition: border-color 0.15s, background 0.15s;
}
.link-card:hover {
  border-color: var(--forest);
  background: var(--forest-soft);
}
.pill-tag {
  display: inline-block;
  font-size: 0.71rem;
  font-weight: 700;
  padding: 0.1rem 0.48rem;
  border-radius: 999px;
  background: var(--forest-soft);
  color: var(--forest-dark);
  margin-bottom: 0.22rem;
}
.link-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--forest-dark);
  margin: 0 0 0.18rem;
  overflow-wrap: anywhere;
}
.link-note {
  font-size: 0.8rem;
  color: var(--muted);
  margin: 0;
  overflow-wrap: anywhere;
}
.note-box {
  padding: 0.72rem 0.85rem;
  border-radius: 10px;
  background: #fcfcfa;
  border: 1px solid var(--border);
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}
.note-box ul {
  margin: 0.35rem 0 0.45rem;
  padding-left: 1.15rem;
}
.tel-link {
  color: var(--heizo);
  font-weight: 700;
  text-decoration: underline;
}
.guest-card {
  padding: 0.8rem 0.95rem;
  border-left: 4px solid var(--guest);
  background: var(--guest-soft);
  border-radius: 10px;
}
.kw-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.45rem;
}
.kw-chip {
  font-size: 0.74rem;
  background: #fff;
  border: 1px solid var(--border);
  padding: 0.12rem 0.5rem;
  border-radius: 999px;
  font-weight: 600;
}
.archive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr));
  gap: 0.85rem;
  padding: 0.9rem;
}
.archive-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.9rem;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  overflow-wrap: anywhere;
}
.archive-thumb-wrap {
  position: relative;
  aspect-ratio: 16 / 9;
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: #dff0e6;
  margin-bottom: 0.15rem;
}
.archive-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.archive-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: auto;
  padding-top: 0.2rem;
}
.btn-link {
  display: inline-block;
  text-decoration: none;
  background: var(--forest);
  color: #fff;
  font-size: 0.84rem;
  font-weight: 700;
  padding: 0.48rem 0.85rem;
  border-radius: 8px;
  text-align: center;
}
.btn-link:hover { background: var(--forest-dark); }
.btn-link-secondary {
  display: inline-block;
  text-decoration: none;
  background: #ffffff;
  color: var(--forest-dark);
  border: 1.5px solid var(--forest);
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.44rem 0.75rem;
  border-radius: 8px;
  text-align: center;
}
.btn-link-secondary:hover { background: var(--forest-soft); }
footer {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0.9rem 1rem 2rem;
  font-size: 0.78rem;
  color: var(--muted);
  text-align: center;
}

/* Mobile breakpoint (<= 920px): single column + tab switching */
@media (max-width: 920px) {
  .container {
    display: block;
    width: 100%;
    padding: 0.65rem 0.7rem;
  }
  .mobile-tabs {
    display: grid;
  }
  .player-card {
    margin: 0 0 0.65rem;
    border-radius: 12px;
    padding: 0.6rem 0.78rem;
  }
  main[data-active-tab="script"] #tab-panel-script { display: block; }
  main[data-active-tab="script"] .col-side { display: none; }

  main[data-active-tab="links"] #tab-panel-script { display: none; }
  main[data-active-tab="links"] .col-side { display: block; }
  main[data-active-tab="links"] #tab-panel-links { display: block; }
  main[data-active-tab="links"] #tab-panel-notes { display: none; }

  main[data-active-tab="notes"] #tab-panel-script { display: none; }
  main[data-active-tab="notes"] .col-side { display: block; }
  main[data-active-tab="notes"] #tab-panel-links { display: none; }
  main[data-active-tab="notes"] #tab-panel-notes { display: block; }
}

/* Narrow phone breakpoint (<= 640px): vertical-only controls, accordion chapters, 2-row transcript */
@media (max-width: 640px) {
  .header-inner { padding: 0.55rem 0.7rem 0.62rem; }
  .brand-bar { margin-bottom: 0.45rem; }
  .nav-links { grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 0.25rem; }
  .nav-links a:nth-child(-n+4) { grid-column: span 3; }
  .nav-links a:nth-child(n+5) { grid-column: span 4; }
  .nav-links a { font-size: 0.72rem; padding: 0.34rem 0.14rem; }
  .ep-hero { padding: 0.62rem 0.75rem; margin-bottom: 0.6rem; }
  .controls { gap: 0.25rem; }
  .btn-group { gap: 0.25rem; }
  .speed-group { display: none; }
  .speed-cycle-btn { display: inline-flex; align-items: center; }
  button { padding: 0.34rem 0.48rem; font-size: 0.76rem; min-height: 36px; }
  button.primary { padding: 0.34rem 0.68rem; }

  .chapter-list {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    padding: 0.6rem 0.75rem;
    gap: 0.38rem;
  }
  .chapter-btn {
    flex-direction: row;
    align-items: baseline;
    gap: 0.45rem;
    width: 100%;
    padding: 0.48rem 0.62rem;
  }
  .chapter-tc {
    flex: 0 0 auto;
  }

  .transcript-body {
    max-height: none;
    overflow-y: visible;
    padding: 0.65rem 0.75rem 1.2rem;
  }
  .line-item {
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-areas:
      "speaker tc"
      "text text";
    gap: 0.28rem 0.55rem;
    padding: 0.55rem 0.55rem;
    border-bottom: 1px solid #f0f2ee;
  }
  .line-tc {
    justify-self: end;
    font-size: 0.74rem;
  }
  .line-text {
    font-size: 0.95rem;
    line-height: 1.72;
  }
  .share-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .share-btn {
    padding: 0.36rem 0.55rem;
    font-size: 0.76rem;
  }
}
"""


def _render_nav(root_prefix: str, active: str, subhead: str = "", page_h1: str = "") -> str:
    def cls(key: str) -> str:
        return ' class="active"' if active == key else ""

    extra = ""
    if page_h1:
        extra += f'<h1 class="page-h1">{html.escape(page_h1)}</h1>'
    if subhead:
        extra += f'<p class="page-subhead">{html.escape(subhead)}</p>'

    return (
        f'<div class="brand-bar">'
        f'<a class="brand" href="{root_prefix}index.html">こだいら防災＆まちラジオ</a>'
        f'<span class="time-pill">毎朝7時</span>'
        f'</div>'
        f'<nav class="nav-links" aria-label="メインメニュー">'
        f'<a href="{root_prefix}index.html"{cls("latest")}>最新回</a>'
        f'<a href="{root_prefix}calendar.html"{cls("calendar")}>カレンダー</a>'
        f'<a href="{root_prefix}spots/index.html"{cls("spots")}>取材手帳</a>'
        f'<a href="{root_prefix}archive.html"{cls("archive")}>過去回</a>'
        f'<a href="{root_prefix}cast.html"{cls("cast")}>出演者</a>'
        f'<a href="{root_prefix}characters.html"{cls("characters")}>防災ノート</a>'
        f'<a href="{root_prefix}tech.html"{cls("tech")}>番組のしくみ</a>'
        f'</nav>'
        f'{extra}'
    )


def _render_episode_page(
    bundle: dict[str, Any],
    all_bundles: list[dict[str, Any]],
    root_prefix: str,
    is_home: bool,
    editorial_plan: dict[str, Any] | None = None,
    site_base_url: str = DEFAULT_SITE_BASE_URL,
    weekly_banners: dict[str, Any] | None = None,
) -> str:
    episode = bundle["episode"]
    manifest = bundle["manifest"]
    meta = episode["meta"]
    mf_meta = manifest["meta"]
    guest = episode.get("guest", {})
    guest_ui = meta["voices"].get("guest", {}).get("ui", {"color": "#4338ca", "bg_soft": "#eef2ff"})

    audio_rel = f"{root_prefix}audio/{meta['output_filename']}"
    is_spinoff = bool(meta.get("is_spinoff"))
    ep_label = meta.get("episode_label") or f"第{meta['episode_number']}回"
    slug = bundle["slug"]
    share_site_rel = f"episodes/{slug}/"
    payload = {
        "slug": slug,
        "site_base_url": site_base_url,
        "share_rel_path": share_site_rel if is_home else f"{root_prefix}{share_site_rel}",
        "share_site_rel_path": share_site_rel,
        "share_date_label": format_short_date_ja(meta["episode_date"], meta.get("weekday_ja", "")),
        "share_headline": clean_episode_headline(meta.get("subtitle", ""), fallback=meta.get("theme_name", "")),
        "is_spinoff": is_spinoff,
        "meta": meta,
        "manifest_meta": mf_meta,
        "guest": guest,
        "cast_href": f"{root_prefix}cast.html#{guest['id']}" if guest.get("id") else f"{root_prefix}cast.html",
        "has_audio": bundle["has_audio"],
        "audio_src": audio_rel,
        "weather": episode.get("weather_summary", {}),
        "links": episode.get("links", []),
        "references": episode.get("references", []),
        "learned_notes": episode.get("learned_notes", {}),
        "segments": manifest["segments"],
        "recent_episodes": [
            {
                "date": b["episode"]["meta"]["episode_date"],
                "weekday_ja": b["episode"]["meta"].get("weekday_ja", ""),
                "theme": b["episode"]["meta"].get("theme_name", ""),
                "guest_name": b["episode"].get("guest", {}).get("name", ""),
                "href": f"{root_prefix}episodes/{b['slug']}/index.html",
                "has_audio": b["has_audio"],
            }
            for b in reversed(all_bundles[-7:])
        ],
    }

    title_esc = html.escape(meta["title"])
    subtitle_esc = html.escape(meta["subtitle"])
    theme_badge_esc = html.escape(meta.get("theme_badge", meta.get("theme_name", "")))
    date_esc = html.escape(meta["episode_date"])
    weekday_short = html.escape((meta.get("weekday_ja", "") or "")[:1])
    dur_esc = html.escape(mf_meta["total_duration_formatted"])
    est_suffix = "（予定）" if mf_meta.get("estimated") else ""
    guest_suffix = f"・ゲスト: {html.escape(guest['name'])}" if guest.get("name") else "・小春＆平蔵スペシャル"
    side_panel_title = "今回のピックアップ＆出演" if is_spinoff else "本日のゲスト＆天気"
    side_panel_hint = "特別企画" if is_spinoff else "曜日テーマ"
    notes_panel_title = "小春＆平蔵のまとめメモ" if is_spinoff else "小春＆平蔵の防災ノート"
    nav_html = _render_nav(root_prefix, "latest" if is_home else "archive")
    og_meta_html = build_episode_og_meta(
        bundle,
        page_rel_url="" if is_home else share_site_rel,
        site_base_url=site_base_url,
        editorial_plan=editorial_plan,
        program_title=meta.get("title") or "毎朝7時！こだいら防災＆まちラジオ",
        og_type="website" if is_home else "article",
        weekly_banners=weekly_banners,
    )
    ep_img = resolve_episode_image(
        bundle,
        editorial_plan=editorial_plan,
        weekly_banners=weekly_banners,
    )
    ep_img_rel = str(ep_img.get("rel_path") or "").strip()
    ep_img_alt = str(ep_img.get("alt") or DEFAULT_HERO_ALT).strip()
    ep_spot_text = str(ep_img.get("caption") or ep_img.get("spot_name") or "").strip()
    ep_hero_media_html = ""
    if ep_img_rel:
        spot_badge_html = (
            f'<span class="ep-hero-spot-badge">📍 {html.escape(ep_spot_text)}</span>'
            if ep_spot_text
            else ""
        )
        ep_hero_media_html = (
            '<div class="ep-hero-media">'
            f'<img src="{html.escape(root_prefix + ep_img_rel, quote=True)}" '
            f'alt="{html.escape(ep_img_alt, quote=True)}" loading="eager" />'
            f"{spot_badge_html}"
            "</div>"
        )

    special_pills_html = ""
    if meta.get("is_holiday") or meta.get("special_feature") or is_spinoff:
        ed_text = meta.get("edition_label") or ""
        if ed_text:
            special_pills_html += f'<span class="edition-pill">{html.escape(ed_text)}</span>'
        sp_feat = meta.get("special_feature")
        if isinstance(sp_feat, dict) and sp_feat.get("title"):
            sp_label = f"特別特集: {sp_feat['title']}"
            if sp_feat.get("phase_label"):
                sp_label += f"（{sp_feat['phase_label']}）"
            special_pills_html += f'<span class="edition-pill">{html.escape(sp_label)}</span>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title_esc} | {html.escape(ep_label)} ({date_esc})</title>
  {og_meta_html}
  <style>
    :root {{
      --guest-color: {html.escape(guest_ui.get("color", "#4338ca"))};
      --guest-bg: {html.escape(guest_ui.get("bg_soft", "#eef2ff"))};
    }}
    {COMMON_CSS}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      {nav_html}
    </div>
  </header>

  <main class="container" id="main-root" data-active-tab="script">
    <section class="col-main">
      <div class="card ep-hero">
        {ep_hero_media_html}
        <div class="ep-meta-row">
          <span class="theme-pill">{theme_badge_esc}</span>
          {special_pills_html}
          <span>{date_esc}（{weekday_short}）・{dur_esc}{est_suffix}{guest_suffix}</span>
        </div>
        <h1 class="ep-title">{subtitle_esc}</h1>
      </div>

      <div class="card player-card">
        <div id="audio-pending" class="audio-pending-banner" style="display:none;">
          この回のMP3音声はまだ生成されていません（<code>.env</code> に <code>GEMINI_API_KEY</code> を設定し <code>build_radio.py</code> を実行すると音声再生ができます）。下の台本・タイムライン・関連リンクはそのままお読みいただけます。
        </div>
        <audio id="radio-audio" preload="metadata"></audio>
        <div class="now-playing">
          <div class="now-chapter" id="now-chapter">再生ボタンを押してお聴きください</div>
          <div class="time-readout" id="time-readout">00:00 / {dur_esc}</div>
        </div>
        <input type="range" class="scrubber" id="scrubber" min="0" max="100" step="0.1" value="0" aria-label="再生位置シークバー" />
        <div class="controls">
          <div class="btn-group">
            <button type="button" class="primary" id="btn-play">▶ 再生</button>
            <button type="button" id="btn-back">-15s</button>
            <button type="button" id="btn-fwd">+15s</button>
          </div>
          <div class="btn-group speed-group" id="speed-group">
            <button type="button" data-rate="0.9">0.9x</button>
            <button type="button" data-rate="1" class="is-selected">1.0x</button>
            <button type="button" data-rate="1.15">1.15x</button>
            <button type="button" data-rate="1.25">1.25x</button>
          </div>
          <div class="btn-group">
            <button type="button" id="btn-speed-cycle" class="speed-cycle-btn">1.0x</button>
            <button type="button" id="btn-autoscroll" class="active-toggle">追従ON</button>
            <button type="button" id="btn-share-toggle" class="share-toggle-btn" aria-expanded="false" aria-controls="share-panel">
              <svg class="share-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
              <span>シェア</span>
            </button>
          </div>
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

      <div class="mobile-tabs" id="mobile-tabs" role="tablist" aria-label="表示切替">
        <button type="button" role="tab" data-tab="script" class="active">台本・目次</button>
        <button type="button" role="tab" data-tab="links">リンク・天気</button>
        <button type="button" role="tab" data-tab="notes">ノート・過去回</button>
      </div>

      <div id="tab-panel-script">
        <details id="chapter-details" class="card chapter-details">
          <summary class="section-head chapter-summary">
            <h2>チャプター目次</h2>
            <span class="hint">開閉</span>
          </summary>
          <div class="chapter-list" id="chapter-list"></div>
        </details>

        <div class="card">
          <div class="section-head">
            <h2>同期台本</h2>
            <span class="hint">セリフをタップで再生</span>
          </div>
          <div class="transcript-body" id="transcript-body"></div>
        </div>
      </div>
    </section>

    <aside class="col-side">
      <div id="tab-panel-links">
        <div class="card">
          <div class="section-head">
            <h2>{html.escape(side_panel_title)}</h2>
            <span class="hint">{html.escape(side_panel_hint)}</span>
          </div>
          <div class="panel-body" id="guest-weather-panel"></div>
        </div>

        <div class="card">
          <div class="section-head">
            <h2>今日の話題・関連リンク</h2>
            <span class="hint">タップで公式ページへ</span>
          </div>
          <div class="panel-body" id="links-panel"></div>
        </div>
      </div>

      <div id="tab-panel-notes">
        <div class="card">
          <div class="section-head">
            <h2>{html.escape(notes_panel_title)}</h2>
            <span class="hint">今日の学び・連絡先</span>
          </div>
          <div class="panel-body" id="notes-panel"></div>
        </div>

        <div class="card">
          <div class="section-head">
            <h2>バックナンバー</h2>
            <a href="{root_prefix}archive.html" class="hint">一覧を見る →</a>
          </div>
          <div class="panel-body" id="recent-panel"></div>
        </div>
      </div>
    </aside>
  </main>

  <footer>
    毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ 小春 ＆ 平蔵 ／ <a href="{root_prefix}listen.html">シンプル聴取ページ</a>
  </footer>

  <script type="application/json" id="episode-data">{_safe_json_for_html(payload)}</script>
  <script>
    (function () {{
      const data = JSON.parse(document.getElementById("episode-data").textContent);
      const mainRoot = document.getElementById("main-root");
      const audio = document.getElementById("radio-audio");
      const btnPlay = document.getElementById("btn-play");
      const btnBack = document.getElementById("btn-back");
      const btnFwd = document.getElementById("btn-fwd");
      const btnAutoScroll = document.getElementById("btn-autoscroll");
      const btnSpeedCycle = document.getElementById("btn-speed-cycle");
      const scrubber = document.getElementById("scrubber");
      const timeReadout = document.getElementById("time-readout");
      const nowChapter = document.getElementById("now-chapter");
      const chapterDetails = document.getElementById("chapter-details");
      const chapterList = document.getElementById("chapter-list");
      const transcriptBody = document.getElementById("transcript-body");
      const speedButtons = Array.from(document.querySelectorAll("#speed-group button"));
      const mobileTabButtons = Array.from(document.querySelectorAll("#mobile-tabs button"));

      if (chapterDetails && window.innerWidth > 920) {{
        chapterDetails.open = true;
      }}

      const speedRates = [1.0, 1.15, 1.25, 1.5, 0.9];
      let speedIdx = 0;
      let autoScroll = true;
      let isScrubbing = false;
      let lastActiveLineIdx = -1;
      let lastActiveSegId = null;

      function fmtTime(sec) {{
        const s = Math.max(0, Math.floor(sec || 0));
        return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
      }}

      function appendContactWithTelLinks(container, text) {{
        const phoneRe = /(0\\d{{1,4}}-\\d{{1,4}}-\\d{{3,4}})/g;
        let last = 0;
        let m;
        while ((m = phoneRe.exec(text)) !== null) {{
          if (m.index > last) {{
            container.appendChild(document.createTextNode(text.slice(last, m.index)));
          }}
          const a = document.createElement("a");
          a.className = "tel-link";
          a.href = "tel:" + m[1];
          a.textContent = m[1];
          container.appendChild(a);
          last = phoneRe.lastIndex;
        }}
        if (last < text.length) {{
          container.appendChild(document.createTextNode(text.slice(last)));
        }}
      }}

      if (data.has_audio) {{
        audio.src = data.audio_src;
      }} else {{
        document.getElementById("audio-pending").style.display = "block";
        btnPlay.disabled = true;
        btnBack.disabled = true;
        btnFwd.disabled = true;
        scrubber.disabled = true;
      }}

      const totalEst = data.manifest_meta.total_duration_sec || 600;
      scrubber.max = String(totalEst);
      timeReadout.textContent = "00:00 / " + fmtTime(totalEst);

      const chapterButtons = new Map();
      const flatLines = [];

      data.segments.forEach((seg, segIdx) => {{
        const cBtn = document.createElement("button");
        cBtn.type = "button";
        cBtn.className = "chapter-btn";
        const tcSpanTop = document.createElement("span");
        tcSpanTop.className = "chapter-tc";
        tcSpanTop.textContent = fmtTime(seg.start_sec) + " 〜 " + fmtTime(seg.end_sec);
        const titleSpanTop = document.createElement("span");
        titleSpanTop.className = "chapter-title";
        titleSpanTop.textContent = (segIdx + 1) + ". " + seg.title;
        cBtn.appendChild(tcSpanTop);
        cBtn.appendChild(titleSpanTop);
        cBtn.addEventListener("click", () => {{
          if (!data.has_audio) return;
          audio.currentTime = seg.start_sec;
          audio.play().catch(() => {{}});
          if (chapterDetails && window.innerWidth <= 920) {{
            chapterDetails.open = false;
          }}
        }});
        chapterList.appendChild(cBtn);
        chapterButtons.set(seg.id, cBtn);

        const divEl = document.createElement("div");
        divEl.className = "seg-divider";
        const sTitle = document.createElement("span");
        sTitle.textContent = (segIdx + 1) + ". " + seg.title;
        const sTc = document.createElement("span");
        sTc.className = "chapter-tc";
        sTc.textContent = fmtTime(seg.start_sec);
        divEl.appendChild(sTitle);
        divEl.appendChild(sTc);
        transcriptBody.appendChild(divEl);

        seg.lines.forEach((line) => {{
          const row = document.createElement("div");
          row.className = "line-item";
          const tc = document.createElement("span");
          tc.className = "line-tc";
          tc.textContent = fmtTime(line.start_sec);

          const sp = document.createElement("span");
          sp.className = "speaker-pill speaker-" + line.speaker;
          sp.textContent = line.speaker_name;

          const txt = document.createElement("span");
          txt.className = "line-text";
          txt.textContent = line.text;

          row.appendChild(tc);
          row.appendChild(sp);
          row.appendChild(txt);
          row.addEventListener("click", () => {{
            if (!data.has_audio) return;
            audio.currentTime = line.start_sec;
            audio.play().catch(() => {{}});
          }});
          transcriptBody.appendChild(row);
          flatLines.push({{ ...line, segId: seg.id, segTitle: seg.title, el: row }});
        }});
      }});

      const gwPanel = document.getElementById("guest-weather-panel");
      const gCard = document.createElement("div");
      gCard.className = "guest-card";
      const gTitle = document.createElement("div");
      gTitle.style.fontWeight = "700";
      if (data.guest && data.guest.name) {{
        gTitle.textContent = data.guest.name + "（" + (data.guest.title || "") + "）";
      }} else {{
        gTitle.textContent = (data.meta && data.meta.theme_badge) || "小春＆平蔵 スピンオフ特別企画";
      }}
      const gDesc = document.createElement("div");
      gDesc.style.fontSize = "0.82rem";
      gDesc.style.marginTop = "0.25rem";
      gDesc.textContent = (data.guest && data.guest.personality) || "";
      const kwWrap = document.createElement("div");
      kwWrap.className = "kw-wrap";
      const chipList = (data.guest && data.guest.keywords_featured && data.guest.keywords_featured.length > 0)
        ? data.guest.keywords_featured
        : ((data.meta && data.meta.kodaira_topics) || []);
      chipList.forEach((kw) => {{
        const chip = document.createElement("span");
        chip.className = "kw-chip";
        chip.textContent = kw;
        kwWrap.appendChild(chip);
      }});
      gCard.appendChild(gTitle);
      gCard.appendChild(gDesc);
      gCard.appendChild(kwWrap);
      const gCastLink = document.createElement("a");
      gCastLink.href = data.cast_href || "cast.html";
      gCastLink.style.display = "inline-block";
      gCastLink.style.marginTop = "0.55rem";
      gCastLink.style.fontSize = "0.8rem";
      gCastLink.style.fontWeight = "700";
      gCastLink.style.textDecoration = "none";
      gCastLink.textContent = "出演者プロフィール＆自己紹介を聴く →";
      gCard.appendChild(gCastLink);
      gwPanel.appendChild(gCard);

      if (data.weather && data.weather.daily && data.weather.daily.length > 0) {{
        const wToday = data.weather.daily[0];
        const wBox = document.createElement("div");
        wBox.className = "note-box";
        const wHead = document.createElement("strong");
        wHead.textContent = "今朝の小平市のお天気（" + wToday.date + "）";
        const wText = document.createElement("div");
        wText.textContent =
          wToday.weather + " ／ 最高 " + wToday.temp_max_c + "℃・最低 " + wToday.temp_min_c +
          "℃ ／ 降水確率 " + wToday.precip_prob_max + "%";
        wBox.appendChild(wHead);
        wBox.appendChild(wText);
        gwPanel.appendChild(wBox);
      }}

      const linksPanel = document.getElementById("links-panel");
      (data.links || []).forEach((lk) => {{
        const a = document.createElement("a");
        a.className = "link-card";
        a.href = lk.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const cat = document.createElement("span");
        cat.className = "pill-tag";
        cat.textContent = lk.category || "関連リンク";
        const title = document.createElement("div");
        title.className = "link-title";
        title.textContent = (lk.title || lk.url) + " ↗";
        const note = document.createElement("p");
        note.className = "link-note";
        note.textContent = lk.note || lk.url;
        a.appendChild(cat);
        a.appendChild(title);
        a.appendChild(note);
        linksPanel.appendChild(a);
      }});

      const notesPanel = document.getElementById("notes-panel");
      const nBox = document.createElement("div");
      nBox.className = "note-box";
      const nTitle = document.createElement("strong");
      nTitle.textContent = "今日身につけたポイント";
      const ul = document.createElement("ul");
      (data.learned_notes.learned_points || []).forEach((pt) => {{
        const li = document.createElement("li");
        li.textContent = pt;
        ul.appendChild(li);
      }});
      nBox.appendChild(nTitle);
      nBox.appendChild(ul);
      if (data.learned_notes.kodaira_discovery) {{
        const disc = document.createElement("div");
        disc.style.marginTop = "0.35rem";
        disc.textContent = "小平発見: " + data.learned_notes.kodaira_discovery;
        nBox.appendChild(disc);
      }}
      notesPanel.appendChild(nBox);

      (data.references || []).forEach((ref) => {{
        const rBox = document.createElement("div");
        rBox.className = "note-box";
        const rTag = document.createElement("span");
        rTag.className = "pill-tag";
        rTag.textContent = ref.category || "メモ";
        const rTitle = document.createElement("div");
        rTitle.style.fontWeight = "700";
        rTitle.textContent = ref.title || "";
        const rDet = document.createElement("div");
        rDet.style.fontSize = "0.8rem";
        rDet.style.color = "var(--muted)";
        rDet.textContent = ref.detail || "";
        const rCon = document.createElement("div");
        rCon.style.fontSize = "0.84rem";
        rCon.style.fontWeight = "700";
        rCon.style.marginTop = "0.2rem";
        appendContactWithTelLinks(rCon, ref.contact || "");
        rBox.appendChild(rTag);
        rBox.appendChild(rTitle);
        rBox.appendChild(rDet);
        rBox.appendChild(rCon);
        notesPanel.appendChild(rBox);
      }});

      const recentPanel = document.getElementById("recent-panel");
      (data.recent_episodes || []).forEach((ep) => {{
        const a = document.createElement("a");
        a.className = "link-card";
        a.href = ep.href;
        const tag = document.createElement("span");
        tag.className = "pill-tag";
        tag.textContent = ep.date + "（" + ep.weekday_ja + "）";
        const title = document.createElement("div");
        title.className = "link-title";
        title.textContent = ep.theme;
        const note = document.createElement("p");
        note.className = "link-note";
        note.textContent = (ep.guest_name ? ("ゲスト: " + ep.guest_name) : "小春＆平蔵スペシャル") + (ep.has_audio ? " ／ 音声あり" : " ／ 台本公開");
        a.appendChild(tag);
        a.appendChild(title);
        a.appendChild(note);
        recentPanel.appendChild(a);
      }});

      mobileTabButtons.forEach((tb) => {{
        tb.addEventListener("click", () => {{
          const tab = tb.dataset.tab || "script";
          mainRoot.dataset.activeTab = tab;
          mobileTabButtons.forEach((b) => b.classList.toggle("active", b === tb));
        }});
      }});

      function applySpeed(rate) {{
        audio.playbackRate = rate;
        btnSpeedCycle.textContent = rate + "x";
        speedButtons.forEach((b) => {{
          b.classList.toggle("is-selected", parseFloat(b.dataset.rate || "1") === rate);
        }});
      }}

      function updateSyncUI() {{
        const cur = audio.currentTime || 0;
        const total = Number.isFinite(audio.duration) ? audio.duration : totalEst;
        if (!isScrubbing) {{
          scrubber.max = String(total || totalEst);
          scrubber.value = String(cur);
        }}
        timeReadout.textContent = fmtTime(cur) + " / " + fmtTime(total);

        let activeSeg = data.segments[0];
        for (const seg of data.segments) {{
          if (cur >= seg.start_sec) activeSeg = seg;
        }}
        if (activeSeg && activeSeg.id !== lastActiveSegId) {{
          if (lastActiveSegId && chapterButtons.has(lastActiveSegId)) {{
            chapterButtons.get(lastActiveSegId).classList.remove("active");
          }}
          if (chapterButtons.has(activeSeg.id)) {{
            const chEl = chapterButtons.get(activeSeg.id);
            chEl.classList.add("active");
          }}
          nowChapter.textContent = activeSeg.title;
          lastActiveSegId = activeSeg.id;
        }}

        let activeLineIdx = -1;
        for (let i = 0; i < flatLines.length; i++) {{
          const l = flatLines[i];
          if (cur >= l.start_sec && cur <= l.end_sec + 0.35) {{
            activeLineIdx = i;
            break;
          }}
          if (cur >= l.start_sec) activeLineIdx = i;
        }}
        if (activeLineIdx !== lastActiveLineIdx) {{
          if (lastActiveLineIdx >= 0 && flatLines[lastActiveLineIdx]) {{
            flatLines[lastActiveLineIdx].el.classList.remove("active");
          }}
          if (activeLineIdx >= 0 && flatLines[activeLineIdx]) {{
            const activeEl = flatLines[activeLineIdx].el;
            activeEl.classList.add("active");
            if (autoScroll && !audio.paused && mainRoot.dataset.activeTab === "script") {{
              activeEl.scrollIntoView({{ block: "center", behavior: "smooth" }});
            }}
          }}
          lastActiveLineIdx = activeLineIdx;
        }}
      }}

      btnPlay.addEventListener("click", () => {{
        if (!data.has_audio) return;
        if (audio.paused) audio.play().catch(() => {{}});
        else audio.pause();
      }});
      btnBack.addEventListener("click", () => {{
        if (!data.has_audio) return;
        audio.currentTime = Math.max(0, audio.currentTime - 15);
        updateSyncUI();
      }});
      btnFwd.addEventListener("click", () => {{
        if (!data.has_audio) return;
        const total = Number.isFinite(audio.duration) ? audio.duration : totalEst;
        audio.currentTime = Math.min(total, audio.currentTime + 15);
        updateSyncUI();
      }});
      btnAutoScroll.addEventListener("click", () => {{
        autoScroll = !autoScroll;
        btnAutoScroll.textContent = autoScroll ? "追従ON" : "追従OFF";
        btnAutoScroll.classList.toggle("active-toggle", autoScroll);
      }});
      speedButtons.forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const rate = parseFloat(btn.dataset.rate || "1");
          const found = speedRates.indexOf(rate);
          if (found >= 0) speedIdx = found;
          applySpeed(rate);
        }});
      }});
      btnSpeedCycle.addEventListener("click", () => {{
        speedIdx = (speedIdx + 1) % speedRates.length;
        applySpeed(speedRates[speedIdx]);
      }});
      scrubber.addEventListener("input", () => {{
        isScrubbing = true;
        const total = Number.isFinite(audio.duration) ? audio.duration : totalEst;
        timeReadout.textContent = fmtTime(Number(scrubber.value)) + " / " + fmtTime(total);
      }});
      scrubber.addEventListener("change", () => {{
        audio.currentTime = Number(scrubber.value);
        isScrubbing = false;
        updateSyncUI();
      }});
      audio.addEventListener("play", () => {{ btnPlay.textContent = "❚❚ 停止"; }});
      audio.addEventListener("pause", () => {{ btnPlay.textContent = "▶ 再生"; }});
      audio.addEventListener("ended", () => {{ btnPlay.textContent = "▶ 再生"; }});
      audio.addEventListener("timeupdate", updateSyncUI);
      audio.addEventListener("loadedmetadata", updateSyncUI);

      const btnShareToggle = document.getElementById("btn-share-toggle");
      const sharePanel = document.getElementById("share-panel");
      const sharePanelTitle = document.getElementById("share-panel-title");
      const btnShareClose = document.getElementById("btn-share-close");
      const btnShareNative = document.getElementById("btn-share-native");
      const btnShareLine = document.getElementById("btn-share-line");
      const btnShareX = document.getElementById("btn-share-x");
      const btnShareCopy = document.getElementById("btn-share-copy");
      const shareFeedback = document.getElementById("share-feedback");
      let shareCopyTimer = null;
      const isMobileDevice = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent || "")
        || (navigator.platform === "MacIntel" && (navigator.maxTouchPoints || 0) > 1);

      function buildShareInfo() {{
        const relPath = data.share_rel_path || ("episodes/" + data.slug + "/");
        const siteRelPath = data.share_site_rel_path || ("episodes/" + data.slug + "/");
        let shareUrl = "";
        if (window.location.protocol === "http:" || window.location.protocol === "https:") {{
          try {{
            shareUrl = new URL(relPath, window.location.href).toString();
          }} catch (_) {{}}
        }}
        if (!shareUrl) {{
          let cleanBase = data.site_base_url || "";
          while (cleanBase.endsWith("/")) cleanBase = cleanBase.slice(0, -1);
          let cleanRel = siteRelPath;
          while (cleanRel.startsWith("/")) cleanRel = cleanRel.slice(1);
          shareUrl = cleanBase ? (cleanBase + "/" + cleanRel) : siteRelPath;
        }}
        const dateLabel = data.share_date_label || (data.meta && data.meta.episode_date) || "";
        const prefix = data.is_spinoff ? ("特別編・" + dateLabel) : dateLabel;
        const rawHeadline = data.share_headline || (data.meta && (data.meta.subtitle || data.meta.theme_name)) || "";
        const shortHeadline = rawHeadline.length > 72 ? (rawHeadline.slice(0, 71) + "…") : rawHeadline;
        const progTitle = (data.meta && data.meta.title) || "毎朝7時！こだいら防災＆まちラジオ";
        const shareText = "【" + prefix + "】" + shortHeadline + "｜" + progTitle;
        const shareTitle = "【" + prefix + "】" + rawHeadline;
        return {{
          url: shareUrl,
          text: shareText,
          title: shareTitle,
          label: prefix + "の回をシェア"
        }};
      }}

      function copyToClipboard(text) {{
        if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {{
          return navigator.clipboard.writeText(text);
        }}
        return new Promise((resolve, reject) => {{
          try {{
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
          }} catch (err) {{
            reject(err);
          }}
        }});
      }}

      function setShareFeedback(msg) {{
        if (shareFeedback) shareFeedback.textContent = msg || "";
      }}

      function closeSharePanel() {{
        if (!sharePanel || !btnShareToggle) return;
        sharePanel.hidden = true;
        btnShareToggle.setAttribute("aria-expanded", "false");
      }}

      const shareInfo = buildShareInfo();
      if (sharePanelTitle) sharePanelTitle.textContent = shareInfo.label;
      if (btnShareLine) {{
        if (isMobileDevice) {{
          btnShareLine.href = "https://line.me/R/share?text=" + encodeURIComponent(shareInfo.text + "\\n" + shareInfo.url);
          btnShareLine.removeAttribute("target");
          btnShareLine.removeAttribute("rel");
        }} else {{
          btnShareLine.href = "https://social-plugins.line.me/lineit/share?url=" + encodeURIComponent(shareInfo.url) + "&text=" + encodeURIComponent(shareInfo.text);
          btnShareLine.setAttribute("target", "_blank");
          btnShareLine.setAttribute("rel", "noopener noreferrer");
        }}
      }}
      if (btnShareX) {{
        btnShareX.href = "https://x.com/intent/tweet?text=" + encodeURIComponent(shareInfo.text) + "&url=" + encodeURIComponent(shareInfo.url);
      }}
      if (btnShareNative && typeof navigator.share === "function") {{
        btnShareNative.hidden = false;
      }}
      if (btnShareToggle && sharePanel) {{
        btnShareToggle.addEventListener("click", () => {{
          if (isMobileDevice && typeof navigator.share === "function") {{
            navigator.share({{
              title: shareInfo.title,
              text: shareInfo.text,
              url: shareInfo.url
            }}).catch((err) => {{
              if (err && err.name === "AbortError") return;
              sharePanel.hidden = false;
              btnShareToggle.setAttribute("aria-expanded", "true");
            }});
            return;
          }}
          const nextHidden = !sharePanel.hidden;
          sharePanel.hidden = nextHidden;
          btnShareToggle.setAttribute("aria-expanded", nextHidden ? "false" : "true");
        }});
      }}
      if (btnShareClose) {{
        btnShareClose.addEventListener("click", closeSharePanel);
      }}
      document.addEventListener("keydown", (ev) => {{
        if (ev.key === "Escape" && sharePanel && !sharePanel.hidden) {{
          closeSharePanel();
        }}
      }});
      if (btnShareCopy) {{
        btnShareCopy.addEventListener("click", () => {{
          copyToClipboard(shareInfo.url).then(() => {{
            btnShareCopy.textContent = "✓ コピーしました";
            setShareFeedback("この回のURLをコピーしました");
            if (shareCopyTimer) clearTimeout(shareCopyTimer);
            shareCopyTimer = setTimeout(() => {{
              btnShareCopy.textContent = "URLをコピー";
            }}, 2200);
          }}).catch(() => {{
            setShareFeedback("コピーできませんでした。URL欄から直接コピーしてください");
          }});
        }});
      }}
      if (btnShareNative) {{
        btnShareNative.addEventListener("click", () => {{
          if (typeof navigator.share !== "function") return;
          navigator.share({{
            title: shareInfo.title,
            text: shareInfo.text,
            url: shareInfo.url
          }}).catch((err) => {{
            if (err && err.name === "AbortError") return;
            copyToClipboard(shareInfo.url).then(() => {{
              setShareFeedback("共有画面を開けなかったため、URLをコピーしました");
            }}).catch(() => {{
              setShareFeedback("共有画面を開けませんでした");
            }});
          }});
        }});
      }}
    }})();
  </script>
</body>
</html>
"""


def _render_archive_page(
    all_bundles: list[dict[str, Any]],
    editorial_plan: dict[str, Any] | None = None,
    weekly_banners: dict[str, Any] | None = None,
) -> str:
    items = []
    for b in reversed(all_bundles):
        ep = b["episode"]
        mf = b["manifest"]
        meta = ep["meta"]
        guest = ep.get("guest", {})
        notes = ep.get("learned_notes", {})
        sp_feat = meta.get("special_feature")
        ep_img = resolve_episode_image(
            b,
            editorial_plan=editorial_plan,
            weekly_banners=weekly_banners,
        )
        items.append(
            {
                "slug": b["slug"],
                "date": meta["episode_date"],
                "episode_number": meta["episode_number"],
                "episode_label": meta.get("episode_label") or f"第{meta['episode_number']}回",
                "is_spinoff": bool(meta.get("is_spinoff")),
                "weekday": meta.get("weekday", ""),
                "weekday_ja": meta.get("weekday_ja", ""),
                "theme_name": meta.get("theme_name", ""),
                "edition_label": meta.get("edition_label", ""),
                "is_holiday": bool(meta.get("is_holiday")),
                "special_title": sp_feat.get("title", "") if isinstance(sp_feat, dict) else "",
                "subtitle": meta["subtitle"],
                "guest_name": guest.get("name", ""),
                "guest_title": guest.get("title", ""),
                "duration": mf["meta"]["total_duration_formatted"],
                "has_audio": b["has_audio"],
                "hero_image": str(ep_img.get("rel_path") or ""),
                "hero_alt": str(ep_img.get("alt") or DEFAULT_HERO_ALT),
                "hero_spot_name": str(ep_img.get("spot_name") or ""),
                "hero_caption": str(ep_img.get("caption") or ""),
                "href": f"episodes/{b['slug']}/index.html",
                "listen_href": f"listen.html?ep={b['slug']}",
                "learned_points": notes.get("learned_points", []),
                "keywords": guest.get("keywords_featured", []),
            }
        )

    nav_html = _render_nav(
        "",
        "archive",
        page_h1="バックナンバー",
        subhead="これまでの放送をいつでも聴く・読むことができます",
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>バックナンバー一覧 | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>
    {COMMON_CSS}
    .filter-bar {{
      display: flex;
      flex-direction: column;
      gap: 0.55rem;
      padding: 0.75rem 0.9rem;
      border-bottom: 1px solid var(--border);
      background: #fcfcfa;
    }}
    .search-input {{
      width: 100%;
      padding: 0.5rem 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: 16px;
      font-family: inherit;
    }}
    .day-pills {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0.35rem;
    }}
    .day-pills button {{
      width: 100%;
      padding: 0.38rem 0.2rem;
    }}
    .day-pills button.active {{
      background: var(--forest);
      color: #fff;
      border-color: var(--forest);
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      {nav_html}
    </div>
  </header>

  <main class="container single">
    <div class="card">
      <div class="panel-body" style="display:flex; flex-direction:row; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:0.65rem;">
        <div style="font-size:0.85rem; min-width:220px; flex:1 1 260px;">
          <strong>📅 今後の放送予定や番組の仕組みもチェック！</strong>
          <div style="color:var(--muted); font-size:0.8rem;">専門家解説テーマの事前カレンダーや、約15分の制作裏話対談も公開中です。</div>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:0.45rem;">
          <a class="btn-link" href="calendar.html">放送内容カレンダー →</a>
          <a class="btn-link" style="background:#0891b2;" href="tech.html#audio-talk">技術解説・15分対談 →</a>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="filter-bar">
        <input type="search" id="search-input" class="search-input" placeholder="キーワード検索（例：GIS、小川パレット、星野…）" />
        <div class="day-pills" id="day-pills">
          <button type="button" data-day="all" class="active">すべて</button>
          <button type="button" data-day="monday">月</button>
          <button type="button" data-day="tuesday">火</button>
          <button type="button" data-day="wednesday">水</button>
          <button type="button" data-day="thursday">木</button>
          <button type="button" data-day="friday">金</button>
          <button type="button" data-day="saturday">土</button>
          <button type="button" data-day="sunday">日</button>
        </div>
      </div>
      <div class="archive-grid" id="archive-grid"></div>
    </div>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）</footer>

  <script type="application/json" id="archive-data">{_safe_json_for_html(items)}</script>
  <script>
    (function () {{
      const items = JSON.parse(document.getElementById("archive-data").textContent);
      const grid = document.getElementById("archive-grid");
      const searchInput = document.getElementById("search-input");
      const dayButtons = Array.from(document.querySelectorAll("#day-pills button"));
      let selectedDay = "all";

      function render() {{
        const q = (searchInput.value || "").trim().toLowerCase();
        grid.innerHTML = "";
        const filtered = items.filter((it) => {{
          if (selectedDay !== "all" && it.weekday !== selectedDay) return false;
          if (!q) return true;
          const hay = [
            it.date, it.theme_name, it.subtitle, it.guest_name,
            ...(it.keywords || []), ...(it.learned_points || [])
          ].join(" ").toLowerCase();
          return hay.includes(q);
        }});
        if (filtered.length === 0) {{
          const empty = document.createElement("p");
          empty.style.color = "var(--muted)";
          empty.textContent = "条件に一致するバックナンバーが見つかりませんでした。";
          grid.appendChild(empty);
          return;
        }}
        filtered.forEach((it) => {{
          const card = document.createElement("article");
          card.className = "archive-card";
          if (it.hero_image) {{
            const thumbWrap = document.createElement("div");
            thumbWrap.className = "archive-thumb-wrap";
            const img = document.createElement("img");
            img.className = "archive-thumb";
            img.src = it.hero_image;
            img.alt = it.hero_alt || it.theme_name;
            img.loading = "lazy";
            thumbWrap.appendChild(img);
            const spotText = (it.hero_caption || it.hero_spot_name || "").trim();
            if (spotText) {{
              const badge = document.createElement("span");
              badge.className = "archive-spot-badge";
              badge.textContent = "📍 " + spotText;
              thumbWrap.appendChild(badge);
            }}
            card.appendChild(thumbWrap);
          }}
          const tag = document.createElement("span");
          tag.className = "pill-tag";
          tag.textContent = it.episode_label + " ・ " + it.date + "（" + it.weekday_ja + "）";
          card.appendChild(tag);
          if (it.is_holiday || it.special_title || it.is_spinoff) {{
            const ed = document.createElement("span");
            ed.className = "edition-pill";
            ed.style.fontSize = "0.72rem";
            ed.textContent = it.special_title ? (it.edition_label + " ／ " + it.special_title) : it.edition_label;
            card.appendChild(ed);
          }}
          const h3 = document.createElement("h3");
          h3.style.margin = "0.2rem 0";
          h3.style.fontSize = "1rem";
          h3.textContent = it.theme_name;
          const sub = document.createElement("div");
          sub.style.fontSize = "0.84rem";
          sub.style.color = "var(--muted)";
          sub.textContent = it.subtitle;
          const g = document.createElement("div");
          g.style.fontSize = "0.82rem";
          g.textContent = (it.guest_name ? ("ゲスト: " + it.guest_name) : "小春＆平蔵スペシャル") + " ／ " + it.duration + (it.has_audio ? "（音声あり）" : "（台本）");
          const actions = document.createElement("div");
          actions.className = "archive-actions";
          const btn = document.createElement("a");
          btn.className = "btn-link";
          btn.href = it.href;
          btn.textContent = "この回を聴く・台本を読む →";
          const btnListen = document.createElement("a");
          btnListen.className = "btn-link-secondary";
          btnListen.href = it.listen_href || ("listen.html?ep=" + encodeURIComponent(it.slug || it.date));
          btnListen.textContent = "リスナー版で聴く";
          actions.appendChild(btn);
          actions.appendChild(btnListen);
          card.appendChild(h3);
          card.appendChild(sub);
          card.appendChild(g);
          card.appendChild(actions);
          grid.appendChild(card);
        }});
      }}

      searchInput.addEventListener("input", render);
      dayButtons.forEach((b) => {{
        b.addEventListener("click", () => {{
          selectedDay = b.dataset.day || "all";
          dayButtons.forEach((x) => x.classList.toggle("active", x === b));
          render();
        }});
      }});
      render();
    }})();
  </script>
</body>
</html>
"""


def _render_cast_page(
    characters: dict[str, Any],
    themes: dict[str, Any],
    cast_intros_cfg: dict[str, Any],
    intros_manifest: dict[str, Any],
) -> str:
    intros_by_id = {e["id"]: e for e in cast_intros_cfg.get("cast_intros", [])}
    mf_by_id = intros_manifest.get("by_id", {})

    def build_member_payload(
        cid: str,
        name: str,
        reading: str,
        role_sub: str,
        badge: str,
        placeholder_badge: str,
        jump_label: str,
        personality: str,
        sub_detail_label: str,
        sub_detail: str,
        fallback_chips: list[str],
        voice_name: str,
        ui_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        color = ui_cfg.get("color", "#1b5e3c")
        bg_soft = ui_cfg.get("bg_soft", "#f0f9ff")
        intro_cfg = intros_by_id.get(cid, {})
        mf = mf_by_id.get(cid, {})
        mp3_rel = mf.get("mp3_rel") or f"audio/intros/intro_{cid}.mp3"
        mp3_path = DOCS_DIR / mp3_rel
        has_audio = mp3_path.exists() and mp3_path.stat().st_size > 10_000
        dur_sec = float(mf.get("duration_sec") or 0.0)
        dur_fmt = mf.get("duration_formatted") or fmt_tc(dur_sec)
        portrait = _resolve_cast_portrait(cid, name, color, bg_soft, placeholder_badge)

        chips: list[str] = []
        for ch in list(intro_cfg.get("highlights") or []) + list(fallback_chips):
            if ch and ch not in chips:
                chips.append(ch)

        return {
            "id": cid,
            "name": name,
            "reading": reading,
            "role_sub": role_sub,
            "badge": badge,
            "jump_label": jump_label,
            "tagline": intro_cfg.get("tagline", ""),
            "personality": personality,
            "sub_detail_label": sub_detail_label,
            "sub_detail": sub_detail,
            "chips": chips[:6],
            "color": color,
            "bg_soft": bg_soft,
            "voice_label": f"Gemini TTS ({voice_name})",
            "portrait": portrait,
            "audio_src": mp3_rel,
            "has_audio": has_audio,
            "duration_sec": dur_sec,
            "duration_formatted": dur_fmt,
            "intro_text": intro_cfg.get("text", ""),
        }

    hosts_out: list[dict[str, Any]] = []
    for h in characters.get("hosts", {}).values():
        clean_habits = [_strip_tts_tag_hints(s) for s in h.get("speaking_habits", [])]
        clean_habits = [s for s in clean_habits if s]
        hosts_out.append(
            build_member_payload(
                cid=h["id"],
                name=h["name"],
                reading=h["reading"],
                role_sub=h["role"],
                badge="レギュラーキャスター",
                placeholder_badge="キャスター",
                jump_label=h["name"],
                personality=h["personality"],
                sub_detail_label="トーク・進行の特徴",
                sub_detail=" ／ ".join(clean_habits),
                fallback_chips=clean_habits,
                voice_name=h["tts"]["gemini_voice"],
                ui_cfg=h.get("ui", {}),
            )
        )

    guests_out: list[dict[str, Any]] = []
    for day_cfg in themes.get("days", {}).values():
        g = day_cfg["guest"]
        day_short = day_cfg["weekday_ja"][:1]
        ed = "15分特集" if day_cfg.get("is_weekend") else "10分"
        guests_out.append(
            build_member_payload(
                cid=g["id"],
                name=g["name"],
                reading=g["reading"],
                role_sub=g["title"],
                badge=f"{day_cfg['weekday_ja']}（{ed}）・{day_cfg['theme_name']}",
                placeholder_badge=f"{day_cfg['weekday_ja']}ゲスト",
                jump_label=f"{day_short}：{g['name']}",
                personality=g["personality"],
                sub_detail_label="小平市とのつながり・注目テーマ",
                sub_detail=g.get("kodaira_connection", ""),
                fallback_chips=g.get("keywords_bank", [])[:4],
                voice_name=g["voice_name"],
                ui_cfg=g.get("ui", {}),
            )
        )

    payload = {
        "hosts": hosts_out,
        "guests": guests_out,
    }
    has_placeholder = any(
        m["portrait"]["is_placeholder"] for m in hosts_out + guests_out
    )
    if has_placeholder:
        cast_footnote = (
            "※ 一部出演者の胸上イラストは制作準備中のため仮アイコンを表示しています（イラストが完成しだい順次切り替わります）。"
            "自己紹介音声は Gemini 3.8 Flash TTS により各キャスター専用ボイスで収録しています。"
        )
    else:
        cast_footnote = (
            "※ 全出演者の胸上イラストは小平の朝スタジオをテーマに描き下ろしたオリジナルイメージです。"
            "自己紹介音声は Gemini 3.8 Flash TTS により各キャスター専用ボイスで収録しています。"
        )
    nav_html = _render_nav(
        "",
        "cast",
        page_h1="出演者紹介",
        subhead="小春・平蔵と7人の防災専門家ゲスト — プロフィール＆自己紹介ボイス",
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>出演者紹介 | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>
    {COMMON_CSS}
    .cast-jump-card {{
      padding: 0.78rem 0.9rem;
      margin-bottom: 0.85rem;
    }}
    .cast-jump-title {{
      font-size: 0.8rem;
      font-weight: 700;
      color: var(--muted);
      margin: 0 0 0.45rem;
    }}
    .cast-jump-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.36rem;
    }}
    .cast-jump-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      text-decoration: none;
      font-size: 0.78rem;
      font-weight: 700;
      padding: 0.28rem 0.62rem;
      border-radius: 999px;
      background: #fff;
      border: 1px solid var(--border);
      color: var(--ink);
    }}
    .cast-jump-link:hover {{
      background: var(--forest-soft);
      border-color: var(--forest);
    }}
    .cast-jump-dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      flex: 0 0 auto;
    }}
    .cast-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.85rem;
      padding: 0.85rem;
    }}
    .cast-card {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 0.9rem;
      background: #fff;
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
      min-width: 0;
      overflow-wrap: anywhere;
      scroll-margin-top: 1rem;
      transition: box-shadow 0.15s;
    }}
    .cast-card.is-playing {{
      box-shadow: 0 8px 24px rgba(18, 64, 40, 0.16);
    }}
    .cast-head {{
      display: grid;
      grid-template-columns: 96px minmax(0, 1fr);
      gap: 0.75rem;
      align-items: start;
      min-width: 0;
    }}
    .cast-avatar-wrap {{
      width: 96px;
      aspect-ratio: 1 / 1;
      border-radius: 14px;
      overflow: hidden;
      border: 2px solid var(--border);
      background: #f8fafc;
    }}
    .cast-avatar {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center top;
      display: block;
    }}
    .cast-head-info {{
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 0.22rem;
    }}
    .cast-badge {{
      display: inline-block;
      align-self: flex-start;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.14rem 0.5rem;
      border-radius: 999px;
    }}
    .cast-name {{
      margin: 0.06rem 0 0;
      font-size: 1.08rem;
      line-height: 1.3;
    }}
    .cast-reading {{
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--muted);
    }}
    .cast-role-sub {{
      font-size: 0.78rem;
      color: var(--muted);
      line-height: 1.4;
    }}
    .cast-tagline {{
      font-size: 0.84rem;
      font-weight: 700;
      color: var(--ink);
      line-height: 1.45;
    }}
    .intro-player {{
      border-radius: 12px;
      padding: 0.65rem 0.75rem;
      border: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 0.42rem;
      min-width: 0;
    }}
    .intro-player-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      flex-wrap: wrap;
      min-width: 0;
    }}
    .intro-play-btn {{
      border: none;
      color: #fff;
      font-weight: 700;
      font-size: 0.82rem;
      padding: 0.42rem 0.85rem;
      border-radius: 999px;
      cursor: pointer;
      min-height: 38px;
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
    }}
    .intro-play-btn:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    .intro-time {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--ink);
      flex: 0 0 auto;
      white-space: nowrap;
    }}
    .intro-scrub {{
      width: 100%;
      height: 6px;
      margin: 0.05rem 0;
      cursor: pointer;
    }}
    .intro-voice-tag {{
      font-size: 0.7rem;
      color: var(--muted);
    }}
    .intro-script-details {{
      border-top: 1px dashed rgba(0, 0, 0, 0.14);
      padding-top: 0.35rem;
      font-size: 0.82rem;
    }}
    .intro-script-details summary {{
      cursor: pointer;
      font-weight: 700;
      font-size: 0.78rem;
      color: var(--forest);
      list-style: none;
    }}
    .intro-script-details summary::-webkit-details-marker {{ display: none; }}
    .intro-script-text {{
      margin: 0.4rem 0 0;
      line-height: 1.68;
      color: var(--ink);
    }}
    .cast-body {{
      font-size: 0.85rem;
      line-height: 1.65;
      color: var(--ink);
      display: flex;
      flex-direction: column;
      gap: 0.45rem;
    }}
    .cast-sub-box {{
      background: #f9faf8;
      border-radius: 9px;
      padding: 0.52rem 0.68rem;
      border: 1px solid var(--border);
      font-size: 0.81rem;
      line-height: 1.58;
    }}
    .cast-sub-box strong {{
      display: block;
      font-size: 0.75rem;
      color: var(--forest);
      margin-bottom: 0.15rem;
    }}
    .cast-footnote {{
      font-size: 0.78rem;
      color: var(--muted);
      padding: 0.7rem 0.9rem;
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 12px;
      line-height: 1.6;
    }}
    @media (max-width: 860px) {{
      .cast-grid {{
        grid-template-columns: minmax(0, 1fr);
        padding: 0.65rem;
        gap: 0.75rem;
      }}
    }}
    @media (max-width: 640px) {{
      .cast-head {{
        grid-template-columns: 82px minmax(0, 1fr);
        gap: 0.6rem;
      }}
      .cast-avatar-wrap {{
        width: 82px;
        border-radius: 12px;
      }}
      .cast-card {{ padding: 0.78rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      {nav_html}
    </div>
  </header>

  <main class="container single">
    <audio id="cast-audio" preload="none"></audio>

    <div class="card cast-jump-card">
      <div class="cast-jump-title">出演者クイックジャンプ（タップで移動）</div>
      <div class="cast-jump-row" id="cast-jump-row"></div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>レギュラーキャスター（小平の「小」と「平」）</h2>
        <span class="hint">毎日朝7時ナビゲート</span>
      </div>
      <div class="cast-grid" id="cast-hosts-grid"></div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>曜日別 防災専門家ゲスト（月〜日・架空キャラクター）</h2>
        <span class="hint">平日10分／土日祝15分</span>
      </div>
      <div class="cast-grid" id="cast-guests-grid"></div>
    </div>

    <div class="cast-footnote">
      {html.escape(cast_footnote)}
    </div>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ <a href="characters.html">累積防災ノートへ →</a></footer>

  <script type="application/json" id="cast-data">{_safe_json_for_html(payload)}</script>
  <script>
    (function () {{
      const data = JSON.parse(document.getElementById("cast-data").textContent);
      const audio = document.getElementById("cast-audio");
      const jumpRow = document.getElementById("cast-jump-row");
      const hostsGrid = document.getElementById("cast-hosts-grid");
      const guestsGrid = document.getElementById("cast-guests-grid");

      const controllers = new Map();
      let activeId = null;
      let isScrubbing = false;

      function fmtTime(sec) {{
        const s = Math.max(0, Math.floor(sec || 0));
        return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
      }}

      function resetController(cid) {{
        const ctrl = controllers.get(cid);
        if (!ctrl) return;
        ctrl.card.classList.remove("is-playing");
        ctrl.btnPlay.textContent = "▶ 自己紹介を聴く";
        ctrl.scrub.value = "0";
        ctrl.timeEl.textContent = "00:00 / " + fmtTime(ctrl.estDur);
      }}

      function startOrToggle(item) {{
        const ctrl = controllers.get(item.id);
        if (!ctrl || !item.has_audio) return;

        if (activeId === item.id) {{
          if (audio.paused) {{
            audio.play().catch(() => {{}});
          }} else {{
            audio.pause();
          }}
          return;
        }}

        if (activeId) {{
          audio.pause();
          resetController(activeId);
        }}

        activeId = item.id;
        ctrl.card.classList.add("is-playing");
        audio.src = item.audio_src;
        audio.currentTime = 0;
        ctrl.btnPlay.textContent = "❚❚ 読み込み中…";
        audio.play().catch(() => {{
          ctrl.btnPlay.textContent = "▶ 自己紹介を聴く";
        }});
      }}

      function renderCard(item, container) {{
        const card = document.createElement("article");
        card.className = "cast-card";
        card.id = item.id;
        card.style.borderTop = "4px solid " + item.color;

        const head = document.createElement("div");
        head.className = "cast-head";

        const avatarWrap = document.createElement("div");
        avatarWrap.className = "cast-avatar-wrap";
        avatarWrap.style.borderColor = item.color;
        const img = document.createElement("img");
        img.className = "cast-avatar";
        img.src = item.portrait.src;
        img.alt = item.name + "のポートレート";
        img.loading = "lazy";
        avatarWrap.appendChild(img);

        const info = document.createElement("div");
        info.className = "cast-head-info";

        const badge = document.createElement("span");
        badge.className = "cast-badge";
        badge.style.background = item.bg_soft;
        badge.style.color = item.color;
        badge.textContent = item.badge;

        const nameH3 = document.createElement("h3");
        nameH3.className = "cast-name";
        nameH3.textContent = item.name + " ";
        const readSpan = document.createElement("span");
        readSpan.className = "cast-reading";
        readSpan.textContent = "（" + item.reading + "）";
        nameH3.appendChild(readSpan);

        const roleSub = document.createElement("div");
        roleSub.className = "cast-role-sub";
        roleSub.textContent = item.role_sub;

        info.appendChild(badge);
        info.appendChild(nameH3);
        info.appendChild(roleSub);

        if (item.tagline) {{
          const tagLine = document.createElement("div");
          tagLine.className = "cast-tagline";
          tagLine.textContent = item.tagline;
          info.appendChild(tagLine);
        }}

        head.appendChild(avatarWrap);
        head.appendChild(info);
        card.appendChild(head);

        const player = document.createElement("div");
        player.className = "intro-player";
        player.style.background = item.bg_soft;

        const pTop = document.createElement("div");
        pTop.className = "intro-player-top";

        const btnPlay = document.createElement("button");
        btnPlay.type = "button";
        btnPlay.className = "intro-play-btn";
        btnPlay.style.background = item.color;
        btnPlay.textContent = item.has_audio ? "▶ 自己紹介を聴く" : "音声準備中";
        btnPlay.disabled = !item.has_audio;

        const timeEl = document.createElement("span");
        timeEl.className = "intro-time";
        timeEl.textContent = "00:00 / " + item.duration_formatted;

        pTop.appendChild(btnPlay);
        pTop.appendChild(timeEl);

        const scrub = document.createElement("input");
        scrub.type = "range";
        scrub.className = "intro-scrub";
        scrub.min = "0";
        scrub.max = String(item.duration_sec || 30);
        scrub.step = "0.1";
        scrub.value = "0";
        scrub.style.accentColor = item.color;
        scrub.setAttribute("aria-label", item.name + "の自己紹介音声シークバー");
        scrub.disabled = !item.has_audio;

        const vTag = document.createElement("div");
        vTag.className = "intro-voice-tag";
        vTag.textContent = "音声ボイス: " + item.voice_label;

        player.appendChild(pTop);
        player.appendChild(scrub);
        player.appendChild(vTag);

        if (item.intro_text) {{
          const det = document.createElement("details");
          det.className = "intro-script-details";
          const sum = document.createElement("summary");
          sum.textContent = "自己紹介メッセージを読む ▾";
          const pTxt = document.createElement("p");
          pTxt.className = "intro-script-text";
          pTxt.textContent = item.intro_text;
          det.appendChild(sum);
          det.appendChild(pTxt);
          player.appendChild(det);
        }}

        card.appendChild(player);

        const body = document.createElement("div");
        body.className = "cast-body";
        const pDesc = document.createElement("p");
        pDesc.style.margin = "0";
        pDesc.textContent = item.personality;
        body.appendChild(pDesc);

        if (item.sub_detail) {{
          const subBox = document.createElement("div");
          subBox.className = "cast-sub-box";
          const subTitle = document.createElement("strong");
          subTitle.textContent = item.sub_detail_label;
          const subTxt = document.createElement("div");
          subTxt.textContent = item.sub_detail;
          subBox.appendChild(subTitle);
          subBox.appendChild(subTxt);
          body.appendChild(subBox);
        }}

        if (item.chips && item.chips.length > 0) {{
          const kw = document.createElement("div");
          kw.className = "kw-wrap";
          item.chips.forEach((ch) => {{
            const chip = document.createElement("span");
            chip.className = "kw-chip";
            chip.textContent = ch;
            kw.appendChild(chip);
          }});
          body.appendChild(kw);
        }}

        card.appendChild(body);
        container.appendChild(card);

        controllers.set(item.id, {{
          item: item,
          card: card,
          btnPlay: btnPlay,
          timeEl: timeEl,
          scrub: scrub,
          estDur: item.duration_sec || 30,
        }});

        btnPlay.addEventListener("click", () => startOrToggle(item));
        scrub.addEventListener("input", () => {{
          isScrubbing = true;
          const ctrl = controllers.get(item.id);
          const total = (activeId === item.id && Number.isFinite(audio.duration)) ? audio.duration : ctrl.estDur;
          ctrl.timeEl.textContent = fmtTime(Number(scrub.value)) + " / " + fmtTime(total);
        }});
        scrub.addEventListener("change", () => {{
          const targetTime = Number(scrub.value);
          if (activeId !== item.id) {{
            if (activeId) {{
              audio.pause();
              resetController(activeId);
            }}
            activeId = item.id;
            controllers.get(item.id).card.classList.add("is-playing");
            audio.src = item.audio_src;
            audio.addEventListener("loadedmetadata", function onMeta() {{
              audio.removeEventListener("loadedmetadata", onMeta);
              audio.currentTime = targetTime;
              audio.play().catch(() => {{}});
            }});
          }} else {{
            audio.currentTime = targetTime;
          }}
          isScrubbing = false;
        }});
      }}

      function addJumpPill(item) {{
        const a = document.createElement("a");
        a.className = "cast-jump-link";
        a.href = "#" + item.id;
        const dot = document.createElement("span");
        dot.className = "cast-jump-dot";
        dot.style.background = item.color;
        a.appendChild(dot);
        a.appendChild(document.createTextNode(item.jump_label));
        jumpRow.appendChild(a);
      }}

      data.hosts.forEach((h) => {{
        addJumpPill(h);
        renderCard(h, hostsGrid);
      }});
      data.guests.forEach((g) => {{
        addJumpPill(g);
        renderCard(g, guestsGrid);
      }});

      audio.addEventListener("loadedmetadata", () => {{
        if (!activeId) return;
        const ctrl = controllers.get(activeId);
        if (!ctrl) return;
        if (Number.isFinite(audio.duration) && audio.duration > 0) {{
          ctrl.estDur = audio.duration;
          ctrl.scrub.max = String(audio.duration);
        }}
        ctrl.timeEl.textContent = fmtTime(audio.currentTime) + " / " + fmtTime(ctrl.estDur);
      }});

      audio.addEventListener("timeupdate", () => {{
        if (!activeId || isScrubbing) return;
        const ctrl = controllers.get(activeId);
        if (!ctrl) return;
        const total = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : ctrl.estDur;
        ctrl.scrub.max = String(total);
        ctrl.scrub.value = String(audio.currentTime);
        ctrl.timeEl.textContent = fmtTime(audio.currentTime) + " / " + fmtTime(total);
      }});

      audio.addEventListener("play", () => {{
        if (!activeId) return;
        const ctrl = controllers.get(activeId);
        if (ctrl) ctrl.btnPlay.textContent = "❚❚ 一時停止";
      }});

      audio.addEventListener("pause", () => {{
        if (!activeId) return;
        const ctrl = controllers.get(activeId);
        if (ctrl && !audio.ended) ctrl.btnPlay.textContent = "▶ 自己紹介を聴く";
      }});

      audio.addEventListener("ended", () => {{
        if (!activeId) return;
        const ctrl = controllers.get(activeId);
        if (ctrl) {{
          ctrl.btnPlay.textContent = "▶ もう一度聴く";
          ctrl.scrub.value = "0";
          ctrl.timeEl.textContent = "00:00 / " + fmtTime(ctrl.estDur);
        }}
      }});
    }})();
  </script>
</body>
</html>
"""


def build_site() -> None:
    """Build all docs/ pages for GitHub Pages and local file:// browsing plus script.md files."""
    ep_dirs = sorted(
        p for p in EPISODES_DIR.iterdir() if p.is_dir() and (p / "episode.json").exists()
    )
    if not ep_dirs:
        raise FileNotFoundError(f"No episodes found under {EPISODES_DIR}")

    characters = _load_json(CONFIG_DIR / "characters.json")
    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    cast_intros_cfg = (
        _load_json(CONFIG_DIR / "cast_intros.json")
        if (CONFIG_DIR / "cast_intros.json").exists()
        else {"cast_intros": []}
    )
    intros_manifest = (
        _load_json(DATA_DIR / "cast_intros_manifest.json")
        if (DATA_DIR / "cast_intros_manifest.json").exists()
        else {"by_id": {}}
    )
    knowledge_log = (
        _load_json(DATA_DIR / "knowledge_log.json")
        if (DATA_DIR / "knowledge_log.json").exists()
        else {"entries": []}
    )
    special_days = (
        _load_json(CONFIG_DIR / "special_days.json")
        if (CONFIG_DIR / "special_days.json").exists()
        else {"recurring": [], "dated_events": []}
    )
    editorial_plan = (
        _load_json(DATA_DIR / "editorial_plan.json")
        if (DATA_DIR / "editorial_plan.json").exists()
        else None
    )
    weekly_banners = load_weekly_banners()
    program_schedule = (
        _load_json(CONFIG_DIR / "program_schedule.json")
        if (CONFIG_DIR / "program_schedule.json").exists()
        else None
    )
    topic_history = (
        _load_json(DATA_DIR / "topic_history.json")
        if (DATA_DIR / "topic_history.json").exists()
        else {"entries": []}
    )
    kodaira_spots = load_kodaira_spots(CONFIG_DIR / "kodaira_spots.json")
    spot_reports = load_spot_reports()
    tech_bundle = (
        _load_episode_bundle(TECH_TALK_DIR)
        if (TECH_TALK_DIR / "episode.json").exists()
        else None
    )

    bundles = [_load_episode_bundle(p) for p in ep_dirs]
    site_base_url = resolve_site_base_url(characters)
    program_title = str((characters.get("program") or {}).get("title") or "毎朝7時！こだいら防災＆まちラジオ")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    for bundle in bundles:
        generate_script_md(bundle)
        ep_slug = bundle["slug"]
        ep_out_dir = DOCS_DIR / "episodes" / ep_slug
        ep_out_dir.mkdir(parents=True, exist_ok=True)
        ep_html = _render_episode_page(
            bundle,
            bundles,
            root_prefix="../../",
            is_home=False,
            editorial_plan=editorial_plan,
            site_base_url=site_base_url,
            weekly_banners=weekly_banners,
        )
        (ep_out_dir / "index.html").write_text(ep_html, encoding="utf-8")

        share_out_dir = DOCS_DIR / "share" / ep_slug
        share_out_dir.mkdir(parents=True, exist_ok=True)
        share_html = render_share_redirect_page(
            bundle,
            site_base_url=site_base_url,
            editorial_plan=editorial_plan,
            program_title=program_title,
            weekly_banners=weekly_banners,
        )
        (share_out_dir / "index.html").write_text(share_html, encoding="utf-8")

    if tech_bundle:
        generate_script_md(tech_bundle)

    sorted_for_latest = sorted(
        bundles,
        key=lambda b: (
            b["episode"]["meta"]["episode_date"],
            0 if b["episode"]["meta"].get("is_spinoff") else 1,
            b["slug"],
        ),
    )
    latest = sorted_for_latest[-1]
    today_jst_str = datetime.now(JST).date().isoformat()

    (DOCS_DIR / "index.html").write_text(
        _render_episode_page(
            latest,
            bundles,
            root_prefix="",
            is_home=True,
            editorial_plan=editorial_plan,
            site_base_url=site_base_url,
            weekly_banners=weekly_banners,
        ),
        encoding="utf-8",
    )
    (DOCS_DIR / "listen.html").write_text(
        render_listen_page(
            bundles=sorted_for_latest,
            characters=characters,
            themes=themes,
            safe_json_fn=_safe_json_for_html,
            editorial_plan=editorial_plan,
            site_base_url=site_base_url,
            weekly_banners=weekly_banners,
        ),
        encoding="utf-8",
    )
    (DOCS_DIR / "calendar.html").write_text(
        render_calendar_page(
            bundles=bundles,
            themes=themes,
            special_days=special_days,
            editorial_plan=editorial_plan,
            program_schedule=program_schedule,
            topic_history=topic_history,
            today_jst_str=today_jst_str,
            common_css=COMMON_CSS,
            nav_html=_render_nav(
                "",
                "calendar",
                page_h1="放送内容カレンダー",
                subhead="過去の放送実績と今後の専門家解説テーマ予定（リクエスト随時受付）",
            ),
            safe_json_fn=_safe_json_for_html,
            kodaira_spots=kodaira_spots,
            spot_reports=spot_reports,
        ),
        encoding="utf-8",
    )
    spot_ctx = build_spot_dossier_context(
        kodaira_spots=kodaira_spots,
        spot_reports=spot_reports,
        topic_history=topic_history,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        bundles=bundles,
        today_jst_str=today_jst_str,
    )
    spots_out_dir = DOCS_DIR / "spots"
    spots_out_dir.mkdir(parents=True, exist_ok=True)
    (spots_out_dir / "index.html").write_text(
        render_spots_index_page(
            kodaira_spots=kodaira_spots,
            spot_reports=spot_reports,
            ctx=spot_ctx,
            common_css=COMMON_CSS,
            nav_html=_render_nav(
                "../",
                "spots",
                page_h1="小平スポット取材手帳",
                subhead="一次ソース検証×写真ベースイラストで読む地域の魅力レポート",
            ),
            safe_json_fn=_safe_json_for_html,
        ),
        encoding="utf-8",
    )
    for sid in spot_ctx["ordered_ids"]:
        spot_page_dir = spots_out_dir / sid
        spot_page_dir.mkdir(parents=True, exist_ok=True)
        (spot_page_dir / "index.html").write_text(
            render_spot_detail_page(
                spot_id=sid,
                dossier=spot_reports[sid],
                spot_reports=spot_reports,
                ctx=spot_ctx,
                common_css=COMMON_CSS,
                nav_html=_render_nav(
                    "../../",
                    "spots",
                    subhead="小平スポット取材手帳 ／ 一次情報ベース単独取材レポート",
                ),
            ),
            encoding="utf-8",
        )
    (DOCS_DIR / "archive.html").write_text(
        _render_archive_page(
            bundles,
            editorial_plan=editorial_plan,
            weekly_banners=weekly_banners,
        ),
        encoding="utf-8",
    )
    (DOCS_DIR / "cast.html").write_text(
        _render_cast_page(characters, themes, cast_intros_cfg, intros_manifest),
        encoding="utf-8",
    )
    (DOCS_DIR / "characters.html").write_text(
        render_notebook_page(
            knowledge_log=knowledge_log,
            bundles=bundles,
            characters=characters,
            themes=themes,
            common_css=COMMON_CSS,
            nav_html=_render_nav(
                "",
                "characters",
                page_h1="防災ノート",
                subhead="小春と平蔵が毎朝書きためる手書き・防災＆こだいら発見日記",
            ),
            safe_json_fn=_safe_json_for_html,
        ),
        encoding="utf-8",
    )
    (DOCS_DIR / "tech.html").write_text(
        render_tech_page(
            tech_bundle=tech_bundle,
            characters=characters,
            themes=themes,
            common_css=COMMON_CSS,
            nav_html=_render_nav(
                "",
                "tech",
                page_h1="番組のしくみ・技術解説",
                subhead="小春・平蔵・AIオーケストレーター ネオンさんが徹底解説（約15分対談＋図解）",
            ),
            safe_json_fn=_safe_json_for_html,
        ),
        encoding="utf-8",
    )

    print(f"Site built successfully in {DOCS_DIR} ({len(bundles)} episode(s))")


def main() -> None:
    build_site()


if __name__ == "__main__":
    main()
