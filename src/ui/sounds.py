import io
import wave

import numpy as np


def _np_to_wav(data, sr=44100):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(np.clip(data * 32767, -32768, 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def _make_start_snd():
    sr, d = 44100, 0.055
    t = np.linspace(0, d, int(sr * d), False)
    w1 = np.sin(2 * np.pi * 660 * t) * np.exp(-t * 30) * 0.15
    w2 = np.sin(2 * np.pi * 880 * t) * np.exp(-t * 30) * 0.15
    return _np_to_wav(
        np.concatenate([w1, np.zeros(int(sr * 0.015)), w2]).astype(np.float32)
    )


def _make_stop_snd():
    sr, d = 44100, 0.055
    t = np.linspace(0, d, int(sr * d), False)
    w1 = np.sin(2 * np.pi * 880 * t) * np.exp(-t * 30) * 0.12
    w2 = np.sin(2 * np.pi * 580 * t) * np.exp(-t * 35) * 0.10
    return _np_to_wav(
        np.concatenate([w1, np.zeros(int(sr * 0.015)), w2]).astype(np.float32)
    )


def _make_blip(freq, dur=0.06, vol=0.12):
    sr = 44100
    t = np.linspace(0, dur, int(sr * dur), False)
    e = np.exp(-t * 40)
    d = np.sin(2 * np.pi * freq * t) * e * vol
    d += np.sin(2 * np.pi * freq * 1.5 * t) * e * vol * 0.3
    return _np_to_wav(d.astype(np.float32))
