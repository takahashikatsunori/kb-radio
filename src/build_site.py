"""Build GitHub Pages and local file:// compatible portal in docs/ plus script.md."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
EPISODES_DIR = ROOT_DIR / "episodes"
DOCS_DIR = ROOT_DIR / "docs"
DOCS_AUDIO_DIR = DOCS_DIR / "audio"

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

    lines_out: list[str] = [
        f"# {meta['title']}",
        "",
        f"**{meta['subtitle']}**",
        "",
        f"- **放送日**: {meta['episode_date']}（{meta.get('weekday_ja', '')}・第{meta['episode_number']}回）",
        f"- **テーマ**: {meta.get('theme_name', '')}",
        f"- **想定/収録時間**: {mf_meta['total_duration_formatted']}（{mf_meta['total_duration_sec']:.1f}秒）{est_label}",
        f"- **レギュラー出演**: 小春（メインパーソナリティ）／ 平蔵（パートナーキャスター）",
        f"- **本日の専門家ゲスト**: {guest.get('name', 'なし')}（{guest.get('title', '')}）",
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
  --shadow: 0 8px 24px rgba(18, 64, 40, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", system-ui, -apple-system, sans-serif;
  background: var(--paper);
  color: var(--ink);
  line-height: 1.65;
}
a { color: var(--forest); }
header {
  background: linear-gradient(135deg, var(--forest-dark) 0%, var(--forest) 65%, #2b7a50 100%);
  color: #ffffff;
  border-bottom: 4px solid var(--amber);
}
.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.15rem 1.25rem 1.45rem;
}
.top-nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.9rem;
}
.brand {
  font-weight: 800;
  font-size: 1.05rem;
  color: #fff;
  text-decoration: none;
  letter-spacing: 0.02em;
}
.nav-links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.nav-links a {
  color: rgba(255,255,255,0.92);
  text-decoration: none;
  font-size: 0.86rem;
  font-weight: 600;
  padding: 0.32rem 0.78rem;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.28);
  background: rgba(255,255,255,0.10);
  transition: background 0.15s;
}
.nav-links a:hover, .nav-links a.active {
  background: #ffffff;
  color: var(--forest-dark);
  border-color: #ffffff;
}
.badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.55rem;
  font-size: 0.78rem;
}
.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.18rem 0.65rem;
  border-radius: 999px;
  background: rgba(255,255,255,0.16);
  border: 1px solid rgba(255,255,255,0.28);
  font-weight: 600;
}
.badge.accent {
  background: var(--amber);
  border-color: var(--amber);
  color: #fff;
}
h1 {
  margin: 0 0 0.25rem;
  font-size: clamp(1.3rem, 2.5vw, 1.85rem);
}
.subtitle {
  margin: 0;
  color: rgba(255,255,255,0.9);
  font-size: 0.94rem;
}
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.25rem;
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(310px, 0.95fr);
  gap: 1.25rem;
  align-items: start;
}
.container.single {
  grid-template-columns: 1fr;
}
@media (max-width: 920px) {
  .container { grid-template-columns: 1fr; }
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow);
  overflow: hidden;
  margin-bottom: 1rem;
}
.section-head {
  padding: 0.8rem 1.1rem;
  background: #fcfcfa;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}
.section-head h2 {
  margin: 0;
  font-size: 0.98rem;
  color: var(--forest-dark);
}
.hint {
  font-size: 0.78rem;
  color: var(--muted);
}
.player-card {
  position: sticky;
  top: 0.65rem;
  z-index: 20;
  padding: 1rem 1.15rem;
  border-top: 4px solid var(--forest);
}
.audio-pending-banner {
  background: var(--amber-soft);
  border: 1px solid #f59e0b;
  color: #92400e;
  border-radius: 8px;
  padding: 0.55rem 0.8rem;
  font-size: 0.83rem;
  margin-bottom: 0.75rem;
}
.now-playing {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.75rem;
  margin-bottom: 0.45rem;
}
.now-label {
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--forest);
}
.now-chapter {
  font-size: 0.96rem;
  font-weight: 700;
}
.time-readout {
  font-variant-numeric: tabular-nums;
  font-size: 0.88rem;
  font-weight: 700;
  color: var(--heizo);
  white-space: nowrap;
}
.scrubber {
  width: 100%;
  accent-color: var(--forest);
  cursor: pointer;
  height: 6px;
  margin: 0.35rem 0 0.7rem;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.btn-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
button {
  font-family: inherit;
  cursor: pointer;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--ink);
  padding: 0.4rem 0.72rem;
  font-size: 0.83rem;
  font-weight: 600;
}
button:hover:not(:disabled) {
  background: var(--forest-soft);
  border-color: var(--forest);
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
button.primary {
  background: var(--forest);
  border-color: var(--forest);
  color: #fff;
  padding: 0.46rem 1.05rem;
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
.chapter-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.5rem;
  padding: 0.85rem 1.05rem;
}
.chapter-btn {
  text-align: left;
  padding: 0.55rem 0.7rem;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}
.chapter-btn.active {
  background: var(--forest-soft);
  border-color: var(--forest);
  box-shadow: inset 3px 0 0 var(--forest);
}
.chapter-tc {
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  color: var(--heizo);
  font-weight: 700;
}
.chapter-title {
  font-size: 0.84rem;
  line-height: 1.35;
}
.transcript-body {
  padding: 0.85rem 1.05rem 1.3rem;
  max-height: 68vh;
  overflow-y: auto;
}
.seg-divider {
  margin: 1.1rem 0 0.6rem;
  padding: 0.42rem 0.72rem;
  background: var(--forest-soft);
  border-left: 4px solid var(--forest);
  border-radius: 6px;
  font-weight: 700;
  font-size: 0.9rem;
  color: var(--forest-dark);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.seg-divider:first-child { margin-top: 0; }
.line-item {
  display: grid;
  grid-template-columns: 48px 86px minmax(0, 1fr);
  gap: 0.5rem;
  padding: 0.52rem 0.6rem;
  border-radius: 10px;
  cursor: pointer;
  border: 1px solid transparent;
  align-items: baseline;
}
.line-item:hover { background: #f3f5f2; }
.line-item.active {
  background: var(--amber-soft);
  border-color: #f59e0b;
}
.line-tc {
  font-variant-numeric: tabular-nums;
  font-size: 0.76rem;
  color: var(--muted);
  font-weight: 600;
}
.speaker-pill {
  font-size: 0.74rem;
  font-weight: 700;
  text-align: center;
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.speaker-koharu { background: var(--koharu-soft); color: var(--koharu); }
.speaker-heizo { background: var(--heizo-soft); color: var(--heizo); }
.speaker-guest { background: var(--guest-soft); color: var(--guest); }
.line-text { font-size: 0.93rem; }
.panel-body {
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.link-card {
  display: block;
  text-decoration: none;
  color: inherit;
  padding: 0.7rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fcfcfa;
  transition: border-color 0.15s, background 0.15s, transform 0.08s;
}
.link-card:hover {
  border-color: var(--forest);
  background: var(--forest-soft);
  transform: translateY(-1px);
}
.pill-tag {
  display: inline-block;
  font-size: 0.71rem;
  font-weight: 700;
  padding: 0.1rem 0.48rem;
  border-radius: 999px;
  background: var(--forest-soft);
  color: var(--forest-dark);
  margin-bottom: 0.25rem;
}
.link-title {
  font-size: 0.89rem;
  font-weight: 700;
  color: var(--forest-dark);
  margin: 0 0 0.2rem;
}
.link-note {
  font-size: 0.8rem;
  color: var(--muted);
  margin: 0;
}
.note-box {
  padding: 0.72rem 0.85rem;
  border-radius: 10px;
  background: #fcfcfa;
  border: 1px solid var(--border);
  font-size: 0.85rem;
}
.note-box ul {
  margin: 0.35rem 0 0.45rem;
  padding-left: 1.15rem;
}
.guest-card {
  padding: 0.85rem 1rem;
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
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 1rem;
  padding: 1rem;
}
.archive-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.95rem;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.btn-link {
  display: inline-block;
  text-decoration: none;
  background: var(--forest);
  color: #fff;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.38rem 0.8rem;
  border-radius: 8px;
  text-align: center;
}
.btn-link:hover { background: var(--forest-dark); }
footer {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem 1.25rem 2.2rem;
  font-size: 0.8rem;
  color: var(--muted);
  text-align: center;
}
"""


