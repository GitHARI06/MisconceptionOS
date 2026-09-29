import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "MisconceptionOS"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    # PostgreSQL is used for concept-scoped conversation persistence. Keep it
    # explicit so deployments do not silently write learner memory elsewhere.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # Local LLM via Ollama
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    FALLBACK_MODEL: str = "llama3:latest"
    
    # Whisper STT config
    WHISPER_MODEL_SIZE: str = "small" # or base / tiny
    WHISPER_DEVICE: str = "cuda" if os.getenv("USE_CUDA", "true").lower() == "true" else "cpu"
    WHISPER_COMPUTE_TYPE: str = "float16" if WHISPER_DEVICE == "cuda" else "int8"
    
    # TTS config
    EDGE_TTS_VOICE: str = "en-US-AndrewMultilingualNeural" # Friendly natural tutor voice
    
    # Knowledge / RAG config
    DATA_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    ENABLE_WEB_SEARCH: bool = True
    
    class Config:
        env_file = ".env"

settings = Settings()
