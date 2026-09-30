import asyncio
import logging
import re
import uuid
from io import BytesIO
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .models import (
    SocraticDirective, StudentInput, SocraticTurnResult, DiagnosticEvidence, DiagnosticCategory,
    InterventionTier, LearnerProfile, StressTestEvaluation, LessonPhase,
    RegisterRequest, LoginRequest
)
from .audio_service import (
    transcribe_audio_base64, synthesize_speech_base64, register_speech, lookup_speech,
    open_tts_stream, TTSUnavailable, whisper_status, prefer_server_stt, speech_text,
)
from .document_store import document_store, DocumentError, format_references, source_list
from .rag_engine import knowledge_engine
from .safety_guard import SafetyGuardrail
from .diagnostic_engine import DiagnosticEngine
from .socratic_policy import SocraticPolicyEngine
from .generator import SocraticGenerator
from .learner_memory import learner_memory
from .postgres_memory import concept_memory
from .stress_test_runner import StressTestRunner
from .auth_service import account_service
from .quiz_service import quiz_service
from . import tutor_persona as persona

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("misconception_os.main")

app = FastAPI(
    title="MisconceptionOS",
    description="Socratic Diagnostic Tutor for Reasoning, Not Answer Delivery",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "status": "online",
        "app": "MisconceptionOS",
        "version": "1.0.0",
        "track": "Yuva Megathon 2026 - Domain 02: Large Language Models"
    }