def _render_nav(root_prefix: str, active: str) -> str:
    def cls(key: str) -> str:
        return ' class="active"' if active == key else ""

    return (
        f'<nav class="top-nav">'
        f'<a class="brand" href="{root_prefix}index.html">毎朝7時！こだいら防災＆まちラジオ</a>'
        f'<div class="nav-links">'
        f'<a href="{root_prefix}index.html"{cls("latest")}>最新回を聴く</a>'
        f'<a href="{root_prefix}archive.html"{cls("archive")}>バックナンバー</a>'
        f'<a href="{root_prefix}characters.html"{cls("characters")}>出演者＆防災ノート</a>'
        f'</div></nav>'
    )


def _render_episode_page(
    bundle: dict[str, Any],
    all_bundles: list[dict[str, Any]],
    root_prefix: str,
    is_home: bool,
) -> str:
    episode = bundle["episode"]
    manifest = bundle["manifest"]
    meta = episode["meta"]
    mf_meta = manifest["meta"]
    guest = episode.get("guest", {})
    guest_ui = meta["voices"].get("guest", {}).get("ui", {"color": "#4338ca", "bg_soft": "#eef2ff"})

    audio_rel = f"{root_prefix}audio/{meta['output_filename']}"
    payload = {
        "meta": meta,
        "manifest_meta": mf_meta,
        "guest": guest,
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
                "href": f"{root_prefix}episodes/{b['episode']['meta']['episode_date']}/index.html",
                "has_audio": b["has_audio"],
            }
            for b in reversed(all_bundles[-7:])
        ],
    }

    title_esc = html.escape(meta["title"])
    subtitle_esc = html.escape(meta["subtitle"])
    theme_badge_esc = html.escape(meta.get("theme_badge", meta.get("theme_name", "")))
    date_esc = html.escape(meta["episode_date"])
    dur_esc = html.escape(mf_meta["total_duration_formatted"])
    est_suffix = "（予定）" if mf_meta.get("estimated") else ""
    nav_html = _render_nav(root_prefix, "latest" if is_home else "archive")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title_esc} | {date_esc}</title>
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
      <div class="badge-row">
        <span class="badge accent">{theme_badge_esc}</span>
        <span class="badge">放送日: {date_esc}（{html.escape(meta.get("weekday_ja", ""))}）</span>
        <span class="badge">収録時間: {dur_esc}{est_suffix}</span>
        <span class="badge">ゲスト: {html.escape(guest.get("name", ""))}</span>
      </div>
      <h1>{title_esc}</h1>
      <p class="subtitle">{subtitle_esc}</p>
    </div>
  </header>

  <main class="container">
    <section>
      <div class="card player-card">
        <div id="audio-pending" class="audio-pending-banner" style="display:none;">
          この回のMP3音声はまだ生成されていません（<code>.env</code> に <code>GEMINI_API_KEY</code> を設定し <code>build_radio.py</code> を実行すると音声再生ができます）。下の台本・タイムライン・関連リンクはそのままお読みいただけます。
        </div>
        <audio id="radio-audio" preload="metadata"></audio>
        <div class="now-playing">
          <div>
            <div class="now-label">再生中のコーナー</div>
            <div class="now-chapter" id="now-chapter">再生ボタンを押してお聴きください</div>
          </div>
          <div class="time-readout" id="time-readout">00:00 / {dur_esc}</div>
        </div>
        <input type="range" class="scrubber" id="scrubber" min="0" max="100" step="0.1" value="0" aria-label="再生位置シークバー" />
        <div class="controls">
          <div class="btn-group">
            <button type="button" class="primary" id="btn-play">▶ 再生</button>
            <button type="button" id="btn-back">↺ 15秒</button>
            <button type="button" id="btn-fwd">15秒 ↻</button>
          </div>
          <div class="btn-group speed-group" id="speed-group">
            <button type="button" data-rate="0.9">0.9x</button>
            <button type="button" data-rate="1" class="is-selected">1.0x</button>
            <button type="button" data-rate="1.15">1.15x</button>
            <button type="button" data-rate="1.25">1.25x</button>
          </div>
          <button type="button" id="btn-autoscroll" class="active-toggle">自動スクロール: ON</button>
        </div>
      </div>

      <div class="card">
        <div class="section-head">
          <h2>チャプタージャンプ</h2>
          <span class="hint">クリックで各コーナーへ移動</span>
        </div>
        <div class="chapter-list" id="chapter-list"></div>
      </div>

      <div class="card">
        <div class="section-head">
          <h2>同期台本タイムライン</h2>
          <span class="hint">小春（ピンク）・平蔵（ブルー）・ゲスト色分け</span>
        </div>
        <div class="transcript-body" id="transcript-body"></div>
      </div>
    </section>

    <aside>
      <div class="card">
        <div class="section-head">
          <h2>本日のゲスト＆天気</h2>
          <span class="hint">曜日テーマ</span>
        </div>
        <div class="panel-body" id="guest-weather-panel"></div>
      </div>

      <div class="card">
        <div class="section-head">
          <h2>今日の話題・関連リンク</h2>
          <span class="hint">クリックで公式ページへ</span>
        </div>
        <div class="panel-body" id="links-panel"></div>
      </div>

      <div class="card">
        <div class="section-head">
          <h2>小春＆平蔵の防災ノート</h2>
          <span class="hint">今日の学び</span>
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
    </aside>
  </main>

  <footer>
    毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ 小春 ＆ 平蔵
  </footer>

  <script type="application/json" id="episode-data">{_safe_json_for_html(payload)}</script>
  <script>
    (function () {{
      const data = JSON.parse(document.getElementById("episode-data").textContent);
      const audio = document.getElementById("radio-audio");
      const btnPlay = document.getElementById("btn-play");
      const btnBack = document.getElementById("btn-back");
      const btnFwd = document.getElementById("btn-fwd");
      const btnAutoScroll = document.getElementById("btn-autoscroll");
      const scrubber = document.getElementById("scrubber");
      const timeReadout = document.getElementById("time-readout");
      const nowChapter = document.getElementById("now-chapter");
      const chapterList = document.getElementById("chapter-list");
      const transcriptBody = document.getElementById("transcript-body");
      const speedButtons = Array.from(document.querySelectorAll("#speed-group button"));

      let autoScroll = true;
      let isScrubbing = false;
      let lastActiveLineIdx = -1;
      let lastActiveSegId = null;

      function fmtTime(sec) {{
        const s = Math.max(0, Math.floor(sec || 0));
        return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
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

      // Guest & Weather panel
      const gwPanel = document.getElementById("guest-weather-panel");
      const gCard = document.createElement("div");
      gCard.className = "guest-card";
      const gTitle = document.createElement("div");
      gTitle.style.fontWeight = "700";
      gTitle.textContent = (data.guest.name || "") + "（" + (data.guest.title || "") + "）";
      const gDesc = document.createElement("div");
      gDesc.style.fontSize = "0.82rem";
      gDesc.style.marginTop = "0.25rem";
      gDesc.textContent = data.guest.personality || "";
      const kwWrap = document.createElement("div");
      kwWrap.className = "kw-wrap";
      (data.guest.keywords_featured || []).forEach((kw) => {{
        const chip = document.createElement("span");
        chip.className = "kw-chip";
        chip.textContent = kw;
        kwWrap.appendChild(chip);
      }});
      gCard.appendChild(gTitle);
      gCard.appendChild(gDesc);
      gCard.appendChild(kwWrap);
      gwPanel.appendChild(gCard);

      if (data.weather && data.weather.daily && data.weather.daily.length > 0) {{
        const wToday = data.weather.daily[0];
        const wBox = document.createElement("div");
        wBox.className = "note-box";
        wBox.innerHTML = "";
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

      // Clickable links panel
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

      // Learned notes & memos panel
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
        rCon.style.fontSize = "0.8rem";
        rCon.style.fontWeight = "700";
        rCon.style.color = "var(--heizo)";
        rCon.textContent = ref.contact || "";
        rBox.appendChild(rTag);
        rBox.appendChild(rTitle);
        rBox.appendChild(rDet);
        rBox.appendChild(rCon);
        notesPanel.appendChild(rBox);
      }});

      // Recent episodes panel
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
        note.textContent = "ゲスト: " + ep.guest_name + (ep.has_audio ? " ／ 音声あり" : " ／ 台本公開");
        a.appendChild(tag);
        a.appendChild(title);
        a.appendChild(note);
        recentPanel.appendChild(a);
      }});

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
            chapterButtons.get(activeSeg.id).classList.add("active");
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
            if (autoScroll && !audio.paused) {{
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
        btnAutoScroll.textContent = "自動スクロール: " + (autoScroll ? "ON" : "OFF");
        btnAutoScroll.classList.toggle("active-toggle", autoScroll);
      }});
      speedButtons.forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const rate = parseFloat(btn.dataset.rate || "1");
          audio.playbackRate = rate;
          speedButtons.forEach((b) => b.classList.toggle("is-selected", b === btn));
        }});
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
      audio.addEventListener("play", () => {{ btnPlay.textContent = "❚❚ 一時停止"; }});
      audio.addEventListener("pause", () => {{ btnPlay.textContent = "▶ 再生"; }});
      audio.addEventListener("ended", () => {{ btnPlay.textContent = "▶ 再生"; }});
      audio.addEventListener("timeupdate", updateSyncUI);
      audio.addEventListener("loadedmetadata", updateSyncUI);
    }})();
  </script>
