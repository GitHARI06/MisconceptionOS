import logging
import uuid
from io import BytesIO
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
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
from .postgres_memory import concept_memory
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
    requested_topic = SocraticPolicyEngine._extract_topic(user_text.lower(), profile.current_topic)
    requested_concept_id = SocraticPolicyEngine.concept_id_for_topic(requested_topic)
    concept_history = []
    active_concept_id = requested_concept_id or profile.current_concept_id
    if active_concept_id:
        concept_history = concept_memory.get_history(session_id, active_concept_id)
    context_history = concept_history or profile.conversation_history

    # 5. Multi-Turn Cognitive Diagnostic Engine
    diagnostic = await DiagnosticEngine.diagnose_reasoning(
        student_text=user_text,
        challenge_id=submission.challenge_id,
        unit_id=submission.unit_id,
        conversation_history=context_history
    )

    # 6. Socratic Policy Arbiter: Compute Next Lesson Step
    directive = SocraticPolicyEngine.determine_next_step(
        student_text=user_text,
        current_phase=profile.current_phase,
        current_topic=profile.current_topic,
        diagnostic=diagnostic,
        conversation_history=context_history,
        stuckness_count=profile.stuckness_turn_count
    )

    # Update profile phase & topic
    profile.current_phase = directive.lesson_phase
    profile.current_topic = directive.topic
    concept_id = SocraticPolicyEngine.concept_id_for_topic(directive.topic)
    profile.current_concept_id = concept_id

    # 7. Socratic Generator + Zero-Leakage Canary
    tutor_text = await SocraticGenerator.generate_response(
        directive=directive,
        student_text=user_text,
        conversation_history=context_history
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
        current_topic=directive.topic,
        concept_id=concept_id
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
        "current_topic": profile.current_topic,
        "current_concept_id": profile.current_concept_id,
        "current_phase": profile.current_phase,
        "concept_states": profile.concept_states,
        "conversation_history": profile.conversation_history,
        "current_tier": profile.current_tier,
        "stuckness_count": profile.stuckness_turn_count,
        "active_misconception_id": profile.active_misconception_id,
        "total_turns": len(profile.conversation_history),
        "concept_conversations": concept_memory.get_conversations(session_id)
    }

@app.get("/api/teacher/concept-conversations/{session_id}")
def get_concept_conversations(session_id: str):
    """Return the learner's PostgreSQL-backed conversation threads by concept."""
    profile = learner_memory.get_or_create_profile(session_id)
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

    profile = learner_memory.get_or_create_profile(session_id)
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
            category = safe(turn.get("category", "insufficient_evidence"))
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