@app.post("/api/auth/register")
def register_student(request: RegisterRequest):
    if not account_service.enabled:
        raise HTTPException(status_code=503, detail="Account storage is not available.")
    try:
        user = account_service.create_account(
            request.username, request.email, request.password, request.class_level
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Account registration failed")
        raise HTTPException(status_code=503, detail="Unable to create the account right now.") from exc
    return {"user": account_service.public_user(user), "token": account_service.issue_token(user)}

@app.post("/api/auth/login")
def login_student(request: LoginRequest):
    if not account_service.enabled:
        raise HTTPException(status_code=503, detail="Account storage is not available.")
    try:
        user = account_service.authenticate(request.identity, request.password)
    except Exception as exc:
        logger.exception("Account login failed")
        raise HTTPException(status_code=503, detail="Unable to sign in right now.") from exc
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")
    return {"user": user, "token": account_service.issue_token(user)}

@app.get("/api/auth/me")
def current_student(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = account_service.user_from_token(authorization.split(" ", 1)[1].strip())
    if not user:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    return {"user": user}

@app.get("/api/quiz/{session_id}")
async def get_concept_quizzes(session_id: str):
    """Generate/cache one quiz for every concept the learner has explored."""
    conversations = concept_memory.get_conversations(session_id)
    quizzes, unavailable = [], []
    for concept_id, turns in conversations.items():
        if not turns:
            continue
        topic = turns[-1].get("topic") or concept_id.replace("_", " ").title()
        dialogue = "\n".join(f"Student: {turn.get('user', '')}\nTutor: {turn.get('tutor', '')}" for turn in turns[-8:])
        try:
            quizzes.append(await asyncio.to_thread(quiz_service.get_or_create_quiz, session_id, concept_id, topic, dialogue))
        except RuntimeError as exc:
            # One concept failing to generate must not hide every other quiz.
            logger.warning("Quiz unavailable for %s: %s", concept_id, exc)
            unavailable.append({"concept_id": concept_id, "topic": topic, "reason": str(exc)})
    if unavailable and not quizzes:
        raise HTTPException(status_code=503, detail=unavailable[0]["reason"])
    return {"session_id": session_id, "quizzes": quizzes, "unavailable": unavailable}

@app.post("/api/quiz/submit")
async def submit_concept_quiz(payload: Dict[str, Any]):
    raw_answers = payload.get("answers") or []
    if not isinstance(raw_answers, list):
        raise HTTPException(status_code=400, detail="answers must be a list")
    try:
        # Unanswered questions arrive as null from the browser: count them as wrong.
        answers = [-1 if answer is None or answer == "" else int(answer) for answer in raw_answers]
        hours = float(payload.get("hours_per_day") or 1.0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="answers must be option numbers") from exc
    try:
        return await asyncio.to_thread(
            quiz_service.submit,
            str(payload.get("session_id", "")),
            str(payload.get("concept_id", "")),
            answers,
            hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/api/quiz/progress")
def update_study_plan_progress(payload: Dict[str, Any]):
    try:
        int(payload.get("day", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="day must be a number") from exc
    try:
        completed_days = quiz_service.set_day_complete(
            session_id=str(payload.get("session_id", "")),
            concept_id=str(payload.get("concept_id", "")),
            day=payload.get("day", 0),
            completed=bool(payload.get("completed", True)),
        )
        return {"session_id": payload.get("session_id"), "concept_id": payload.get("concept_id"), "completed_days": completed_days}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/api/quiz/clear-plan")
def clear_study_plan(payload: Dict[str, Any]):
    quiz_service.clear_study_plan(str(payload.get("session_id", "")), str(payload.get("concept_id", "")))
    return {"session_id": payload.get("session_id"), "concept_id": payload.get("concept_id"), "cleared": True}

@app.get("/api/quiz/attempts/{session_id}")
def get_quiz_attempts(session_id: str):
    return {"session_id": session_id, "attempts": quiz_service.attempts(session_id)}

@app.get("/api/curriculum/challenges")
def get_challenges(unit_id: str = "physics_mechanics"):
    unit = knowledge_engine.units.get(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return {
        "unit": unit,
        "concepts": knowledge_engine.get_unit_concepts(unit_id),
        "challenges": [ch for ch in knowledge_engine.challenges.values() if ch.get("unit_id") == unit_id]
    }

@app.post("/api/audio/transcribe")
async def transcribe_audio(payload: Dict[str, str]):
    audio_base64 = payload.get("audio_base64")
    if not audio_base64:
        raise HTTPException(status_code=400, detail="Missing audio_base64")
    text = await transcribe_audio_base64(audio_base64)
    return {"transcription": text}

@app.get("/api/audio/status")
def audio_status():
    return {"whisper": whisper_status(), "prefer_server_stt": prefer_server_stt()}


async def _stream_response(spoken: str, voice: Optional[str] = None, rate: int = 0):
    try:
        iterator = await open_tts_stream(spoken, voice, already_clean=True, rate=rate)
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Neural voice unavailable: {exc}") from exc
    return StreamingResponse(iterator, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/audio/stream/{token}")
async def stream_speech(token: str):
    """Stream a tutor reply as MP3 while it is being synthesised."""
    entry = lookup_speech(token)
    if not entry:
        raise HTTPException(status_code=404, detail="This audio link has expired.")
    spoken, voice, rate = entry
    return await _stream_response(spoken, voice, rate)


@app.get("/api/audio/speak")
async def speak_text(text: str = "", rate: int = 0):
    """Stream arbitrary short text (e.g. the greeting). Cached after first use."""
    spoken = speech_text(text[:1500])
    if not spoken:
        raise HTTPException(status_code=400, detail="Missing text")
    return await _stream_response(spoken, rate=max(-40, min(30, rate)))


@app.post("/api/audio/synthesize")
async def synthesize_speech(payload: Dict[str, str]):
    text = payload.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="Missing text")
    audio_b64 = await synthesize_speech_base64(text)
    return {"audio_base64": audio_b64}

GRADED_PHASES = {LessonPhase.SOCRATIC_CHALLENGE, LessonPhase.SOCRATIC_SCAFFOLDING, LessonPhase.TRANSFER_CHECK}
NEW_TOPIC_MARKERS = ["let's learn", "lets learn", "teach me", "want to learn", "study "]


async def _voice(text: str, voice_mode: str, rate: int = 0):
    """Reply audio according to the client's voice mode: (audio_base64, tts_url)."""
    mode = (voice_mode or "inline").lower()
    if mode == "stream":
        token = register_speech(text, rate=rate)
        return None, (f"/api/audio/stream/{token}" if token else None)
    if mode == "none":
        return None, None
    return await synthesize_speech_base64(text, rate=rate), None


def _guard_result(session_id, user_text, tutor_text, voice, concept_id, concept_name, reason,
                  phase=LessonPhase.GREETING, topic=None, injection=False, out_of_scope=False, stt_source=None):
    audio_b64, tts_url = voice
    return SocraticTurnResult(
        session_id=session_id,
        user_utterance=user_text,
        tutor_text=tutor_text,
        audio_base64=audio_b64,
        tts_url=tts_url,
        stt_source=stt_source,
        lesson_phase=phase,
        current_topic=topic,
        intervention_tier=InterventionTier.DIAGNOSTIC_PROBE,
        diagnostic=DiagnosticEvidence(
            category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
            affected_concept_id=concept_id,
            affected_concept_name=concept_name,
            confidence=1.0,
            evidence_quote=user_text,
            pedagogical_reason=reason,
            reasoning_soundness_score=0.0,
        ),
        leakage_check_passed=True,
        is_prompt_injection=injection,
        is_out_of_scope=out_of_scope,
    )


async def _classroom_reply(session_id, submission, profile, user_text, tutor_text, stt_source, end_session=False):
    """A tutor reply to a classroom request (pace, repeat, name, goodbye).
    Logged in the conversation but never graded, and the lesson state is kept."""
    diagnostic = DiagnosticEvidence(
        category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
        affected_concept_id="tutor_dialogue",
        affected_concept_name="Classroom dialogue",
        confidence=1.0,
        evidence_quote=user_text,
        pedagogical_reason="Classroom request (not a physics answer); nothing was graded.",
        reasoning_soundness_score=0.0,
    )
    phase = LessonPhase.GREETING if end_session else profile.current_phase
    learner_memory.update_state(
        session_id=session_id, user_text=user_text, tutor_text=tutor_text, diagnostic=diagnostic,
        tier=profile.current_tier, current_phase=phase, current_topic=profile.current_topic,
        concept_id=profile.current_concept_id, graded=False,
    )
    if end_session:
        profile.session_start_index = len(profile.conversation_history)
        profile.stuckness_turn_count = 0
        learner_memory.save_store()
    audio_b64, tts_url = await _voice(tutor_text, submission.voice_mode, profile.speech_rate)
    return SocraticTurnResult(
        session_id=session_id,
        user_utterance=user_text,
        tutor_text=tutor_text,
        audio_base64=audio_b64,
        tts_url=tts_url,
        stt_source=stt_source,
        lesson_phase=phase,
        current_topic=profile.current_topic,
        intervention_tier=profile.current_tier,
        diagnostic=diagnostic,
        leakage_check_passed=True,
        learner_mastery={cid: c.mastery_prob for cid, c in profile.concept_states.items()},
        speech_rate=profile.speech_rate,
        learner_name=persona.display_name(profile),
    )


class SessionStart(BaseModel):
    session_id: str
    learner_name: Optional[str] = None
    hour: Optional[int] = Field(default=None, ge=0, le=23)
    voice_mode: str = "stream"


@app.post("/api/tutor/session-start")
async def start_tutoring_session(payload: SessionStart):
    """Personal greeting for a new sitting. A returning learner is welcomed
    back and offered to pick up where they left off; the lesson restarts from
    the greeting (topic and mastery are kept), so their first words are never
    graded as the answer to a question asked in an earlier sitting."""
    profile = learner_memory.get_profile(payload.session_id)
    if profile is not None:
        if payload.learner_name and not persona.display_name(profile):
            profile.learner_name = payload.learner_name.strip()[:40]
        profile.current_phase = LessonPhase.GREETING
        profile.stuckness_turn_count = 0
        profile.session_start_index = len(profile.conversation_history)
        learner_memory.save_store()
    elif payload.learner_name:
        profile = LearnerProfile(session_id=payload.session_id, learner_name=payload.learner_name.strip()[:40])
    text = persona.greeting(profile, payload.hour)
    rate = profile.speech_rate if profile else 0
    audio_b64, tts_url = await _voice(text, payload.voice_mode, rate)
    return {
        "text": text,
        "tts_url": tts_url,
        "audio_base64": audio_b64,
        "learner_name": persona.display_name(profile),
        "returning": bool(profile and profile.current_topic),
        "speech_rate": rate,
    }


@app.post("/api/chat/turn", response_model=SocraticTurnResult)
async def process_student_turn(submission: StudentInput):
    session_id = submission.session_id or str(uuid.uuid4())
    browser_text = (submission.text or "").strip()
    user_text = browser_text
    stt_source = "browser" if browser_text else None
    existing_profile = learner_memory.get_profile(session_id)
    guard_phase = existing_profile.current_phase if existing_profile else LessonPhase.GREETING
    guard_topic = existing_profile.current_topic if existing_profile else None
    voice_mode = submission.voice_mode

    # 1. Speech-to-text. The browser streams its own transcript; Whisper
    # (with a physics vocabulary prompt) is used when it is the more accurate
    # engine available (GPU) or when the browser heard nothing.
    if submission.audio_base64 and (not browser_text or prefer_server_stt()):
        whisper_text = (await transcribe_audio_base64(submission.audio_base64, topic=guard_topic)).strip()
        if whisper_text:
            user_text, stt_source = whisper_text, "whisper"

    # The microphone heard the tutor's own last reply (speakers, no headset).
    last_tutor = next((str(t.get("tutor", "")) for t in reversed(existing_profile.conversation_history)
                       if t.get("tutor")), "") if existing_profile else ""
    if user_text and last_tutor:
        cleaned = persona.strip_echo(user_text, last_tutor)
        if not cleaned:
            result = _guard_result(session_id, user_text, last_tutor, (None, None), "echo_guard", "Echo filter",
                                   "The utterance matched the tutor's own last reply (speaker echo); ignored.",
                                   phase=guard_phase, topic=guard_topic, stt_source=stt_source)
            result.echo_detected = True
            return result
        user_text = cleaned

    # Nothing intelligible was said (silence, noise, failed transcription).
    # Ask again instead of recording it as an "I don't know" answer, which
    # used to lower mastery and push the learner towards escalation.
    if not user_text:
        msg = "Sorry, I didn't catch that. Could you say it again?"
        return _guard_result(session_id, "", msg, await _voice(msg, voice_mode, existing_profile.speech_rate if existing_profile else 0),
                             "input_guard", "Input Check", "No intelligible learner input was received; nothing was recorded.",
                             phase=guard_phase, topic=guard_topic)

    # 2. Layer 1: Adversarial Prompt Injection Guard
    is_attack, deflection_msg = SafetyGuardrail.detect_prompt_injection(user_text)
    if is_attack:
        return _guard_result(session_id, user_text, deflection_msg, await _voice(deflection_msg, voice_mode, existing_profile.speech_rate if existing_profile else 0),
                             "security_guard", "Prompt Injection Filter",
                             "Adversarial prompt injection attempt detected and neutralized. Socratic persona preserved.",
                             phase=guard_phase, topic=guard_topic, injection=True, stt_source=stt_source)

    # 3. Physics-only boundary with an interdisciplinary physics allowance.
    # For example, air pollution is accepted because atmospheric flow,
    # particles, diffusion, radiation, and thermodynamics are physics topics.
    # A topic supplied by the history drawer is already a persisted physics
    # concept. It allows short follow-ups such as "continue" to resume that
    # concept without being rejected by the front-door vocabulary guard.
    # Classroom requests ("slow down", "say that again", "my name is ...")
    # are part of tutoring even though they contain no physics words.
    intent = persona.detect_intent(user_text)
    introduced_name = persona.extract_name(user_text)
    classroom_request = bool(introduced_name) or intent in {
        "pace_slower", "pace_faster", "pace_normal", "repeat", "end_session", "hint",
        "explain_differently", "frustration", "resume",
    }
    clearly_off_topic = not classroom_request and SafetyGuardrail.is_clearly_non_physics(user_text)
    # Mid-lesson follow-ups ("what happens when it hits the wall?") often
    # contain no physics vocabulary; they belong to the lesson in progress.
    in_lesson = bool(existing_profile and existing_profile.current_topic
                     and existing_profile.current_phase != LessonPhase.GREETING)
    fast_physics_match = not clearly_off_topic and (in_lesson or classroom_request or SafetyGuardrail.is_physics_query(user_text))
    grounded_physics_match = False
    if not clearly_off_topic and not fast_physics_match and not submission.topic:
        # A question answered by the learner's own uploaded material is in
        # scope. Otherwise ambiguous queries take the slower retrieval path.
        # This keeps normal voice turns fast while allowing unfamiliar physics phrasing.
        if await asyncio.to_thread(document_store.search, user_text, 1, False):
            grounded_physics_match = True
        else:
            grounded_context = await asyncio.to_thread(knowledge_engine.search_live_grounding, user_text, 2)
            grounded_physics_match = SafetyGuardrail.is_physics_grounding(user_text, grounded_context)
    if clearly_off_topic or (not fast_physics_match and not grounded_physics_match and not submission.topic):
        scope_msg = (
            "I’m focused on physics, so I can help when a question connects to motion, forces, energy, "
            "heat, fluids, waves, light, electricity, fields, radiation, particles, or related physical systems. "
            "Could you reframe your question through a physics lens?"
        )
        return _guard_result(session_id, user_text, scope_msg, await _voice(scope_msg, voice_mode, existing_profile.speech_rate if existing_profile else 0),
                             "physics_scope_guard", "Physics Scope Boundary",
                             "The query did not contain a recognizable physics or physics-interdisciplinary framing.",
                             phase=guard_phase, topic=guard_topic, out_of_scope=True, stt_source=stt_source)

    # 4. Retrieve persistent profile & the active concept's conversation.
    profile = learner_memory.get_or_create_profile(session_id, submission.unit_id or "physics_mechanics")
    text_lower = user_text.lower()
    previous_phase = profile.current_phase
    explicit_topic = SocraticPolicyEngine._extract_topic(text_lower, None)
    wants_new_topic = any(marker in text_lower for marker in NEW_TOPIC_MARKERS)
    topic_selection_turn = bool(explicit_topic) and (previous_phase == LessonPhase.GREETING or wants_new_topic)

    policy_topic = profile.current_topic
    policy_phase = previous_phase
    if topic_selection_turn:
        active_topic = SocraticPolicyEngine.canonical_topic(explicit_topic)
    elif submission.topic:
        # Resuming a concept from the history drawer.
        active_topic = SocraticPolicyEngine.canonical_topic(submission.topic)
        if SocraticPolicyEngine.concept_id_for_topic(active_topic) != profile.current_concept_id:
            policy_topic = active_topic
            policy_phase = LessonPhase.DOUBT_CHECK if previous_phase != LessonPhase.GREETING else previous_phase
    else:
        active_topic = profile.current_topic
    active_concept_id = SocraticPolicyEngine.concept_id_for_topic(active_topic) or profile.current_concept_id
    if active_concept_id != profile.current_concept_id:
        # A new concept starts with a clean anti-loop counter.
        profile.stuckness_turn_count = 0

    concept_history = concept_memory.get_history(session_id, active_concept_id) if active_concept_id else []
    context_history = concept_history or [
        t for t in profile.conversation_history if "user" in t and "tutor" in t
    ][-12:]

    # ---- Tutor persona: the learner's name, pace and classroom requests.
    if submission.learner_name and not persona.display_name(profile):
        profile.learner_name = submission.learner_name.strip()[:40]
    if introduced_name:
        profile.learner_name = introduced_name
    seed = f"{session_id}:{len(profile.conversation_history)}"
    quick_text = None
    if introduced_name and persona.is_only_name_introduction(user_text):
        quick_text = persona.name_reply(introduced_name, profile)
    elif intent in ("pace_slower", "pace_faster", "pace_normal"):
        profile.speech_rate = {"pace_slower": max(-40, profile.speech_rate - 12),
                               "pace_faster": min(30, profile.speech_rate + 12),
                               "pace_normal": 0}[intent]
        quick_text = persona.pace_reply(intent, context_history, seed)
    elif intent == "repeat":
        quick_text = persona.repeat_reply(context_history)
    elif intent == "end_session":
        quick_text = persona.recap(profile, profile.session_start_index)
    if quick_text:
        return await _classroom_reply(session_id, submission, profile, user_text, quick_text, stt_source,
                                      end_session=(intent == "end_session"))

    # Returning learner says "yes, let's continue" to the welcome-back greeting.
    resuming = (intent == "resume" and previous_phase == LessonPhase.GREETING and bool(profile.current_topic)
                and not topic_selection_turn)
    if resuming:
        explicit_topic = profile.current_topic
        topic_selection_turn = True

    # 5. Multi-Turn Cognitive Diagnostic Engine. Only answers to a challenge
    # need the (slower) model diagnosis; the policy ignores the diagnosis in
    # the greeting / teaching / doubt phases.
    # Retrieval from the uploaded library runs in parallel with diagnosis.
    retrieval_query = f"{user_text} {active_topic or ''}".strip()
    if len(user_text.split()) <= 4 and context_history:
        # Short follow-ups ("why?", "another example") are about the last reply.
        retrieval_query += " " + str(context_history[-1].get("tutor", ""))[:300]
    retrieval_task = asyncio.create_task(asyncio.to_thread(document_store.search, retrieval_query))

    if topic_selection_turn or policy_phase not in GRADED_PHASES:
        diagnostic = DiagnosticEngine._multi_turn_heuristic(user_text, context_history)
    else:
        diagnostic = await DiagnosticEngine.diagnose_reasoning(
            student_text=user_text,
            challenge_id=submission.challenge_id,
            unit_id=submission.unit_id,
            conversation_history=context_history
        )
    try:
        reference_hits = await retrieval_task
    except Exception as exc:
        logger.warning("Document retrieval failed: %s", exc)
        reference_hits = []

    # 6. Socratic Policy Arbiter: Compute Next Lesson Step
    directive = SocraticPolicyEngine.determine_next_step(
        student_text=user_text,
        current_phase=policy_phase,
        current_topic=policy_topic,
        diagnostic=diagnostic,
        conversation_history=context_history,
        stuckness_count=profile.stuckness_turn_count
    )

    # Classroom requests that shape the next move without being graded.
    affect = None
    ungraded_request = False
    in_challenge = policy_phase in GRADED_PHASES
    topic_label = policy_topic or directive.topic or "this idea"
    if resuming:
        directive.pedagogical_goal = (
            f"The learner is coming back to {topic_label}. Welcome them back, recap the key idea in two short sentences, "
            "and ask whether they would like a quick challenge to check they still remember it."
        )
    elif intent == "hint":
        ungraded_request = True
        directive = SocraticDirective(
            tier=InterventionTier.SCAFFOLDED_HINT,
            lesson_phase=LessonPhase.SOCRATIC_SCAFFOLDING if in_challenge else LessonPhase.RESOLVING_DOUBT,
            topic=topic_label,
            pedagogical_goal="The learner asked for a hint. Give ONE small hint that moves them a single step closer, without revealing the answer, then invite them to try again.",
            allowed_information_scope="One sub-step hint.",
        )
    elif intent == "explain_differently":
        ungraded_request = True
        directive = SocraticDirective(
            tier=InterventionTier.CONCEPTUAL_EXPLANATION,
            lesson_phase=LessonPhase.SOCRATIC_SCAFFOLDING if in_challenge else LessonPhase.RESOLVING_DOUBT,
            topic=topic_label,
            pedagogical_goal="The learner did not follow the last explanation. Explain the same idea again with a completely different everyday analogy than before, in simpler words. If a challenge is open, do not give its answer. Check understanding with one question.",
            allowed_information_scope="Re-explanation with a new analogy.",
        )
    elif intent == "frustration":
        ungraded_request = True
        affect = "frustration"
        directive = SocraticDirective(
            tier=InterventionTier.SCAFFOLDED_HINT,
            lesson_phase=LessonPhase.SOCRATIC_SCAFFOLDING if in_challenge else LessonPhase.RESOLVING_DOUBT,
            topic=topic_label,
            pedagogical_goal="The learner is frustrated. Reassure them warmly that this is a hard idea and that struggling is normal, then offer a much smaller, easier first step and ask one simple question about it.",
            allowed_information_scope="Encouragement and a very small sub-step.",
        )

    # Update profile phase & topic
    profile.current_phase = directive.lesson_phase
    directive.topic = SocraticPolicyEngine.canonical_topic(directive.topic) or directive.topic
    profile.current_topic = directive.topic
    concept_id = SocraticPolicyEngine.concept_id_for_topic(directive.topic)
    profile.current_concept_id = concept_id

    # 7. Socratic Generator + Zero-Leakage Canary
    if directive.lesson_phase == LessonPhase.GREETING:
        reference_hits = []
    tutor_text = await SocraticGenerator.generate_response(
        directive=directive,
        student_text=user_text,
        conversation_history=context_history,
        reference_hits=reference_hits,
        profile=profile,
        affect=affect,
    )

    # The UI sends challenge_id="freeform_inquiry", so also recognise a
    # curriculum challenge the tutor presented during the conversation.
    explicit_challenge = knowledge_engine.get_challenge(submission.challenge_id or "") or {}
    challenge = explicit_challenge
    if not challenge and context_history:
        challenge = knowledge_engine.infer_challenge(
            " ".join(str(t.get("tutor", "")) for t in context_history[-4:])
        ) or {}
    if directive.lesson_phase in (LessonPhase.TRANSFER_CHECK, LessonPhase.DOUBT_CHECK):
        # The learner has already reasoned their way to the answer; the
        # tutor may now confirm it.
        zero_leak_ok, sanitized_text = True, tutor_text
    else:
        zero_leak_ok, sanitized_text = SafetyGuardrail.verify_zero_leakage(
            tutor_text,
            challenge.get("solution_redactions", [])
        )

    # 8. Transfer Question Check
    transfer_ready = (directive.lesson_phase == LessonPhase.TRANSFER_CHECK)
    # Only show the curriculum transfer card for an explicitly selected
    # challenge; in free conversation the tutor already asks its own
    # transfer question and a second, different one would confuse learners.
    transfer_q = explicit_challenge.get("transfer_question") if transfer_ready else None

    # 9. Update Persistent Learner Memory (with phase & topic)
    graded = (
        not ungraded_request
        and not topic_selection_turn
        and policy_phase in GRADED_PHASES
        and directive.lesson_phase in {LessonPhase.SOCRATIC_SCAFFOLDING, LessonPhase.TRANSFER_CHECK, LessonPhase.DOUBT_CHECK}
    )
    updated_profile = learner_memory.update_state(
        session_id=session_id,
        user_text=user_text,
        tutor_text=sanitized_text,
        diagnostic=diagnostic,
        tier=directive.tier,
        current_phase=directive.lesson_phase,
        current_topic=directive.topic,
        concept_id=concept_id,
        graded=graded,
    )

    # Recovery verification: the learner solved the transfer problem.
    if graded and policy_phase == LessonPhase.TRANSFER_CHECK and directive.lesson_phase == LessonPhase.DOUBT_CHECK:
        verified_cid = diagnostic.affected_concept_id
        if verified_cid in (None, "", "general_inquiry"):
            verified_cid = concept_id
        learner_memory.verify_recovery(session_id, verified_cid)

    # 10. Voice output (inline base64, or a URL the browser streams)
    audio_b64, tts_url = await _voice(sanitized_text, voice_mode, persona.speech_rate_for(profile, directive.lesson_phase))

    # Format mastery map
    mastery_map = {cid: c.mastery_prob for cid, c in updated_profile.concept_states.items()}

    return SocraticTurnResult(
        session_id=session_id,
        user_utterance=user_text,
        tutor_text=sanitized_text,
        audio_base64=audio_b64,
        lesson_phase=directive.lesson_phase,
        current_topic=directive.topic,
        intervention_tier=directive.tier,
        diagnostic=diagnostic,
        leakage_check_passed=zero_leak_ok,
        is_prompt_injection=False,
        is_out_of_scope=False,
        transfer_ready=transfer_ready,
        transfer_question=transfer_q,
        learner_mastery=mastery_map,
        tts_url=tts_url,
        stt_source=stt_source,
        sources=source_list(reference_hits),
        speech_rate=profile.speech_rate,
        learner_name=persona.display_name(profile),
    )

@app.get("/api/teacher/learner-state/{session_id}")
def get_teacher_view(session_id: str):
    # Viewing a session must not create (and persist) an empty learner.
    profile = learner_memory.get_profile(session_id) or LearnerProfile(session_id=session_id)
    return {
        "session_id": profile.session_id,
        "unit_id": profile.unit_id,
        "current_topic": profile.current_topic,
        "current_concept_id": profile.current_concept_id,
        "current_phase": profile.current_phase,
        "concept_states": profile.concept_states,
        "conversation_history": profile.conversation_history,
        "current_tier": profile.current_tier,
        "stuckness_count": profile.stuckness_turn_count,
        "active_misconception_id": profile.active_misconception_id,
        "total_turns": len(profile.conversation_history),
        "concept_conversations": concept_memory.get_conversations(session_id),
        "quiz_attempts": quiz_service.attempts(session_id)
    }

@app.get("/api/teacher/concept-conversations/{session_id}")
def get_concept_conversations(session_id: str):
    """Return the learner's PostgreSQL-backed conversation threads by concept."""
    profile = learner_memory.get_profile(session_id) or LearnerProfile(session_id=session_id)
    return {
        "session_id": session_id,
        "current_concept_id": profile.current_concept_id,
        "current_topic": profile.current_topic,
        "conversations": concept_memory.get_conversations(session_id),
    }

@app.get("/api/teacher/report/{session_id}")
def download_teacher_report(session_id: str):
    """Generate a readable PDF evidence report for the current learner session."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        )
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF reporting requires the reportlab package.") from exc

    profile = learner_memory.get_profile(session_id) or LearnerProfile(session_id=session_id)
    buffer = BytesIO()
    teal = colors.HexColor("#0F766E")
    navy = colors.HexColor("#0F172A")
    slate = colors.HexColor("#475569")
    light = colors.HexColor("#F1F5F9")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=navy, spaceAfter=6))
    styles.add(ParagraphStyle(name="ReportSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=slate, spaceAfter=14))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=teal, spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=navy))
    styles.add(ParagraphStyle(name="MutedSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=slate))

    def safe(value):
        return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(slate)
        canvas.drawString(18 * mm, 9 * mm, "LearnAble Physics Tutor - Teacher Evidence Report")
        canvas.drawRightString(192 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=20 * mm,
        title="LearnAble Physics Tutor Teacher Evidence Report",
        author="LearnAble Physics Tutor",
    )
    story = [
        Paragraph("LearnAble Physics Tutor", styles["ReportTitle"]),
        Paragraph("Teacher Diagnostic and Evidence Report", styles["ReportSubtitle"]),
        Paragraph("Session overview", styles["Section"]),
    ]

    overview = [
        [Paragraph("Session ID", styles["MutedSmall"]), Paragraph(safe(profile.session_id), styles["BodySmall"]), Paragraph("Generated", styles["MutedSmall"]), Paragraph(safe(__import__("datetime").datetime.now().isoformat(timespec="seconds")), styles["BodySmall"])],
        [Paragraph("Unit", styles["MutedSmall"]), Paragraph(safe(profile.unit_id), styles["BodySmall"]), Paragraph("Current topic", styles["MutedSmall"]), Paragraph(safe(profile.current_topic or "Not selected"), styles["BodySmall"])],
        [Paragraph("Lesson phase", styles["MutedSmall"]), Paragraph(safe(profile.current_phase.value), styles["BodySmall"]), Paragraph("Intervention tier", styles["MutedSmall"]), Paragraph(safe(profile.current_tier.value), styles["BodySmall"])],
        [Paragraph("Total turns", styles["MutedSmall"]), Paragraph(str(len(profile.conversation_history)), styles["BodySmall"]), Paragraph("Stuckness count", styles["MutedSmall"]), Paragraph(str(profile.stuckness_turn_count), styles["BodySmall"])],
    ]
    overview_table = Table(overview, colWidths=[28 * mm, 62 * mm, 32 * mm, 58 * mm])
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), light), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(overview_table)

    story.append(Paragraph("Concept mastery", styles["Section"]))
    concepts = [[Paragraph("Concept", styles["MutedSmall"]), Paragraph("Mastery", styles["MutedSmall"]), Paragraph("Attempts", styles["MutedSmall"]), Paragraph("Status", styles["MutedSmall"]), Paragraph("Misconceptions", styles["MutedSmall"])]]
    for concept in profile.concept_states.values():
        status = "Verified" if concept.recovery_verified else "In progress"
        misconceptions = ", ".join(concept.misconceptions_logged) or "None logged"
        concepts.append([
            Paragraph(safe(concept.concept_name), styles["BodySmall"]),
            Paragraph(f"{round(concept.mastery_prob * 100)}%", styles["BodySmall"]),
            Paragraph(str(concept.total_attempts), styles["BodySmall"]),
            Paragraph(status, styles["BodySmall"]),
            Paragraph(safe(misconceptions), styles["BodySmall"]),
        ])
    mastery_table = Table(concepts, colWidths=[58 * mm, 22 * mm, 22 * mm, 25 * mm, 53 * mm], repeatRows=1)
    mastery_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, light]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(mastery_table)

    story.append(Paragraph("Evidence-backed audit log", styles["Section"]))
    if not profile.conversation_history:
        story.append(Paragraph("No learner interactions logged yet.", styles["MutedSmall"]))
    else:
        for index, turn in enumerate(profile.conversation_history, start=1):
            timestamp = safe(turn.get("timestamp", "Recent"))
            if turn.get("type") == "TEACHER_OVERRIDE" or turn.get("timestamp") == "TEACHER_OVERRIDE":
                story.append(Paragraph(f"Entry {index}  |  {timestamp}  |  teacher override", styles["MutedSmall"]))
                story.append(Paragraph(
                    f"<b>Teacher set mastery</b> of {safe(turn.get('concept_id'))} to {round(float(turn.get('new_mastery') or 0) * 100)}%: {safe(turn.get('teacher_note'))}",
                    styles["BodySmall"]))
                story.append(Spacer(1, 6))
                continue
            category = safe(turn.get("category", "insufficient_evidence"))
            if turn.get("graded") and (turn.get("reasoning_soundness") or 0) >= 0.85 and not turn.get("is_lucky_guess"):
                category = "sound reasoning"
            story.append(Paragraph(f"Turn {index}  |  {timestamp}  |  {category}", styles["MutedSmall"]))
            story.append(Paragraph(f"<b>Learner:</b> {safe(turn.get('user', ''))}", styles["BodySmall"]))
            story.append(Paragraph(f"<b>Evidence:</b> {safe(turn.get('evidence', ''))}", styles["BodySmall"]))
            if turn.get("is_lucky_guess"):
                story.append(Paragraph("Lucky-guess flag: correct answer arrived with flawed reasoning.", styles["MutedSmall"]))
            story.append(Spacer(1, 6))

    story.append(Paragraph("Report scope", styles["Section"]))
    story.append(Paragraph("This report contains observable learner submissions and diagnostic evidence. It does not include hidden chain-of-thought or private model reasoning.", styles["MutedSmall"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    filename = f"learnable-physics-evidence-{session_id}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

class TeacherOverrideRequest(BaseModel):
    session_id: str
    concept_id: str
    override_mastery_prob: float = Field(ge=0.0, le=1.0)
    teacher_note: str = ""

@app.post("/api/teacher/override")
def teacher_override(req: TeacherOverrideRequest):
    profile = learner_memory.get_profile(req.session_id)
    if profile and req.concept_id in profile.concept_states:
        profile.concept_states[req.concept_id].mastery_prob = req.override_mastery_prob
        profile.conversation_history.append({
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "type": "TEACHER_OVERRIDE",
            "teacher_note": req.teacher_note,
            "concept_id": req.concept_id,
            "new_mastery": req.override_mastery_prob
        })
        learner_memory.save_store()
        return {"status": "success", "profile": profile}
    raise HTTPException(status_code=404, detail="Concept not found")

@app.get("/api/stress-tests/run")
async def run_stress_tests():
    results = await StressTestRunner.run_all_tests()
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    zero_leak_count = sum(1 for r in results if r.zero_leakage_passed)
    
    return {
        "total_tests": total,
        "passed_tests": passed,
        "zero_leakage_rate": f"{(zero_leak_count/total)*100:.1f}%",
        "success_rate": f"{(passed/total)*100:.1f}%",
        "results": results
    }

@app.post("/api/web/grounding")
async def web_grounding_search(payload: Dict[str, str]):
    query = payload.get("query", "")
    doc_hits, snippets = await asyncio.gather(
        asyncio.to_thread(document_store.search, query),
        asyncio.to_thread(knowledge_engine.search_live_grounding, query),
    )
    if doc_hits:
        snippets = format_references(doc_hits, max_chars=2500) + "\n\n" + snippets
    return {"query": query, "grounding_snippets": snippets}


# ---------------------------------------------------------------- documents (RAG)
@app.get("/api/documents")
def list_documents():
    return {
        "documents": document_store.list_documents(),
        "storage": "postgresql" if document_store.uses_database else "local-file",
        "max_upload_mb": settings.MAX_UPLOAD_MB,
    }


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...), title: Optional[str] = Form(default=None)):
    limit = int(settings.MAX_UPLOAD_MB * 1024 * 1024)
    data = await file.read(limit + 1)
    try:
        doc = await asyncio.to_thread(document_store.add_document, file.filename or "upload.txt", data, title)
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"document": doc}


class PastedText(BaseModel):
    title: str = ""
    text: str


@app.post("/api/documents/text")
async def add_pasted_text(payload: PastedText):
    title = (payload.title or "").strip() or "Pasted notes"
    safe_name = re.sub(r"[^A-Za-z0-9_. -]+", "", title)[:80] or "notes"
    try:
        doc = await asyncio.to_thread(
            document_store.add_document, f"{safe_name}.txt", payload.text.encode("utf-8"), title
        )
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"document": doc}


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str):
    if not await asyncio.to_thread(document_store.delete_document, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}


@app.get("/api/documents/search")
async def search_documents(q: str = "", k: int = 5):
    hits = await asyncio.to_thread(document_store.search, q, max(1, min(k, 20)))
    return {"query": q, "results": hits}

