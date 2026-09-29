import json
import logging
import requests
from typing import Dict, Any, Optional, List
from .models import DiagnosticCategory, DiagnosticEvidence
from .rag_engine import knowledge_engine
from .config import settings

logger = logging.getLogger("misconception_os.diagnostic")

MULTI_TURN_DIAGNOSTIC_PROMPT = """You are an expert Cognitive Diagnostic Engine for Science and Mathematics Education.
Analyze the student's latest utterance in the context of the ongoing multi-turn Socratic tutoring dialogue.

Previous Dialogue Context:
{dialogue_context}

Student's Latest Response:
"{student_text}"

Task:
1. Determine if the student is answering the tutor's previous question or asking a brand-new question.
2. If answering the tutor's question, evaluate whether their answer and reasoning are conceptually sound:
   - If they correctly answered (e.g. "first law" or "inertia" for constant motion in space): set category to `insufficient_evidence` (or sound mastery), `reasoning_soundness_score` to 0.95.
   - If they made a cognitive error or misconception (e.g. "third law", "needs force"): classify into `wrong_rule_definition`, `overgeneralization`, `missing_prerequisite`, `procedural_error`, or `calculation_slip`.
3. Provide concise, teacher-readable evidence of their cognitive learning state.

Respond in STRICT JSON:
{{
  "category": "insufficient_evidence | wrong_rule_definition | overgeneralization | missing_prerequisite | procedural_error | calculation_slip",
  "affected_concept_id": "concept_id",
  "affected_concept_name": "Concept Name",
  "confidence": 0.90,
  "evidence_quote": "exact phrase from student",
  "pedagogical_reason": "concise teacher-readable evidence of their reasoning",
  "detected_misconception_id": null,
  "reasoning_soundness_score": 0.9,
  "is_correct_answer_with_flawed_reasoning": false
}}
"""

class DiagnosticEngine:
    @staticmethod
    def _multi_turn_heuristic(student_text: str, conversation_history: List[Dict[str, Any]]) -> DiagnosticEvidence:
        text_lower = student_text.lower().strip()
        last_tutor_turn = conversation_history[-1]["tutor"].lower() if conversation_history else ""

        # Context Check: Did tutor ask about deep space probe / inertia?
        if "spacecraft" in last_tutor_turn or "gliding" in last_tutor_turn or "voyager" in last_tutor_turn or "which law" in last_tutor_turn:
            if "first" in text_lower or "1st" in text_lower or "inertia" in text_lower or "1" in text_lower:
                return DiagnosticEvidence(
                    category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
                    affected_concept_id="newton_first_law_inertia",
                    affected_concept_name="Newton's 1st Law (Inertia)",
                    confidence=0.96,
                    evidence_quote=student_text,
                    pedagogical_reason="Student correctly applied Newton's First Law (Inertia) to explain constant velocity with zero net force in deep space.",
                    detected_misconception_id=None,
                    reasoning_soundness_score=0.95,
                    is_correct_answer_with_flawed_reasoning=False
                )
            elif "second" in text_lower or "2nd" in text_lower or "third" in text_lower or "3rd" in text_lower:
                return DiagnosticEvidence(
                    category=DiagnosticCategory.WRONG_RULE_DEFINITION,
                    affected_concept_id="newton_first_law_inertia",
                    affected_concept_name="Newton's 1st Law (Inertia)",
                    confidence=0.90,
                    evidence_quote=student_text,
                    pedagogical_reason="Student misidentified the governing law for constant velocity in deep space.",
                    detected_misconception_id="PHYS_MISC_01",
                    reasoning_soundness_score=0.2,
                    is_correct_answer_with_flawed_reasoning=False
                )

        # Context Check: Freefall in vacuum / moon drop
        if "moon" in last_tutor_turn or "feather" in last_tutor_turn or "hammer" in last_tutor_turn:
            if "same" in text_lower or "together" in text_lower or "equal" in text_lower:
                return DiagnosticEvidence(
                    category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
                    affected_concept_id="gravitational_acceleration_freefall",
                    affected_concept_name="Gravitational Acceleration in Vacuum",
                    confidence=0.95,
                    evidence_quote=student_text,
                    pedagogical_reason="Student correctly concluded that all masses accelerate identically in a vacuum (a = g).",
                    detected_misconception_id=None,
                    reasoning_soundness_score=0.95,
                    is_correct_answer_with_flawed_reasoning=False
                )

        # General inquiry heuristic
        if "three laws" in text_lower or "3 laws" in text_lower:
            return DiagnosticEvidence(
                category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
                affected_concept_id="newton_laws_overview",
                affected_concept_name="Newton's Laws of Motion",
                confidence=0.90,
                evidence_quote=student_text,
                pedagogical_reason="Student requested foundational explanation of Newton's 3 Laws.",
                detected_misconception_id=None,
                reasoning_soundness_score=0.5,
                is_correct_answer_with_flawed_reasoning=False
            )

        return DiagnosticEvidence(
            category=DiagnosticCategory.INSUFFICIENT_EVIDENCE,
            affected_concept_id="general_inquiry",
            affected_concept_name="General Topic Dialogue",
            confidence=0.80,
            evidence_quote=student_text,
            pedagogical_reason="Student provided conversational reasoning.",
            detected_misconception_id=None,
            reasoning_soundness_score=0.6,
            is_correct_answer_with_flawed_reasoning=False
        )

    @classmethod
    async def diagnose_reasoning(
        cls,
        student_text: str,
        challenge_id: Optional[str] = None,
        unit_id: str = "physics_mechanics",
        conversation_history: List[Dict[str, Any]] = []
    ) -> DiagnosticEvidence:
        """Multi-turn cognitive diagnosis maintaining full dialogue context."""
        context_str = ""
        for turn in conversation_history[-3:]:
            context_str += f"Tutor: {turn.get('tutor', '')}\nStudent: {turn.get('user', '')}\n"

        try:
            prompt = MULTI_TURN_DIAGNOSTIC_PROMPT.format(
                dialogue_context=context_str if context_str else "Beginning of dialogue session.",
                student_text=student_text
            )
            res = requests.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1}
                },
                timeout=5.0
            )
            if res.status_code == 200:
                body = res.json()
                parsed = json.loads(body.get("response", "{}"))
                return DiagnosticEvidence(
                    category=DiagnosticCategory(parsed.get("category", "insufficient_evidence")),
                    affected_concept_id=parsed.get("affected_concept_id", "newton_first_law_inertia"),
                    affected_concept_name=parsed.get("affected_concept_name", "Newtonian Mechanics"),
                    confidence=float(parsed.get("confidence", 0.90)),
                    evidence_quote=parsed.get("evidence_quote", student_text),
                    pedagogical_reason=parsed.get("pedagogical_reason", "Diagnostic inference with dialogue context."),
                    detected_misconception_id=parsed.get("detected_misconception_id"),
                    reasoning_soundness_score=float(parsed.get("reasoning_soundness_score", 0.8)),
                    is_correct_answer_with_flawed_reasoning=bool(parsed.get("is_correct_answer_with_flawed_reasoning", False))
                )
        except Exception as e:
            logger.info(f"Multi-turn LLM diagnosis fallback: {e}")

        return cls._multi_turn_heuristic(student_text, conversation_history)
