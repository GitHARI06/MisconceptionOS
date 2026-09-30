"""Speech pipeline: Whisper speech-to-text and streaming Edge text-to-speech.

Design goals
  * Accuracy: a larger Whisper model when a GPU is present, a physics
    vocabulary prompt so terms like "inertia" or "entropy" are recognised,
    and speech-only segment filtering.
  * Responsiveness: tutor audio is streamed to the browser while Edge is
    still synthesising it (first sound in well under a second), recently
    spoken phrases are cached, and all blocking work runs off the event loop.
  * Natural speech: maths and units are rewritten into words before
    synthesis, so "\\(v = u + at\\)" is read as "v equals u plus a t".
"""

import asyncio
import base64
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from typing import AsyncIterator, Dict, Optional

from .config import settings

logger = logging.getLogger("misconception_os.audio")

# --------------------------------------------------------------------------
# Speech-to-text (faster-whisper)
# --------------------------------------------------------------------------

# A short vocabulary prompt biases Whisper towards physics terms without
# forcing them into the transcript.
PHYSICS_PROMPT = (
    "A student is talking to a physics tutor about Newton's laws, inertia, net force, "
    "acceleration, velocity, momentum, friction, gravity, free fall, kinetic and potential energy, "
    "work, power, thermodynamics, entropy, heat, temperature, pressure, waves, frequency, optics, "
    "refraction, electric current, voltage, resistance, magnetism, quantum physics, 9.8 m/s², 12 N."
)

_whisper_model = None
_whisper_failed = False
_whisper_loading = False
_whisper_device = None
_whisper_model_name = None
_whisper_lock = threading.Lock()


def _resolve_device() -> str:
    if settings.WHISPER_DEVICE != "cuda":
        return "cpu"
    try:
        import ctranslate2
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


def _resolve_model_name(device: str) -> str:
    configured = (settings.WHISPER_MODEL_SIZE or "auto").strip()
    if configured.lower() != "auto":
        return configured
    # small.en is markedly more accurate than tiny.en and still real-time on a
    # GPU; base.en is the accuracy/latency sweet spot on CPU.
    return "small.en" if device == "cuda" else "base.en"


def get_whisper_model():
    """Load faster-whisper once. A failed load is remembered so every voice
    turn does not retry a slow (or impossible) model load."""
    global _whisper_model, _whisper_failed, _whisper_loading, _whisper_device, _whisper_model_name
    if _whisper_model is not None or _whisper_failed:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is not None or _whisper_failed:
            return _whisper_model
        _whisper_loading = True
        try:
            from faster_whisper import WhisperModel
            device = _resolve_device()
            name = _resolve_model_name(device)
            compute_type = "float16" if device == "cuda" else "int8"
            logger.info(f"Loading faster-whisper {name} on {device} ({compute_type})...")
            _whisper_model = WhisperModel(name, device=device, compute_type=compute_type)
            _whisper_device, _whisper_model_name = device, name
            logger.info("faster-whisper ready!")
        except Exception as e:
            logger.error(f"Whisper unavailable, voice input will rely on browser speech recognition: {e}")
            _whisper_failed = True
            _whisper_model = None
        finally:
            _whisper_loading = False
    return _whisper_model


# Warm up in the background so the API starts immediately.
if settings.WHISPER_WARMUP:
    threading.Thread(target=get_whisper_model, daemon=True).start()


def whisper_status() -> Dict[str, object]:
    return {
        "ready": _whisper_model is not None,
        "loading": _whisper_loading,
        "failed": _whisper_failed,
        "device": _whisper_device,
        "model": _whisper_model_name,
    }


def prefer_server_stt() -> bool:
    """Should the server's Whisper transcript win over the browser's?

    auto    -> yes when Whisper runs on a GPU (more accurate, still fast);
               on CPU the browser transcript is used so turns stay snappy
               and Whisper is only the fallback.
    whisper -> always prefer Whisper when it is available.
    browser -> only use Whisper when the browser sent no text at all.
    """
    preference = (settings.STT_PREFERENCE or "auto").lower()
    if preference == "browser" or _whisper_failed:
        return False
    if preference == "whisper":
        return True
    return _whisper_model is not None and _whisper_device == "cuda"


