"""End-to-end test harness.

Starts a stand-in Ollama server and the real FastAPI backend (as a separate
uvicorn process) and talks to it over HTTP, exactly like the frontend does.

Requirements:
  * PostgreSQL reachable at TEST_DATABASE_URL
    (default postgresql://postgres:postgres@localhost:5432/misconception_os_test)
  * pip install -r requirements.txt pytest

Run from the backend folder:  python -m pytest tests -v
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
import pytest

sys.path.insert(0, os.path.dirname(__file__))
# In-process imports of app modules must not start loading a real Whisper model.
os.environ.setdefault("DISABLE_WHISPER_WARMUP", "true")
import mock_ollama  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = {}
_fake_dir = tempfile.mkdtemp()
FAKES = {"tts_log": os.path.join(_fake_dir, "tts.jsonl"), "stt_log": os.path.join(_fake_dir, "stt.jsonl")}


def read_log(name):
    import json as _json
    path = FAKES[name]
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [_json.loads(line) for line in f if line.strip()]
DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/misconception_os_test")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def ollama():
    port = _free_port()
    server = mock_ollama.serve(port)
    base = f"http://127.0.0.1:{port}"

    class Ctl:
        url = base

        def mode(self, name: str):
            httpx.post(f"{base}/__mode", json={"mode": name})

        def calls(self):
            return httpx.post(f"{base}/__calls", json={}).json()["calls"]

        def prompts(self):
            return httpx.post(f"{base}/__prompts", json={}).json()["prompts"]

    yield Ctl()
    server.shutdown()


@pytest.fixture(scope="session")
def server(ollama):
    port = _free_port()
    store = os.path.join(tempfile.mkdtemp(), "learner_store.json")
    STORE["path"] = store
    env = {
        **os.environ,
        "DATABASE_URL": DB_URL,
        "OLLAMA_BASE_URL": ollama.url,
        "AUTH_SECRET": "test-secret-" + uuid.uuid4().hex,
        "LEARNER_STORE_PATH": store,
        "USE_CUDA": "false",
        "DISABLE_WHISPER_WARMUP": "true",
        "DISABLE_WEB_SEARCH": "true",
        # Stand-in speech engines (tests/fakes) instead of the real network/model ones.
        "PYTHONPATH": os.path.join(os.path.dirname(__file__), "fakes") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "FAKE_TTS_LOG": FAKES["tts_log"],
        "FAKE_STT_LOG": FAKES["stt_log"],
        "STT_PREFERENCE": "whisper",
        "MAX_UPLOAD_MB": "2",
        "DOCUMENT_STORE_PATH": os.path.join(tempfile.mkdtemp(), "documents_store.json"),
    }
    log_path = os.path.join(tempfile.gettempdir(), f"misconception_backend_{port}.log")
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR, env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(base + "/", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("backend did not start:\n" + open(log_path).read())
    print(f"\nbackend log: {log_path}")
    yield base
    proc.terminate()
    try:
        proc.wait(10)
    except Exception:
        proc.kill()


@pytest.fixture
def api(server, ollama):
    ollama.mode("good")
    with httpx.Client(base_url=server, timeout=90) as client:
        yield client
    ollama.mode("good")


@pytest.fixture
def sid():
    return f"test-{uuid.uuid4().hex[:12]}"


def turn(api, sid, text, **extra):
    payload = {"session_id": sid, "challenge_id": "freeform_inquiry", "unit_id": "physics_mechanics", "text": text, **extra}
    r = api.post("/api/chat/turn", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def state(api, sid):
    r = api.get(f"/api/teacher/learner-state/{sid}")
    assert r.status_code == 200, r.text
    return r.json()
