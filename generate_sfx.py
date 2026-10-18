"""
Pro-quality Sound Effect Generator for Poker Trainer.
Generates all game SFX using synthesis with ADSR envelopes,
harmonics, noise layers, and stereo imaging. Pure Python, no deps.
"""
import math
import os
import random
import struct
import wave

ASSETS_DIR = "assets"
SAMPLE_RATE = 44100


def adsr_envelope(n_samples, attack=0.01, decay=0.1, sustain_level=0.6, release=0.15):
    """Generate an ADSR envelope curve (0.0 to 1.0)."""
    total_s = n_samples / SAMPLE_RATE
    env = []
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        if t < attack:
            val = t / attack
        elif t < attack + decay:
            val = 1.0 - (1.0 - sustain_level) * ((t - attack) / decay)
        elif t < total_s - release:
            val = sustain_level
        else:
            remaining = total_s - t
            val = sustain_level * (remaining / release) if release > 0 else 0
        env.append(max(0.0, min(1.0, val)))
    return env


def sine_wave(freq, n_samples, phase=0.0):
    return [math.sin(2 * math.pi * freq * i / SAMPLE_RATE + phase) for i in range(n_samples)]


def noise(n_samples, seed=42):
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(n_samples)]


def low_pass(samples, cutoff_freq):
    """Simple one-pole low-pass filter."""
    rc = 1.0 / (2.0 * math.pi * cutoff_freq)
    dt = 1.0 / SAMPLE_RATE
    alpha = dt / (rc + dt)
    out = [0.0] * len(samples)
    out[0] = alpha * samples[0]
    for i in range(1, len(samples)):
        out[i] = out[i - 1] + alpha * (samples[i] - out[i - 1])
    return out


def mix(*tracks, volumes=None):
    """Mix multiple tracks together with optional per-track volumes."""
    if volumes is None:
        volumes = [1.0] * len(tracks)
    max_len = max(len(t) for t in tracks)
    out = [0.0] * max_len
    for track, vol in zip(tracks, volumes, strict=False):
        for i in range(len(track)):
            out[i] += track[i] * vol
    return out


def normalize(samples, peak=0.85):
    mx = max(abs(s) for s in samples) or 1.0
    return [s / mx * peak for s in samples]


def apply_envelope(samples, envelope):
    return [s * e for s, e in zip(samples, envelope, strict=False)]


def concat(*segments):
    out = []
    for seg in segments:
        out.extend(seg)
    return out


def silence(duration_ms):
    return [0.0] * int(SAMPLE_RATE * duration_ms / 1000)


def reverb(samples, delay_ms=40, decay=0.3, taps=4):
    """Simple multi-tap delay reverb."""
    out = list(samples)
    for tap in range(1, taps + 1):
        delay_samples = int(SAMPLE_RATE * delay_ms * tap / 1000)
        gain = decay ** tap
        for i in range(delay_samples, len(out)):
            out[i] += samples[i - delay_samples] * gain
    return out


def create_wav(filename, samples, stereo=False):
    """Write samples to WAV. Samples should be -1.0 to 1.0 floats."""
    filepath = os.path.join(ASSETS_DIR, filename)
    samples = normalize(samples)
    with wave.open(filepath, 'w') as wf:
        n_channels = 2 if stereo else 1
        wf.setnchannels(n_channels)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        data = b''
        for s in samples:
            packed = struct.pack('<h', int(max(-1.0, min(1.0, s)) * 32000))
            if stereo:
                data += packed + packed
            else:
                data += packed
        wf.writeframes(data)
    print(f"  -> {filepath} ({len(samples) / SAMPLE_RATE:.2f}s)")


def gen_win():
    """Bright, satisfying poker win chime. Major arpeggio + shimmer."""
    notes = [
        (523.25, 0.12),   # C5
        (659.25, 0.12),   # E5
        (783.99, 0.10),   # G5
        (1046.50, 0.30),  # C6 (octave resolve)
    ]
    audio = []
    for freq, dur in notes:
        n = int(SAMPLE_RATE * dur)
        env = adsr_envelope(n, attack=0.005, decay=0.04, sustain_level=0.7, release=dur * 0.4)
        tone = sine_wave(freq, n)
        h2 = sine_wave(freq * 2, n)
        h3 = sine_wave(freq * 3, n)
        shimmer = noise(n, seed=int(freq))
        shimmer = low_pass(shimmer, 8000)
        mixed = mix(tone, h2, h3, shimmer, volumes=[1.0, 0.3, 0.1, 0.04])
        audio.extend(apply_envelope(mixed, env))
        audio.extend(silence(15))

    audio = reverb(audio, delay_ms=35, decay=0.25, taps=3)
    create_wav("win.wav", audio)


