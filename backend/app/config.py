import os
import logging
from pydantic_settings import BaseSettings

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_AUTH_SECRET = "misconceptionos-dev-auth-secret-change-me"


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    APP_NAME: str = "MisconceptionOS"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    # PostgreSQL is used for concept-scoped conversation persistence. Keep it
    # explicit so deployments do not silently write learner memory elsewhere.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    AUTH_SECRET: str = os.getenv("AUTH_SECRET", _DEFAULT_AUTH_SECRET)

    # Local LLM via Ollama
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    FALLBACK_MODEL: str = "llama3:latest"

    # Whisper STT config
    # "auto" picks small.en on a GPU and base.en on CPU.
    WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "auto")
    # Which transcript wins when the browser and Whisper both have one:
    # auto (Whisper on GPU, browser on CPU), whisper, or browser.
    STT_PREFERENCE: str = os.getenv("STT_PREFERENCE", "auto")
    STT_TIMEOUT_SECONDS: float = float(os.getenv("STT_TIMEOUT_SECONDS", "8"))
    WHISPER_DEVICE: str = "cuda" if _env_flag("USE_CUDA", True) else "cpu"
    WHISPER_COMPUTE_TYPE: str = "float16" if WHISPER_DEVICE == "cuda" else "int8"
    # Loading Whisper can take many seconds (and downloads the model the first
    # time), so it is warmed up in a background thread unless disabled.
    WHISPER_WARMUP: bool = not _env_flag("DISABLE_WHISPER_WARMUP", False)

    # TTS config
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "en-US-AndrewMultilingualNeural")  # Friendly natural tutor voice
    TTS_FIRST_CHUNK_TIMEOUT_SECONDS: float = float(os.getenv("TTS_FIRST_CHUNK_TIMEOUT_SECONDS", "8"))

    # Knowledge / RAG config
    DATA_DIR: str = os.path.join(_APP_DIR, "data")
    LEARNER_STORE_PATH: str = os.getenv("LEARNER_STORE_PATH", os.path.join(_APP_DIR, "data", "learner_store.json"))
    ENABLE_WEB_SEARCH: bool = not _env_flag("DISABLE_WEB_SEARCH", False)
    WEB_SEARCH_TIMEOUT_SECONDS: int = 6

    # Uploaded documents (RAG)
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")
    ENABLE_EMBEDDINGS: bool = not _env_flag("DISABLE_EMBEDDINGS", False)
    MAX_UPLOAD_MB: float = float(os.getenv("MAX_UPLOAD_MB", "20"))
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "4"))
    # Used only when DATABASE_URL is not set.
    DOCUMENT_STORE_PATH: str = os.getenv("DOCUMENT_STORE_PATH", os.path.join(_APP_DIR, "data", "documents_store.json"))

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

if settings.AUTH_SECRET == _DEFAULT_AUTH_SECRET:
    logging.getLogger("misconception_os.config").warning(
        "AUTH_SECRET is not set; using the insecure development default. Set AUTH_SECRET in backend/.env."
    )
