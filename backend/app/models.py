from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class LessonPhase(str, Enum):
    GREETING = "GREETING"                       # "Good morning, welcome to learning..."
    TOPIC_TEACHING = "TOPIC_TEACHING"           # Teacher introduction, definition, how it works
    DOUBT_CHECK = "DOUBT_CHECK"                 # Asking for doubts or clarifications
    RESOLVING_DOUBT = "RESOLVING_DOUBT"         # Answering doubt + asking "Did you understand?"
    SOCRATIC_CHALLENGE = "SOCRATIC_CHALLENGE"   # Testing understanding with a scenario problem
    SOCRATIC_SCAFFOLDING = "SOCRATIC_SCAFFOLDING"# Probing misconceptions, counter-examples, hints
    TRANSFER_CHECK = "TRANSFER_CHECK"           # Verifying conceptual recovery

class DiagnosticCategory(str, Enum):
    MISSING_PREREQUISITE = "missing_prerequisite"
    WRONG_RULE_DEFINITION = "wrong_rule_definition"
    PROCEDURAL_ERROR = "procedural_error"
    OVERGENERALIZATION = "overgeneralization"
    CALCULATION_SLIP = "calculation_slip"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

class InterventionTier(str, Enum):
    DIAGNOSTIC_PROBE = "DIAGNOSTIC_PROBE"
    COGNITIVE_CONFLICT = "COGNITIVE_CONFLICT"
    SCAFFOLDED_HINT = "SCAFFOLDED_HINT"
    CONCEPTUAL_EXPLANATION = "CONCEPTUAL_EXPLANATION"
    TRANSFER_VERIFICATION = "TRANSFER_VERIFICATION"

class StudentInput(BaseModel):
    session_id: str
    challenge_id: Optional[str] = "freeform_inquiry"
    unit_id: Optional[str] = "physics_mechanics"
    text: Optional[str] = None
    audio_base64: Optional[str] = None
    current_phase: Optional[LessonPhase] = None
    topic: Optional[str] = None

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    class_level: str

class LoginRequest(BaseModel):
    identity: str
    password: str

class DiagnosticEvidence(BaseModel):
    category: DiagnosticCategory
    affected_concept_id: str
    affected_concept_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_quote: str
    pedagogical_reason: str
    detected_misconception_id: Optional[str] = None
    reasoning_soundness_score: float = Field(ge=0.0, le=1.0)
    is_correct_answer_with_flawed_reasoning: bool = False

class SocraticDirective(BaseModel):
    tier: InterventionTier
    lesson_phase: LessonPhase
    topic: str
    pedagogical_goal: str
    allowed_information_scope: str
    forbidden_tokens: List[str] = []
    scaffold_step: int = 1
    counter_example_prompt: Optional[str] = None

class SocraticTurnResult(BaseModel):
    session_id: str
    user_utterance: str
    tutor_text: str
    audio_base64: Optional[str] = None
    lesson_phase: LessonPhase
    current_topic: Optional[str] = None
    intervention_tier: InterventionTier
    diagnostic: DiagnosticEvidence
    leakage_check_passed: bool
    is_prompt_injection: bool = False
    is_out_of_scope: bool = False
    transfer_ready: bool = False
    transfer_question: Optional[str] = None
    learner_mastery: Dict[str, float] = {}
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

class ConceptMastery(BaseModel):
    concept_id: str
    concept_name: str
    mastery_prob: float = 0.15
    total_attempts: int = 0
    correct_reasonings: int = 0
    misconceptions_logged: List[str] = []
    recovery_verified: bool = False

class LearnerProfile(BaseModel):
    session_id: str
    learner_name: str = "Student"
    unit_id: str = "physics_mechanics"
    current_topic: Optional[str] = None
    current_concept_id: Optional[str] = None
    current_phase: LessonPhase = LessonPhase.GREETING
    concept_states: Dict[str, ConceptMastery] = {}
    conversation_history: List[Dict[str, Any]] = []
    current_tier: InterventionTier = InterventionTier.DIAGNOSTIC_PROBE
    stuckness_turn_count: int = 0
    active_misconception_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class StressTestEvaluation(BaseModel):
    test_id: str
    test_name: str
    description: str
    user_input: str
    expected_diagnosis: str
    actual_diagnosis: str
    expected_tier: str
    actual_tier: str
    zero_leakage_passed: bool
    injection_deflected: bool
    passed: bool
    latency_ms: float
    feedback: str
