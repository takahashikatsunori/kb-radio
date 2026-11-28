"""Render standalone spot dossier reading portal (docs/spots/index.html) and individual spot article pages (docs/spots/<spot_id>/index.html)."""

from __future__ import annotations

import hashlib
import html
from string import Template
from typing import Any, Callable

from kodaira_spots import compute_spot_usage, match_spots_in_text

OP_STATUS_LABEL_JA: dict[str, str] = {
    "open": "一次確認：営業・公開中",
    "seasonal": "一次確認：季節営業・開園",
    "limited": "一次確認：事前予約・限定公開",
    "renovation": "一次確認：改修・リニューアル予定/中",
    "closed": "一次確認：閉業・閉鎖確認済",
}

OP_STATUS_BADGE_CLS: dict[str, str] = {
    "open": "is-open",
    "seasonal": "is-seasonal",
    "limited": "is-limited",
    "renovation": "is-renovation",
    "closed": "is-closed",
}

SEASON_JA: dict[str, str] = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
    "all": "通年",
}

ART_KIND_LABEL_JA: dict[str, str] = {
    "scene": "風景スケッチ",
    "feature": "見どころ図解",
    "menu": "メニュー・味めぐり",
    "sign": "看板・シンボル",
    "item": "特徴・設備ノート",
}


