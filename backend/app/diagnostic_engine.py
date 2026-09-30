import asyncio
import json
import logging
import re
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

# Reasoning patterns used by the offline heuristic. Whole-word regexes are
# used on purpose: substring checks such as `"1" in text` used to grade
# "a force of 12 N" as a correct First-Law answer.
NEGATION = r"\b(no|not|never|zero|without|doesn'?t|don'?t|isn'?t|won'?t|needn'?t)\b"
SOUND_INERTIA = re.compile(
    r"\b(net\s+)?force\s+(is|must\s+be|should\s+be|=|equals|would\s+be)\s+(0|zero|none)\b"
    r"|\bzero\s+(net\s+)?force\b|\bno\s+(net\s+|external\s+|forward\s+|extra\s+)?force\b"
    r"|\b(doesn'?t|does\s+not|don'?t|do\s+not)\s+(need|require)\s+(a\s+|any\s+)?(net\s+|forward\s+|continuous\s+)?force\b"
    r"|\binertia\b|\b(first|1st)\s+law\b|\bacceleration\s+(is\s+)?(0|zero)\b|\b0\s*n\b"
)
SUSTAINING_FORCE_MISCONCEPTION = re.compile(
    r"\b(needs?|must|requires?|have\s+to|has\s+to|keep|keeps|pushing|push)\b.{0,40}\b(force|push|newtons?|\d+\s*n)\b"
    r"|\b(force|push)\b.{0,40}\b(or\s+it\s+(will\s+)?(stop|slow)|to\s+keep|keeps?\s+it)\b"
)
IDK = re.compile(r"\b(i\s+)?(don'?t|do\s+not)\s+know\b|\bno\s+idea\b|\bnot\s+sure\b|\bconfused\b|\bhaven'?t\s+learned\b")


def _evidence(category, concept_id, concept_name, confidence, quote, reason, misconception=None, soundness=0.6, lucky=False):
    return DiagnosticEvidence(
        category=category, affected_concept_id=concept_id, affected_concept_name=concept_name,
        confidence=confidence, evidence_quote=quote, pedagogical_reason=reason,
        detected_misconception_id=misconception, reasoning_soundness_score=soundness,
        is_correct_answer_with_flawed_reasoning=lucky,
    )