def _is_cuda_runtime_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("cublas", "cudnn", "cuda", "libcudart", "cufft"))


def _switch_whisper_to_cpu(reason: Exception) -> None:
    """The GPU was detected but its CUDA libraries are missing or broken
    (e.g. cublas64_12.dll not found on Windows). Fall back to the CPU model
    once instead of failing every voice turn."""
    global _whisper_model, _whisper_device, _whisper_model_name, _whisper_failed
    with _whisper_lock:
        if _whisper_device == "cpu":
            return
        logger.warning(f"Whisper on GPU failed ({reason}); switching to CPU. "
                       "Install the CUDA 12 cuBLAS/cuDNN libraries to use the GPU.")
        try:
            from faster_whisper import WhisperModel
            name = _resolve_model_name("cpu") if (settings.WHISPER_MODEL_SIZE or "auto").lower() == "auto" else settings.WHISPER_MODEL_SIZE
            _whisper_model = WhisperModel(name, device="cpu", compute_type="int8")
            _whisper_device, _whisper_model_name = "cpu", name
        except Exception as exc:
            logger.error(f"Whisper CPU fallback failed too: {exc}")
            _whisper_model, _whisper_failed = None, True


def _transcribe_file(temp_path: str, topic: Optional[str] = None) -> str:
    try:
        return _transcribe_once(temp_path, topic)
    except Exception as exc:
        if _whisper_device == "cuda" and _is_cuda_runtime_error(exc):
            _switch_whisper_to_cpu(exc)
            if _whisper_model is not None:
                return _transcribe_once(temp_path, topic)
        raise


def _transcribe_once(temp_path: str, topic: Optional[str] = None) -> str:
    model = get_whisper_model()
    if model is None:
        return ""
    prompt = PHYSICS_PROMPT if not topic else f"{PHYSICS_PROMPT} Today's topic: {topic}."
    on_gpu = _whisper_device == "cuda"
    segments, info = model.transcribe(
        temp_path,
        beam_size=5 if on_gpu else 1,
        language="en",
        initial_prompt=prompt,
        condition_on_previous_text=False,
        temperature=0.0,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
    )
    # Keep only speech-like Whisper segments. Browser echo cancellation
    # and microphone noise suppression handle the input signal; this
    # second gate prevents residual silence/noise from becoming a query.
    clean_segments = []
    for segment in segments:
        no_speech_prob = getattr(segment, "no_speech_prob", 0.0) or 0.0
        avg_logprob = getattr(segment, "avg_logprob", 0.0) or 0.0
        text = (segment.text or "").strip()
        if no_speech_prob < 0.65 and avg_logprob > -1.2 and text:
            clean_segments.append(text)
    transcript = " ".join(clean_segments).strip()
    # Whisper occasionally echoes its prompt on near-silent audio.
    if transcript and transcript.lower() in PHYSICS_PROMPT.lower():
        return ""
    return transcript


def _suffix_for(data_url_header: str) -> str:
    header = data_url_header.lower()
    if "mp4" in header or "m4a" in header or "aac" in header:
        return ".mp4"
    if "ogg" in header:
        return ".ogg"
    if "wav" in header:
        return ".wav"
    return ".webm"