def _safe_http_url(raw_url: Any) -> str:
    u = str(raw_url or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


def _render_spot_sketch_svg(name: str, category_label: str, area: str) -> str:
    """Return warm notebook-sketch inline SVG banner (16:9) when spot has no raster illustration yet."""
    uid = hashlib.md5(f"{name}|{area}".encode("utf-8")).hexdigest()[:8]
    title = html.escape((name or "")[:26])
    cat = html.escape(category_label or "小平スポット")
    area_esc = html.escape(area or "東京都小平市")
    return f"""<svg class="spot-sketch-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" role="img" aria-label="{title} 取材ノートスケッチ">
  <defs>
    <linearGradient id="sketchPaper_{uid}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#fffdf8"/>
      <stop offset="55%" stop-color="#f7fbf7"/>
      <stop offset="100%" stop-color="#ecf5ee"/>
    </linearGradient>
    <pattern id="ruledLines_{uid}" width="800" height="36" patternUnits="userSpaceOnUse">
      <line x1="0" y1="35" x2="800" y2="35" stroke="#d9e7dd" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="800" height="450" rx="18" fill="url(#sketchPaper_{uid})"/>
  <rect width="800" height="450" rx="18" fill="url(#ruledLines_{uid})" opacity="0.65"/>
  <rect x="24" y="24" width="752" height="402" rx="14" fill="none" stroke="#9ec4ab" stroke-width="2" stroke-dasharray="8 6"/>
  <circle cx="676" cy="116" r="54" fill="#fde68a" fill-opacity="0.42" stroke="#d97706" stroke-width="1.8" stroke-dasharray="4 4"/>
  <text x="676" y="110" text-anchor="middle" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="14" font-weight="700" fill="#92400e">写真取材</text>
  <text x="676" y="132" text-anchor="middle" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="14" font-weight="700" fill="#92400e">準備中</text>
  <rect x="52" y="54" width="248" height="34" rx="17" fill="#dcfce7" stroke="#86efac" stroke-width="1.5"/>
  <text x="176" y="77" text-anchor="middle" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="15" font-weight="700" fill="#166534">{cat}</text>
  <text x="52" y="190" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="28" font-weight="800" fill="#1f2937">{title}</text>
  <text x="52" y="236" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="18" font-weight="600" fill="#4b5563">{area_esc} ｜ 一次ソース取材手帳</text>
  <path d="M52 290 C140 264, 210 310, 310 282 C420 250, 520 306, 720 278" fill="none" stroke="#1b5e3c" stroke-width="2.5" stroke-linecap="round" opacity="0.55"/>
  <circle cx="102" cy="346" r="10" fill="#1b5e3c" opacity="0.22"/>
  <circle cx="140" cy="346" r="10" fill="#d97706" opacity="0.28"/>
  <circle cx="178" cy="346" r="10" fill="#2563eb" opacity="0.22"/>
  <text x="206" y="352" font-family="'Hiragino Kaku Gothic ProN','Yu Gothic UI','Meiryo',sans-serif" font-size="14" fill="#64748b">今後の巡回取材で現地写真ベースのデフォルメイラストを順次追加予定</text>
</svg>"""


def build_spot_dossier_context(
    kodaira_spots: dict[str, Any],
    spot_reports: dict[str, dict[str, Any]],
    topic_history: dict[str, Any] | None,
    editorial_plan: dict[str, Any] | None,
    program_schedule: dict[str, Any] | None,
    bundles: list[dict[str, Any]],
    today_jst_str: str,
) -> dict[str, Any]:
    """Assemble shared lookup maps for spot index & individual reading pages."""
    spots_list = [
        sp
        for sp in (kodaira_spots.get("spots") or [])
        if isinstance(sp, dict) and sp.get("id")
    ]
    spots_by_id: dict[str, dict[str, Any]] = {str(s["id"]): s for s in spots_list}
    cats_by_id: dict[str, dict[str, Any]] = {
        str(c["id"]): c
        for c in (kodaira_spots.get("categories") or [])
        if isinstance(c, dict) and c.get("id")
    }
    topic_entries = (topic_history or {}).get("entries") or []
    usage_map = compute_spot_usage(
        kodaira_spots,
        topic_entries,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
        reference_date=today_jst_str,
    )

    # Reverse connections so spot links work bidirectionally across standalone pages
    reverse_conns: dict[str, list[dict[str, str]]] = {}
    explicit_targets: dict[str, set[str]] = {}
    for sid, dossier in spot_reports.items():
        conns = [c for c in (dossier.get("connections") or []) if isinstance(c, dict) and c.get("spot_id")]
        explicit_targets[sid] = {str(c["spot_id"]) for c in conns}
    for sid, dossier in spot_reports.items():
        src_name = str(dossier.get("spot_name") or (spots_by_id.get(sid) or {}).get("name") or sid)
        for c in (dossier.get("connections") or []):
            if not isinstance(c, dict) or not c.get("spot_id"):
                continue
            rel_id = str(c["spot_id"]).strip()
            if rel_id == sid or rel_id not in spot_reports:
                continue
            if sid in explicit_targets.get(rel_id, set()):
                continue
            reverse_conns.setdefault(rel_id, []).append(
                {
                    "spot_id": sid,
                    "relation": str(c.get("relation") or "関連スポット").strip(),
                    "note": f"{src_name}側の取材メモから連携：{str(c.get('note') or '').strip()}".rstrip("："),
                }
            )

    # Map aired episodes per spot_id
    history_spots_by_date: dict[str, list[str]] = {}
    for th in topic_entries:
        if not isinstance(th, dict) or not th.get("date"):
            continue
        d_str = str(th["date"])
        sids = list(th.get("spot_ids") or [])
        if not sids:
            joined = "\n".join(
                [
                    str(th.get("subtitle") or ""),
                    " ".join(str(x) for x in (th.get("kodaira_topics") or [])),
                    str(th.get("special_feature_title") or ""),
                ]
            )
            sids = match_spots_in_text(joined, kodaira_spots)
        for x in sids:
            if x not in history_spots_by_date.setdefault(d_str, []):
                history_spots_by_date[d_str].append(x)

    aired_episodes_by_spot: dict[str, list[dict[str, str]]] = {}
    for b in sorted(bundles, key=lambda item: str(item["episode"]["meta"]["episode_date"]), reverse=True):
        ep = b["episode"]
        meta = ep["meta"]
        if meta.get("is_spinoff"):
            continue
        d_str = str(meta["episode_date"])
        subtitle = str(meta.get("subtitle") or "")
        ep_label = str(meta.get("episode_label") or f"第{meta.get('episode_number', '')}回")
        slug = str(b["slug"])
        matched_ids = set(history_spots_by_date.get(d_str, []))
        text_fallback = "\n".join(
            [
                subtitle,
                " ".join(str(x) for x in (meta.get("kodaira_topics") or [])),
                str(ep.get("special_feature", {}).get("title") or "") if isinstance(ep.get("special_feature"), dict) else "",
            ]
        )
        for x in match_spots_in_text(text_fallback, kodaira_spots):
            matched_ids.add(x)
        for sid in matched_ids:
            aired_episodes_by_spot.setdefault(sid, []).append(
                {
                    "date": d_str,
                    "label": ep_label,
                    "subtitle": subtitle,
                    "slug": slug,
                }
            )

    # Order dossier IDs following config/kodaira_spots.json order first, then any trailing IDs
    ordered_ids = [
        str(sp["id"])
        for sp in spots_list
        if str(sp["id"]) in spot_reports and (spot_reports[str(sp["id"])].get("entries") or [])
    ]
    for sid in sorted(spot_reports):
        if sid not in ordered_ids and (spot_reports[sid].get("entries") or []):
            ordered_ids.append(sid)

    return {
        "spots_by_id": spots_by_id,
        "cats_by_id": cats_by_id,
        "usage_map": usage_map,
        "reverse_conns": reverse_conns,
        "aired_episodes_by_spot": aired_episodes_by_spot,
        "ordered_ids": ordered_ids,
    }


SPOTS_CSS = """
.spots-hero {
  padding: 1.05rem 1.15rem;
  border-left: 4px solid var(--forest);
  background: linear-gradient(135deg, #fffdf8 0%, #f3fbf5 100%);
}
.spots-lead {
  margin: 0.4rem 0 0;
  font-size: 0.9rem;
  line-height: 1.68;
  color: var(--ink);
}
.spots-stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.72rem;
}
.spots-stat-pill {
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.25rem 0.65rem;
  border-radius: 999px;
  background: var(--forest-soft);
  color: var(--forest-dark);
  border: 1px solid #bbf7d0;
}
.spots-stat-pill.is-warm {
  background: #fffbeb;
  color: #92400e;
  border-color: #fde68a;
}
.spots-stat-pill.is-art {
  background: #fdf2f8;
  color: #9d174d;
  border-color: #fbcfe8;
}
.spots-controls {
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.spots-search {
  width: 100%;
  box-sizing: border-box;
  padding: 0.56rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 0.92rem;
  font-family: inherit;
  background: #fff;
}
.spots-filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.38rem;
}
.spots-filter-label {
  font-size: 0.76rem;
  font-weight: 700;
  color: var(--muted);
  margin-right: 0.15rem;
}
.spots-pill-btn {
  border: 1px solid var(--border);
  background: #fff;
  color: var(--ink);
  border-radius: 999px;
  padding: 0.28rem 0.68rem;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
}
.spots-pill-btn.active {
  background: var(--forest);
  color: #fff;
  border-color: var(--forest);
}
.spots-featured-strip {
  padding: 0.85rem 1rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 0.65rem;
}
.spots-ready-mini {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.7rem 0.82rem;
  border-radius: 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  text-decoration: none;
  color: var(--ink);
}
.spots-ready-mini:hover {
  border-color: #d97706;
}
.spots-ready-mini strong {
  font-size: 0.88rem;
  color: #92400e;
}
.spots-ready-mini span {
  font-size: 0.78rem;
  line-height: 1.5;
  color: var(--ink);
}
.spots-index-grid {
  padding: 0.95rem;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.95rem;
}
.spot-article-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  background: #fff;
  min-width: 0;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}
.spot-card-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  background: #f8faf8;
  border-bottom: 1px solid var(--border);
}
.spot-sketch-svg {
  display: block;
  width: 100%;
  height: auto;
}
.spot-card-body {
  padding: 0.85rem 0.95rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.spot-card-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}
.spot-badge {
  font-size: 0.71rem;
  font-weight: 700;
  padding: 0.14rem 0.52rem;
  border-radius: 999px;
}
.spot-badge.cat { background: var(--forest-soft); color: var(--forest-dark); }
.spot-badge.art { background: #fdf2f8; color: #9d174d; }
.spot-badge.ready { background: #fef3c7; color: #92400e; }
.spot-badge.high { background: #e0f2fe; color: #0369a1; }
.spot-badge.low { background: #f1f5f9; color: #475569; }
.spot-badge.is-open { background: #dcfce7; color: #166534; }
.spot-badge.is-seasonal { background: #fef9c3; color: #854d0e; }
.spot-badge.is-limited { background: #e0e7ff; color: #3730a3; }
.spot-badge.is-renovation { background: #ffedd5; color: #9a3412; }
.spot-badge.is-closed { background: #fee2e2; color: #991b1b; }
.spot-card-title {
  margin: 0;
  font-size: 1.03rem;
  line-height: 1.4;
  font-weight: 800;
  color: var(--ink);
}
.spot-card-meta {
  font-size: 0.77rem;
  color: var(--muted);
}
.spot-card-lead {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.62;
  color: var(--ink);
}
.spot-card-footer {
  margin-top: auto;
  padding-top: 0.45rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  font-size: 0.76rem;
  color: var(--muted);
}
.spot-read-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.38rem 0.78rem;
  border-radius: 999px;
  background: var(--forest);
  color: #fff;
  text-decoration: none;
  font-size: 0.8rem;
  font-weight: 700;
}
.spot-read-btn:hover {
  background: var(--forest-dark);
}

/* Detail page layout */
.spot-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: var(--muted);
  margin-bottom: 0.25rem;
}
.spot-breadcrumb a {
  color: var(--forest-dark);
  font-weight: 700;
  text-decoration: none;
}
.spot-breadcrumb a:hover {
  text-decoration: underline;
}
.spot-detail-hero {
  overflow: hidden;
  border-top: 4px solid var(--forest);
}
.spot-hero-art-wrap {
  background: #f8faf8;
  border-bottom: 1px solid var(--border);
}
.spot-hero-art-img {
  display: block;
  width: 100%;
  max-height: 500px;
  object-fit: cover;
}
.spot-hero-art-cap {
  padding: 0.52rem 1rem;
  font-size: 0.78rem;
  color: var(--muted);
  background: #f8faf8;
  border-top: 1px solid var(--border);
  line-height: 1.5;
}
.spot-detail-head {
  padding: 1rem 1.15rem 1.15rem;
}
.spot-detail-title {
  margin: 0.45rem 0 0.35rem;
  font-size: clamp(1.22rem, 3.6vw, 1.62rem);
  line-height: 1.35;
  color: var(--ink);
}
.spot-detail-lead {
  margin: 0.35rem 0 0;
  font-size: 0.96rem;
  line-height: 1.72;
  color: var(--ink);
  font-weight: 500;
}
.spot-quick-grid {
  padding: 0.95rem 1.15rem;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem 1rem;
}
.spot-quick-item {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 0.85rem;
  line-height: 1.58;
}
.spot-quick-label {
  display: block;
  font-size: 0.73rem;
  font-weight: 700;
  color: var(--muted);
}
.spot-url-row {
  padding: 0 1.15rem 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.42rem;
}
.spot-url-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  background: #f0f9ff;
  color: #0369a1;
  border: 1px solid #bae6fd;
  font-size: 0.78rem;
  font-weight: 700;
  text-decoration: none;
  overflow-wrap: anywhere;
}
.spot-url-pill:hover {
  background: #e0f2fe;
}
.spot-essay-body {
  padding: 1rem 1.15rem 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.82rem;
}
.spot-essay-body p {
  margin: 0;
  font-size: 0.94rem;
  line-height: 1.85;
  color: var(--ink);
}
.spot-editor-note {
  margin-top: 0.25rem;
  padding: 0.78rem 0.95rem;
  border-radius: 10px;
  border-left: 4px solid #d97706;
  background: #fffdf5;
  font-size: 0.87rem;
  line-height: 1.68;
  color: #78350f;
}
.spot-art-grid {
  padding: 0.95rem 1.1rem 1.1rem;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9rem;
}
.spot-art-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
  min-width: 0;
}
.spot-art-card img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  background: #f8faf8;
}
.spot-art-cap-box {
  padding: 0.72rem 0.85rem 0.82rem;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}
.spot-art-cap-box h3 {
  margin: 0;
  font-size: 0.94rem;
  color: var(--ink);
}
.spot-art-cap-box p {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.58;
  color: var(--ink);
}
.spot-art-provenance {
  font-size: 0.73rem;
  color: var(--muted);
}
.spot-conn-wrap {
  padding: 0.95rem 1.15rem 1.1rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}
.spot-conn-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
}
.spot-conn-card {
  display: flex;
  flex-direction: column;
  gap: 0.24rem;
  padding: 0.72rem 0.85rem;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: #f8faf8;
  text-decoration: none;
  color: var(--ink);
  min-width: 0;
  overflow-wrap: anywhere;
}
.spot-conn-card:hover {
  border-color: var(--forest);
  background: #f0fdf4;
}
.spot-conn-rel {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--forest-dark);
}
.spot-leads-box {
  padding: 0.75rem 0.95rem;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
}
.spot-leads-box h3 {
  margin: 0 0 0.4rem;
  font-size: 0.88rem;
  color: var(--ink);
}
.spot-leads-box ul,
.spot-ep-list {
  margin: 0;
  padding-left: 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  font-size: 0.84rem;
  line-height: 1.6;
}
.spot-timeline {
  padding: 0.95rem 1.15rem 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.spot-log-entry {
  border: 1px solid var(--border);
  border-left: 4px solid var(--forest);
  border-radius: 10px;
  padding: 0.8rem 0.95rem;
  background: #fff;
  min-width: 0;
  overflow-wrap: anywhere;
}
.spot-log-meta {
  font-size: 0.76rem;
  font-weight: 700;
  color: var(--forest-dark);
  margin-bottom: 0.25rem;
}
.spot-log-headline {
  margin: 0 0 0.45rem;
  font-size: 0.95rem;
  font-weight: 800;
  color: var(--ink);
}
.spot-log-entry ul {
  margin: 0 0 0.45rem;
  padding-left: 1.15rem;
  font-size: 0.85rem;
  line-height: 1.62;
}
.spot-log-note {
  font-size: 0.81rem;
  line-height: 1.55;
  color: var(--muted);
  margin-top: 0.25rem;
}
.spot-pager {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.6rem;
}
.spot-pager a {
  display: inline-flex;
  align-items: center;
  padding: 0.45rem 0.85rem;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--forest-dark);
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 700;
}
.spot-pager a:hover {
  background: var(--forest-soft);
}
@media (max-width: 760px) {
  .spots-index-grid,
  .spot-quick-grid,
  .spot-art-grid,
  .spot-conn-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
"""

SPOTS_INDEX_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>小平スポット取材手帳（イラスト付き読み物） | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>
$COMMON_CSS
$SPOTS_CSS
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      $NAV_HTML
    </div>
  </header>

  <main class="container single">
    <div class="card spots-hero">
      <h2 style="margin:0; font-size:1.08rem;">地域の魅力を愛情深く掘り下げる、一次情報ベースの継続取材ノート</h2>
      <p class="spots-lead">
        放送日だけでなく日々の巡回取材で集めた小平のまち・寺社・農園・公共施設・お店・インフラの発見を、公式情報によるファクトチェックと写真ベースのデフォルメイラスト付き読み物としてスポットごとに一冊ずつまとめました。長期に積み重なるネタ同士のつながりから、番組の特集企画が生まれます。
      </p>
      <div class="spots-stats-row" id="spots-stats-row"></div>
    </div>

    <div class="card" id="ready-specials-card" style="display:none;">
      <div class="section-head">
        <h2>⭐ 継続取材から育った長期特集候補（特集化OK）</h2>
        <span class="hint">番組の深掘り特集に発展できるネタ</span>
      </div>
      <div class="spots-featured-strip" id="spots-ready-strip"></div>
    </div>

    <div class="card spots-controls">
      <input type="search" id="spots-search" class="spots-search" placeholder="スポット名・本文・イラスト・エリア・つながりで検索（例：糧うどん、イルミネーション、免震、テルメ…）" />
      <div class="spots-filter-row" id="spots-mode-filters">
        <span class="spots-filter-label">絞り込み:</span>
        <button type="button" class="spots-pill-btn active" data-mode="all">すべて</button>
        <button type="button" class="spots-pill-btn" data-mode="illustrated">🎨 イラスト付き読み物</button>
        <button type="button" class="spots-pill-btn" data-mode="ready">⭐ 特集化OK</button>
        <button type="button" class="spots-pill-btn" data-mode="high">⚡ 高頻度巡回</button>
      </div>
      <div class="spots-filter-row" id="spots-cat-filters">
        <span class="spots-filter-label">ジャンル:</span>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>取材レポート一覧（全$DOSSIER_COUNTスポット）</h2>
        <span class="hint">タップすると各スポットの単独読み物ページが開きます</span>
      </div>
      <div class="spots-index-grid" id="spots-index-grid"></div>
    </div>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ <a href="../calendar.html#spot-catalog">全127スポット題材カタログへ →</a></footer>

  <script type="application/json" id="spots-index-data">$INDEX_JSON</script>
  <script>
    (function () {
      const payload = JSON.parse(document.getElementById("spots-index-data").textContent);
      const statsEl = document.getElementById("spots-stats-row");
      const readyCard = document.getElementById("ready-specials-card");
      const readyStrip = document.getElementById("spots-ready-strip");
      const searchEl = document.getElementById("spots-search");
      const modeBtns = Array.from(document.querySelectorAll("#spots-mode-filters button"));
      const catWrap = document.getElementById("spots-cat-filters");
      const gridEl = document.getElementById("spots-index-grid");

      let mode = "all";
      let catFilter = "all";

      function addStatPill(text, cls) {
        const span = document.createElement("span");
        span.className = "spots-stat-pill " + (cls || "");
        span.textContent = text;
        statsEl.appendChild(span);
      }

      const st = payload.stats || {};
      addStatPill("📚 取材レポート公開: " + (st.dossier_spots || 0) + "スポット / 全" + (st.catalog_total || 127));
      addStatPill("🎨 イラスト掲載: " + (st.illustrated_spots || 0) + "スポット（計" + (st.total_illustrations || 0) + "点）", "is-art");
      addStatPill("⭐ 特集化OK: " + (st.ready_specials || 0) + "件", "is-warm");
      addStatPill("📝 一次確認ログ: 計" + (st.total_entries || 0) + "回", "");

      const readyItems = (payload.spots || []).filter((s) => s.special_ready && s.special_theme);
      if (readyItems.length > 0 && readyCard && readyStrip) {
        readyCard.style.display = "";
        readyItems.forEach((item) => {
          const a = document.createElement("a");
          a.className = "spots-ready-mini";
          a.href = item.href;
          const strong = document.createElement("strong");
          strong.textContent = "⭐ " + item.name;
          const span = document.createElement("span");
          span.textContent = item.special_theme;
          a.appendChild(strong);
          a.appendChild(span);
          readyStrip.appendChild(a);
        });
      }

      if (catWrap) {
        const allBtn = document.createElement("button");
        allBtn.type = "button";
        allBtn.className = "spots-pill-btn active";
        allBtn.dataset.cat = "all";
        allBtn.textContent = "全ジャンル (" + (st.dossier_spots || 0) + ")";
        catWrap.appendChild(allBtn);

        (payload.categories || []).forEach((c) => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "spots-pill-btn";
          b.dataset.cat = c.id;
          b.textContent = c.icon + " " + c.label + " (" + c.count + ")";
          catWrap.appendChild(b);
        });

        const catBtns = Array.from(catWrap.querySelectorAll("button"));
        catBtns.forEach((btn) => {
          btn.addEventListener("click", () => {
            catFilter = btn.dataset.cat || "all";
            catBtns.forEach((x) => x.classList.toggle("active", x === btn));
            renderCards();
          });
        });
      }

      modeBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
          mode = btn.dataset.mode || "all";
          modeBtns.forEach((x) => x.classList.toggle("active", x === btn));
          renderCards();
        });
      });

      if (searchEl) {
        searchEl.addEventListener("input", renderCards);
      }

      function renderCards() {
        gridEl.innerHTML = "";
        const q = (searchEl ? searchEl.value : "").trim().toLowerCase();
        const items = (payload.spots || []).filter((sp) => {
          if (mode === "illustrated" && !(sp.illustration_count > 0)) return false;
          if (mode === "ready" && !sp.special_ready) return false;
          if (mode === "high" && sp.patrol_tier !== "high") return false;
          if (catFilter !== "all" && sp.category !== catFilter) return false;
          if (!q) return true;
          return (sp.search_text || "").toLowerCase().includes(q);
        });

        if (items.length === 0) {
          const empty = document.createElement("p");
          empty.style.padding = "1rem";
          empty.style.color = "var(--muted)";
          empty.textContent = "条件に合うスポット取材記事が見つかりませんでした。";
          gridEl.appendChild(empty);
          return;
        }

        items.forEach((sp) => {
          const art = document.createElement("article");
          art.className = "spot-article-card";

          const linkImg = document.createElement("a");
          linkImg.href = sp.href;
          linkImg.style.display = "block";
          if (sp.hero_src) {
            const img = document.createElement("img");
            img.className = "spot-card-thumb";
            img.src = sp.hero_src;
            img.alt = sp.name + " 取材イラスト";
            img.loading = "lazy";
            linkImg.appendChild(img);
          } else {
            const holder = document.createElement("div");
            holder.innerHTML = sp.placeholder_svg;
            linkImg.appendChild(holder.firstElementChild);
          }
          art.appendChild(linkImg);

          const body = document.createElement("div");
          body.className = "spot-card-body";

          const badges = document.createElement("div");
          badges.className = "spot-card-badges";

          const bCat = document.createElement("span");
          bCat.className = "spot-badge cat";
          bCat.textContent = sp.category_icon + " " + sp.category_label;
          badges.appendChild(bCat);

          const bOp = document.createElement("span");
          bOp.className = "spot-badge " + (sp.op_badge_cls || "is-open");
          bOp.textContent = sp.op_status_short;
          badges.appendChild(bOp);

          if (sp.illustration_count > 0) {
            const bArt = document.createElement("span");
            bArt.className = "spot-badge art";
            bArt.textContent = "🎨 イラスト" + sp.illustration_count + "点";
            badges.appendChild(bArt);
          }
          if (sp.special_ready) {
            const bReady = document.createElement("span");
            bReady.className = "spot-badge ready";
            bReady.textContent = "⭐ 特集化OK";
            badges.appendChild(bReady);
          }
          body.appendChild(badges);

          const h3 = document.createElement("h3");
          h3.className = "spot-card-title";
          h3.textContent = sp.name;
          body.appendChild(h3);

          const meta = document.createElement("div");
          meta.className = "spot-card-meta";
          meta.textContent = "📍 " + sp.area + "（" + sp.station + "）｜ 最終確認: " + sp.last_checked_at;
          body.appendChild(meta);

          const lead = document.createElement("p");
          lead.className = "spot-card-lead";
          lead.textContent = sp.lead_text;
          body.appendChild(lead);

          const footer = document.createElement("div");
          footer.className = "spot-card-footer";

          const countsSpan = document.createElement("span");
          countsSpan.textContent =
            "📝 取材" + sp.entry_count + "回 ／ 🔗 つながり" + sp.connection_count + "件";
          footer.appendChild(countsSpan);

          const readBtn = document.createElement("a");
          readBtn.className = "spot-read-btn";
          readBtn.href = sp.href;
          readBtn.textContent = "📖 取材記事を読む →";
          footer.appendChild(readBtn);

          body.appendChild(footer);
          art.appendChild(body);
          gridEl.appendChild(art);
        });
      }

      renderCards();
    })();
  </script>
