"""Original FM-radio style BGM and jingle synthesizer using NumPy and wave."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
BGM_ASSET_VERSION = "v3"


def _midi_to_freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _lowpass_fir(stereo: np.ndarray, cutoff_hz: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Apply a smooth Hamming-windowed sinc low-pass filter per channel."""
    fc = min(max(cutoff_hz / sr, 0.005), 0.45)
    num_taps = 41
    n = np.arange(num_taps) - (num_taps - 1) / 2.0
    h = np.sinc(2.0 * fc * n) * np.hamming(num_taps)
    h /= np.sum(h)
    out = np.empty_like(stereo)
    for ch in range(stereo.shape[1]):
        out[:, ch] = np.convolve(stereo[:, ch], h, mode="same")
    return out


def _soft_reverb(
    stereo: np.ndarray,
    sr: int = SAMPLE_RATE,
    wet: float = 0.24,
    decay: float = 0.52,
) -> np.ndarray:
    """Add warm studio ambiance via multi-tap stereo delays and damping."""
    n = stereo.shape[0]
    wet_buf = np.zeros_like(stereo)
    taps_ms = [23.0, 37.0, 53.0, 73.0, 101.0, 137.0, 179.0]
    for idx, ms in enumerate(taps_ms):
        delay = int(sr * ms / 1000.0)
        if delay >= n:
            continue
        gain = (decay ** (idx + 1)) * 0.48
        src_ch = idx % 2
        dst_ch = (idx + 1) % 2
        wet_buf[delay:, dst_ch] += stereo[: n - delay, src_ch] * gain
        wet_buf[delay:, src_ch] += stereo[: n - delay, src_ch] * (gain * 0.45)

    wet_buf = _lowpass_fir(wet_buf, 3200.0, sr)
    return stereo * (1.0 - wet * 0.35) + wet_buf * wet


def _pan_stereo(mono: np.ndarray, pan: float = 0.0) -> np.ndarray:
    """Constant-power stereo panning (-1.0 left to +1.0 right)."""
    pan_clamped = max(-1.0, min(1.0, pan))
    angle = (pan_clamped + 1.0) * (math.pi / 4.0)
    left = mono * math.cos(angle)
    right = mono * math.sin(angle)
    return np.column_stack((left, right))


def _place_chunk(
    buf: np.ndarray,
    start_sample: int,
    chunk: np.ndarray,
    wrap: bool = False,
) -> None:
    """Add stereo chunk into buffer, optionally wrapping around for seamless loops."""
    buf_len = buf.shape[0]
    chunk_len = chunk.shape[0]
    if wrap:
        start_mod = start_sample % buf_len
        first = min(chunk_len, buf_len - start_mod)
        buf[start_mod : start_mod + first] += chunk[:first]
        rem = chunk_len - first
        if rem > 0:
            # Split remaining across buffer boundary (handle chunks > buf_len safely)
            offset = first
            while rem > 0:
                take = min(rem, buf_len)
                buf[:take] += chunk[offset : offset + take]
                offset += take
                rem -= take
    else:
        if start_sample >= buf_len or start_sample + chunk_len <= 0:
            return
        src_start = max(0, -start_sample)
        dst_start = max(0, start_sample)
        copy_len = min(chunk_len - src_start, buf_len - dst_start)
        if copy_len > 0:
            buf[dst_start : dst_start + copy_len] += chunk[src_start : src_start + copy_len]


