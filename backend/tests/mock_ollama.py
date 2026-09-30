"""A stand-in for the Ollama HTTP API used by the end-to-end tests.

It answers the four prompt families the backend sends (diagnosis, tutor
reply, quiz, study plan) and can be switched into failure modes through
POST /__mode so the tests can exercise every fallback path:

  good      realistic, well-formed answers
  garbage   non-JSON / truncated text
  badvalues JSON with out-of-range or unknown enum values
  leaky     the tutor reply blurts out the challenge answer
  slow      sleeps longer than the backend timeouts
  error     HTTP 500 for everything
"""

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"mode": "good", "calls": [], "prompts": []}


def _diagnosis(prompt: str) -> dict:
    m = re.search(r'Student\'s Latest Response:\s*"(.*?)"\s*\n', prompt, re.S)
    text = (m.group(1) if m else "").lower()
    if any(k in text for k in ["don't know", "dont know", "no idea"]):
        return {"category": "insufficient_evidence", "affected_concept_id": "newton_first_law_inertia",
                "affected_concept_name": "Newton's 1st Law", "confidence": 0.8, "evidence_quote": text,
                "pedagogical_reason": "Learner expressed uncertainty.", "detected_misconception_id": None,
                "reasoning_soundness_score": 0.3, "is_correct_answer_with_flawed_reasoning": False}
    if re.search(r"(net force (must be|is) (0|zero))|zero net force|no net force|inertia|a = 0|acceleration is 0|second law|cannot|can't", text):
        return {"category": "insufficient_evidence", "affected_concept_id": "newton_first_law_inertia",
                "affected_concept_name": "Newton's 1st Law", "confidence": 0.93, "evidence_quote": text,
                "pedagogical_reason": "Sound reasoning: zero net force for constant velocity.",
                "detected_misconception_id": None, "reasoning_soundness_score": 0.95,
                "is_correct_answer_with_flawed_reasoning": False}
    if re.search(r"force|push|need|must", text):
        return {"category": "wrong_rule_definition", "affected_concept_id": "newton_first_law_inertia",
                "affected_concept_name": "Newton's 1st Law", "confidence": 0.9, "evidence_quote": text,
                "pedagogical_reason": "Believes motion requires a sustaining force.",
                "detected_misconception_id": "PHYS_MISC_01", "reasoning_soundness_score": 0.2,
                "is_correct_answer_with_flawed_reasoning": False}
    return {"category": "insufficient_evidence", "affected_concept_id": "general_inquiry",
            "affected_concept_name": "General", "confidence": 0.7, "evidence_quote": text,
            "pedagogical_reason": "Conversational turn.", "detected_misconception_id": None,
            "reasoning_soundness_score": 0.6, "is_correct_answer_with_flawed_reasoning": False}


def _quiz(prompt: str) -> dict:
    topic = re.search(r"for the concept: (.+?)\.\n", prompt)
    topic = topic.group(1) if topic else "physics"
    return {"questions": [
        {"id": f"q{i}", "question": f"{topic} question {i}?",
         "options": [f"A{i}", f"B{i}", f"C{i}", f"D{i}"], "answer": i % 4,
         "explanation": f"Because of {topic}."} for i in range(1, 6)]}


def _plan(prompt: str) -> dict:
    topic = re.search(r"study plan for (.+?)\.\n", prompt)
    topic = topic.group(1) if topic else "physics"
    return {"title": f"{topic} plan", "goal": f"Master {topic}", "duration_days": 3, "schedule": [
        {"day": d, "minutes": 60, "focus": f"{topic} focus {d}", "activity": f"{topic} activity {d}",
         "checkpoint": f"check {d}", "blocks": [{"minutes": 30, "task": "a"}, {"minutes": 30, "task": "b"}]}
        for d in range(1, 4)]}


def _embed(text: str, dims: int = 64) -> list:
    """Deterministic bag-of-words vector: similar texts get similar vectors."""
    vector = [0.0] * dims
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) > 3:
            vector[sum(map(ord, word)) % dims] += 1.0
    return vector


def _tutor(prompt: str) -> str:
    phase = re.search(r"Current Lesson Phase: (\w+)", prompt)
    phase = phase.group(1) if phase else ""
    topic = re.search(r"Current Topic: (.*)", prompt)
    topic = topic.group(1).strip() if topic else "physics"
    ref = re.search(r"Reference material from the learner's uploaded documents:\n(\[[^\]]+\])\s*([^\n]{0,160})", prompt)
    if ref:
        return f"[{phase}] According to {ref.group(1)}: {ref.group(2)} What do you think follows from that?"
    if STATE["mode"] == "leaky":
        return "Honestly the answer is zero force: 0 N, because inertia keeps it moving. They land at the same time."
    return (f"[{phase}] Let's think about {topic} carefully. Picture a concrete situation and "
            f"tell me what you expect to happen, and why?")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"models": [{"name": "llama3.2:3b"}], "mode": STATE["mode"]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/__mode":
            STATE["mode"] = body.get("mode", "good")
            STATE["calls"].clear()
            STATE["prompts"].clear()
            return self._send(200, {"mode": STATE["mode"]})
        if self.path == "/__calls":
            return self._send(200, {"calls": STATE["calls"]})
        if self.path == "/__prompts":
            return self._send(200, {"prompts": STATE["prompts"][-20:]})
        if self.path == "/api/embed":
            STATE["calls"].append("embed")
            if STATE["mode"] in ("error", "noembed"):
                return self._send(404, {"error": "model not found"})
            inputs = body.get("input") or []
            inputs = [inputs] if isinstance(inputs, str) else inputs
            return self._send(200, {"embeddings": [_embed(t) for t in inputs]})
        prompt = body.get("prompt", "")
        kind = ("diagnosis" if "Cognitive Diagnostic Engine" in prompt else
                "quiz" if "multiple-choice physics quiz" in prompt else
                "plan" if "study plan" in prompt else "tutor")
        STATE["calls"].append(kind)
        STATE["prompts"].append({"kind": kind, "prompt": prompt[-6000:]})
        mode = STATE["mode"]
        if mode == "error":
            return self._send(500, {"error": "boom"})
        if mode == "slow":
            time.sleep(40)
        if mode == "lag":            # a noticeable but normal model delay
            time.sleep(2)
        if mode == "garbage":
            return self._send(200, {"response": "{not json" if kind != "tutor" else "ok"})
        if kind == "diagnosis":
            out = _diagnosis(prompt)
            if mode == "badvalues":
                out.update({"category": "sound mastery", "confidence": 1.7})
            return self._send(200, {"response": json.dumps(out)})
        if kind == "quiz":
            out = _quiz(prompt)
            if mode == "badvalues":
                for q in out["questions"]:
                    q["answer"] = "B"
            return self._send(200, {"response": json.dumps(out)})
        if kind == "plan":
            return self._send(200, {"response": json.dumps(_plan(prompt))})
        return self._send(200, {"response": _tutor(prompt)})


def serve(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    import sys
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 11435)
    while True:
        time.sleep(3600)
