import logging
import uuid
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .models import (
    StudentInput, SocraticTurnResult, DiagnosticEvidence, DiagnosticCategory,
    InterventionTier, LearnerProfile, StressTestEvaluation, LessonPhase
)
from .audio_service import transcribe_audio_base64, synthesize_speech_base64
from .rag_engine import knowledge_engine
from .safety_guard import SafetyGuardrail
from .diagnostic_engine import DiagnosticEngine
from .socratic_policy import SocraticPolicyEngine
from .generator import SocraticGenerator
from .learner_memory import learner_memory
from .stress_test_runner import StressTestRunner

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

@app.post("/api/audio/synthesize")
async def synthesize_speech(payload: Dict[str, str]):
    text = payload.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="Missing text")
    audio_b64 = await synthesize_speech_base64(text)
    return {"audio_base64": audio_b64}

@app.post("/api/chat/turn", response_model=SocraticTurnResult)
async def process_student_turn(submission: StudentInput):
    session_id = submission.session_id or str(uuid.uuid4())
    user_text = submission.text or ""
    
    # 1. Voice STT if audio supplied
    if submission.audio_base64:
        stt_text = await transcribe_audio_base64(submission.audio_base64)
        if stt_text:
            user_text = stt_text
            
    if not user_text.strip():
        user_text = "I don't know"

    # 2. Layer 1: Adversarial Prompt Injection Guard
    is_attack, deflection_msg = SafetyGuardrail.detect_prompt_injection(user_text)
    if is_attack:
        audio_b64 = await synthesize_speech_base64(deflection_msg)
        return SocraticTurnResult(
            session_id=session_id,
            user_utterance=user_text,
            tutor_text=deflection_msg,
            audio_base64=audio_b64,
            lesson_phase=LessonPhase.GREETING,
            intervention_tier=InterventionTier.DIAGNOSTIC_PROBE,
            diagnostic=DiagnosticEvidence(
                category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
                affected_concept_id="security_guard",
                affected_concept_name="Prompt Injection Filter",
                confidence=1.0,
                evidence_quote=user_text,
                pedagogical_reason="Adversarial prompt injection attempt detected and neutralized. Socratic persona preserved.",
                reasoning_soundness_score=0.0
            ),
            leakage_check_passed=True,
            is_prompt_injection=True,
            is_out_of_scope=False
        )

    # 3. (Scope guard removed — FSM handles any STEM topic via classroom lifecycle)

    # 4. Retrieve persistent profile & conversation history
    profile = learner_memory.get_or_create_profile(session_id, submission.unit_id)

    # 5. Multi-Turn Cognitive Diagnostic Engine
    diagnostic = await DiagnosticEngine.diagnose_reasoning(
        student_text=user_text,
        challenge_id=submission.challenge_id,
        unit_id=submission.unit_id,
        conversation_history=profile.conversation_history
    )

    # 6. Socratic Policy Arbiter: Compute Next Lesson Step
    directive = SocraticPolicyEngine.determine_next_step(
        student_text=user_text,
        current_phase=profile.current_phase,
        current_topic=profile.current_topic,
        diagnostic=diagnostic,
        conversation_history=profile.conversation_history,
        stuckness_count=profile.stuckness_turn_count
    )

    # Update profile phase & topic
    profile.current_phase = directive.lesson_phase
    profile.current_topic = directive.topic

    # 7. Socratic Generator + Zero-Leakage Canary
    tutor_text = await SocraticGenerator.generate_response(
        directive=directive,
        student_text=user_text,
        conversation_history=profile.conversation_history
    )
    
    challenge = knowledge_engine.get_challenge(submission.challenge_id) or {}
    zero_leak_ok, sanitized_text = SafetyGuardrail.verify_zero_leakage(
        tutor_text,
        challenge.get("solution_redactions", [])
    )

    # 8. Transfer Question Check
    transfer_ready = (directive.lesson_phase == LessonPhase.TRANSFER_CHECK)
    transfer_q = challenge.get("transfer_question") if transfer_ready else None

    # 9. Update Persistent Learner Memory (with phase & topic)
    updated_profile = learner_memory.update_state(
        session_id=session_id,
        user_text=user_text,
        tutor_text=sanitized_text,
        diagnostic=diagnostic,
        tier=directive.tier,
        current_phase=directive.lesson_phase,
        current_topic=directive.topic
    )

    # 10. Voice TTS Output
    audio_b64 = await synthesize_speech_base64(sanitized_text)

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
        learner_mastery=mastery_map
    )

@app.get("/api/teacher/learner-state/{session_id}")
def get_teacher_view(session_id: str):
    profile = learner_memory.get_or_create_profile(session_id)
    return {
        "session_id": profile.session_id,
        "unit_id": profile.unit_id,
        "concept_states": profile.concept_states,
        "conversation_history": profile.conversation_history,
        "current_tier": profile.current_tier,
        "stuckness_count": profile.stuckness_turn_count,
        "active_misconception_id": profile.active_misconception_id,
        "total_turns": len(profile.conversation_history)
    }

class TeacherOverrideRequest(BaseModel):
    session_id: str
    concept_id: str
    override_mastery_prob: float
    teacher_note: str

@app.post("/api/teacher/override")
def teacher_override(req: TeacherOverrideRequest):
    profile = learner_memory.get_or_create_profile(req.session_id)
    if req.concept_id in profile.concept_states:
        profile.concept_states[req.concept_id].mastery_prob = req.override_mastery_prob
        profile.conversation_history.append({
            "timestamp": "TEACHER_OVERRIDE",
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
def web_grounding_search(payload: Dict[str, str]):
    query = payload.get("query", "")
    snippets = knowledge_engine.search_live_grounding(query)
    return {"query": query, "grounding_snippets": snippets}
