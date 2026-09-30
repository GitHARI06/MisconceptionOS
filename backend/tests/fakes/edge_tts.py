"""Test stand-in for edge_tts: 'synthesises' text into fake MP3 bytes.

Each synthesis is logged (one JSON line per call) to $FAKE_TTS_LOG so tests
can check caching and the exact text that would be spoken.
"""
import asyncio
import base64
import json
import os


_FAILED_ONCE = set()


class Communicate:
    def __init__(self, text, voice, rate="+0%", **kwargs):
        self.text, self.voice, self.rate = text, voice, rate

    async def stream(self):
        log = os.getenv("FAKE_TTS_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"text": self.text, "voice": self.voice, "rate": self.rate}) + "\n")
        if "FAILTTS" in self.text:
            raise ConnectionError("simulated Edge outage")
        if "FLAKYONCE" in self.text and self.text not in _FAILED_ONCE:
            _FAILED_ONCE.add(self.text)
            raise ConnectionError("simulated dropped connection")
        mp3 = os.getenv("FAKE_TTS_MP3")
        if mp3:  # browser tests: real, playable audio (stored as base64 text)
            raw = open(mp3, "rb").read()
            payload = base64.b64decode(raw) if mp3.endswith(".b64") else raw
        else:    # API tests: the spoken text itself, so tests can inspect it
            payload = b"ID3" + self.text.encode("utf-8")
        # Edge synthesises several times faster than real time; mimic that.
        step = 2048 if mp3 else 64
        for start in range(0, len(payload), step):
            await asyncio.sleep(0.01)
            yield {"type": "audio", "data": payload[start:start + step]}
        yield {"type": "WordBoundary", "offset": 0}

    async def save(self, path):
        with open(path, "wb") as f:
            async for chunk in self.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