def gen_lose():
    """Soft descending tone, not harsh. Two notes sliding down."""
    n_total = int(SAMPLE_RATE * 0.45)
    env = adsr_envelope(n_total, attack=0.01, decay=0.15, sustain_level=0.4, release=0.2)

    tone = []
    for i in range(n_total):
        t = i / SAMPLE_RATE
        freq = 350 - 120 * (t / 0.45)
        val = math.sin(2 * math.pi * freq * t)
        val += 0.3 * math.sin(2 * math.pi * freq * 0.5 * t)
        tone.append(val)

    n2 = noise(n_total, seed=99)
    n2 = low_pass(n2, 600)
    mixed = mix(tone, n2, volumes=[1.0, 0.08])
    audio = apply_envelope(mixed, env)
    audio = reverb(audio, delay_ms=50, decay=0.2, taps=2)
    create_wav("lose.wav", audio)


def gen_deal():
    """Quick card snap/flick sound. Noise burst + high click."""
    n = int(SAMPLE_RATE * 0.08)
    env = adsr_envelope(n, attack=0.001, decay=0.02, sustain_level=0.1, release=0.04)

    click = noise(n, seed=7)
    click = low_pass(click, 4000)
    snap = sine_wave(2200, n)
    snap2 = sine_wave(3800, n)

    mixed = mix(click, snap, snap2, volumes=[0.7, 0.4, 0.15])
    audio = apply_envelope(mixed, env)
    audio = reverb(audio, delay_ms=15, decay=0.15, taps=2)
    create_wav("deal.wav", audio)


def gen_chip():
    """Poker chip click/clink. Metallic transient."""
    n = int(SAMPLE_RATE * 0.12)
    env = adsr_envelope(n, attack=0.001, decay=0.03, sustain_level=0.15, release=0.06)

    t1 = sine_wave(3200, n)
    t2 = sine_wave(5400, n)
    t3 = sine_wave(7100, n)
    body = noise(n, seed=22)
    body = low_pass(body, 6000)

    mixed = mix(t1, t2, t3, body, volumes=[0.5, 0.3, 0.15, 0.35])
    audio = apply_envelope(mixed, env)
    audio = reverb(audio, delay_ms=20, decay=0.2, taps=2)
    create_wav("chip.wav", audio)


def gen_click():
    """Subtle UI click. Very short."""
    n = int(SAMPLE_RATE * 0.035)
    env = adsr_envelope(n, attack=0.001, decay=0.01, sustain_level=0.05, release=0.015)

    click = sine_wave(1800, n)
    body = noise(n, seed=55)
    body = low_pass(body, 3000)

    mixed = mix(click, body, volumes=[0.6, 0.3])
    audio = apply_envelope(mixed, env)
    create_wav("click.wav", audio)


def gen_streak():
    """Achievement sound for hitting a streak. Ascending sparkle."""
    notes = [
        (880, 0.06),    # A5
        (1108.7, 0.06), # C#6
        (1318.5, 0.06), # E6
        (1760, 0.15),   # A6
    ]
    audio = []
    for i, (freq, dur) in enumerate(notes):
        n = int(SAMPLE_RATE * dur)
        env = adsr_envelope(n, attack=0.003, decay=0.02, sustain_level=0.6, release=dur * 0.5)
        tone = sine_wave(freq, n)
        h2 = sine_wave(freq * 2, n)
        sparkle = noise(n, seed=int(freq) + i)
        sparkle = low_pass(sparkle, 10000)
        mixed = mix(tone, h2, sparkle, volumes=[1.0, 0.25, 0.06])
        audio.extend(apply_envelope(mixed, env))
        audio.extend(silence(10))

    audio = reverb(audio, delay_ms=30, decay=0.3, taps=3)
    create_wav("streak.wav", audio)


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    print("Generating poker SFX...")
    gen_win()
    gen_lose()
    gen_deal()
    gen_chip()
    gen_click()
    gen_streak()
    print("Done! All SFX generated in assets/")


if __name__ == "__main__":
    main()