def _clamp(value, default):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class DiagnosticEngine:
    @staticmethod
    def _multi_turn_heuristic(student_text: str, conversation_history: List[Dict[str, Any]]) -> DiagnosticEvidence:
        text_lower = student_text.lower().strip()
        last_tutor_turn = conversation_history[-1]["tutor"].lower() if conversation_history else ""

        # Correct outcome + incorrect causal explanation: explicitly retain
        # the lucky-guess flag so mastery cannot be granted from the matching
        # final answer alone.
        if (
            ("same time" in text_lower or "at the same time" in text_lower)
            and any(marker in text_lower for marker in ["round", "spherical", "size doesn't", "size does not"])
        ):
            return DiagnosticEvidence(
                category=DiagnosticCategory.OVERGENERALIZATION,
                affected_concept_id="gravitational_acceleration_freefall",
                affected_concept_name="Gravitational Acceleration in Vacuum",
                confidence=0.98,
                evidence_quote=student_text,
                pedagogical_reason="The learner reached the correct equal-arrival conclusion but attributed it to shape or size instead of shared gravitational acceleration and the cancellation of mass in a = F/m.",
                detected_misconception_id="PHYS_MISC_02",
                reasoning_soundness_score=0.15,
                is_correct_answer_with_flawed_reasoning=True,
            )

        if IDK.search(text_lower):
            return _evidence(DiagnosticCategory.INSUFFICIENT_EVIDENCE, "general_inquiry", "General Topic Dialogue", 0.9,
                             student_text, "Learner expressed uncertainty rather than a misconception; more evidence is needed.",
                             soundness=0.3)

        # Thermodynamics challenge: can room heat spontaneously re-boil the coffee?
        if any(k in last_tutor_turn for k in ["coffee", "boil", "refrigerator"]):
            if "refrigerator" in last_tutor_turn and re.search(r"\b(work|compressor|electric|energy\s+input|external|pump)", text_lower):
                return _evidence(DiagnosticCategory.INSUFFICIENT_EVIDENCE, "thermodynamics_second_law", "Second Law of Thermodynamics",
                                 0.9, student_text, "Learner recognised that moving heat from cold to hot requires external work.", soundness=0.92)
            if re.search(r"\b(no|cannot|can'?t|won'?t|impossible|never)\b|second\s+law|entropy", text_lower):
                return _evidence(DiagnosticCategory.INSUFFICIENT_EVIDENCE, "thermodynamics_second_law", "Second Law of Thermodynamics",
                                 0.9, student_text, "Learner correctly stated that heat does not flow spontaneously from cold to hot.", soundness=0.92)
            if re.search(r"\b(yes|can|will|could)\b", text_lower):
                return _evidence(DiagnosticCategory.WRONG_RULE_DEFINITION, "thermodynamics_second_law", "Second Law of Thermodynamics",
                                 0.85, student_text, "Learner believes heat can flow spontaneously from a colder to a hotter body.",
                                 misconception="PHYS_MISC_HEAT_FLOW", soundness=0.2)

        # Transfer question about a probe coasting in deep space.
        if any(k in last_tutor_turn for k in ["voyager", "space probe", "deep space", "spacecraft"]):
            if re.search(r"\b(stays?\s+the\s+same|doesn'?t\s+change|does\s+not\s+change|constant|no\s+change|same\s+speed|keeps?\s+(its|the\s+same)\s+(speed|velocity))\b", text_lower) or SOUND_INERTIA.search(text_lower):
                return _evidence(DiagnosticCategory.INSUFFICIENT_EVIDENCE, "newton_first_law_inertia", "Newton's 1st Law (Inertia)",
                                 0.94, student_text, "Learner applied the First Law: with no net force the velocity stays constant.", soundness=0.95)
            if re.search(r"\b(second|2nd|third|3rd)\s+law\b|\bslows?\s+down\b|\bstops?\b", text_lower):
                return _evidence(DiagnosticCategory.WRONG_RULE_DEFINITION, "newton_first_law_inertia", "Newton's 1st Law (Inertia)",
                                 0.9, student_text, "Learner expects the probe to slow down or misidentified the governing law.",
                                 misconception="PHYS_MISC_01", soundness=0.2)

        # Freefall in vacuum / moon drop
        if "moon" in last_tutor_turn or "feather" in last_tutor_turn or "hammer" in last_tutor_turn:
            if re.search(r"\b(same|together|equal|simultaneous)", text_lower):
                return _evidence(DiagnosticCategory.INSUFFICIENT_EVIDENCE, "gravitational_acceleration_freefall", "Gravitational Acceleration in Vacuum",
                                 0.95, student_text, "Student correctly concluded that all masses accelerate identically in a vacuum (a = g).", soundness=0.95)

        # Constant-velocity / inertia reasoning (the puck challenge). Sound
        # reasoning is checked first so "no force is needed" is not mistaken
        # for the sustaining-force misconception.
        if SOUND_INERTIA.search(text_lower) and not re.search(r"\b(second|2nd|third|3rd)\s+law\b", text_lower):
            return _evidence(DiagnosticCategory.INSUFFICIENT_EVIDENCE, "newton_first_law_inertia", "Newton's 1st Law (Inertia)",
                             0.93, student_text, "Learner explained constant velocity with zero net force (inertia).", soundness=0.95)
        if SUSTAINING_FORCE_MISCONCEPTION.search(text_lower):
            return _evidence(DiagnosticCategory.WRONG_RULE_DEFINITION, "newton_first_law_inertia", "Newton's 1st Law (Inertia)",
                             0.9, student_text, "Learner believes a continuous force is needed to keep an object moving at constant velocity.",
                             misconception="PHYS_MISC_01", soundness=0.2)
        if re.search(r"\b(second|2nd|third|3rd)\s+law\b", text_lower) and any(k in last_tutor_turn for k in ["which law", "gliding", "puck", "frictionless"]):
            return _evidence(DiagnosticCategory.WRONG_RULE_DEFINITION, "newton_first_law_inertia", "Newton's 1st Law (Inertia)",
                             0.9, student_text, "Student misidentified the governing law for constant velocity.",
                             misconception="PHYS_MISC_01", soundness=0.2)

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
        high_confidence_case = cls._multi_turn_heuristic(student_text, conversation_history)
        if high_confidence_case.is_correct_answer_with_flawed_reasoning:
            return high_confidence_case
        context_str = ""
        for turn in conversation_history[-3:]:
            context_str += f"Tutor: {turn.get('tutor', '')}\nStudent: {turn.get('user', '')}\n"

        try:
            prompt = MULTI_TURN_DIAGNOSTIC_PROMPT.format(
                dialogue_context=context_str if context_str else "Beginning of dialogue session.",
                student_text=student_text
            )
            # requests is blocking: run it in a worker thread so a slow model
            # never freezes the event loop (and every other learner) with it.
            res = await asyncio.to_thread(
                requests.post,
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1}
                },
                timeout=8.0
            )
            if res.status_code == 200:
                body = res.json()
                parsed = json.loads(body.get("response", "{}"))
                if not isinstance(parsed, dict):
                    raise ValueError("diagnosis was not a JSON object")
                try:
                    category = DiagnosticCategory(str(parsed.get("category", "")).strip().lower())
                except ValueError:
                    category = DiagnosticCategory.INSUFFICIENT_EVIDENCE
                llm_result = DiagnosticEvidence(
                    category=category,
                    affected_concept_id=str(parsed.get("affected_concept_id") or "general_inquiry"),
                    affected_concept_name=str(parsed.get("affected_concept_name") or "General Topic Dialogue"),
                    confidence=_clamp(parsed.get("confidence"), 0.7),
                    evidence_quote=str(parsed.get("evidence_quote") or student_text),
                    pedagogical_reason=str(parsed.get("pedagogical_reason") or "Diagnostic inference with dialogue context."),
                    detected_misconception_id=parsed.get("detected_misconception_id") or None,
                    reasoning_soundness_score=_clamp(parsed.get("reasoning_soundness_score"), 0.5),
                    is_correct_answer_with_flawed_reasoning=bool(parsed.get("is_correct_answer_with_flawed_reasoning", False))
                )
                # A small local model can be over-generous. Never let it award
                # mastery for an answer that states the known sustaining-force
                # misconception without also stating the correct principle.
                if (llm_result.reasoning_soundness_score >= 0.85
                        and SUSTAINING_FORCE_MISCONCEPTION.search(student_text.lower())
                        and not SOUND_INERTIA.search(student_text.lower())):
                    return high_confidence_case if high_confidence_case.reasoning_soundness_score < 0.85 else llm_result
                return llm_result
        except Exception as e:
            logger.info(f"Multi-turn LLM diagnosis fallback: {e}")

        return cls._multi_turn_heuristic(student_text, conversation_history)