async def transcribe_audio_base64(audio_base64: str, topic: Optional[str] = None) -> str:
    """Transcribe browser-recorded audio (a data URL or bare base64)."""
    temp_path = None
    try:
        if not audio_base64:
            return ""
        suffix = ".webm"
        if "," in audio_base64:
            header, audio_base64 = audio_base64.split(",", 1)
            suffix = _suffix_for(header)
        try:
            audio_bytes = base64.b64decode(audio_base64, validate=False)
        except Exception:
            return ""
        if len(audio_bytes) < 100:
            return ""

        temp_path = os.path.join(tempfile.gettempdir(), f"whisper_{uuid.uuid4().hex}{suffix}")
        with open(temp_path, "wb") as f:
            f.write(audio_bytes)

        # Whisper is CPU/GPU-bound and synchronous: run it off the event loop
        # so one learner's transcription never stalls every other request.
        return await asyncio.wait_for(
            asyncio.to_thread(_transcribe_file, temp_path, topic),
            timeout=settings.STT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Whisper transcription timed out; using the browser transcript instead.")
        return ""
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


# --------------------------------------------------------------------------
# Text-to-speech (Edge neural voices)
# --------------------------------------------------------------------------

_GREEK = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta", "Delta": "delta",
    "theta": "theta", "lambda": "lambda", "mu": "mu", "pi": "pi", "rho": "rho", "sigma": "sigma",
    "tau": "tau", "omega": "omega", "Omega": "omega", "eta": "eta", "epsilon": "epsilon", "phi": "phi",
}

_UNITS = [
    (r"m\s*/\s*s\s*(\^\s*2|²)", "meters per second squared"),
    (r"m\s*/\s*s", "meters per second"),
    (r"km\s*/\s*h", "kilometers per hour"),
    (r"kg\s*m\s*/\s*s", "kilogram meters per second"),
    (r"°\s*C\b", "degrees Celsius"),
    (r"°\s*F\b", "degrees Fahrenheit"),
    (r"\bkg\b", "kilograms"),
    (r"\bN\b", "newtons"),
    (r"\bJ\b", "joules"),
    (r"\bW\b", "watts"),
    (r"\bV\b", "volts"),
    (r"\bA\b", "amps"),
    (r"\bHz\b", "hertz"),
    (r"\bPa\b", "pascals"),
    (r"\bK\b", "kelvin"),
    (r"\bm\b", "meters"),
    (r"\bs\b", "seconds"),
    (r"\bmph\b", "miles per hour"),
]


def _speak_math(expr: str) -> str:
    """Turn a small LaTeX/plain maths expression into words."""
    s = expr
    s = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"\1 over \2", s)
    s = re.sub(r"\\sqrt\{([^}]*)\}", r"the square root of \1", s)
    s = re.sub(r"\\(" + "|".join(_GREEK) + r")\b", lambda m: " " + _GREEK[m.group(1)] + " ", s)
    s = re.sub(r"_\{([^}]*)\}", r" \1", s)
    s = re.sub(r"_(\w)", r" \1", s)
    s = re.sub(r"\^\{?2\}?|²", " squared", s)
    s = re.sub(r"\^\{?3\}?|³", " cubed", s)
    s = re.sub(r"\^\{([^}]*)\}", r" to the power \1", s)
    s = re.sub(r"\^(\w+)", r" to the power \1", s)
    s = s.replace("\\cdot", " times ").replace("\\times", " times ").replace("×", " times ")
    s = s.replace("\\approx", " is about ").replace("≈", " is about ")
    s = s.replace("\\neq", " is not equal to ").replace("≠", " is not equal to ")
    s = s.replace("\\leq", " is at most ").replace("\\geq", " is at least ")
    s = s.replace("\\to", " to ").replace("\\rightarrow", " gives ").replace("→", " gives ")
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = re.sub(r"(?<=[\w)])\s*=\s*", " equals ", s)
    s = re.sub(r"\s\+\s|(?<=\w)\+(?=\w)", " plus ", s)
    s = re.sub(r"\s-\s", " minus ", s)
    s = re.sub(r"(?<=\w)\s*/\s*(?=\w)", " over ", s)
    s = re.sub(r"(?<=\d)(?=[a-zA-Z])", " ", s)                      # "2mv" -> "2 mv"
    if len(s) < 40:
        s = re.sub(r"\b([a-zA-Z])([a-zA-Z])\b", r"\1 \2", s)          # "at" -> "a t" in formulas
    s = s.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", s).strip()


