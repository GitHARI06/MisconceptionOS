"""Tutor persona: personal greetings, classroom requests, pace, recap, style."""

import pytest

from conftest import turn, state, read_log

WRONG = "There must be a forward force of 12 Newtons pushing it, or it will stop."


def start(api, sid, name=None, hour=18):
    body = {"session_id": sid, "hour": hour, "voice_mode": "none"}
    if name:
        body["learner_name"] = name
    r = api.post("/api/tutor/session-start", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def into_challenge(api, sid, ollama=None):
    if ollama:
        ollama.mode("error")        # scripted tutor -> the known puck challenge
    turn(api, sid, "hi")
    turn(api, sid, "let's learn newton's laws")
    r = turn(api, sid, "no doubts, I'm ready")
    assert r["lesson_phase"] == "SOCRATIC_CHALLENGE"
    return r


def last_tutor_prompt(ollama):
    prompts = [p for p in ollama.prompts() if p["kind"] == "tutor"]
    return prompts[-1]["prompt"] if prompts else ""


# ---------------------------------------------------------------- greetings
def test_new_learner_gets_time_aware_personal_greeting(api, sid):
    g = start(api, sid, name="Priya", hour=19)
    assert g["text"].startswith("Good evening, Priya!") and g["returning"] is False
    assert start(api, sid + "x", hour=8)["text"].startswith("Good morning!")
    assert start(api, sid + "y", hour=14)["text"].startswith("Good afternoon!")
    # a greeting alone does not register a learner
    assert state(api, sid)["total_turns"] == 0


def test_returning_learner_is_welcomed_back_and_can_resume(api, ollama, sid):
    into_challenge(api, sid, ollama)
    turn(api, sid, WRONG)
    ollama.mode("good")
    g = start(api, sid, name="Arjun")
    assert g["returning"] is True and "Newtonian Mechanics" in g["text"] and "pick up" in g["text"]
    s = state(api, sid)
    assert s["current_phase"] == "GREETING" and s["stuckness_count"] == 0
    mastery_before = {k: v["mastery_prob"] for k, v in s["concept_states"].items()}
    r = turn(api, sid, "yes, let's continue")
    assert r["lesson_phase"] == "TOPIC_TEACHING" and r["current_topic"] == "Newtonian Mechanics"
    assert "coming back to Newtonian Mechanics" in last_tutor_prompt(ollama)
    assert {k: v["mastery_prob"] for k, v in state(api, sid)["concept_states"].items()} == mastery_before


def test_account_name_is_used(api, ollama, sid):
    turn(api, sid, "hi", learner_name="Meera")
    turn(api, sid, "let's learn optics", learner_name="Meera")
    assert "The learner's name is Meera" in last_tutor_prompt(ollama)
    assert start(api, sid)["text"].startswith("Good evening, Meera!")


# ---------------------------------------------------------------- classroom requests
def test_learner_can_introduce_themselves(api, ollama, sid):
    r = turn(api, sid, "Hi, my name is Priya")
    assert r["is_out_of_scope"] is False and "Nice to meet you, Priya" in r["tutor_text"]
    assert r["learner_name"] == "Priya"
    r = turn(api, sid, "let's learn thermodynamics")
    assert "The learner's name is Priya" in last_tutor_prompt(ollama)
    # name + a real request: the request is still answered
    r = turn(api, sid + "b", "my name is Kabir and I want to learn optics")
    assert r["current_topic"] == "Optics"


def test_pace_requests_change_the_voice(api, ollama, sid):
    into_challenge(api, sid, ollama)
    r = turn(api, sid, "can you speak a bit slower please", voice_mode="stream")
    assert r["is_out_of_scope"] is False
    assert "slow" in r["tutor_text"].lower() and "puck" in r["tutor_text"].lower(), "should repeat the open question"
    assert r["lesson_phase"] == "SOCRATIC_CHALLENGE"
    api.get(r["tts_url"])
    assert read_log("tts_log")[-1]["rate"] == "-12%"
    r = turn(api, sid, "a bit slower", voice_mode="stream")
    api.get(r["tts_url"])
    assert read_log("tts_log")[-1]["rate"] == "-24%"
    r = turn(api, sid, "normal speed", voice_mode="stream")
    api.get(r["tts_url"])
    assert read_log("tts_log")[-1]["rate"] == "+0%"


def test_pace_is_remembered_in_the_greeting_voice(api, sid):
    turn(api, sid, "hi")
    turn(api, sid, "please slow down")
    g = api.post("/api/tutor/session-start", json={"session_id": sid, "hour": 10, "voice_mode": "stream"}).json()
    assert g["speech_rate"] == -12
    api.get(g["tts_url"])
    assert read_log("tts_log")[-1]["rate"] == "-12%"


def test_repeat_says_the_last_thing_again_without_grading(api, ollama, sid):
    r = into_challenge(api, sid, ollama)
    before = state(api, sid)
    ollama.mode("good")
    calls_before = len([c for c in ollama.calls() if c == "tutor"])
    again = turn(api, sid, "sorry, can you repeat that?")
    assert r["tutor_text"] in again["tutor_text"]
    assert again["lesson_phase"] == "SOCRATIC_CHALLENGE"
    assert len([c for c in ollama.calls() if c == "tutor"]) == calls_before, "repeat should not call the model"
    after = state(api, sid)
    assert after["stuckness_count"] == before["stuckness_count"] and after["concept_states"] == before["concept_states"]
    # repeating twice does not stack "Sure. Sure. ..."
    twice = turn(api, sid, "say that again")
    assert not twice["tutor_text"].startswith("Sure. Sure.")


def test_hint_request_is_a_hint_not_a_wrong_answer(api, ollama, sid):
    into_challenge(api, sid, ollama)
    r = turn(api, sid, "can I get a hint?")
    assert r["intervention_tier"] == "SCAFFOLDED_HINT" and r["lesson_phase"] == "SOCRATIC_SCAFFOLDING"
    assert "0 N" not in r["tutor_text"] and "zero force" not in r["tutor_text"].lower()
    s = state(api, sid)
    assert s["stuckness_count"] == 0 and all(c["total_attempts"] == 0 for c in s["concept_states"].values())
    ollama.mode("good")
    turn(api, sid, "give me a hint")
    assert "asked for a hint" in last_tutor_prompt(ollama)
    # after hints, a wrong answer still gets the normal first-tier response
    r = turn(api, sid, WRONG)
    assert r["intervention_tier"] == "COGNITIVE_CONFLICT"


def test_frustration_gets_reassurance_and_a_smaller_step(api, ollama, sid):
    into_challenge(api, sid, ollama)
    r = turn(api, sid, "ugh this is too hard, I give up")
    text = r["tutor_text"].lower()
    assert any(w in text for w in ["okay", "normal", "tricky"]) and "smaller" in text
    assert r["tutor_text"].rstrip().endswith("?")
    assert state(api, sid)["stuckness_count"] == 0
    ollama.mode("good")
    turn(api, sid, "I'm so bad at physics")
    prompt = last_tutor_prompt(ollama)
    assert "sounds frustrated" in prompt and "smaller" in prompt


def test_explain_differently_asks_for_a_new_analogy(api, ollama, sid):
    turn(api, sid, "hi")
    turn(api, sid, "let's learn thermodynamics")
    turn(api, sid, "what is entropy?")
    r = turn(api, sid, "I still don't get it")
    assert r["lesson_phase"] == "RESOLVING_DOUBT"
    assert "different everyday analogy" in last_tutor_prompt(ollama)


def test_goodbye_gives_a_recap_and_next_step(api, ollama, sid):
    into_challenge(api, sid, ollama)
    turn(api, sid, WRONG)
    r = turn(api, sid, "okay that's all for today, bye")
    text = r["tutor_text"]
    assert "Newtonian Mechanics" in text and "Next time" in text and "See you soon" in text
    assert r["lesson_phase"] == "GREETING"
    # a new sitting starts clean: an immediate goodbye has nothing new to recap
    r = turn(api, sid, "bye")
    assert "We worked on" not in r["tutor_text"]


def test_recap_celebrates_verified_mastery(api, ollama, sid):
    into_challenge(api, sid, ollama)
    turn(api, sid, "The net force is zero, inertia keeps it moving at constant velocity.")
    turn(api, sid, "Its speed stays the same because no net force acts on the probe")
    r = turn(api, sid, "let's stop here")
    assert "really understand" in r["tutor_text"]


# ---------------------------------------------------------------- spoken style
def test_prompt_carries_the_spoken_style_guide(api, ollama, sid):
    turn(api, sid, "hi")
    turn(api, sid, "let's learn waves")
    prompt = last_tutor_prompt(ollama)
    assert "read aloud" in prompt and "exactly one clear question" in prompt
    assert "never intelligence" in prompt


def test_long_model_answers_are_trimmed_for_listening():
    from app.tutor_persona import fit_for_voice
    long = " ".join(f"This is explanation sentence number {i} with several words." for i in range(12)) + " Can you try it?"
    out = fit_for_voice(long)
    assert out.endswith("Can you try it?") and len(out) < len(long) and out.count(".") <= 5
    short = "Nice thinking. What happens next?"
    assert fit_for_voice(short) == short


@pytest.mark.parametrize("text, intent", [
    ("I see you used F = ma", None), ("the hint is in the question", None), ("we can ignore friction", None),
    ("please slow down", "pace_slower"), ("pardon?", "repeat"), ("goodbye", "end_session"),
    ("hint", "hint"), ("I give up", "frustration"), ("yes please", "resume"),
])
def test_intent_detection(text, intent):
    from app.tutor_persona import detect_intent
    assert detect_intent(text) == intent
