import logging
import re
from typing import Dict, Any, List, Optional
from .models import LessonPhase, InterventionTier, SocraticDirective, DiagnosticEvidence, DiagnosticCategory
from .rag_engine import knowledge_engine

logger = logging.getLogger("misconception_os.policy")

class SocraticPolicyEngine:
    # These aliases provide stable concept buckets while still allowing the
    # teacher to respond naturally to the learner's exact wording.
    TOPIC_ALIASES = (
        # Thermodynamics and thermal physics
        ("first law of thermodynamics", "Thermodynamics"),
        ("second law of thermodynamics", "Thermodynamics"),
        ("third law of thermodynamics", "Thermodynamics"),
        ("zeroth law of thermodynamics", "Thermodynamics"),
        ("heat engine", "Thermodynamics"),
        ("heat transfer", "Thermodynamics"),
        ("thermodynamic", "Thermodynamics"),
        ("thermochemistry", "Thermodynamics"),
        ("calorimetry", "Thermodynamics"),
        ("entropy", "Thermodynamics"),
        ("enthalpy", "Thermodynamics"),
        ("ideal gas", "Thermodynamics"),
        ("gas law", "Thermodynamics"),
        ("thermal", "Thermodynamics"),
        ("heat", "Thermodynamics"),
        ("temperature", "Thermodynamics"),
        ("simple harmonic", "Simple Harmonic Motion"),
        ("electromagnetic", "Electromagnetism"),
        ("quantum mechanics", "Quantum Physics"),
        ("relativistic mechanics", "Relativity"),
        ("statistical mechanics", "Thermodynamics"),
        # Mechanics and motion
        ("projectile", "Kinematics"),
        ("relative motion", "Kinematics"),
        ("displacement", "Kinematics"),
        ("velocity", "Kinematics"),
        ("acceleration", "Kinematics"),
        ("friction", "Newtonian Mechanics"),
        ("inertia", "Newtonian Mechanics"),
        ("gravitation", "Gravity and Free Fall"),
        ("newton", "Newtonian Mechanics"),
        ("mechanics", "Newtonian Mechanics"),
        ("kinematic", "Kinematics"),
        ("motion", "Motion"),
        ("dynamic", "Dynamics"),
        ("force", "Forces and Newton's Laws"),
        ("energy", "Energy and Work"),
        ("work", "Work and Energy"),
        ("momentum", "Momentum and Collisions"),
        ("impulse", "Impulse and Momentum"),
        ("circular", "Circular Motion"),
        ("rotation", "Rotational Motion"),
        ("torque", "Torque and Angular Momentum"),
        ("gravity", "Gravity and Free Fall"),
        ("freefall", "Gravity and Free Fall"),
        ("fluid", "Fluid Mechanics"),
        ("pressure", "Pressure and Fluids"),
        ("oscillation", "Oscillations"),
        ("wave", "Waves"),
        ("sound", "Sound Waves"),
        ("optics", "Optics"),
        ("light", "Light and Optics"),
        ("reflection", "Reflection of Light"),
        ("refraction", "Refraction of Light"),
        ("electric field", "Electric Fields"),
        ("electricity", "Electricity"),
        ("voltage", "Electric Potential and Voltage"),
        ("circuit", "Electric Circuits"),
        ("current", "Electric Current"),
        ("magnetism", "Magnetism"),
        ("magnetic", "Magnetic Fields"),
        ("semiconductor", "Semiconductors"),
        ("relativity", "Relativity"),
        ("quantum", "Quantum Physics"),
        ("atomic", "Atomic Physics"),
        ("nuclear", "Nuclear Physics"),
        ("particle", "Particle Physics"),
        ("astro", "Astrophysics"),
        ("space", "Astrophysics"),
    )

    @classmethod
    def canonical_topic(cls, topic: Optional[str]) -> Optional[str]:
        if not topic:
            return None
        normalized = topic.lower().strip()
        for marker, label in cls.TOPIC_ALIASES:
            if re.search(rf"\b{re.escape(marker)}", normalized):
                return label
        return topic.strip().title()

    @staticmethod
    def concept_id_for_topic(topic: Optional[str]) -> Optional[str]:
        canonical = SocraticPolicyEngine.canonical_topic(topic)
        if not canonical:
            return None
        concept_id = re.sub(r"[^a-z0-9]+", "_", canonical.lower()).strip("_")
        return concept_id[:120] or None

    @staticmethod
    def is_question(text_lower: str) -> bool:
        """True when the learner is asking rather than answering. Checks the
        start of the utterance so answers such as "however it moves, it needs
        a force" are still graded."""
        text_lower = text_lower.strip()
        if text_lower.endswith("?"):
            return True
        if re.match(r"^(what|why|how|when|where|which|who|is|are|does|do|can|could|would|should)\b(?!['’])(?!\s+not\b)", text_lower):
            return True
        return any(m in text_lower for m in ["can you explain", "could you explain", "difference between", "meaning of", "what does"])

    @staticmethod
    def _extract_topic(text_lower: str, current_topic: Optional[str] = None) -> Optional[str]:
        """Return a readable topic only when the learner actually supplied one."""
        for marker, label in SocraticPolicyEngine.TOPIC_ALIASES:
            # Word-start match: "waves" -> Waves, but "homework" is not Work.
            if re.search(rf"\b{re.escape(marker)}", text_lower):
                return label

        # Covers natural language such as “teach me integration” without
        # pretending that a greeting or a yes/no response is a topic.
        match = re.search(
            r"(?:learn|teach|study|explain|about|what(?:'s| is)|tell me about)\s+(?:me\s+)?(?:the\s+)?(.+?)(?:[?.!]|$)",
            text_lower,
        )
        if match:
            candidate = match.group(1).strip(" ,")
            ignored = {"something", "anything", "it", "this", "that", "more"}
            if candidate and candidate not in ignored and len(candidate) >= 2:
                return candidate.title()
        return current_topic

    @staticmethod
    def determine_next_step(
        student_text: str,
        current_phase: LessonPhase,
        current_topic: Optional[str],
        diagnostic: DiagnosticEvidence,
        conversation_history: List[Dict[str, Any]],
        stuckness_count: int
    ) -> SocraticDirective:
        text_lower = student_text.lower().strip()
        last_tutor_turn = conversation_history[-1]["tutor"].lower() if conversation_history else ""

        # A topic switch is valid at any point in a lesson. Resetting into
        # TOPIC_TEACHING prevents an old challenge from hijacking the new lesson.
        requested_topic = SocraticPolicyEngine._extract_topic(text_lower, current_topic)
        explicit_topic_request = (
            current_phase == LessonPhase.GREETING and requested_topic
        ) or any(k in text_lower for k in ["let's learn", "lets learn", "teach me", "want to learn", "study "])
        if explicit_topic_request and requested_topic:
            return SocraticDirective(
                tier=InterventionTier.CONCEPTUAL_EXPLANATION,
                lesson_phase=LessonPhase.TOPIC_TEACHING,
                topic=requested_topic,
                pedagogical_goal=f"Introduce {requested_topic} like an expert teacher: define it, explain how it works, give one intuitive example, and ask about doubts.",
                allowed_information_scope=f"Core principles and definitions of {requested_topic}.",
                forbidden_tokens=[]
            )

        # Friendly greetings and empty/ambiguous openings should keep the
        # learner at the front door instead of triggering a random lesson.
        greeting_words = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "start", "begin"}
        if current_phase == LessonPhase.GREETING and (not text_lower or text_lower in greeting_words):
            return SocraticDirective(
                tier=InterventionTier.DIAGNOSTIC_PROBE,
                lesson_phase=LessonPhase.GREETING,
                topic=current_topic or "",
                pedagogical_goal="Greet the learner and ask what they would like to learn today.",
                allowed_information_scope="Greeting only.",
                forbidden_tokens=[]
            )

        # =========================================================================
        # 1. TOPIC SELECTION / START PHASE
        # =========================================================================
        # If student mentions a topic ("let's learn thermodynamics", "teach me python", "newton laws")
        if current_phase == LessonPhase.GREETING:
            # Extract topic
            extracted_topic = requested_topic

            if not extracted_topic:
                return SocraticDirective(
                    tier=InterventionTier.DIAGNOSTIC_PROBE,
                    lesson_phase=LessonPhase.GREETING,
                    topic="",
                    pedagogical_goal="Ask the learner to name a topic or subject they want to learn.",
                    allowed_information_scope="Greeting and topic selection.",
                    forbidden_tokens=[]
                )

            return SocraticDirective(
                tier=InterventionTier.CONCEPTUAL_EXPLANATION,
                lesson_phase=LessonPhase.TOPIC_TEACHING,
                topic=extracted_topic,
                pedagogical_goal=f"Introduce {extracted_topic} like an expert teacher: give a clear overview, core definition, how it works, and ask if the student has any doubts or wants to test their understanding.",
                allowed_information_scope=f"Core principles and definitions of {extracted_topic}.",
                forbidden_tokens=[]
            )

        # =========================================================================
        # 2. DOUBT CHECK / CLARIFICATION PHASE
        # =========================================================================
        # Check if student says "no doubts", "i understand", "i'm ready", "let's test"
        no_doubts_keywords = ["no doubts", "no doubt", "no questions", "no question", "i have none", "nothing else", "i understand", "understood", "all clear", "i'm ready", "im ready", "let's test", "lets test", "ask me", "yes i got it", "yes i understand", "makes sense", "got it", "harder challenge", "another challenge", "challenge me", "test me", "quiz me"]
        has_no_doubts = any(k in text_lower for k in no_doubts_keywords)

        if current_phase in [LessonPhase.TOPIC_TEACHING, LessonPhase.DOUBT_CHECK, LessonPhase.RESOLVING_DOUBT]:
            if has_no_doubts:
                # Transition to Socratic Challenge
                topic_name = current_topic or "the topic"
                return SocraticDirective(
                    tier=InterventionTier.DIAGNOSTIC_PROBE,
                    lesson_phase=LessonPhase.SOCRATIC_CHALLENGE,
                    topic=topic_name,
                    pedagogical_goal=f"The student is ready! Present a thought-provoking, scenario-based Socratic challenge on {topic_name} to test their conceptual reasoning.",
                    allowed_information_scope=f"Scenario problem for {topic_name}.",
                    forbidden_tokens=[]
                )

            else:
                # Student has a doubt or question
                return SocraticDirective(
                    tier=InterventionTier.CONCEPTUAL_EXPLANATION,
                    lesson_phase=LessonPhase.RESOLVING_DOUBT,
                    topic=current_topic or "the topic",
                    pedagogical_goal="Answer the student's doubt with a clear explanation, then ask: 'Did that make sense / did you understand, or would you like another example?'",
                    allowed_information_scope="Clarification of the student's specific question.",
                    forbidden_tokens=[]
                )

        # A learner can ask for clarification during a challenge or after a
        # hint. Treat it as a doubt instead of incorrectly grading the question.
        if SocraticPolicyEngine.is_question(text_lower):
            return SocraticDirective(
                tier=InterventionTier.CONCEPTUAL_EXPLANATION,
                lesson_phase=LessonPhase.RESOLVING_DOUBT,
                topic=current_topic or "the topic",
                pedagogical_goal="Answer the learner's specific doubt clearly, then ask whether they understood or want another example.",
                allowed_information_scope="Clarification of the learner's specific question.",
                forbidden_tokens=[]
            )

        # =========================================================================
        # 3. SOCRATIC CHALLENGE & SCAFFOLDING PHASE
        # =========================================================================
        # Student says "I don't know"
        idk_keywords = ["don't know", "dont know", "no idea", "not sure", "confused", "sorry"]
        if any(k in text_lower for k in idk_keywords):
            return SocraticDirective(
                tier=InterventionTier.SCAFFOLDED_HINT,
                lesson_phase=LessonPhase.SOCRATIC_SCAFFOLDING,
                topic=current_topic or "the topic",
                pedagogical_goal="Respond empathetically without fake praise ('No worries at all!'). Break the problem into an intuitive, simple clue or sub-step.",
                allowed_information_scope="Sub-component hint.",
                forbidden_tokens=[]
            )

        sound = diagnostic.reasoning_soundness_score >= 0.85 and not diagnostic.is_correct_answer_with_flawed_reasoning

        # The learner has now solved the transfer problem as well: recovery is
        # verified. Close the loop instead of serving transfer problems forever.
        if sound and current_phase == LessonPhase.TRANSFER_CHECK:
            topic_name = current_topic or "the topic"
            return SocraticDirective(
                tier=InterventionTier.CONCEPTUAL_EXPLANATION,
                lesson_phase=LessonPhase.DOUBT_CHECK,
                topic=topic_name,
                pedagogical_goal=f"The learner solved the transfer problem, so their understanding of {topic_name} is verified. Congratulate them specifically, summarise the principle in one sentence, and ask whether they want a harder challenge or a new topic.",
                allowed_information_scope="Summary of the verified principle.",
                forbidden_tokens=[]
            )

        # Student's reasoning is sound (> 0.85)
        if sound:
            return SocraticDirective(
                tier=InterventionTier.TRANSFER_VERIFICATION,
                lesson_phase=LessonPhase.TRANSFER_CHECK,
                topic=current_topic or "the topic",
                pedagogical_goal="Affirm the student's insight enthusiastically ('Spot on!'), explain why it works in 1 sentence, and present a fresh transfer problem to verify true conceptual mastery.",
                allowed_information_scope="Affirmation and isomorphic transfer problem.",
                forbidden_tokens=[]
            )

        # Student has a misconception (Wrong Rule / Overgeneralization)
        # Anti-Looping: if stuck >= 2, escalate to clear decomposition
        if stuckness_count >= 2:
            return SocraticDirective(
                tier=InterventionTier.CONCEPTUAL_EXPLANATION,
                lesson_phase=LessonPhase.SOCRATIC_SCAFFOLDING,
                topic=current_topic or "the topic",
                pedagogical_goal="Student is stuck after multiple hints. Escalate to a clear conceptual decomposition. Do not repeat previous questions.",
                allowed_information_scope="Foundational concept clarification.",
                forbidden_tokens=[]
            )
        else:
            return SocraticDirective(
                tier=InterventionTier.COGNITIVE_CONFLICT,
                lesson_phase=LessonPhase.SOCRATIC_SCAFFOLDING,
                topic=current_topic or "the topic",
                pedagogical_goal="Student made a misconception. Do NOT reveal the solution directly. Present a vivid thought experiment or counter-example to challenge their mental model.",
                allowed_information_scope="Counter-example and guiding question.",
                forbidden_tokens=[]
            )