</body>
</html>
"""


def _render_archive_page(all_bundles: list[dict[str, Any]]) -> str:
    items = []
    for b in reversed(all_bundles):
        ep = b["episode"]
        mf = b["manifest"]
        meta = ep["meta"]
        guest = ep.get("guest", {})
        notes = ep.get("learned_notes", {})
        items.append(
            {
                "date": meta["episode_date"],
                "episode_number": meta["episode_number"],
                "weekday": meta.get("weekday", ""),
                "weekday_ja": meta.get("weekday_ja", ""),
                "theme_name": meta.get("theme_name", ""),
                "subtitle": meta["subtitle"],
                "guest_name": guest.get("name", ""),
                "guest_title": guest.get("title", ""),
                "duration": mf["meta"]["total_duration_formatted"],
                "has_audio": b["has_audio"],
                "href": f"episodes/{meta['episode_date']}/index.html",
                "learned_points": notes.get("learned_points", []),
                "keywords": guest.get("keywords_featured", []),
            }
        )

    nav_html = _render_nav("", "archive")
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
      flex-wrap: wrap;
      gap: 0.6rem;
      padding: 0.9rem 1rem;
      border-bottom: 1px solid var(--border);
      background: #fcfcfa;
      align-items: center;
    }}
    .search-input {{
      flex: 1 1 240px;
      padding: 0.45rem 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: 0.9rem;
      font-family: inherit;
    }}
    .day-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
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
      <h1>バックナンバー アーカイブ</h1>
      <p class="subtitle">これまでの放送回をいつでも聴く・読むことができます</p>
    </div>
  </header>

  <main class="container single">
    <div class="card">
      <div class="filter-bar">
        <input type="search" id="search-input" class="search-input" placeholder="キーワード検索（例：GIS、小川パレット、星野、防災庁…）" />
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
          const top = document.createElement("div");
          top.innerHTML = "";
          const tag = document.createElement("span");
          tag.className = "pill-tag";
          tag.textContent = "第" + it.episode_number + "回 ・ " + it.date + "（" + it.weekday_ja + "）";
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
          g.textContent = "ゲスト: " + it.guest_name + " ／ 時間: " + it.duration + (it.has_audio ? "（音声あり）" : "（台本）");
          const btn = document.createElement("a");
          btn.className = "btn-link";
          btn.href = it.href;
          btn.textContent = "この回を聴く・台本を読む →";
          card.appendChild(tag);
          card.appendChild(h3);
          card.appendChild(sub);
          card.appendChild(g);
          card.appendChild(btn);
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


def _render_characters_page(
    characters: dict[str, Any],
    themes: dict[str, Any],
    knowledge_log: dict[str, Any],
) -> str:
    payload = {
        "hosts": list(characters["hosts"].values()),
        "days": list(themes["days"].values()),
        "entries": list(reversed(knowledge_log.get("entries", []))),
    }
    nav_html = _render_nav("", "characters")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>出演者＆防災ノート | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>{COMMON_CSS}</style>
</head>
<body>
  <header>
    <div class="header-inner">
      {nav_html}
      <h1>キャスター ＆ 曜日別専門家図鑑・防災ノート</h1>
      <p class="subtitle">小春と平蔵、そして7人の専門家が毎日小平市の暮らしと防災を楽しくお届けします</p>
    </div>
  </header>

  <main class="container single">
    <div class="card">
      <div class="section-head">
        <h2>レギュラーキャスター（小平の「小」と「平」）</h2>
      </div>
      <div class="archive-grid" id="hosts-grid"></div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>曜日別テーマ ＆ 専門家ゲスト（月〜日）</h2>
        <span class="hint">平日は約10分 ／ 土日は約15分特集</span>
      </div>
      <div class="archive-grid" id="guests-grid"></div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>累積「小春＆平蔵の防災・こだいら発見ノート」</h2>
      </div>
      <div class="panel-body" id="log-list"></div>
    </div>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）</footer>

  <script type="application/json" id="char-data">{_safe_json_for_html(payload)}</script>
  <script>
    (function () {{
      const data = JSON.parse(document.getElementById("char-data").textContent);
      const hostsGrid = document.getElementById("hosts-grid");
      data.hosts.forEach((h) => {{
        const c = document.createElement("div");
        c.className = "archive-card";
        c.style.borderTop = "4px solid " + (h.ui ? h.ui.color : "#1b5e3c");
        const title = document.createElement("h3");
        title.style.margin = "0";
        title.textContent = h.name + "（" + h.reading + "）";
        const role = document.createElement("div");
        role.className = "pill-tag";
        role.textContent = h.role;
        const p = document.createElement("p");
        p.style.margin = "0";
        p.style.fontSize = "0.88rem";
        p.textContent = h.personality;
        c.appendChild(role);
        c.appendChild(title);
        c.appendChild(p);
        hostsGrid.appendChild(c);
      }});

      const guestsGrid = document.getElementById("guests-grid");
      data.days.forEach((d) => {{
        const g = d.guest;
        const c = document.createElement("div");
        c.className = "archive-card";
        c.style.borderLeft = "4px solid " + (g.ui ? g.ui.color : "#4338ca");
        const tag = document.createElement("span");
        tag.className = "pill-tag";
        tag.textContent = d.weekday_ja + "（" + (d.is_weekend ? "15分特集" : "10分") + "）: " + d.theme_name;
        const title = document.createElement("h3");
        title.style.margin = "0";
        title.style.fontSize = "1rem";
        title.textContent = g.name + "（" + g.reading + "）";
        const role = document.createElement("div");
        role.style.fontSize = "0.8rem";
        role.style.color = "var(--muted)";
        role.textContent = g.title;
        const desc = document.createElement("p");
        desc.style.margin = "0";
        desc.style.fontSize = "0.85rem";
        desc.textContent = g.personality + " " + g.kodaira_connection;
        c.appendChild(tag);
        c.appendChild(title);
        c.appendChild(role);
        c.appendChild(desc);
        guestsGrid.appendChild(c);
      }});

      const logList = document.getElementById("log-list");
      data.entries.forEach((e) => {{
        const box = document.createElement("div");
        box.className = "note-box";
        const head = document.createElement("strong");
        head.textContent = e.date + "（" + e.weekday + "）テーマ: " + e.theme + " ／ ゲスト: " + e.guest_name;
        const ul = document.createElement("ul");
        (e.learned_points || []).forEach((pt) => {{
          const li = document.createElement("li");
          li.textContent = pt;
          ul.appendChild(li);
        }});
        box.appendChild(head);
        box.appendChild(ul);
        if (e.kodaira_discovery) {{
          const disc = document.createElement("div");
          disc.textContent = "小平発見: " + e.kodaira_discovery;
          box.appendChild(disc);
        }}
        logList.appendChild(box);
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
    knowledge_log = (
        _load_json(DATA_DIR / "knowledge_log.json")
        if (DATA_DIR / "knowledge_log.json").exists()
        else {"entries": []}
    )

    bundles = [_load_episode_bundle(p) for p in ep_dirs]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    for bundle in bundles:
        generate_script_md(bundle)
        ep_date = bundle["episode"]["meta"]["episode_date"]
        ep_out_dir = DOCS_DIR / "episodes" / ep_date
        ep_out_dir.mkdir(parents=True, exist_ok=True)
        ep_html = _render_episode_page(bundle, bundles, root_prefix="../../", is_home=False)
        (ep_out_dir / "index.html").write_text(ep_html, encoding="utf-8")

    latest = bundles[-1]
    (DOCS_DIR / "index.html").write_text(
        _render_episode_page(latest, bundles, root_prefix="", is_home=True),
        encoding="utf-8",
    )
    (DOCS_DIR / "archive.html").write_text(_render_archive_page(bundles), encoding="utf-8")
    (DOCS_DIR / "characters.html").write_text(
        _render_characters_page(characters, themes, knowledge_log), encoding="utf-8"
    )

    print(f"Site built successfully in {DOCS_DIR} ({len(bundles)} episode(s))")


def main() -> None:
    build_site()


if __name__ == "__main__":
    main()