def _synth_ep_note(
    midi: float,
    dur_sec: float,
    vel: float = 0.7,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Synthesize a warm Rhodes-style electric piano note."""
    n = max(1, int(dur_sec * sr))
    t = np.arange(n, dtype=np.float64) / sr
    freq = _midi_to_freq(midi)

    # Gentle attack + warm sustain decay + smooth release
    attack_n = min(n, max(1, int(0.012 * sr)))
    release_n = min(n, max(1, int(min(0.28, dur_sec * 0.35) * sr)))
    env = np.exp(-t * 1.65)
    env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
    env[-release_n:] *= np.linspace(1.0, 0.0, release_n)

    # Characteristic soft tine ping at attack
    tine_attack = np.minimum(1.0, t / 0.004)
    tine_env = np.exp(-t * 34.0) * tine_attack
    tine = 0.14 * np.sin(2.0 * math.pi * (freq * 4.0) * t) * tine_env

    # Warm body harmonics
    body = (
        0.72 * np.sin(2.0 * math.pi * freq * t)
        + 0.22 * np.sin(2.0 * math.pi * (freq * 2.0) * t) * np.exp(-t * 2.5)
        + 0.07 * np.sin(2.0 * math.pi * (freq * 3.0) * t) * np.exp(-t * 4.2)
    )
    # Subtle warm tremolo
    tremolo = 1.0 - 0.05 * (0.5 - 0.5 * np.cos(2.0 * math.pi * 3.8 * t))
    return (body * env * tremolo + tine) * vel * 0.42


def _synth_bell_note(
    midi: float,
    dur_sec: float,
    vel: float = 0.75,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Synthesize a soft marimba/celesta chime note for jingles and accents."""
    n = max(1, int(dur_sec * sr))
    t = np.arange(n, dtype=np.float64) / sr
    freq = _midi_to_freq(midi)

    attack_n = min(n, max(1, int(0.006 * sr)))
    release_n = min(n, max(1, int(0.08 * sr)))
    env = np.exp(-t * 4.2)
    env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
    env[-release_n:] *= np.linspace(1.0, 0.0, release_n)

    tone = (
        0.78 * np.sin(2.0 * math.pi * freq * t)
        + 0.18 * np.sin(2.0 * math.pi * (freq * 2.0) * t) * np.exp(-t * 8.0)
        + 0.08 * np.sin(2.0 * math.pi * (freq * 3.98) * t) * np.exp(-t * 16.0)
    )
    return tone * env * vel * 0.38


def _synth_pad_chord(
    midis: list[float],
    dur_sec: float,
    amp: float = 0.14,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Synthesize a warm detuned stereo pad chord."""
    n = max(1, int(dur_sec * sr))
    t = np.arange(n, dtype=np.float64) / sr

    attack_n = min(n // 2, int(0.45 * sr))
    release_n = min(n // 2, int(0.55 * sr))
    env = np.ones(n, dtype=np.float64)
    if attack_n > 0:
        env[:attack_n] = np.sin(np.linspace(0.0, math.pi / 2.0, attack_n)) ** 2
    if release_n > 0:
        env[-release_n:] *= np.sin(np.linspace(math.pi / 2.0, 0.0, release_n)) ** 2

    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)
    for idx, midi in enumerate(midis):
        f_l = _midi_to_freq(midi - 0.04)
        f_r = _midi_to_freq(midi + 0.04)
        phase = idx * 0.7
        sig_l = (
            0.75 * np.sin(2.0 * math.pi * f_l * t + phase)
            + 0.25 * np.sin(2.0 * math.pi * (f_l * 2.0) * t + phase)
        )
        sig_r = (
            0.75 * np.sin(2.0 * math.pi * f_r * t + phase + 0.3)
            + 0.25 * np.sin(2.0 * math.pi * (f_r * 2.0) * t + phase + 0.3)
        )
        left += sig_l
        right += sig_r

    scale = amp / max(1, len(midis))
    stereo = np.column_stack((left * env * scale, right * env * scale))
    return _lowpass_fir(stereo, 1800.0, sr)


def _synth_bass_note(
    midi: float,
    dur_sec: float,
    vel: float = 0.65,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Synthesize a warm rounded bass note."""
    n = max(1, int(dur_sec * sr))
    t = np.arange(n, dtype=np.float64) / sr
    freq = _midi_to_freq(midi)

    attack_n = min(n, max(1, int(0.015 * sr)))
    release_n = min(n, max(1, int(0.12 * sr)))
    env = np.exp(-t * 2.2)
    env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
    env[-release_n:] *= np.linspace(1.0, 0.0, release_n)

    tone = (
        0.82 * np.sin(2.0 * math.pi * freq * t)
        + 0.18 * np.sin(2.0 * math.pi * (freq * 2.0) * t) * np.exp(-t * 5.0)
    )
    return tone * env * vel * 0.36


def _synth_soft_shaker(dur_sec: float = 0.06, amp: float = 0.045, seed: int = 0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Synthesize a gentle brushed shaker pulse for news bed momentum."""
    rng = np.random.default_rng(seed)
    n = max(1, int(dur_sec * sr))
    t = np.arange(n, dtype=np.float64) / sr
    noise = rng.standard_normal(n)
    # Soft band-shaped envelope via difference + lowpass
    shaped = np.diff(noise, prepend=0.0) * np.exp(-t * 55.0)
    shaped[: min(n, int(0.008 * sr))] *= np.linspace(0.0, 1.0, min(n, int(0.008 * sr)))
    stereo = _pan_stereo(shaped * amp, pan=0.18)
    return _lowpass_fir(stereo, 4800.0, sr)


def _synth_soft_kick(dur_sec: float = 0.16, amp: float = 0.14, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Synthesize a warm, muffled low pulse (not a club kick)."""
    n = max(1, int(dur_sec * sr))
    t = np.arange(n, dtype=np.float64) / sr
    freq_sweep = 48.0 + 42.0 * np.exp(-t * 28.0)
    phase = 2.0 * math.pi * np.cumsum(freq_sweep) / sr
    env = np.exp(-t * 18.0)
    env[: min(n, int(0.004 * sr))] *= np.linspace(0.0, 1.0, min(n, int(0.004 * sr)))
    return _pan_stereo(np.sin(phase) * env * amp, pan=0.0)


def _finalize_and_write(path: Path, stereo: np.ndarray, target_dbfs: float = -3.0, sr: int = SAMPLE_RATE) -> None:
    """Apply gentle saturation, peak normalization, and write 16-bit Stereo WAV."""
    # Gentle warm saturation on peaks
    stereo = np.tanh(stereo * 1.05) / 1.05
    peak = float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if peak > 1e-6:
        target_lin = 10.0 ** (target_dbfs / 20.0)
        stereo = stereo * (target_lin / peak)
    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype("<i2")

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _build_opening_jingle(path: Path) -> None:
    """Build ~9s bright morning FM opening jingle (Cmaj7 -> Fmaj7 -> G6 -> Cmaj9)."""
    sr = SAMPLE_RATE
    total_sec = 9.2
    buf = np.zeros((int(total_sec * sr), 2), dtype=np.float64)
    beat = 60.0 / 108.0  # ~0.5556s

    chords = [
        (0.0, [60, 64, 67, 71], 48),   # Cmaj7
        (2.0, [65, 69, 72, 76], 41),   # Fmaj7
        (4.0, [67, 71, 74, 76], 43),   # G6
        (6.0, [60, 64, 67, 71, 74], 48),  # Cmaj9
    ]
    for b_pos, midis, bass_m in chords:
        t0 = b_pos * beat
        dur = 2.8 if b_pos < 6.0 else 4.2
        pad = _synth_pad_chord(midis, dur, amp=0.16, sr=sr)
        _place_chunk(buf, int(t0 * sr), pad)
        bass = _pan_stereo(_synth_bass_note(bass_m, dur * 0.9, vel=0.72, sr=sr), 0.0)
        _place_chunk(buf, int(t0 * sr), bass)
        for j, m in enumerate(midis):
            ep = _pan_stereo(_synth_ep_note(m, dur * 0.85, vel=0.72, sr=sr), -0.18 + 0.1 * j)
            _place_chunk(buf, int((t0 + j * 0.03) * sr), ep)

    # Uplifting bell/marimba arpeggio motif
    melody = [
        (0.0, 72, 0.75, -0.25),
        (0.5, 76, 0.78, -0.10),
        (1.0, 79, 0.82, 0.10),
        (1.5, 83, 0.85, 0.25),
        (2.0, 81, 0.80, -0.15),
        (2.5, 79, 0.76, 0.05),
        (3.0, 76, 0.82, 0.20),
        (4.0, 74, 0.78, -0.20),
        (4.5, 76, 0.80, 0.0),
        (5.0, 79, 0.84, 0.15),
        (5.5, 83, 0.88, 0.28),
        (6.0, 84, 0.92, 0.0),
        (6.5, 79, 0.70, -0.18),
        (7.0, 83, 0.74, 0.18),
        (7.5, 86, 0.80, 0.0),
    ]
    for b_pos, midi, vel, pan in melody:
        note = _pan_stereo(_synth_bell_note(midi, 1.5, vel=vel, sr=sr), pan)
        _place_chunk(buf, int(b_pos * beat * sr), note)

    buf = _soft_reverb(buf, sr=sr, wet=0.30, decay=0.56)
    buf = _lowpass_fir(buf, 7500.0, sr)
    fade_in = int(0.03 * sr)
    fade_out = int(1.6 * sr)
    buf[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    buf[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    _finalize_and_write(path, buf, target_dbfs=-3.5, sr=sr)


def _build_stinger(path: Path) -> None:
    """Build ~3.5s refreshing corner transition chime & chord stinger."""
    sr = SAMPLE_RATE
    total_sec = 3.5
    buf = np.zeros((int(total_sec * sr), 2), dtype=np.float64)

    # Crisp 4-note ascending chime + warm chord sustain
    notes = [
        (0.05, 72, 0.75, -0.25),
        (0.22, 76, 0.78, -0.05),
        (0.39, 79, 0.82, 0.15),
        (0.56, 84, 0.86, 0.0),
    ]
    for t_sec, midi, vel, pan in notes:
        chime = _pan_stereo(_synth_bell_note(midi, 1.8, vel=vel, sr=sr), pan)
        _place_chunk(buf, int(t_sec * sr), chime)

    pad = _synth_pad_chord([60, 64, 67, 71, 74], 2.6, amp=0.14, sr=sr)
    _place_chunk(buf, int(0.52 * sr), pad)
    for j, midi in enumerate([60, 64, 67, 71]):
        ep = _pan_stereo(_synth_ep_note(midi, 2.2, vel=0.58, sr=sr), -0.2 + 0.13 * j)
        _place_chunk(buf, int((0.52 + j * 0.02) * sr), ep)

    buf = _soft_reverb(buf, sr=sr, wet=0.32, decay=0.55)
    buf = _lowpass_fir(buf, 7000.0, sr)
    fade_in = int(0.02 * sr)
    fade_out = int(0.9 * sr)
    buf[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    buf[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    _finalize_and_write(path, buf, target_dbfs=-4.5, sr=sr)


def _build_guest_jingle(path: Path) -> None:
    """Build ~4.0s bright, welcoming FM guest introduction jingle."""
    sr = SAMPLE_RATE
    total_sec = 4.0
    buf = np.zeros((int(total_sec * sr), 2), dtype=np.float64)

    # Welcoming Fmaj7 -> G6 -> Cmaj9 ascending motif
    chords = [
        (0.05, [65, 69, 72, 76], 41, 0.9),
        (0.75, [67, 71, 74, 76], 43, 0.9),
        (1.45, [60, 64, 67, 71, 74], 48, 2.3),
    ]
    for t0, midis, bass_m, dur in chords:
        _place_chunk(buf, int(t0 * sr), _synth_pad_chord(midis, dur, amp=0.14, sr=sr))
        _place_chunk(buf, int(t0 * sr), _pan_stereo(_synth_bass_note(bass_m, dur * 0.8, vel=0.62, sr=sr), 0.0))
        for j, m in enumerate(midis):
            ep = _pan_stereo(_synth_ep_note(m, dur * 0.9, vel=0.60, sr=sr), -0.20 + 0.10 * j)
            _place_chunk(buf, int((t0 + j * 0.02) * sr), ep)

    # Sparkling arpeggio bells
    arp = [
        (0.08, 72, 0.72, -0.22),
        (0.24, 76, 0.74, -0.10),
        (0.40, 79, 0.78, 0.05),
        (0.56, 81, 0.80, 0.18),
        (0.78, 79, 0.76, -0.12),
        (0.96, 83, 0.80, 0.12),
        (1.14, 84, 0.84, 0.0),
        (1.45, 88, 0.88, 0.0),
        (1.85, 86, 0.65, 0.18),
    ]
    for t_sec, midi, vel, pan in arp:
        _place_chunk(buf, int(t_sec * sr), _pan_stereo(_synth_bell_note(midi, 1.4, vel=vel, sr=sr), pan))

    buf = _soft_reverb(buf, sr=sr, wet=0.33, decay=0.56)
    buf = _lowpass_fir(buf, 7400.0, sr)
    fade_in = int(0.02 * sr)
    fade_out = int(1.0 * sr)
    buf[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    buf[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    _finalize_and_write(path, buf, target_dbfs=-4.2, sr=sr)


def _build_loop_bgm(
    path: Path,
    bpm: float,
    progression: list[tuple[list[int], int]],
    cycles: int,
    style: str,
) -> None:
    """Build a seamless looping stereo BGM bed on exact bar boundaries."""
    sr = SAMPLE_RATE
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4.0
    total_bars = len(progression) * cycles
    total_samples = int(round(total_bars * bar_sec * sr))
    buf = np.zeros((total_samples, 2), dtype=np.float64)

    for cycle in range(cycles):
        for chord_idx, (midis, bass_m) in enumerate(progression):
            bar_idx = cycle * len(progression) + chord_idx
            bar_start_sec = bar_idx * bar_sec
            bar_start_smp = int(round(bar_start_sec * sr))

            # Warm pad underneath every bar
            pad = _synth_pad_chord(midis, bar_sec * 1.08, amp=0.12, sr=sr)
            _place_chunk(buf, bar_start_smp, pad, wrap=True)

            # Rounded bass on beats 1 and 3 (or 1 and 2.5)
            b1 = _pan_stereo(_synth_bass_note(bass_m, beat_sec * 1.8, vel=0.66, sr=sr), 0.0)
            _place_chunk(buf, bar_start_smp, b1, wrap=True)
            b2_pos = bar_start_smp + int(round(beat_sec * 2.5 * sr))
            b2 = _pan_stereo(_synth_bass_note(bass_m + 7, beat_sec * 1.2, vel=0.45, sr=sr), 0.0)
            _place_chunk(buf, b2_pos, b2, wrap=True)

            if style == "warm":
                # Gentle EP chord + soft top voicings on off-beats
                for j, m in enumerate(midis):
                    ep = _pan_stereo(_synth_ep_note(m, bar_sec * 0.9, vel=0.56, sr=sr), -0.22 + 0.14 * j)
                    _place_chunk(buf, bar_start_smp + int(0.025 * j * sr), ep, wrap=True)
                # Gentle melodic sparkle on beat 2.5 and 3.5
                accent_m = midis[(bar_idx + 2) % len(midis)] + 12
                acc = _pan_stereo(_synth_ep_note(accent_m, beat_sec * 1.3, vel=0.38, sr=sr), 0.22)
                _place_chunk(buf, bar_start_smp + int(round(beat_sec * 2.5 * sr)), acc, wrap=True)

            elif style == "news":
                # Lightly pulsing rhythmic EP + subtle soft brush/thump
                for step, vel in [(0.0, 0.54), (1.5, 0.42), (3.0, 0.44)]:
                    pos = bar_start_smp + int(round(beat_sec * step * sr))
                    for j, m in enumerate(midis):
                        ep = _pan_stereo(_synth_ep_note(m, beat_sec * 1.35, vel=vel, sr=sr), -0.18 + 0.12 * j)
                        _place_chunk(buf, pos + int(0.012 * j * sr), ep, wrap=True)
                for b in range(4):
                    b_smp = bar_start_smp + int(round(beat_sec * b * sr))
                    if b in (0, 2):
                        _place_chunk(buf, b_smp, _synth_soft_kick(amp=0.10, sr=sr), wrap=True)
                    else:
                        _place_chunk(buf, b_smp, _synth_soft_shaker(amp=0.032, seed=bar_idx * 4 + b, sr=sr), wrap=True)
                    off_smp = bar_start_smp + int(round(beat_sec * (b + 0.5) * sr))
                    _place_chunk(buf, off_smp, _synth_soft_shaker(amp=0.018, seed=bar_idx * 8 + b, sr=sr), wrap=True)

            elif style == "feature":
                # Calm arpeggiated EP across the bar
                arp_order = [0, 1, 2, 3, 2, 1, 3, 2]
                for step_i, note_idx in enumerate(arp_order):
                    m = midis[note_idx % len(midis)]
                    if step_i in (3, 7):
                        m += 12
                    pos = bar_start_smp + int(round(beat_sec * (step_i * 0.5) * sr))
                    pan = -0.24 + 0.07 * step_i
                    ep = _pan_stereo(_synth_ep_note(m, beat_sec * 1.4, vel=0.45, sr=sr), pan)
                    _place_chunk(buf, pos, ep, wrap=True)

    # Apply reverb and wrap tail cleanly back across boundary for seamless looping
    rev_pad = int(0.6 * sr)
    extended = np.vstack((buf, buf[:rev_pad]))
    extended = _soft_reverb(extended, sr=sr, wet=0.22, decay=0.50)
    # Use tail section wrapped into beginning, keeping interior smoothly continuous
    looped = extended[:total_samples].copy()
    cross = int(0.08 * sr)
    w = np.linspace(0.0, 1.0, cross)[:, None]
    looped[:cross] = looped[:cross] * w + extended[total_samples : total_samples + cross] * (1.0 - w)

    # Keep speech-presence range uncluttered so voice sits cleanly on top
    looped = _lowpass_fir(looped, 4200.0, sr)
    _finalize_and_write(path, looped, target_dbfs=-6.0, sr=sr)


def _build_outro_jingle(path: Path) -> None:
    """Build ~10s warm ending theme with gentle fade-out."""
    sr = SAMPLE_RATE
    total_sec = 10.2
    buf = np.zeros((int(total_sec * sr), 2), dtype=np.float64)
    beat = 60.0 / 84.0

    chords = [
        (0.0, [65, 69, 72, 76], 41),      # Fmaj7
        (2.0, [67, 71, 74, 77], 43),      # G6/7
        (4.0, [64, 67, 71, 74], 40),      # Em7
        (6.0, [60, 64, 67, 71, 74], 48),  # Cmaj9
    ]
    for b_pos, midis, bass_m in chords:
        t0 = b_pos * beat
        dur = 2.6 if b_pos < 6.0 else 5.2
        _place_chunk(buf, int(t0 * sr), _synth_pad_chord(midis, dur, amp=0.16, sr=sr))
        _place_chunk(buf, int(t0 * sr), _pan_stereo(_synth_bass_note(bass_m, dur * 0.9, vel=0.65, sr=sr), 0.0))
        for j, m in enumerate(midis):
            ep = _pan_stereo(_synth_ep_note(m, dur * 0.85, vel=0.62, sr=sr), -0.2 + 0.1 * j)
            _place_chunk(buf, int((t0 + j * 0.04) * sr), ep)

    melody = [
        (0.5, 76, 0.65, -0.15),
        (1.5, 79, 0.70, 0.10),
        (2.5, 77, 0.68, -0.10),
        (3.5, 76, 0.65, 0.15),
        (4.5, 74, 0.66, -0.15),
        (5.5, 72, 0.68, 0.10),
        (6.0, 76, 0.74, 0.0),
        (7.0, 79, 0.68, 0.20),
        (8.0, 84, 0.72, 0.0),
    ]
    for b_pos, midi, vel, pan in melody:
        _place_chunk(buf, int(b_pos * beat * sr), _pan_stereo(_synth_bell_note(midi, 2.0, vel=vel, sr=sr), pan))

    buf = _soft_reverb(buf, sr=sr, wet=0.34, decay=0.58)
    buf = _lowpass_fir(buf, 6200.0, sr)
    fade_in = int(0.05 * sr)
    fade_out = int(3.0 * sr)
    buf[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    buf[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None] ** 1.4
    _finalize_and_write(path, buf, target_dbfs=-4.0, sr=sr)


def ensure_bgm_assets(cache_dir: Path) -> dict[str, Path]:
    """Generate (or reuse cached) FM radio jingle and BGM WAV assets."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    version_file = cache_dir / ".bgm_version"
    current_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""

    assets = {
        "opening_jingle": cache_dir / "opening_jingle.wav",
        "stinger": cache_dir / "stinger.wav",
        "guest_jingle": cache_dir / "guest_jingle.wav",
        "bgm_warm": cache_dir / "bgm_warm.wav",
        "bgm_news": cache_dir / "bgm_news.wav",
        "bgm_feature": cache_dir / "bgm_feature.wav",
        "outro_jingle": cache_dir / "outro_jingle.wav",
    }

    if current_version == BGM_ASSET_VERSION and all(p.exists() and p.stat().st_size > 1000 for p in assets.values()):
        return assets

    print("Generating FM radio BGM & jingle assets...")
    _build_opening_jingle(assets["opening_jingle"])
    _build_stinger(assets["stinger"])
    _build_guest_jingle(assets["guest_jingle"])
    _build_loop_bgm(
        assets["bgm_warm"],
        bpm=88.0,
        progression=[
            ([60, 64, 67, 71], 48),  # Cmaj7
            ([57, 60, 64, 67], 45),  # Am7
            ([53, 57, 60, 64], 41),  # Fmaj7
            ([55, 59, 62, 64], 43),  # G6
        ],
        cycles=3,
        style="warm",
    )
    _build_loop_bgm(
        assets["bgm_news"],
        bpm=100.0,
        progression=[
            ([62, 66, 69, 73], 50),  # Dmaj7
            ([59, 62, 66, 69], 47),  # Bm7
            ([55, 59, 62, 66], 43),  # Gmaj7
            ([57, 61, 64, 66], 45),  # A6
        ],
        cycles=3,
        style="news",
    )
    _build_loop_bgm(
        assets["bgm_feature"],
        bpm=82.0,
        progression=[
            ([53, 57, 60, 64], 41),  # Fmaj7
            ([50, 53, 57, 60], 38),  # Dm7
            ([58, 62, 65, 69], 46),  # Bbmaj7
            ([60, 64, 67, 69], 48),  # C6
        ],
        cycles=3,
        style="feature",
    )
    _build_outro_jingle(assets["outro_jingle"])

    version_file.write_text(BGM_ASSET_VERSION, encoding="utf-8")
    return assets


if __name__ == "__main__":
    out_assets = ensure_bgm_assets(Path(".cache/bgm"))
    for name, wav_path in out_assets.items():
        with wave.open(str(wav_path), "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
            print(f"{name}: {wav_path} ({dur:.2f}s, {wf.getnchannels()}ch, {wf.getframerate()}Hz)")