def speech_text(text: str) -> str:
    """Rewrite tutor text (markdown + LaTeX) into something a voice reads well."""
    if not text:
        return ""
    s = text
    s = re.sub(r"```.*?```", " ", s, flags=re.S)
    # Citations such as "[Lecture notes, p.3]" are shown on screen, not read out.
    s = re.sub(r"\s*\[[^\]\n]{1,160}?,\s*p\.\s*\d+\]", "", s)
    # Inline and display maths.
    # Maths is converted first and fenced with \x02..\x03 so the unit rules
    # below never turn the variable "m" into "meters".
    fence = lambda spoken: f"\x02{spoken}\x03"
    s = re.sub(r"\\\((.+?)\\\)", lambda m: fence(_speak_math(m.group(1))), s, flags=re.S)
    s = re.sub(r"\\\[(.+?)\\\]", lambda m: fence(_speak_math(m.group(1))), s, flags=re.S)
    s = re.sub(r"\$\$(.+?)\$\$", lambda m: fence(_speak_math(m.group(1))), s, flags=re.S)
    s = re.sub(r"\$(.+?)\$", lambda m: fence(_speak_math(m.group(1))), s)
    # Bare formulas such as "F = ma" or "ΔU = Q - W".
    s = re.sub(r"\b([A-Za-zΔ]{1,3})\s*=\s*([A-Za-z0-9Δ ]{1,20}?)(?=[,.;)]|\s(?:and|or|so|which|where)\b|$)",
               lambda m: fence(_speak_math(f"{m.group(1)} = {m.group(2)}")), s)
    s = s.replace("Δ", "delta ")
    # Markdown.
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^\s*[-*•]\s+", "", s, flags=re.M)
    s = re.sub(r"^\s*#+\s*", "", s, flags=re.M)
    s = re.sub(r"[*_`#>|]", "", s)
    s = re.sub(r"\[[^\]]*redacted[^\]]*\]", "that value", s, flags=re.I)
    # Units after numbers ("12 N", "9.8 m/s^2", "20°C").
    parts = re.split(r"(\x02[^\x03]*\x03)", s)
    for index, part in enumerate(parts):
        if part.startswith("\x02"):
            continue
        for pattern, spoken in _UNITS:
            part = re.sub(r"(?<=\d)\s*" + pattern, " " + spoken, part)
        parts[index] = part
    s = "".join(parts).replace("\x02", "").replace("\x03", "")
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)
    s = re.sub(r"\be\.g\.", "for example", s)
    s = re.sub(r"\bi\.e\.", "that is", s)
    s = re.sub(r"\bvs\.?\b", "versus", s)
    # Emoji and other symbols the voice would spell out.
    s = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", s)
    s = s.replace("\\", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


class _LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.data: "OrderedDict[str, bytes]" = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[bytes]:
        with self.lock:
            value = self.data.get(key)
            if value is not None:
                self.data.move_to_end(key)
            return value

    def put(self, key: str, value: bytes) -> None:
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.capacity:
                self.data.popitem(last=False)


_tts_cache = _LRUCache(128)
_edge_semaphore: Optional[asyncio.Semaphore] = None


def _edge_slots() -> asyncio.Semaphore:
    global _edge_semaphore
    if _edge_semaphore is None:
        _edge_semaphore = asyncio.Semaphore(2)
    return _edge_semaphore
# Short-lived handles so the browser can stream a reply with a plain GET.
_speech_tokens: "OrderedDict[str, tuple]" = OrderedDict()
_speech_tokens_lock = threading.Lock()
_SPEECH_TOKEN_TTL = 15 * 60


def register_speech(text: str, voice: Optional[str] = None, rate: int = 0) -> Optional[str]:
    """Store text for streaming and return a token for /api/audio/stream/{token}."""
    spoken = speech_text(text)
    if not spoken:
        return None
    token = uuid.uuid4().hex
    now = time.time()
    with _speech_tokens_lock:
        _speech_tokens[token] = (spoken, voice or settings.EDGE_TTS_VOICE, now, int(rate))
        while _speech_tokens:
            oldest_token, (_, _, created, _) = next(iter(_speech_tokens.items()))
            if now - created > _SPEECH_TOKEN_TTL or len(_speech_tokens) > 1000:
                _speech_tokens.popitem(last=False)
            else:
                break
    return token


def lookup_speech(token: str) -> Optional[tuple]:
    with _speech_tokens_lock:
        entry = _speech_tokens.get(token)
    if not entry or time.time() - entry[2] > _SPEECH_TOKEN_TTL:
        return None
    return entry[0], entry[1], entry[3]


def _rate_arg(rate: int) -> str:
    rate = max(-50, min(50, int(rate or 0)))
    return f"{rate:+d}%"


def _cache_key(spoken: str, voice: str, rate: int = 0) -> str:
    return f"{voice}|{_rate_arg(rate)}|{spoken}"


class TTSUnavailable(Exception):
    pass


async def tts_stream(text: str, voice: Optional[str] = None, already_clean: bool = False, rate: int = 0) -> AsyncIterator[bytes]:
    """Yield MP3 bytes as Edge produces them.

    The first chunk is awaited *before* this generator is handed to the HTTP
    response (see open_tts_stream) so a failure becomes a clean error the
    browser can fall back from, rather than a broken half-played file.
    """
    voice = voice or settings.EDGE_TTS_VOICE
    spoken = text if already_clean else speech_text(text)
    if not spoken:
        return
    cached = _tts_cache.get(_cache_key(spoken, voice, rate))
    if cached is not None:
        yield cached
        return
    import edge_tts
    # Edge throttles bursts of parallel connections from one client, so at
    # most a few syntheses run at once; the rest wait their turn.
    async with _edge_slots():
        communicate = edge_tts.Communicate(spoken, voice, rate=_rate_arg(rate))
        collected = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                collected.extend(chunk["data"])
                yield chunk["data"]
    if collected:
        _tts_cache.put(_cache_key(spoken, voice, rate), bytes(collected))


async def open_tts_stream(text: str, voice: Optional[str] = None, already_clean: bool = False, rate: int = 0) -> AsyncIterator[bytes]:
    """Start synthesis and wait for the first audio chunk (bounded). Returns an
    iterator that replays that chunk and then streams the rest."""
    last_error: Optional[Exception] = None
    for attempt in range(2):            # one retry: Edge sometimes drops a connection
        generator = tts_stream(text, voice, already_clean, rate)
        try:
            first = await asyncio.wait_for(generator.__anext__(), timeout=settings.TTS_FIRST_CHUNK_TIMEOUT_SECONDS)
            break
        except StopAsyncIteration:
            raise TTSUnavailable("nothing to say")
        except Exception as exc:
            await generator.aclose()
            last_error = exc
            logger.warning(f"Edge-TTS attempt {attempt + 1} failed: {exc.__class__.__name__}: {exc}")
            if attempt == 0:
                await asyncio.sleep(0.6)
    else:
        raise TTSUnavailable(f"{last_error.__class__.__name__}: {last_error}") from last_error

    async def replay():
        yield first
        try:
            async for chunk in generator:
                yield chunk
        except Exception as exc:  # network dropped mid-reply: end the file cleanly
            logger.warning(f"Edge-TTS stream interrupted: {exc}")

    return replay()


async def synthesize_speech_base64(text: str, voice: Optional[str] = None, rate: int = 0) -> Optional[str]:
    """Whole-reply synthesis as base64 (kept for clients that do not stream)."""
    spoken = speech_text(text)
    if not spoken:
        return None
    try:
        voice = voice or settings.EDGE_TTS_VOICE
        cached = _tts_cache.get(_cache_key(spoken, voice, rate))
        if cached is not None:
            return base64.b64encode(cached).decode("utf-8")
        # Long replies take longer to synthesise; scale the budget with length
        # instead of a flat 5 s that silently dropped long answers.
        budget = min(30.0, 5.0 + len(spoken) / 60.0)

        async def collect() -> bytes:
            buffer = bytearray()
            async for chunk in tts_stream(spoken, voice, already_clean=True, rate=rate):
                buffer.extend(chunk)
            return bytes(buffer)

        audio = await asyncio.wait_for(collect(), timeout=budget)
        return base64.b64encode(audio).decode("utf-8") if audio else None
    except Exception as e:
        logger.info(f"Edge-TTS skipped ({e}); proceeding with Web Speech TTS fallback.")
        return None
