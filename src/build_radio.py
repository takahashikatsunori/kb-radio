"""Build daily Kodaira radio MP3 and manifest using Gemini 3.8 Flash TTS (or Edge TTS fallback)."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

import edge_tts
import imageio_ffmpeg
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

from bgm_synth import SAMPLE_RATE, ensure_bgm_assets

ROOT_DIR = Path(__file__).resolve().parent.parent
EPISODES_DIR = ROOT_DIR / "episodes"
GEMINI_CACHE_DIR = ROOT_DIR / ".cache" / "tts_gemini"
EDGE_CACHE_DIR = ROOT_DIR / ".cache" / "tts_edge"
BGM_CACHE_DIR = ROOT_DIR / ".cache" / "bgm"
DOCS_AUDIO_DIR = ROOT_DIR / "docs" / "audio"

GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"
MAX_BLOCK_TURNS = 4
MAX_BLOCK_CHARS = 420


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS."""
    total = max(0, int(round(seconds)))
    mins, secs = divmod(total, 60)
    return f"{mins:02d}:{secs:02d}"


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _read_wav_stereo(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sr = wf.getframerate()
        if sr != SAMPLE_RATE:
            raise ValueError(f"Expected {SAMPLE_RATE} Hz WAV, got {sr} Hz: {path}")
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels == 1:
        return np.column_stack((samples, samples))
    return samples.reshape(-1, channels)[:, :2]


def _read_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        if sr != SAMPLE_RATE:
            raise ValueError(f"Expected {SAMPLE_RATE} Hz WAV, got {sr} Hz: {path}")
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples


def _write_wav_stereo(path: Path, stereo: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _group_lines_into_blocks(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group sequential lines into multi-speaker blocks of <=2 unique speakers, <=4 turns, <=420 chars."""
    blocks: list[list[dict[str, Any]]] = []
    cur_block: list[dict[str, Any]] = []
    cur_speakers: set[str] = set()
    cur_chars = 0

    for line in lines:
        sp = line["speaker"]
        spoken = line.get("tts_text") or line["text"]
        line_len = len(spoken)

        next_speakers = cur_speakers | {sp}
        would_exceed_speakers = len(next_speakers) > 2
        would_exceed_turns = len(cur_block) >= MAX_BLOCK_TURNS
        would_exceed_chars = bool(cur_block) and (cur_chars + line_len > MAX_BLOCK_CHARS)

        if cur_block and (would_exceed_speakers or would_exceed_turns or would_exceed_chars):
            blocks.append(cur_block)
            cur_block = []
            cur_speakers = set()
            cur_chars = 0

        cur_block.append(line)
        cur_speakers.add(sp)
        cur_chars += line_len

    if cur_block:
        blocks.append(cur_block)
    return blocks


def _decode_audio_field_to_bytes(raw_data: Any) -> bytes:
    """Convert SDK audio data field (raw WAV bytes or base64 string/bytes) to WAV bytes."""
    if isinstance(raw_data, (bytes, bytearray)):
        b = bytes(raw_data)
        if b[:4] == b"RIFF":
            return b
        try:
            decoded = base64.b64decode(b, validate=True)
            if decoded[:4] == b"RIFF":
                return decoded
        except Exception:  # noqa: BLE001
            pass
        return b
    if isinstance(raw_data, str):
        return base64.b64decode(raw_data)
    raise ValueError(f"Unsupported audio data type: {type(raw_data)}")


def _extract_wav_from_interaction(interaction: Any) -> bytes:
    """Extract WAV bytes from an Interactions API response object."""
    out_audio = getattr(interaction, "output_audio", None)
    if out_audio is not None:
        data = getattr(out_audio, "data", None)
        if data:
            return _decode_audio_field_to_bytes(data)

    direct_bytes = getattr(interaction, "audio_bytes", None)
    if direct_bytes:
        return _decode_audio_field_to_bytes(direct_bytes)

    for step in getattr(interaction, "steps", None) or []:
        for item in getattr(step, "content", None) or getattr(step, "outputs", None) or []:
            if getattr(item, "type", None) == "audio":
                data = getattr(item, "data", None)
                if data:
                    return _decode_audio_field_to_bytes(data)

    raise RuntimeError("No audio payload found in Gemini Interactions response")


def _synthesize_block_gemini(
    client: genai.Client,
    block: list[dict[str, Any]],
    voices_cfg: dict[str, Any],
    raw_wav_path: Path,
) -> None:
    """Synthesize a 1-or-2-speaker dialogue block via Gemini 3.8 Flash TTS with caching."""
    unique_speakers: list[str] = []
    for line in block:
        if line["speaker"] not in unique_speakers:
            unique_speakers.append(line["speaker"])

    cache_payload = {
        "model": GEMINI_TTS_MODEL,
        "speakers": [
            {"id": sp, "voice": voices_cfg[sp]["gemini_voice"]} for sp in unique_speakers
        ],
        "turns": [
            {
                "speaker": l["speaker"],
                "style": l.get("style") or voices_cfg[l["speaker"]].get("default_style", ""),
                "text": l.get("tts_text") or l["text"],
            }
            for l in block
        ],
    }
    key = hashlib.sha256(
        json.dumps(cache_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    cached_wav = GEMINI_CACHE_DIR / f"{key}.wav"
    if cached_wav.exists() and cached_wav.stat().st_size > 1000:
        raw_wav_path.write_bytes(cached_wav.read_bytes())
        return

    cached_wav.parent.mkdir(parents=True, exist_ok=True)
    content_parts = [
        {
            "type": "text",
            "text": l.get("tts_text") or l["text"],
            "annotations": [
                {
                    "type": "speech_metadata",
                    "speaker": l["speaker"],
                    "style": l.get("style") or voices_cfg[l["speaker"]].get("default_style", ""),
                }
            ],
        }
        for l in block
    ]
    speaker_configs = [
        {
            "speaker": sp,
            "voice": voices_cfg[sp]["gemini_voice"],
            "language": "ja-JP",
        }
        for sp in unique_speakers
    ]

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            try:
                interaction = client.interactions.create(
                    model=GEMINI_TTS_MODEL,
                    input=[{"type": "user_input", "content": content_parts}],
                    response_format={"type": "audio", "mime_type": "audio/wav"},
                    generation_config={
                        "speech_config": {"speakers": speaker_configs},
                    },
                )
                wav_bytes = _extract_wav_from_interaction(interaction)
            except Exception as inter_exc:  # noqa: BLE001
                err_str = str(inter_exc)
                # Retry rate/transient errors directly; fall back to generate_content only on schema/endpoint mismatch
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str:
                    raise
                if len(unique_speakers) == 1:
                    sp = unique_speakers[0]
                    speech_cfg = types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voices_cfg[sp]["gemini_voice"]
                            )
                        )
                    )
                else:
                    speech_cfg = types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=[
                                types.SpeakerVoiceConfig(
                                    speaker=sp,
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                            voice_name=voices_cfg[sp]["gemini_voice"]
                                        )
                                    ),
                                )
                                for sp in unique_speakers
                            ]
                        )
                    )
                parts_gc = [
                    {
                        "text": l.get("tts_text") or l["text"],
                        "speech_metadata": {
                            "speaker": l["speaker"],
                            "style": l.get("style") or voices_cfg[l["speaker"]].get("default_style", ""),
                        },
                    }
                    for l in block
                ]
                resp = client.models.generate_content(
                    model=GEMINI_TTS_MODEL,
                    contents=[{"role": "user", "parts": parts_gc}],
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=speech_cfg,
                    ),
                )
                inline_data = resp.candidates[0].content.parts[0].inline_data.data
                wav_bytes = _decode_audio_field_to_bytes(inline_data)

            if len(wav_bytes) < 512:
                raise RuntimeError("Gemini TTS returned empty audio payload")
            tmp = cached_wav.with_suffix(".wav.tmp")
            tmp.write_bytes(wav_bytes)
            tmp.replace(cached_wav)
            raw_wav_path.write_bytes(wav_bytes)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2.0 * (2**attempt))

    raise RuntimeError(f"Gemini TTS synthesis failed after retries: {last_err}")


async def _synthesize_line_edge(
    sem: asyncio.Semaphore,
    voice: str,
    rate: str,
    pitch: str,
    spoken_text: str,
    mp3_path: Path,
) -> None:
    if mp3_path.exists() and mp3_path.stat().st_size > 512:
        return
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = mp3_path.with_suffix(".mp3.tmp")
    async with sem:
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                comm = edge_tts.Communicate(text=spoken_text, voice=voice, rate=rate, pitch=pitch)
                await comm.save(str(tmp_path))
                if tmp_path.exists() and tmp_path.stat().st_size > 512:
                    tmp_path.replace(mp3_path)
                    return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                tmp_path.unlink(missing_ok=True)
                await asyncio.sleep(1.5 * (2**attempt))
        raise RuntimeError(f"Edge TTS failed after retries: {last_err}")


async def _synthesize_all_edge(episode: dict[str, Any]) -> dict[str, Path]:
    voices = episode["meta"]["voices"]
    sem = asyncio.Semaphore(3)
    tasks: list[asyncio.Task[None]] = []
    key_to_mp3: dict[str, Path] = {}
    for seg in episode["segments"]:
        for line in seg["lines"]:
            v_cfg = voices[line["speaker"]]
            clean_spoken = _strip_tags(line.get("tts_text") or line["text"])
            voice = v_cfg.get("edge_voice") or v_cfg.get("voice") or "ja-JP-NanamiNeural"
            rate = v_cfg.get("edge_rate") or v_cfg.get("rate") or "+2%"
            pitch = v_cfg.get("edge_pitch") or v_cfg.get("pitch") or "+0Hz"
            key = hashlib.sha256(f"{voice}|{rate}|{pitch}|{clean_spoken}".encode("utf-8")).hexdigest()[:24]
            mp3_path = EDGE_CACHE_DIR / f"{key}.mp3"
            key_to_mp3[key] = mp3_path
            tasks.append(asyncio.create_task(_synthesize_line_edge(sem, voice, rate, pitch, clean_spoken, mp3_path)))
    await asyncio.gather(*tasks)
    return key_to_mp3


def _resample_and_normalize(
    ffmpeg_exe: str,
    src_audio_path: Path,
    wav_44k_path: Path,
    target_rms_dbfs: float = -20.0,
) -> np.ndarray:
    """Convert any WAV/MP3 (e.g. Gemini 24kHz WAV) to 44.1kHz mono, trim silence, and normalize."""
    if not wav_44k_path.exists() or wav_44k_path.stat().st_mtime < src_audio_path.stat().st_mtime:
        subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-i",
                str(src_audio_path),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav_44k_path),
            ],
            check=True,
            capture_output=True,
        )

    mono = _read_wav_mono(wav_44k_path)
    if mono.size == 0:
        return mono

    thresh = 10.0 ** (-45.0 / 20.0)
    win = max(1, int(0.010 * SAMPLE_RATE))
    pad = int(0.045 * SAMPLE_RATE)
    n_frames = len(mono) // win
    if n_frames > 0:
        framed = np.abs(mono[: n_frames * win]).reshape(n_frames, win)
        active = np.where(np.max(framed, axis=1) >= thresh)[0]
        if active.size > 0:
            start_idx = max(0, int(active[0]) * win - pad)
            end_idx = min(len(mono), int(active[-1] + 1) * win + pad)
            mono = mono[start_idx:end_idx]

    fade_n = min(len(mono) // 4, int(0.006 * SAMPLE_RATE))
    if fade_n > 0:
        mono[:fade_n] *= np.linspace(0.0, 1.0, fade_n)
        mono[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)

    active_samples = mono[np.abs(mono) > 10.0 ** (-38.0 / 20.0)]
    rms = (
        float(np.sqrt(np.mean(active_samples**2)))
        if active_samples.size > 100
        else float(np.sqrt(np.mean(mono**2)))
    )
    if rms > 1e-6:
        mono = mono * (10.0 ** (target_rms_dbfs / 20.0) / rms)

    peak_limit = 10.0 ** (-3.0 / 20.0)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > peak_limit:
        mono = mono * (peak_limit / peak)
    return mono


def _pan_mono(mono: np.ndarray, pan: float) -> np.ndarray:
    pan_c = max(-1.0, min(1.0, pan))
    angle = (pan_c + 1.0) * (math.pi / 4.0)
    return np.column_stack((mono * math.cos(angle), mono * math.sin(angle)))


def _add_audio(dst: np.ndarray, start_sample: int, src: np.ndarray, gain: float = 1.0) -> None:
    if start_sample >= dst.shape[0] or start_sample + src.shape[0] <= 0:
        return
    src_s = max(0, -start_sample)
    dst_s = max(0, start_sample)
    n = min(src.shape[0] - src_s, dst.shape[0] - dst_s)
    if n > 0:
        dst[dst_s : dst_s + n] += src[src_s : src_s + n] * gain


def _build_looped_bgm(
    bgm_stereo: np.ndarray,
    num_samples: int,
    fade_in_sec: float = 1.2,
    fade_out_sec: float = 1.2,
) -> np.ndarray:
    if num_samples <= 0:
        return np.zeros((0, 2), dtype=np.float64)
    reps = math.ceil(num_samples / bgm_stereo.shape[0])
    tiled = np.tile(bgm_stereo, (reps, 1))[:num_samples].copy()
    fi = min(num_samples // 2, int(fade_in_sec * SAMPLE_RATE))
    fo = min(num_samples // 2, int(fade_out_sec * SAMPLE_RATE))
    if fi > 0:
        tiled[:fi] *= np.linspace(0.0, 1.0, fi)[:, None]
    if fo > 0:
        tiled[-fo:] *= np.linspace(1.0, 0.0, fo)[:, None]
    return tiled


def _compute_ducking_envelope(
    total_samples: int,
    speech_intervals: list[tuple[int, int]],
    speech_gain: float = 0.11,
    idle_gain: float = 0.36,
    lookahead_sec: float = 0.16,
    attack_sec: float = 0.25,
    release_sec: float = 0.65,
) -> np.ndarray:
    hop = int(0.010 * SAMPLE_RATE)
    n_frames = math.ceil(total_samples / hop) + 1
    target = np.full(n_frames, idle_gain, dtype=np.float64)
    look_frames = int(lookahead_sec / 0.010)
    tail_hold_frames = int(0.08 / 0.010)

    for s_smp, e_smp in speech_intervals:
        f_start = max(0, s_smp // hop - look_frames)
        f_end = min(n_frames, math.ceil(e_smp / hop) + tail_hold_frames)
        target[f_start:f_end] = speech_gain

    alpha_attack = 1.0 - math.exp(-0.010 / max(0.02, attack_sec / 3.0))
    alpha_release = 1.0 - math.exp(-0.010 / max(0.02, release_sec / 3.0))
    env_frames = np.empty(n_frames, dtype=np.float64)
    cur = idle_gain
    for i in range(n_frames):
        t_val = target[i]
        cur += (t_val - cur) * (alpha_attack if t_val < cur else alpha_release)
        env_frames[i] = cur

    frame_x = np.arange(n_frames, dtype=np.float64) * hop
    sample_x = np.arange(total_samples, dtype=np.float64)
    return np.interp(sample_x, frame_x, env_frames)


def _probe_mp3_duration(ffmpeg_exe: str, mp3_path: Path) -> float | None:
    res = subprocess.run(
        [ffmpeg_exe, "-i", str(mp3_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in res.stderr.splitlines():
        if "Duration:" in line:
            part = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
            hms = part.split(":")
            if len(hms) == 3:
                return int(hms[0]) * 3600 + int(hms[1]) * 60 + float(hms[2])
    return None


def _run_dry_run(episode: dict[str, Any], tts_engine: str) -> None:
    """Validate 2-speaker block chunking, voice mappings, and estimated API request count."""
    voices = episode["meta"]["voices"]
    total_blocks = 0
    total_lines = 0
    total_chars = 0
    print(f"=== DRY RUN ({tts_engine.upper()}) : {episode['meta']['episode_date']} ===")
    for seg in episode["segments"]:
        lines = seg["lines"]
        blocks = _group_lines_into_blocks(lines) if tts_engine == "gemini" else [[l] for l in lines]
        total_blocks += len(blocks)
        total_lines += len(lines)
        seg_chars = sum(len(l["text"]) for l in lines)
        total_chars += seg_chars
        print(f"\nSegment [{seg['id']}] {seg['title']} ({len(lines)} lines, {seg_chars} chars -> {len(blocks)} blocks)")
        for b_idx, blk in enumerate(blocks):
            sps = []
            for l in blk:
                if l["speaker"] not in sps:
                    sps.append(l["speaker"])
            if tts_engine == "gemini":
                assert len(sps) <= 2, f"Block exceeded 2 speakers: {sps}"
            sp_desc = ", ".join(f"{voices[s]['name']}({voices[s].get('gemini_voice', voices[s].get('edge_voice', ''))})" for s in sps)
            blk_chars = sum(len(l.get("tts_text") or l["text"]) for l in blk)
            print(f"  Block {b_idx+1:02d}: {len(blk)} turns, {blk_chars:3d} tts_chars, speakers=[{sp_desc}]")

    print(f"\nSummary: {total_lines} lines | {total_chars} display chars | {total_blocks} TTS requests (RPD-safe <= 100)")


def build_episode(
    episode_json_path: Path,
    tts_engine: str = "gemini",
    bitrate: str = "112k",
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Build complete stereo MP3 in docs/audio/ and manifest.json beside episode.json."""
    load_dotenv(ROOT_DIR / ".env")
    episode = json.loads(episode_json_path.read_text(encoding="utf-8"))
    meta = episode["meta"]
    voices = meta["voices"]

    if dry_run:
        _run_dry_run(episode, tts_engine)
        return None

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    bgm_paths = ensure_bgm_assets(BGM_CACHE_DIR)
    bgm_buffers = {name: _read_wav_stereo(p) for name, p in bgm_paths.items()}

    speech_placements: list[tuple[int, np.ndarray]] = []
    speech_intervals: list[tuple[int, int]] = []
    jingle_placements: list[tuple[int, np.ndarray, float]] = []
    bgm_placements: list[tuple[int, int, str]] = []
    timeline_segments: list[dict[str, Any]] = []

    cursor_smp = 0
    global_idx = 0
    total_requests = 0

    if tts_engine == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key or api_key == "your_gemini_api_key_here":
            print(
                "ERROR: GEMINI_API_KEY is not set. Copy .env.example to .env and enter your Gemini API key, "
                "or pass --tts-engine edge for offline fallback testing.",
                file=sys.stderr,
            )
            sys.exit(1)
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        GEMINI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    else:
        client = None
        edge_map = asyncio.run(_synthesize_all_edge(episode))

    for seg in episode["segments"]:
        seg_start_smp = cursor_smp
        intro_name = seg.get("intro_jingle")

        if intro_name and intro_name in bgm_buffers:
            jingle = bgm_buffers[intro_name]
            if intro_name == "opening_jingle":
                lead_smp = int(5.0 * SAMPLE_RATE)
                jingle_placements.append((cursor_smp, jingle, 0.72))
                bgm_bed_start_smp = cursor_smp + int(7.2 * SAMPLE_RATE)
                cursor_smp += lead_smp
            elif intro_name == "guest_jingle":
                cursor_smp += int(0.35 * SAMPLE_RATE)
                jingle_placements.append((cursor_smp, jingle, 0.72))
                bgm_bed_start_smp = cursor_smp + int(2.70 * SAMPLE_RATE)
                cursor_smp += int(2.15 * SAMPLE_RATE)
            else:
                cursor_smp += int(0.35 * SAMPLE_RATE)
                jingle_placements.append((cursor_smp, jingle, 0.68))
                bgm_bed_start_smp = cursor_smp + int(2.40 * SAMPLE_RATE)
                cursor_smp += int(1.85 * SAMPLE_RATE)
        else:
            bgm_bed_start_smp = cursor_smp

        seg_speech_start_smp = cursor_smp
        seg_lines_manifest: list[dict[str, Any]] = []
        blocks = _group_lines_into_blocks(seg["lines"]) if tts_engine == "gemini" else [[l] for l in seg["lines"]]
        line_idx_in_seg = 0

        for blk_idx, blk in enumerate(blocks):
            total_requests += 1
            if tts_engine == "gemini":
                assert client is not None
                raw_wav = GEMINI_CACHE_DIR / f"_raw_{seg['id']}_{blk_idx}.wav"
                wav_44k = GEMINI_CACHE_DIR / f"_44k_{seg['id']}_{blk_idx}.wav"
                _synthesize_block_gemini(client, blk, voices, raw_wav)
                mono = _resample_and_normalize(ffmpeg_exe, raw_wav, wav_44k)
                raw_wav.unlink(missing_ok=True)
                wav_44k.unlink(missing_ok=True)
                blk_speakers = {l["speaker"] for l in blk}
                pan = float(voices[next(iter(blk_speakers))].get("pan", 0.0)) if len(blk_speakers) == 1 else 0.0
                time.sleep(0.25)
            else:
                l0 = blk[0]
                v_cfg = voices[l0["speaker"]]
                clean_spoken = _strip_tags(l0.get("tts_text") or l0["text"])
                voice = v_cfg.get("edge_voice") or v_cfg.get("voice") or "ja-JP-NanamiNeural"
                rate = v_cfg.get("edge_rate") or v_cfg.get("rate") or "+2%"
                pitch = v_cfg.get("edge_pitch") or v_cfg.get("pitch") or "+0Hz"
                key = hashlib.sha256(f"{voice}|{rate}|{pitch}|{clean_spoken}".encode("utf-8")).hexdigest()[:24]
                mp3_path = edge_map[key]
                wav_44k = EDGE_CACHE_DIR / f"{key}.wav"
                mono = _resample_and_normalize(ffmpeg_exe, mp3_path, wav_44k)
                pan = float(v_cfg.get("pan", 0.0))

            stereo = _pan_mono(mono, pan)
            blk_start_smp = cursor_smp
            blk_end_smp = cursor_smp + stereo.shape[0]
            speech_placements.append((blk_start_smp, stereo))
            speech_intervals.append((blk_start_smp, blk_end_smp))

            pause_after = float(blk[-1].get("pause_after", 0.34))
            cursor_smp = blk_end_smp + int(pause_after * SAMPLE_RATE)

            # Distribute per-line timestamps proportionally inside multi-turn blocks
            blk_dur_sec = (blk_end_smp - blk_start_smp) / SAMPLE_RATE
            blk_start_sec = blk_start_smp / SAMPLE_RATE
            weights = [max(4, len(l["text"])) for l in blk]
            total_w = sum(weights)
            t_cur = blk_start_sec
            for l_i, line in enumerate(blk):
                part_dur = blk_dur_sec * (weights[l_i] / total_w)
                l_start = round(t_cur, 3)
                l_end = round(t_cur + part_dur, 3)
                t_cur += part_dur
                seg_lines_manifest.append(
                    {
                        "index": line_idx_in_seg,
                        "global_index": global_idx,
                        "speaker": line["speaker"],
                        "speaker_name": voices[line["speaker"]]["name"],
                        "text": line["text"],
                        "start_sec": l_start,
                        "end_sec": l_end,
                        "duration_sec": round(l_end - l_start, 3),
                    }
                )
                line_idx_in_seg += 1
                global_idx += 1

        seg_speech_end_smp = cursor_smp
        bgm_name = seg.get("bgm")
        if bgm_name and bgm_name in bgm_buffers:
            bed_end_smp = seg_speech_end_smp + int(0.8 * SAMPLE_RATE)
            if seg.get("outro_jingle"):
                bed_end_smp = max(bgm_bed_start_smp, seg_speech_end_smp - int(1.5 * SAMPLE_RATE))
            bgm_placements.append((bgm_bed_start_smp, bed_end_smp, bgm_name))

        outro_name = seg.get("outro_jingle")
        if outro_name and outro_name in bgm_buffers:
            outro = bgm_buffers[outro_name]
            outro_start_smp = max(0, seg_speech_end_smp - int(3.2 * SAMPLE_RATE))
            jingle_placements.append((outro_start_smp, outro, 0.72))
            cursor_smp = max(cursor_smp, outro_start_smp + outro.shape[0] + int(0.4 * SAMPLE_RATE))

        timeline_segments.append(
            {
                "id": seg["id"],
                "title": seg["title"],
                "bgm": bgm_name,
                "intro_jingle": intro_name,
                "outro_jingle": outro_name,
                "start_sec": round(seg_start_smp / SAMPLE_RATE, 3),
                "speech_start_sec": round(seg_speech_start_smp / SAMPLE_RATE, 3),
                "end_sec": round(cursor_smp / SAMPLE_RATE, 3),
                "duration_sec": round((cursor_smp - seg_start_smp) / SAMPLE_RATE, 3),
                "lines": seg_lines_manifest,
            }
        )

    total_samples = cursor_smp + int(0.5 * SAMPLE_RATE)
    print(f"Mixing {global_idx} lines ({total_requests} TTS chunks) over {total_samples / SAMPLE_RATE:.2f}s...")

    speech_track = np.zeros((total_samples, 2), dtype=np.float64)
    for s_smp, chunk in speech_placements:
        _add_audio(speech_track, s_smp, chunk, gain=1.0)

    jingle_track = np.zeros((total_samples, 2), dtype=np.float64)
    for s_smp, chunk, base_gain in jingle_placements:
        _add_audio(jingle_track, s_smp, chunk, gain=base_gain)

    bgm_track = np.zeros((total_samples, 2), dtype=np.float64)
    for s_smp, e_smp, bgm_name in bgm_placements:
        length = e_smp - s_smp
        if length > 0:
            _add_audio(bgm_track, s_smp, _build_looped_bgm(bgm_buffers[bgm_name], length), gain=1.0)

    duck_env = _compute_ducking_envelope(total_samples, speech_intervals, speech_gain=0.11, idle_gain=0.36)
    jingle_duck_env = _compute_ducking_envelope(
        total_samples, speech_intervals, speech_gain=0.14, idle_gain=0.75, lookahead_sec=0.18, attack_sec=0.35, release_sec=0.80
    )
    mixed = speech_track + bgm_track * duck_env[:, None] + jingle_track * jingle_duck_env[:, None]

    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.95:
        mixed = mixed * (0.95 / peak)

    DOCS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    temp_wav = DOCS_AUDIO_DIR / "_mix_temp.wav"
    output_mp3 = DOCS_AUDIO_DIR / meta["output_filename"]

    print(f"Mastering MP3 ({bitrate} Stereo, -16 LUFS) -> {output_mp3}...")
    _write_wav_stereo(temp_wav, mixed)
    try:
        subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-i",
                str(temp_wav),
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
                f"title={meta['title']} ({meta['episode_date']})",
                "-metadata",
                "artist=小春 & 平蔵",
                "-metadata",
                f"album={meta['title']}",
                "-metadata",
                f"date={meta['episode_date']}",
                "-metadata",
                "genre=Podcast",
                str(output_mp3),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        temp_wav.unlink(missing_ok=True)

    mp3_dur = _probe_mp3_duration(ffmpeg_exe, output_mp3)
    total_sec = round(mp3_dur if mp3_dur is not None else total_samples / SAMPLE_RATE, 3)

    manifest = {
        "meta": {
            "title": meta["title"],
            "subtitle": meta["subtitle"],
            "episode_date": meta["episode_date"],
            "episode_number": meta["episode_number"],
            "output_filename": meta["output_filename"],
            "tts_engine": tts_engine,
            "tts_model": GEMINI_TTS_MODEL if tts_engine == "gemini" else "edge-tts",
            "tts_requests": total_requests,
            "total_duration_sec": total_sec,
            "total_duration_formatted": format_timestamp(total_sec),
            "line_count": global_idx,
        },
        "segments": timeline_segments,
    }
    manifest_path = episode_json_path.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Build Complete ===")
    print(f"MP3      : {output_mp3} ({output_mp3.stat().st_size / (1024 * 1024):.2f} MB)")
    print(f"Duration : {format_timestamp(total_sec)} ({total_sec:.2f}s) | Requests: {total_requests}")
    return manifest


def _find_latest_episode_json() -> Path:
    candidates = sorted(
        (p / "episode.json" for p in EPISODES_DIR.iterdir() if p.is_dir() and (p / "episode.json").exists()),
        key=lambda p: p.parent.name,
    )
    if not candidates:
        raise FileNotFoundError(f"No episode.json found under {EPISODES_DIR}")
    return candidates[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build radio MP3 and manifest.json")
    parser.add_argument("episode", nargs="?", help="Path to episode.json")
    parser.add_argument("--latest", action="store_true", help="Build the newest episode directory")
    parser.add_argument("--tts-engine", choices=["gemini", "edge"], default="gemini")
    parser.add_argument("--bitrate", default="112k")
    parser.add_argument("--dry-run", action="store_true", help="Verify chunking and request counts without calling TTS API")
    args = parser.parse_args()

    if args.latest or not args.episode:
        ep_path = _find_latest_episode_json()
    else:
        ep_path = Path(args.episode).resolve()

    build_episode(
        ep_path,
        tts_engine=args.tts_engine,
        bitrate=args.bitrate,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
