"""Render kbt-2608 local XYZ tile wide (~1/25,000) and detail (~1/5,000) PNG locator maps for spot dossiers."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

JST = timezone(timedelta(hours=9))
SPOT_REPORTS_DIR = ROOT_DIR / "data" / "spot_reports"
DOCS_SPOTS_ASSETS_DIR = ROOT_DIR / "docs" / "assets" / "spots"
DEFAULT_TILES_DIR = Path(
    os.environ.get("KBT2608_TILES_DIR")
    or r"c:\Users\katsunori\Documents\GitHub\kbt-2608\tiles"
)

TILE_PIXEL_SIZE = 512  # kbt-2608 stores 512x512 (2x) Retina XYZ PNG tiles
WIDE_SPEC = {
    "filename": "map_wide.png",
    "zoom": 14,
    "native_w": 768,
    "native_h": 512,
    "out_w": 768,
    "out_h": 512,
    "scale_label": "広域 約1/25,000",
    "scale_bar_m": 500,
    "ring_radius_high": 10,
    "ring_radius_approx": 22,
}
DETAIL_SPEC = {
    "filename": "map_detail.png",
    "zoom": 17,
    "native_w": 1152,
    "native_h": 768,
    "out_w": 864,
    "out_h": 576,
    "scale_label": "詳細 約1/5,000",
    "scale_bar_m": 100,
    "ring_radius_high": 14,
    "ring_radius_approx": 36,
}

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\BIZ-UDGothicB.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\arialbd.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for cand in FONT_CANDIDATES:
        p = Path(cand)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def latlon_to_world_px(lat: float, lon: float, zoom: int, tile_px: int = TILE_PIXEL_SIZE) -> tuple[float, float]:
    """Convert WGS84 (lat, lon) to global XYZ pixel coordinates at `zoom` with `tile_px` per tile."""
    n = float(1 << zoom)
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, float(lat))))
    px = ((float(lon) + 180.0) / 360.0) * n * tile_px
    py = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * tile_px
    return px, py


def meters_per_native_px(lat: float, zoom: int, tile_px: int = TILE_PIXEL_SIZE) -> float:
    """Return ground meters per pixel on tiles of size `tile_px` (512px = zoom+1 factor)."""
    scale_factor = float(1 << zoom) * (float(tile_px) / 256.0)
    return 156543.03392 * math.cos(math.radians(float(lat))) / scale_factor


def _stitch_tiles(
    lat: float,
    lon: float,
    zoom: int,
    native_w: int,
    native_h: int,
    out_w: int,
    out_h: int,
    tiles_dir: Path,
    *,
    spot_id: str = "",
) -> tuple[Image.Image, int, int]:
    """Stitch kbt-2608 XYZ PNG tiles centered accurately at (lat, lon)."""
    cx, cy = latlon_to_world_px(lat, lon, zoom, TILE_PIXEL_SIZE)
    left = cx - native_w / 2.0
    top = cy - native_h / 2.0
    right = left + native_w
    bottom = top + native_h

    tx0 = math.floor(left / TILE_PIXEL_SIZE)
    tx1 = math.floor((right - 1e-9) / TILE_PIXEL_SIZE)
    ty0 = math.floor(top / TILE_PIXEL_SIZE)
    ty1 = math.floor((bottom - 1e-9) / TILE_PIXEL_SIZE)

    cols = tx1 - tx0 + 1
    rows = ty1 - ty0 + 1
    mosaic = Image.new("RGBA", (cols * TILE_PIXEL_SIZE, rows * TILE_PIXEL_SIZE), (241, 245, 249, 255))

    total_tiles = 0
    missing_tiles = 0
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            total_tiles += 1
            tile_path = tiles_dir / str(zoom) / str(tx) / f"{ty}.png"
            if not tile_path.is_file():
                missing_tiles += 1
                continue
            try:
                with Image.open(tile_path) as im:
                    tile_rgba = im.convert("RGBA")
                mosaic.paste(tile_rgba, ((tx - tx0) * TILE_PIXEL_SIZE, (ty - ty0) * TILE_PIXEL_SIZE))
            except OSError as exc:
                missing_tiles += 1
                print(f"[WARN] Failed reading tile {tile_path}: {exc}", file=sys.stderr)

    if missing_tiles:
        prefix = f"[{spot_id}] " if spot_id else ""
        print(
            f"[WARN] {prefix}z={zoom}: {missing_tiles}/{total_tiles} tiles missing under {tiles_dir}",
            file=sys.stderr,
        )

    rel_left = left - tx0 * TILE_PIXEL_SIZE
    rel_top = top - ty0 * TILE_PIXEL_SIZE
    rel_right = rel_left + native_w
    rel_bottom = rel_top + native_h

    cropped = mosaic.transform(
        (native_w, native_h),
        Image.Transform.EXTENT,
        (rel_left, rel_top, rel_right, rel_bottom),
        resample=Image.Resampling.BICUBIC,
    )
    if (out_w, out_h) != (native_w, native_h):
        cropped = cropped.resize((out_w, out_h), Image.Resampling.LANCZOS)
    return cropped, total_tiles, missing_tiles


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    bg: tuple[int, int, int, int] = (255, 255, 255, 232),
    border: tuple[int, int, int, int] = (203, 213, 225, 255),
    fg: tuple[int, int, int, int] = (15, 23, 42, 255),
    pad_x: int = 20,
    pad_y: int = 10,
    radius: int = 14,
) -> tuple[int, int, int, int]:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    rect = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    draw.rounded_rectangle(rect, radius=radius, fill=bg, outline=border, width=2)
    draw.text((x + pad_x - bbox[0], y + pad_y - bbox[1]), text, font=font, fill=fg)
    return rect


def _draw_teardrop_pin(
    draw: ImageDraw.ImageDraw,
    tip_x: float,
    tip_y: float,
    confidence: str,
    ring_radius_px: int,
    ss: int = 2,
) -> None:
    """Draw a high-contrast locator pin whose sharp tip lands precisely at (tip_x, tip_y) in 2x space."""
    is_high = confidence == "high"
    pin_color = (220, 38, 38, 255) if is_high else (217, 119, 6, 255)

    # Accuracy ring centered directly on (tip_x, tip_y)
    ring_r = ring_radius_px * ss
    ring_bbox = (tip_x - ring_r, tip_y - ring_r, tip_x + ring_r, tip_y + ring_r)
    if is_high:
        draw.ellipse(ring_bbox, fill=(220, 38, 38, 52), outline=(220, 38, 38, 195), width=2 * ss)
    else:
        draw.ellipse(ring_bbox, fill=(217, 119, 6, 40))
        for deg in range(0, 360, 20):
            draw.arc(ring_bbox, start=deg, end=deg + 11, fill=(217, 119, 6, 220), width=2 * ss)

    # Subtle ground shadow right at pin tip
    draw.ellipse(
        (tip_x - 7 * ss, tip_y - 2 * ss, tip_x + 7 * ss, tip_y + 3 * ss),
        fill=(15, 23, 42, 75),
    )

    # Outer white border teardrop -> inner colored teardrop -> white center hole
    radius = 12 * ss
    stem_h = 31 * ss
    head_cy = tip_y - stem_h
    head_cx = tip_x

    def draw_drop(drop_tip_y: float, r_val: float, fill_rgba: tuple[int, int, int, int]) -> None:
        dist = max(r_val + 1.0, drop_tip_y - head_cy)
        ratio = r_val / dist
        y_tang = head_cy + r_val * ratio
        x_off = r_val * math.sqrt(max(0.0, 1.0 - ratio * ratio))
        draw.polygon(
            [(head_cx, drop_tip_y), (head_cx - x_off, y_tang), (head_cx + x_off, y_tang)],
            fill=fill_rgba,
        )
        draw.ellipse(
            (head_cx - r_val, head_cy - r_val, head_cx + r_val, head_cy + r_val),
            fill=fill_rgba,
        )

    draw_drop(tip_y + 2 * ss, radius + 2.5 * ss, (255, 255, 255, 248))
    draw_drop(tip_y, float(radius), pin_color)
    inner_r = 4.6 * ss
    draw.ellipse(
        (head_cx - inner_r, head_cy - inner_r, head_cx + inner_r, head_cy + inner_r),
        fill=(255, 255, 255, 255),
    )


def _decorate_map(
    base_rgba: Image.Image,
    lat: float,
    spec: dict[str, Any],
    confidence: str,
) -> Image.Image:
    out_w, out_h = base_rgba.size
    ss = 2
    overlay = Image.new("RGBA", (out_w * ss, out_h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_badge = _load_font(13 * ss)
    font_small = _load_font(11 * ss)
    font_compass = _load_font(12 * ss)

    ring_r = int(spec["ring_radius_high"] if confidence == "high" else spec["ring_radius_approx"])
    _draw_teardrop_pin(
        draw,
        tip_x=(out_w * ss) / 2.0,
        tip_y=(out_h * ss) / 2.0,
        confidence=confidence,
        ring_radius_px=ring_r,
        ss=ss,
    )

    # Top-left scale pill
    margin = 12 * ss
    badge_bg = (27, 94, 60, 232) if spec["zoom"] <= 15 else (15, 61, 38, 232)
    _draw_pill(
        draw,
        (margin, margin),
        str(spec["scale_label"]),
        font_badge,
        bg=badge_bg,
        border=(255, 255, 255, 220),
        fg=(255, 255, 255, 255),
        pad_x=11 * ss,
        pad_y=6 * ss,
        radius=12 * ss,
    )

    # Top-right north compass chip
    chip_sz = 36 * ss
    cx0 = out_w * ss - margin - chip_sz
    cy0 = margin
    draw.ellipse(
        (cx0, cy0, cx0 + chip_sz, cy0 + chip_sz),
        fill=(255, 255, 255, 232),
        outline=(203, 213, 225, 255),
        width=2,
    )
    mid_x = cx0 + chip_sz / 2.0
    draw.polygon(
        [(mid_x, cy0 + 6 * ss), (mid_x - 4.5 * ss, cy0 + 15 * ss), (mid_x + 4.5 * ss, cy0 + 15 * ss)],
        fill=(220, 38, 38, 240),
    )
    n_bbox = draw.textbbox((0, 0), "N", font=font_compass)
    nw = n_bbox[2] - n_bbox[0]
    draw.text((mid_x - nw / 2.0 - n_bbox[0], cy0 + 16 * ss - n_bbox[1]), "N", font=font_compass, fill=(15, 23, 42, 255))

    # Bottom-left ground scale bar
    m_per_native = meters_per_native_px(lat, int(spec["zoom"]), TILE_PIXEL_SIZE)
    m_per_out = m_per_native * (float(spec["native_w"]) / float(out_w))
    bar_m = int(spec["scale_bar_m"])
    bar_px_2x = int(round((bar_m / m_per_out) * ss))
    bar_txt = f"{bar_m}m"
    tb = draw.textbbox((0, 0), bar_txt, font=font_small)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    sb_w = max(bar_px_2x, tw) + 20 * ss
    sb_h = th + 20 * ss
    sb_x = margin
    sb_y = out_h * ss - margin - sb_h
    draw.rounded_rectangle(
        (sb_x, sb_y, sb_x + sb_w, sb_y + sb_h),
        radius=8 * ss,
        fill=(255, 255, 255, 232),
        outline=(203, 213, 225, 255),
        width=2,
    )
    bar_x0 = sb_x + 10 * ss
    bar_y0 = sb_y + sb_h - 11 * ss
    half_bar = bar_px_2x // 2
    draw.rectangle((bar_x0, bar_y0, bar_x0 + half_bar, bar_y0 + 5 * ss), fill=(27, 94, 60, 255))
    draw.rectangle(
        (bar_x0 + half_bar, bar_y0, bar_x0 + bar_px_2x, bar_y0 + 5 * ss),
        fill=(255, 255, 255, 255),
        outline=(27, 94, 60, 255),
        width=2,
    )
    draw.text((bar_x0 - tb[0], sb_y + 5 * ss - tb[1]), bar_txt, font=font_small, fill=(15, 23, 42, 255))

    # Bottom-right subtle credit pill
    credit = "© OSM / 小平市防災タウンマップ"
    cb = draw.textbbox((0, 0), credit, font=font_small)
    cw = cb[2] - cb[0]
    ch = cb[3] - cb[1]
    cr_x = out_w * ss - margin - (cw + 16 * ss)
    cr_y = out_h * ss - margin - (ch + 12 * ss)
    _draw_pill(
        draw,
        (cr_x, cr_y),
        credit,
        font_small,
        bg=(255, 255, 255, 222),
        border=(203, 213, 225, 230),
        fg=(51, 65, 85, 255),
        pad_x=8 * ss,
        pad_y=6 * ss,
        radius=7 * ss,
    )

    overlay_down = overlay.resize((out_w, out_h), Image.Resampling.LANCZOS)
    return Image.alpha_composite(base_rgba, overlay_down).convert("RGB")


def render_maps_for_dossier(
    spot_id: str,
    dossier: dict[str, Any],
    *,
    tiles_dir: Path = DEFAULT_TILES_DIR,
) -> dict[str, Any]:
    """Render both wide and detail locator PNGs into docs/assets/spots/<spot_id>/ and return updated location dict."""
    loc = dossier.get("location")
    if not isinstance(loc, dict) or loc.get("lat") is None or loc.get("lon") is None:
        raise ValueError(f"[{spot_id}] dossier['location'] with lat and lon is required.")

    lat = float(loc["lat"])
    lon = float(loc["lon"])
    confidence = str(loc.get("confidence") or "high").strip().lower()
    if confidence not in {"high", "medium", "area"}:
        confidence = "medium"

    out_dir = DOCS_SPOTS_ASSETS_DIR / spot_id
    out_dir.mkdir(parents=True, exist_ok=True)

    maps_meta: dict[str, Any] = {}
    for key, spec in (("wide", WIDE_SPEC), ("detail", DETAIL_SPEC)):
        base_rgba, _, _ = _stitch_tiles(
            lat,
            lon,
            int(spec["zoom"]),
            int(spec["native_w"]),
            int(spec["native_h"]),
            int(spec["out_w"]),
            int(spec["out_h"]),
            tiles_dir,
            spot_id=spot_id,
        )
        final_rgb = _decorate_map(base_rgba, lat, spec, confidence)
        out_path = out_dir / str(spec["filename"])
        final_rgb.save(out_path, format="PNG", optimize=True)
        maps_meta[key] = {
            "src": f"assets/spots/{spot_id}/{spec['filename']}",
            "zoom": int(spec["zoom"]),
            "width": int(spec["out_w"]),
            "height": int(spec["out_h"]),
            "scale_label": str(spec["scale_label"]),
        }

    updated_loc = dict(loc)
    updated_loc["lat"] = round(lat, 6)
    updated_loc["lon"] = round(lon, 6)
    updated_loc["confidence"] = confidence
    updated_loc["maps"] = maps_meta
    if not updated_loc.get("verified_at"):
        updated_loc["verified_at"] = datetime.now(JST).date().isoformat()
    return updated_loc


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render kbt-2608 locator maps for Kodaira spot dossiers.")
    parser.add_argument("--spot-id", default="", help="Render maps for a single spot_id")
    parser.add_argument("--all", action="store_true", help="Render maps for all dossiers containing location coordinates")
    parser.add_argument("--tiles-dir", default=str(DEFAULT_TILES_DIR), help="Path to kbt-2608 tiles/{z}/{x}/{y}.png")
    parser.add_argument("--lat", type=float, default=None, help="Optional latitude override/initializer for --spot-id")
    parser.add_argument("--lon", type=float, default=None, help="Optional longitude override/initializer for --spot-id")
    parser.add_argument("--address", default="", help="Optional verified_address override for --spot-id")
    parser.add_argument("--confidence", default="", choices=["", "high", "medium", "area"], help="Coordinate confidence")
    parser.add_argument("--method", default="", help="verification_method string")
    parser.add_argument("--note", default="", help="accuracy_note string")
    args = parser.parse_args()

    tiles_dir = Path(args.tiles_dir)
    if not tiles_dir.is_dir():
        raise FileNotFoundError(f"Tiles directory not found: {tiles_dir}")

    if not args.spot_id and not args.all:
        raise ValueError("Specify --spot-id <id> or --all.")

    if args.spot_id:
        dp = SPOT_REPORTS_DIR / f"{args.spot_id}.json"
        if not dp.is_file():
            raise FileNotFoundError(f"Dossier not found: {dp}")
        targets = [dp]
    else:
        targets = sorted(SPOT_REPORTS_DIR.glob("*.json"))

    rendered = 0
    for dp in targets:
        sid = dp.stem
        dossier = _load_json(dp)
        if args.spot_id:
            loc = dict(dossier.get("location") or {})
            if args.lat is not None:
                loc["lat"] = args.lat
            if args.lon is not None:
                loc["lon"] = args.lon
            if args.address:
                loc["verified_address"] = args.address
            if args.confidence:
                loc["confidence"] = args.confidence
            if args.method:
                loc["verification_method"] = args.method
            if args.note:
                loc["accuracy_note"] = args.note
            dossier["location"] = loc

        if not isinstance(dossier.get("location"), dict) or dossier["location"].get("lat") is None:
            print(f"[SKIP] {sid}: no location.lat/lon yet")
            continue

        updated_loc = render_maps_for_dossier(sid, dossier, tiles_dir=tiles_dir)
        dossier["location"] = updated_loc
        _save_json(dp, dossier)
        rendered += 1
        print(
            f"MAP_OK: {sid} | ({updated_loc['lat']:.6f}, {updated_loc['lon']:.6f}) | conf={updated_loc['confidence']}"
        )

    print(f"RENDERED_SPOT_MAPS: {rendered}")


if __name__ == "__main__":
    main()
