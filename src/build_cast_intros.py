"""Generate cast self-introduction MP3s using Gemini 3.8 Flash TTS and procedural BGM."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import numpy as np
from dotenv import load_dotenv
from google import genai

from bgm_synth import SAMPLE_RATE, ensure_bgm_assets
from build_radio import (
    BGM_CACHE_DIR,
    DOCS_AUDIO_DIR,
    GEMINI_CACHE_DIR,
    GEMINI_TTS_MODEL,
    _add_audio,
    _build_looped_bgm,
    _close_gemini_client_quietly,
    _compute_ducking_envelope,
    _create_gemini_tts_client,
    _probe_mp3_duration,
    _read_wav_stereo,
    _resample_and_normalize,
    _synthesize_block_gemini,
    _write_wav_stereo,
    format_timestamp,
)

JST = timezone(timedelta(hours=9))
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
TMP_WORK_DIR = ROOT_DIR / ".cache" / "cast_intros_tmp"
INTROS_AUDIO_DIR = DOCS_AUDIO_DIR / "intros"
MANIFEST_PATH = DATA_DIR / "cast_intros_manifest.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_cast_roster() -> dict[str, dict[str, Any]]:
    """Build cast metadata map keyed by host/guest id from config files."""
    characters = _load_json(CONFIG_DIR / "characters.json")
    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    roster: dict[str, dict[str, Any]] = {}

    for host_id, h in characters.get("hosts", {}).items():
        roster[host_id] = {
            "id": host_id,
            "name": h["name"],
            "role": h["role"],
            "voice_name": h["tts"]["gemini_voice"],
            "default_style": h["tts"]["default_style"],
        }

    for day_cfg in themes.get("days", {}).values():
        g = day_cfg["guest"]
        roster[g["id"]] = {
            "id": g["id"],
            "name": g["name"],
            "role": f"{day_cfg['weekday_ja']}｜{g['title']}",
            "voice_name": g["voice_name"],
            "default_style": g["default_style"],
        }
    return roster


def _master_intro_mp3(
    client: genai.Client,
    ffmpeg_exe: str,
    bgm_buffers: dict[str, np.ndarray],
    entry: dict[str, Any],
    member: dict[str, Any],
    output_mp3: Path,
    bitrate: str,
) -> float:
    """Synthesize a single self-introduction clip, mix ducked BGM, and master to MP3."""
    cid = entry["id"]
    style = entry.get("style") or member["default_style"]
    bgm_name = entry.get("bgm") or "bgm_warm"
    if bgm_name not in bgm_buffers:
        bgm_name = "bgm_warm"

    TMP_WORK_DIR.mkdir(parents=True, exist_ok=True)
    raw_wav = TMP_WORK_DIR / f"{cid}_raw.wav"
    wav_44k = TMP_WORK_DIR / f"{cid}_44k.wav"
    mix_wav = TMP_WORK_DIR / f"{cid}_mix.wav"

    try:
        block = [
            {
                "speaker": cid,
                "text": entry["text"],
                "tts_text": entry["tts_text"],
                "style": style,
            }
        ]
        voices_cfg = {
            cid: {
                "gemini_voice": member["voice_name"],
                "default_style": style,
            }
        }
        _synthesize_block_gemini(client, block, voices_cfg, raw_wav)
        mono = _resample_and_normalize(ffmpeg_exe, raw_wav, wav_44k, target_rms_dbfs=-20.0)
        speech_stereo = np.column_stack((mono, mono))

        lead_smp = int(0.45 * SAMPLE_RATE)
        tail_smp = int(1.10 * SAMPLE_RATE)
        total_samples = lead_smp + len(mono) + tail_smp
        speech_intervals = [(lead_smp, lead_smp + len(mono))]

        speech_track = np.zeros((total_samples, 2), dtype=np.float64)
        _add_audio(speech_track, lead_smp, speech_stereo, gain=1.0)

        bgm_track = _build_looped_bgm(
            bgm_buffers[bgm_name],
            total_samples,
            fade_in_sec=0.35,
            fade_out_sec=0.90,
        )
        duck_env = _compute_ducking_envelope(
            total_samples,
            speech_intervals,
            speech_gain=0.10,
            idle_gain=0.28,
        )
        mixed = speech_track + bgm_track * duck_env[:, None]

        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.95:
            mixed = mixed * (0.95 / peak)

        output_mp3.parent.mkdir(parents=True, exist_ok=True)
        _write_wav_stereo(mix_wav, mixed)
        subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-i",
                str(mix_wav),
                "-af",
                "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "2",
                "-metadata",
                f"title={member['name']} 自己紹介 | こだいら防災＆まちラジオ",
                "-metadata",
                f"artist={member['name']}",
                "-metadata",
                "album=毎朝7時！こだいら防災＆まちラジオ 出演者自己紹介",
                "-metadata",
                "genre=Podcast",
                str(output_mp3),
            ],
            check=True,
            capture_output=True,
        )
        dur = _probe_mp3_duration(ffmpeg_exe, output_mp3)
        return round(dur if dur is not None else total_samples / SAMPLE_RATE, 2)
    finally:
        for p in (raw_wav, wav_44k, mix_wav):
            p.unlink(missing_ok=True)


def build_cast_intros(
    only_id: str | None = None,
    force: bool = False,
    bitrate: str = "112k",
) -> dict[str, Any]:
    """Generate missing (or forced) cast intro MP3s and write data/cast_intros_manifest.json."""
    load_dotenv(ROOT_DIR / ".env")
    cfg = _load_json(CONFIG_DIR / "cast_intros.json")
    entries = cfg.get("cast_intros", [])
    roster = _resolve_cast_roster()

    valid_ids = {e["id"] for e in entries}
    if only_id and only_id not in valid_ids:
        raise ValueError(f"Unknown cast id '{only_id}'. Valid IDs: {sorted(valid_ids)}")

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    needs_synth: list[str] = []
    for e in entries:
        cid = e["id"]
        if only_id and cid != only_id:
            continue
        mp3_path = INTROS_AUDIO_DIR / f"intro_{cid}.mp3"
        if force or not (mp3_path.exists() and mp3_path.stat().st_size > 10_000):
            needs_synth.append(cid)

    client_holder: dict[str, Any] | None = None
    bgm_buffers: dict[str, np.ndarray] = {}
    if needs_synth:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key or api_key == "your_gemini_api_key_here":
            print(
                "ERROR: GEMINI_API_KEY is not set. Configure .env with your Gemini API key.",
                file=sys.stderr,
            )
            sys.exit(1)
        client_holder = {
            "client": _create_gemini_tts_client(api_key),
            "api_key": api_key,
        }
        GEMINI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        bgm_paths = ensure_bgm_assets(BGM_CACHE_DIR)
        bgm_buffers = {name: _read_wav_stereo(p) for name, p in bgm_paths.items()}

    manifest_entries: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    try:
        for e in entries:
            cid = e["id"]
            member = roster[cid]
            mp3_path = INTROS_AUDIO_DIR / f"intro_{cid}.mp3"
            mp3_rel = f"audio/intros/intro_{cid}.mp3"

            if cid in needs_synth:
                assert client_holder is not None
                print(f"Synthesizing {cid} ({member['name']} / voice={member['voice_name']})...")
                dur_sec = _master_intro_mp3(
                    client=client_holder,
                    ffmpeg_exe=ffmpeg_exe,
                    bgm_buffers=bgm_buffers,
                    entry=e,
                    member=member,
                    output_mp3=mp3_path,
                    bitrate=bitrate,
                )
                print(f"  -> {mp3_path} ({format_timestamp(dur_sec)} / {mp3_path.stat().st_size} bytes)")
            elif mp3_path.exists() and mp3_path.stat().st_size > 10_000:
                dur = _probe_mp3_duration(ffmpeg_exe, mp3_path)
                dur_sec = round(dur if dur is not None else 0.0, 2)
            else:
                continue

            item = {
                "id": cid,
                "name": member["name"],
                "voice_name": member["voice_name"],
                "tts_model": GEMINI_TTS_MODEL,
                "mp3_rel": mp3_rel,
                "duration_sec": dur_sec,
                "duration_formatted": format_timestamp(dur_sec),
                "tagline": e["tagline"],
                "text": e["text"],
            }
            manifest_entries.append(item)
            by_id[cid] = item
    finally:
        if client_holder is not None:
            _close_gemini_client_quietly(client_holder.get("client"))

    manifest = {
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "tts_model": GEMINI_TTS_MODEL,
        "entries": manifest_entries,
        "by_id": by_id,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved cast intro manifest: {MANIFEST_PATH} ({len(manifest_entries)} clip(s))")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cast self-introduction MP3s via Gemini TTS")
    parser.add_argument("--only", default=None, help="Synthesize only this cast ID (e.g., koharu)")
    parser.add_argument("--force", action="store_true", help="Re-render existing intro MP3 files")
    parser.add_argument("--bitrate", default="112k", help="Output MP3 bitrate (default: 112k)")
    args = parser.parse_args()
    build_cast_intros(only_id=args.only, force=args.force, bitrate=args.bitrate)


if __name__ == "__main__":
    main()