</body>
</html>
""")


def render_spots_index_page(
    kodaira_spots: dict[str, Any],
    spot_reports: dict[str, dict[str, Any]],
    ctx: dict[str, Any],
    common_css: str,
    nav_html: str,
    safe_json_fn: Callable[[Any], str],
) -> str:
    """Render docs/spots/index.html listing all spot reading pages."""
    spots_by_id = ctx["spots_by_id"]
    cats_by_id = ctx["cats_by_id"]
    reverse_conns = ctx["reverse_conns"]
    ordered_ids = ctx["ordered_ids"]

    cat_counts: dict[str, int] = {}
    cards_out: list[dict[str, Any]] = []
    illustrated_spots = 0
    total_illustrations = 0
    ready_specials = 0
    total_entries = 0

    for sid in ordered_ids:
        dossier = spot_reports[sid]
        sp = spots_by_id.get(sid) or {}
        cid = str(dossier.get("category") or sp.get("category") or "")
        c_meta = cats_by_id.get(cid) or {"label": cid, "icon": "📍"}
        cat_label = str(c_meta.get("label") or cid)
        cat_icon = str(c_meta.get("icon") or "📍")
        cat_counts[cid] = cat_counts.get(cid, 0) + 1

        entries = [e for e in (dossier.get("entries") or []) if isinstance(e, dict)]
        latest = entries[-1]
        total_entries += len(entries)

        arts = [a for a in (dossier.get("illustrations") or []) if isinstance(a, dict) and a.get("src")]
        if arts:
            illustrated_spots += 1
            total_illustrations += len(arts)
        hero_art = next((a for a in arts if a.get("id") == "hero"), arts[0] if arts else None)
        hero_src = f"../{hero_art['src']}" if hero_art else ""

        sfp = dossier.get("special_feature_potential") if isinstance(dossier.get("special_feature_potential"), dict) else {}
        if sfp.get("ready"):
            ready_specials += 1

        essay = dossier.get("editorial_essay") if isinstance(dossier.get("editorial_essay"), dict) else {}
        lead_text = str(essay.get("lead") or latest.get("headline") or sp.get("summary") or "").strip()

        op_code = str(dossier.get("operating_status") or "open")
        op_short = OP_STATUS_LABEL_JA.get(op_code, op_code).replace("一次確認：", "")
        out_conns = [c for c in (dossier.get("connections") or []) if isinstance(c, dict) and c.get("spot_id")]
        all_conn_count = len({c["spot_id"] for c in out_conns + reverse_conns.get(sid, [])})

        name = str(dossier.get("spot_name") or sp.get("name") or sid)
        area = str(sp.get("area") or "")
        station = str(sp.get("station") or "")
        last_checked = str(dossier.get("last_checked_at") or dossier.get("last_researched_at") or "")

        search_bits = [
            name,
            cat_label,
            area,
            station,
            lead_text,
            str(latest.get("headline") or ""),
            str(sfp.get("theme_idea") or ""),
            *[str(a.get("title") or "") + " " + str(a.get("caption") or "") for a in arts],
            *[str(x) for x in (essay.get("paragraphs") or [])],
            *[str(x) for x in (latest.get("discoveries") or [])],
        ]

        cards_out.append(
            {
                "id": sid,
                "name": name,
                "href": f"{sid}/index.html",
                "category": cid,
                "category_label": cat_label,
                "category_icon": cat_icon,
                "area": area,
                "station": station,
                "patrol_tier": str(dossier.get("patrol_tier") or sp.get("patrol_tier") or "low"),
                "op_status_short": op_short,
                "op_badge_cls": OP_STATUS_BADGE_CLS.get(op_code, "is-open"),
                "last_checked_at": last_checked,
                "lead_text": lead_text,
                "hero_src": hero_src,
                "placeholder_svg": "" if hero_src else _render_spot_sketch_svg(name, cat_label, area),
                "illustration_count": len(arts),
                "entry_count": len(entries),
                "connection_count": all_conn_count,
                "special_ready": bool(sfp.get("ready")),
                "special_theme": str(sfp.get("theme_idea") or "").strip(),
                "search_text": " ".join(search_bits),
            }
        )

    # Sort illustrated showcase articles first so visitors immediately see rich visual stories, then config order
    cards_out.sort(key=lambda c: (0 if c["illustration_count"] > 0 else 1, 0 if c["special_ready"] else 1))

    cats_list = [
        {
            "id": str(c["id"]),
            "label": str(c.get("label") or c["id"]),
            "icon": str(c.get("icon") or "📍"),
            "count": cat_counts[str(c["id"])],
        }
        for c in (kodaira_spots.get("categories") or [])
        if isinstance(c, dict) and str(c.get("id") or "") in cat_counts
    ]

    index_payload = {
        "stats": {
            "dossier_spots": len(cards_out),
            "catalog_total": len(kodaira_spots.get("spots") or []),
            "illustrated_spots": illustrated_spots,
            "total_illustrations": total_illustrations,
            "ready_specials": ready_specials,
            "total_entries": total_entries,
        },
        "categories": cats_list,
        "spots": cards_out,
    }

    return SPOTS_INDEX_TEMPLATE.substitute(
        COMMON_CSS=common_css,
        SPOTS_CSS=SPOTS_CSS,
        NAV_HTML=nav_html,
        DOSSIER_COUNT=str(len(cards_out)),
        INDEX_JSON=safe_json_fn(index_payload),
    )


def render_spot_detail_page(
    spot_id: str,
    dossier: dict[str, Any],
    spot_reports: dict[str, dict[str, Any]],
    ctx: dict[str, Any],
    common_css: str,
    nav_html: str,
) -> str:
    """Render standalone reading article page docs/spots/<spot_id>/index.html."""
    spots_by_id = ctx["spots_by_id"]
    cats_by_id = ctx["cats_by_id"]
    usage_map = ctx["usage_map"]
    reverse_conns = ctx["reverse_conns"]
    aired_episodes_by_spot = ctx["aired_episodes_by_spot"]
    ordered_ids = ctx["ordered_ids"]

    sp = spots_by_id.get(spot_id) or {}
    cid = str(dossier.get("category") or sp.get("category") or "")
    c_meta = cats_by_id.get(cid) or {"label": cid, "icon": "📍"}
    cat_label = str(c_meta.get("label") or cid)
    cat_icon = str(c_meta.get("icon") or "📍")

    name = str(dossier.get("spot_name") or sp.get("name") or spot_id)
    area = str(sp.get("area") or "小平市内")
    station = str(sp.get("station") or "-")
    address_hint = str(sp.get("address_hint") or "-")
    best_seasons = "・".join(SEASON_JA.get(str(x), str(x)) for x in (sp.get("best_seasons") or ["all"]))
    patrol_tier = str(dossier.get("patrol_tier") or sp.get("patrol_tier") or "low")
    patrol_label = "⚡ 高頻度巡回（約4〜5日周期）" if patrol_tier == "high" else "📅 安定巡回（約16日周期）"

    op_code = str(dossier.get("operating_status") or "open")
    op_label = OP_STATUS_LABEL_JA.get(op_code, op_code)
    op_cls = OP_STATUS_BADGE_CLS.get(op_code, "is-open")
    op_note = str(dossier.get("operating_status_note") or "").strip()
    last_checked = str(dossier.get("last_checked_at") or dossier.get("last_researched_at") or "-")
    last_researched = str(dossier.get("last_researched_at") or "-")

    entries = [e for e in (dossier.get("entries") or []) if isinstance(e, dict)]
    latest = entries[-1] if entries else {}

    essay = dossier.get("editorial_essay") if isinstance(dossier.get("editorial_essay"), dict) else {}
    lead_text = str(essay.get("lead") or sp.get("summary") or latest.get("headline") or "").strip()
    paragraphs = [str(p).strip() for p in (essay.get("paragraphs") or []) if str(p).strip()]
    if not paragraphs:
        fallback_items = [str(x).strip() for x in (dossier.get("curated_highlights") or []) if str(x).strip()]
        if sp.get("summary"):
            paragraphs.append(str(sp["summary"]).strip())
        if fallback_items:
            paragraphs.append("これまでの取材で見えてきた魅力：" + "／".join(fallback_items) + "。")
    editor_note = str(essay.get("editor_note") or "").strip()

    # Official URLs collected from dossier + entries
    all_urls: list[str] = []
    for raw_u in list(dossier.get("official_urls") or []):
        u = _safe_http_url(raw_u)
        if u and u not in all_urls:
            all_urls.append(u)
    for e in entries:
        for src in (e.get("primary_sources") or []):
            if isinstance(src, dict):
                u = _safe_http_url(src.get("url"))
                if u and u not in all_urls:
                    all_urls.append(u)
    url_pills_html = "".join(
        f'<a class="spot-url-pill" href="{html.escape(u, quote=True)}" target="_blank" rel="noopener noreferrer">🔗 {html.escape(u)}</a>'
        for u in all_urls
    )

    # Illustrations: hero banner + gallery cards
    arts = [a for a in (dossier.get("illustrations") or []) if isinstance(a, dict) and a.get("src")]
    hero_art = next((a for a in arts if a.get("id") == "hero"), arts[0] if arts else None)
    gallery_arts = [a for a in arts if a is not hero_art] if len(arts) > 1 else ([] if hero_art else [])

    if hero_art:
        hero_src = html.escape(f"../../{hero_art['src']}", quote=True)
        hero_title = html.escape(str(hero_art.get("title") or name))
        hero_cap = html.escape(str(hero_art.get("caption") or ""))
        hero_based = html.escape(str(hero_art.get("based_on") or ""))
        cap_parts = []
        if hero_title:
            cap_parts.append(f"<strong>🎨 {hero_title}</strong>")
        if hero_cap:
            cap_parts.append(hero_cap)
        if hero_based:
            cap_parts.append(f"（参照一次写真・典拠: {hero_based}）")
        hero_visual_html = (
            f'<div class="spot-hero-art-wrap">'
            f'<img class="spot-hero-art-img" src="{hero_src}" alt="{hero_title}" />'
            f'<div class="spot-hero-art-cap">{" — ".join(cap_parts[:2])}'
            f'{" " + cap_parts[2] if len(cap_parts) > 2 else ""}</div>'
            f'</div>'
        )
    else:
        hero_visual_html = f'<div class="spot-hero-art-wrap">{_render_spot_sketch_svg(name, cat_label, area)}</div>'

    gallery_section_html = ""
    if gallery_arts or (hero_art and len(arts) >= 2):
        cards_to_show = gallery_arts if gallery_arts else arts
        g_cards: list[str] = []
        for a in cards_to_show:
            a_src = html.escape(f"../../{a['src']}", quote=True)
            a_title = html.escape(str(a.get("title") or "見どころイラスト"))
            a_cap = html.escape(str(a.get("caption") or ""))
            a_kind = html.escape(ART_KIND_LABEL_JA.get(str(a.get("kind") or "feature"), "特徴イラスト"))
            a_based = html.escape(str(a.get("based_on") or ""))
            prov = f'<div class="spot-art-provenance">📷 参照もと: {a_based}</div>' if a_based else ""
            g_cards.append(
                f'<article class="spot-art-card">'
                f'<img src="{a_src}" alt="{a_title}" loading="lazy" />'
                f'<div class="spot-art-cap-box">'
                f'<span class="spot-badge art" style="align-self:flex-start;">{a_kind}</span>'
                f'<h3>{a_title}</h3>'
                f'<p>{a_cap}</p>'
                f'{prov}'
                f'</div>'
                f'</article>'
            )
        gallery_section_html = (
            '<div class="card">'
            '<div class="section-head">'
            '<h2>🎨 見どころ・名物・特徴デフォルメ図鑑</h2>'
            '<span class="hint">現地・公式写真に基づくイラスト解説</span>'
            '</div>'
            f'<div class="spot-art-grid">{"".join(g_cards)}</div>'
            '</div>'
        )

    # Essay HTML
    para_html = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
    editor_html = (
        f'<div class="spot-editor-note"><strong>🎙️ 小春＆平蔵の取材メモ：</strong>{html.escape(editor_note)}</div>'
        if editor_note
        else ""
    )

    # Bidirectional connections + aired broadcasts + next research leads
    merged_conns: list[dict[str, str]] = []
    seen_conn_ids: set[str] = set()
    for c in list(dossier.get("connections") or []) + list(reverse_conns.get(spot_id, [])):
        if not isinstance(c, dict):
            continue
        rel_id = str(c.get("spot_id") or "").strip()
        if not rel_id or rel_id in seen_conn_ids or rel_id == spot_id:
            continue
        seen_conn_ids.add(rel_id)
        merged_conns.append(c)

    conn_cards_html = ""
    if merged_conns:
        c_items: list[str] = []
        for c in merged_conns:
            rel_id = str(c["spot_id"])
            rel_sp = spots_by_id.get(rel_id) or {}
            rel_dos = spot_reports.get(rel_id)
            rel_name = str((rel_dos or {}).get("spot_name") or rel_sp.get("name") or rel_id)
            has_page = bool(rel_dos and (rel_dos.get("entries") or []))
            href = f"../{html.escape(rel_id, quote=True)}/index.html" if has_page else "../../calendar.html#spot-catalog"
            page_tag = "📖 取材記事あり" if has_page else "📍 カタログ掲載"
            c_items.append(
                f'<a class="spot-conn-card" href="{href}">'
                f'<span class="spot-conn-rel">{html.escape(str(c.get("relation") or "関連"))} ｜ {page_tag}</span>'
                f'<strong>{html.escape(rel_name)}</strong>'
                f'<span style="font-size:0.8rem; line-height:1.5;">{html.escape(str(c.get("note") or ""))}</span>'
                f'</a>'
            )
        conn_cards_html = f'<div class="spot-conn-grid">{"".join(c_items)}</div>'

    aired_eps = aired_episodes_by_spot.get(spot_id) or []
    usage = usage_map.get(spot_id) or {}
    planned_dates = list(usage.get("planned_dates") or [])
    hint_dates = list(usage.get("hint_dates") or [])

    broadcast_html_parts: list[str] = []
    if aired_eps:
        li = "".join(
            f'<li><a href="../../episodes/{html.escape(ep["slug"], quote=True)}/index.html">'
            f'{html.escape(ep["date"])}（{html.escape(ep["label"])}）: {html.escape(ep["subtitle"])}</a></li>'
            for ep in aired_eps
        )
        broadcast_html_parts.append(f'<div><strong>📻 過去の関連放送回</strong><ul class="spot-ep-list">{li}</ul></div>')
    if planned_dates:
        broadcast_html_parts.append(
            f'<div class="spot-log-note">📅 週間編成予定日: {", ".join(html.escape(d) for d in planned_dates)}</div>'
        )
    elif hint_dates:
        broadcast_html_parts.append(
            f'<div class="spot-log-note">🗓️ 今後の放送候補日（仮予定）: {", ".join(html.escape(d) for d in hint_dates)}</div>'
        )

    leads = [str(x).strip() for x in (dossier.get("next_research_leads") or []) if str(x).strip()]
    leads_html = ""
    if leads:
        leads_li = "".join(f"<li>{html.escape(ld)}</li>" for ld in leads)
        leads_html = f'<div class="spot-leads-box"><h3>🔭 次回の巡回・深掘り取材リード</h3><ul>{leads_li}</ul></div>'

    # Longitudinal timeline (newest first)
    log_cards: list[str] = []
    for e in reversed(entries):
        rdate = html.escape(str(e.get("researched_at") or e.get("date") or "-"))
        hl = html.escape(str(e.get("headline") or ""))
        fc = e.get("fact_check") if isinstance(e.get("fact_check"), dict) else {}
        checked = html.escape(str(fc.get("checked_at") or rdate))
        method = html.escape(str(fc.get("method") or "一次ソース照合"))
        disc_li = "".join(f"<li>{html.escape(str(d))}</li>" for d in (e.get("discoveries") or []) if str(d).strip())
        extra_notes: list[str] = []
        if e.get("seasonal_note"):
            extra_notes.append(f'<div class="spot-log-note">🌸 <strong>季節メモ:</strong> {html.escape(str(e["seasonal_note"]))}</div>')
        if e.get("disaster_tie_in"):
            extra_notes.append(f'<div class="spot-log-note">🛡️ <strong>防災・暮らしの備え:</strong> {html.escape(str(e["disaster_tie_in"]))}</div>')
        excl = [str(x).strip() for x in (e.get("excluded_unverified_claims") or []) if str(x).strip()]
        if excl:
            extra_notes.append(
                f'<div class="spot-log-note" style="color:#991b1b;">⚠️ <strong>未確認・否定情報の除外:</strong> {html.escape(" / ".join(excl))}</div>'
            )
        src_links = " / ".join(
            f'<a href="{html.escape(_safe_http_url(s.get("url")), quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(str(s.get("title") or "一次ソース"))}</a>'
            for s in (e.get("primary_sources") or [])
            if isinstance(s, dict) and _safe_http_url(s.get("url"))
        )
        log_cards.append(
            f'<div class="spot-log-entry">'
            f'<div class="spot-log-meta">📅 {rdate} 取材 ｜ ✓ {checked} 一次確認（{method}）</div>'
            f'<h3 class="spot-log-headline">{hl}</h3>'
            f'<ul>{disc_li}</ul>'
            f'{"".join(extra_notes)}'
            f'<div class="spot-log-note">🔗 一次ソース: {src_links or "記録あり"}</div>'
            f'</div>'
        )

    # Disaster angles & special feature potential
    angles_html = "".join(
        f'<span class="spot-badge cat">💡 {html.escape(str(a))}</span>'
        for a in (list(sp.get("disaster_angles") or []) + list(dossier.get("story_angles") or []))[:5]
        if str(a).strip()
    )
    sfp = dossier.get("special_feature_potential") if isinstance(dossier.get("special_feature_potential"), dict) else {}
    sfp_html = ""
    if sfp.get("theme_idea"):
        sfp_badge = "⭐ 特集化OK" if sfp.get("ready") else "🌱 長期特集の種"
        sfp_html = (
            f'<div class="spot-editor-note" style="border-left-color:#1b5e3c; background:#f0fdf4; color:#14532d;">'
            f'<strong>{sfp_badge}: {html.escape(str(sfp["theme_idea"]))}</strong>'
            + (f'<br />{html.escape(str(sfp.get("reason") or ""))}' if sfp.get("reason") else "")
            + '</div>'
        )

    # Prev / Next dossier pager
    idx = ordered_ids.index(spot_id) if spot_id in ordered_ids else -1
    prev_link = '<a href="../index.html">← 取材手帳一覧へ</a>'
    next_link = '<a href="../../calendar.html#spot-catalog">全127スポット一覧 →</a>'
    if idx > 0:
        pid = ordered_ids[idx - 1]
        pname = str((spot_reports.get(pid) or {}).get("spot_name") or (spots_by_id.get(pid) or {}).get("name") or pid)
        prev_link = f'<a href="../{html.escape(pid, quote=True)}/index.html">← {html.escape(pname)}</a>'
    if 0 <= idx < len(ordered_ids) - 1:
        nid = ordered_ids[idx + 1]
        nname = str((spot_reports.get(nid) or {}).get("spot_name") or (spots_by_id.get(nid) or {}).get("name") or nid)
        next_link = f'<a href="../{html.escape(nid, quote=True)}/index.html">{html.escape(nname)} →</a>'

    connections_section = ""
    if conn_cards_html or broadcast_html_parts or leads_html:
        connections_section = (
            '<div class="card">'
            '<div class="section-head">'
            '<h2>🔗 日々のつながり＆取材の幅を広げるメモ</h2>'
            '<span class="hint">周辺スポット・過去放送・次回の注目ポイント</span>'
            '</div>'
            '<div class="spot-conn-wrap">'
            f'{conn_cards_html}'
            f'{"".join(broadcast_html_parts)}'
            f'{leads_html}'
            '</div>'
            '</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(name)} 取材レポート | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>
{common_css}
{SPOTS_CSS}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      {nav_html}
    </div>
  </header>

  <main class="container single">
    <nav class="spot-breadcrumb" aria-label="パンくずリスト">
      <a href="../index.html">📖 小平スポット取材手帳</a>
      <span>›</span>
      <span>{html.escape(cat_icon)} {html.escape(cat_label)}</span>
      <span>›</span>
      <span>{html.escape(name)}</span>
    </nav>

    <article class="card spot-detail-hero">
      {hero_visual_html}
      <div class="spot-detail-head">
        <div class="spot-card-badges">
          <span class="spot-badge cat">{html.escape(cat_icon)} {html.escape(cat_label)}</span>
          <span class="spot-badge {op_cls}">{html.escape(op_label)}</span>
          <span class="spot-badge {html.escape(patrol_tier)}">{html.escape(patrol_label)}</span>
          <span class="spot-badge low">📝 取材蓄積 {len(entries)}回</span>
        </div>
        <h1 class="spot-detail-title">{html.escape(name)}</h1>
        <p class="spot-detail-lead">{html.escape(lead_text)}</p>
      </div>
    </article>

    <div class="card">
      <div class="section-head">
        <h2>📍 おでかけ・一次確認データ</h2>
        <span class="hint">最終確認: {html.escape(last_checked)}（取材更新: {html.escape(last_researched)}）</span>
      </div>
      <div class="spot-quick-grid">
        <div class="spot-quick-item"><span class="spot-quick-label">エリア・住所</span>{html.escape(area)} ／ {html.escape(address_hint)}</div>
        <div class="spot-quick-item"><span class="spot-quick-label">最寄り駅</span>{html.escape(station)}</div>
        <div class="spot-quick-item"><span class="spot-quick-label">一次確認済みの営業・公開状況</span>{html.escape(op_note or op_label)}</div>
        <div class="spot-quick-item"><span class="spot-quick-label">おすすめの季節</span>{html.escape(best_seasons)}</div>
      </div>
      {f'<div class="spot-url-row">{url_pills_html}</div>' if url_pills_html else ''}
    </div>

    <div class="card">
      <div class="section-head">
        <h2>📖 編集部の取材ストーリー</h2>
        <span class="hint">小平の暮らしと魅力の深掘りレポート</span>
      </div>
      <div class="spot-essay-body">
        {para_html}
        {editor_html}
      </div>
    </div>

    {gallery_section_html}

    {connections_section}

    <div class="card">
      <div class="section-head">
        <h2>🛡️ 防災とのつながり ＆ 特集企画ポテンシャル</h2>
        <span class="hint">番組テーマへの展開メモ</span>
      </div>
      <div class="spot-essay-body">
        <div class="spot-card-badges">{angles_html}</div>
        {sfp_html}
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h2>🗓️ 長期取材ログ（一次ソース検証タイムライン）</h2>
        <span class="hint">新着順・日付別の確認記録</span>
      </div>
      <div class="spot-timeline">
        {''.join(log_cards)}
      </div>
    </div>

    <div class="spot-pager">
      {prev_link}
      <a href="../index.html">📚 取材手帳一覧</a>
      {next_link}
    </div>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ <a href="../../calendar.html#spot-catalog">全127スポット題材カタログへ →</a></footer>
</body>
</html>
"""
