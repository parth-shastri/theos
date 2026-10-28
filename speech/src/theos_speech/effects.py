"""The approved subtle robotic treatment. Each request owns its effect state."""

from io import BytesIO

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pedalboard import Compressor, HighpassFilter, LowShelfFilter, Pedalboard, PitchShift
from scipy.signal import butter, sosfilt


def apply_voice(wav: bytes) -> bytes:
    """Process PCM audio and return a volume-matched WAV for MP3 encoding."""
    x, sr = sf.read(BytesIO(wav), dtype="float32", always_2d=True)
    if not 8000 <= sr <= 48000 or not len(x) or not np.isfinite(x).all():
        raise ValueError("Invalid upstream audio.")
    x = x.mean(axis=1)

    # 1. Apply the same pitch, bass, and compression used in the approved audition.
    base = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=65),
            PitchShift(semitones=-1.2),
            LowShelfFilter(cutoff_frequency_hz=140, gain_db=2, q=0.7),
            Compressor(threshold_db=-22, ratio=2, attack_ms=12, release_ms=150),
        ]
    )(x, sr)

    def delay(audio, ms):
        return np.pad(audio, (round(ms * sr / 1000), 0))[: len(audio)]

    def bandpass(audio, low, high):
        return sosfilt(butter(2, [low, high], btype="bandpass", fs=sr, output="sos"), audio).astype(
            np.float32
        )

    # 2. Keep the main voice forward with quiet parallel texture.
    shadow = Pedalboard([PitchShift(semitones=-3)])(base, sr)
    shadow = delay(bandpass(shadow, 100, 2000), 8)
    resonance = bandpass(delay(base, 3.5) - 0.5 * delay(base, 7), 250, 3000)
    ring = bandpass(base * np.sin(2 * np.pi * 68 * np.arange(len(base)) / sr), 180, 3200)
    result = base + 0.055 * shadow + 0.045 * resonance + 0.009 * ring

    # 3. Pad only the loudness measurement for very short replies.
    meter = pyln.Meter(sr)
    measured = np.pad(result, (0, max(0, round(0.4 * sr) + 1 - len(result))))
    loudness = meter.integrated_loudness(measured)
    if np.isfinite(loudness):
        result *= 10 ** ((-23 - loudness) / 20)
    peak = np.max(np.abs(result))
    ceiling = 10 ** (-1.5 / 20)
    if peak > ceiling:
        result *= ceiling / peak
    output = BytesIO()
    sf.write(output, result, sr, format="WAV", subtype="PCM_16")
    return output.getvalue()
