import io
import os
import uuid
import base64
import tempfile
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("misconception_os.audio")

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            logger.info(f"Loading faster-whisper tiny.en on {device} ({compute_type})...")
            _whisper_model = WhisperModel("tiny.en", device=device, compute_type=compute_type)
            logger.info("faster-whisper tiny.en ready!")
        except Exception as e:
            logger.error(f"Whisper initialization fallback: {e}")
            _whisper_model = None
    return _whisper_model

# Warmup on load
try:
    get_whisper_model()
except Exception:
    pass

async def transcribe_audio_base64(audio_base64: str) -> str:
    """Transcribes audio using faster-whisper on CUDA."""
    temp_path = None
    try:
        if not audio_base64:
            return ""
        if "," in audio_base64:
            audio_base64 = audio_base64.split(",", 1)[1]
        
        audio_bytes = base64.b64decode(audio_base64)
        if len(audio_bytes) < 100:
            return ""
            
        temp_filename = f"whisper_{uuid.uuid4().hex}.webm"
        temp_path = os.path.join(tempfile.gettempdir(), temp_filename)
        with open(temp_path, "wb") as f:
            f.write(audio_bytes)
            
        model = get_whisper_model()
        if model is None:
            return ""
            
        segments, info = model.transcribe(
            temp_path,
            beam_size=1,
            language="en",
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
            if no_speech_prob < 0.65 and avg_logprob > -1.5 and segment.text.strip():
                clean_segments.append(segment.text.strip())
        transcribed_text = " ".join(clean_segments).strip()
        return transcribed_text
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

async def synthesize_speech_base64(text: str, voice: str = "en-US-AndrewMultilingualNeural") -> Optional[str]:
    """Synthesizes text to speech with low latency using edge-tts."""
    if not text or not text.strip():
        return None
        
    temp_path = None
    try:
        import edge_tts
        temp_filename = f"tts_{uuid.uuid4().hex}.mp3"
        temp_path = os.path.join(tempfile.gettempdir(), temp_filename)
            
        clean_text = text.replace("$", "").replace("#", "").replace("*", "").replace("`", "").replace("\\", "")
        communicate = edge_tts.Communicate(clean_text, voice)
        await asyncio.wait_for(communicate.save(temp_path), timeout=5.0)
        
        with open(temp_path, "rb") as f:
            audio_data = f.read()
            
        return base64.b64encode(audio_data).decode("utf-8")
    except Exception as e:
        logger.info(f"Edge-TTS skipped ({e}); proceeding with Web Speech TTS fallback.")
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
