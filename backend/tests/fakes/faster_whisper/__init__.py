"""Test stand-in for faster_whisper.

The "audio" a test uploads contains a marker `SAY:<text>\n`; the fake model
returns that text as one speech segment. Calls (model name and transcribe
keyword arguments) are logged to $FAKE_STT_LOG for assertions.
"""
import json
import os
from types import SimpleNamespace


def _log(entry):
    log = os.getenv("FAKE_STT_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


class WhisperModel:
    def __init__(self, name, device="cpu", compute_type="int8", **kwargs):
        self.name = name
        _log({"event": "load", "model": name, "device": device})

    def transcribe(self, path, **kwargs):
        data = open(path, "rb").read()
        _log({"event": "transcribe", "suffix": os.path.splitext(path)[1],
              **{k: v for k, v in kwargs.items() if k != "vad_parameters"}})
        segments = []
        if data.startswith(b"ID3") and b"SAY:" not in data and not os.getenv("FAKE_TTS_MP3"):
            # audio produced by the fake edge_tts: "hear" the text it encoded
            segments.append(SimpleNamespace(text=" " + data[3:].decode("utf-8", "ignore"), no_speech_prob=0.02, avg_logprob=-0.2))
        elif b"SAY:" in data:
            text = data.split(b"SAY:", 1)[1].split(b"\n", 1)[0].decode("utf-8")
            segments.append(SimpleNamespace(text=" " + text, no_speech_prob=0.02, avg_logprob=-0.2))
        elif b"NOISE" in data:
            segments.append(SimpleNamespace(text=" (static)", no_speech_prob=0.95, avg_logprob=-2.0))
        return iter(segments), SimpleNamespace(language="en")
