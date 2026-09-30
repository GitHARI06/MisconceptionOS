import asyncio
import json
import logging
import re
import requests
from typing import Dict, Any, Optional, List
from .models import SocraticDirective, InterventionTier, LessonPhase
from .safety_guard import SafetyGuardrail
from .config import settings

logger = logging.getLogger("misconception_os.generator")

CLASSROOM_PROMPT = """You are MisconceptionOS, an expert, warm, adaptive Physics Teacher.

Current Lesson Phase: {lesson_phase}
Current Topic: {topic}
Pedagogical Directive: {pedagogical_goal}

Recent Dialogue History:
{dialogue_context}

Student's Latest Response:
"{student_text}"
{reference_block}
Guidelines by Phase:
1. IF `TOPIC_TEACHING`:
   - Infer the exact physics concept the learner requested, even if it is not a named topic in a curriculum list.
   - Teach it like a master teacher: give an intuitive explanation, precise definition, governing principles, assumptions, and one concrete example.
   - Connect it to the learner's apparent level. Do not dump a memorized topic template.
2. IF `RESOLVING_DOUBT`:
   - Answer the exact question in the latest student message first. Use prior turns when the latest message is short or refers to “that”, “why”, or “another example”.
   - Correct misunderstandings gently, distinguish related laws, and use an equation or analogy only when it helps.
   - End with one natural check-for-understanding or a targeted follow-up question, varying the wording.
3. IF `SOCRATIC_CHALLENGE`:
   - Present ONE vivid, thought-provoking scenario challenge to test their conceptual reasoning.
4. IF `SOCRATIC_SCAFFOLDING`:
   - If they say "I don't know" or express confusion: Respond warmly ("No worries at all!"), break it down into an easy clue.
   - If they have a misconception: Present a counter-example thought experiment to challenge their mental model (never give the raw answer).
5. IF `TRANSFER_CHECK`:
   - Celebrate their correct insight ("Spot on! Exactly right!"), explain WHY, and present a fresh isomorphic scenario.

Tone: Warm, conversational, intellectually stimulating (under 3-4 sentences).
{style_block}

Conversation-quality rules:
- Answer the student's exact latest question first; do not substitute a generic topic summary.
- Use the recent dialogue to resolve short follow-ups such as "why?", "how?", or "another example?".
- If the student asks for another example, give a genuinely different, concrete example than the previous one.
- Vary wording naturally. Never repeat a previous tutor response verbatim or use filler such as "identify the physical quantities involved" unless it directly answers the question.
- Stay within physics, explain uncertainty honestly, and ask one useful follow-up question.
- When reference material from the learner's uploaded documents is provided, ground your explanation in it and mention the source in brackets, e.g. [Lecture notes, p.3]. If it does not cover the question, rely on your own physics knowledge and do not invent citations.
- While the learner is working on a challenge, use the reference material for hints only; never quote a final answer from it.
- Physics is broad: reason about mechanics, thermodynamics, fluids, waves, optics, electricity, magnetism, relativity, quantum, atomic, nuclear, astrophysics, and unfamiliar subtopics.

Generate your teacher response:"""

class SocraticGenerator:
    @staticmethod
    def _deterministic_response(
        directive: SocraticDirective,
        student_text: str,
        conversation_history: List[Dict[str, Any]],
        reference_hits: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        text_lower = student_text.lower().strip()
        topic_lower = directive.topic.lower()
        last_tutor_turn = conversation_history[-1]["tutor"].lower() if conversation_history else ""
        last_student_turn = conversation_history[-1]["user"].lower() if conversation_history else ""
        recent_student_context = " ".join(
            str(turn.get("user", "")).lower() for turn in conversation_history[-3:]
        )

        if directive.lesson_phase == LessonPhase.GREETING:
            return "Good morning, welcome to learning. What shall we learn today?"

        # Offline, the learner's own notes are the best explanation we have
        # for teaching and doubt turns.
        if reference_hits and directive.lesson_phase in (LessonPhase.TOPIC_TEACHING, LessonPhase.RESOLVING_DOUBT):
            hit = reference_hits[0]
            sentences = re.split(r"(?<=[.!?])\s+", hit["text"].strip())
            excerpt = " ".join(sentences[:3]).strip()
            if len(excerpt) > 420:
                excerpt = excerpt[:420].rsplit(" ", 1)[0] + "…"
            closing = (
                "Do you have any doubts about this, or are you ready to test your understanding?"
                if directive.lesson_phase == LessonPhase.TOPIC_TEACHING
                else "Did that answer your question, or would you like another example?"
            )
            return f"Here is what your material says [{hit['title']}, p.{hit['page']}]: {excerpt}\n\n{closing}"

        # Phase 1: TOPIC TEACHING
        if directive.lesson_phase == LessonPhase.TOPIC_TEACHING:
            if "thermodynamics" in topic_lower or "thermodynamics" in text_lower:
                return (
                    "Thermodynamics is the branch of physics that studies heat, work, temperature, and energy transformations. "
                    "It is governed by foundational laws: the First Law (Conservation of Energy) and the Second Law (heat naturally flows from hotter to colder bodies, and entropy always increases). "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding with a challenge?"
                )
            elif any(term in topic_lower for term in ["kinematics", "motion"]):
                return (
                    "Kinematics describes how objects move without focusing on what causes that motion. "
                    "We use position, displacement, velocity, acceleration, and time to describe motion, often with relationships such as \\(v = u + at\\). "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["dynamics", "force", "newton"]):
                return (
                    "Dynamics studies how forces change an object's motion. Newton's laws connect force, mass, and acceleration: the net force determines acceleration, while balanced forces produce no acceleration. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["energy", "work"]):
                return (
                    "Work and energy describe how motion changes and how physical systems transfer or store the ability to do work. "
                    "Work transfers energy through a force acting over a distance, and conservation of energy lets us track those changes from one form to another. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["momentum", "impulse", "collision"]):
                return (
                    "Momentum measures an object's quantity of motion as mass multiplied by velocity, while impulse describes how a force changes momentum over time. "
                    "In an isolated system, total momentum is conserved, which makes collisions easier to analyze. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["wave", "sound", "oscillation"]):
                return (
                    "Waves are repeating disturbances that transfer energy and information, while the medium or field oscillates around equilibrium. "
                    "We will connect amplitude, wavelength, frequency, and speed, and use them to explain phenomena such as sound, resonance, and interference. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["optic", "light", "reflection", "refraction"]):
                return (
                    "Optics studies light and how it travels, reflects, refracts, and forms images. "
                    "We will use ray models and wave ideas to explain mirrors, lenses, color, and the bending of light between materials. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["electric", "circuit", "voltage", "current", "magnet"]):
                return (
                    "Electricity and magnetism describe how charges, fields, currents, and potentials interact. "
                    "We will build the idea from charge and electric fields, then connect voltage, current, resistance, circuits, and magnetic effects. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif any(term in topic_lower for term in ["quantum", "relativity", "atomic", "nuclear", "particle", "astrophysics"]):
                return (
                    f"{directive.topic} explores physical systems where the usual everyday model needs a deeper framework. "
                    "We will start with the central idea and its assumptions, define the important quantities, and connect the theory to an observable example. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )
            elif "newton" in topic_lower or "mechanics" in topic_lower or "motion" in text_lower:
                return (
                    "Newtonian Mechanics is the foundational physics of how forces cause objects to move and accelerate. "
                    "It is built upon three laws: 1. **Inertia** (constant velocity unless a net force acts), 2. **\\(F = ma\\)** (force causes acceleration), and 3. **Action-Reaction** (forces occur in equal and opposite pairs). "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding with a scenario?"
                )
            elif "recursion" in topic_lower or "algorithm" in text_lower:
                return (
                    "Recursion is a programming technique where a function calls itself to solve smaller instances of the same problem. "
                    "It relies on two essential parts: a **Base Case** (to halt further calls) and a **Recursive Step** (which pushes execution frames onto the call stack and unwinds when returning). "
                    "\n\nDo you have any doubts or questions on this, or are you ready for a problem?"
                )
            else:
                return (
                    f"{directive.topic} is the systematic study of its key ideas, relationships, and applications. "
                    f"We will begin with the definition, see how the main principles work, and connect them to a simple real-world example. "
                    "\n\nDo you have any doubts or questions on this, or are you ready to test your understanding?"
                )

        # Phase 2: RESOLVING DOUBT
        if directive.lesson_phase == LessonPhase.RESOLVING_DOUBT:
            # Keep the subject of a follow-up request such as “another
            # example?” from being lost when the latest message is short.
            doubt_context = f"{recent_student_context} {text_lower}"

            if any(term in doubt_context for term in [
                "conservation of energy", "law of conservation", "energy cannot be created",
                "energy can't be created", "energy can neither be created"
            ]):
                if "example" in text_lower or "another" in text_lower:
                    return (
                        "Here is another example: when a roller coaster descends, gravitational potential energy decreases while kinetic energy increases. "
                        "Ignoring friction, the total energy stays constant—the energy changes form rather than disappearing. "
                        "Can you identify where the energy goes when the coaster climbs the next hill?"
                    )
                return (
                    "The law of conservation of energy says that energy cannot be created or destroyed; it can only be transferred or transformed. "
                    "For example, a battery changes chemical energy into electrical energy, which can become light, heat, or motion. "
                    "Did that make sense, or would you like another example?"
                )

            if any(term in doubt_context for term in ["first law", "second law", "third law", "newton"]):
                if "example" in text_lower or "another" in text_lower:
                    return (
                        "Here is another example: when you push a shopping cart, your force on the cart is paired with an equal and opposite force from the cart on you. "
                        "That pair is Newton's Third Law, while the cart's acceleration is described by the net force in Newton's Second Law. "
                        "Which law would you use to explain why the cart speeds up?"
                    )

            if "entropy" in text_lower:
                return (
                    "Entropy is a measure of the disorder or randomness in a physical system. According to the Second Law of Thermodynamics, "
                    "in any spontaneous process, the total entropy of the universe always increases, meaning heat naturally disperses and cannot spontaneously concentrate without external work. "
                    "\n\nDid that make sense and did you understand, or would you like another example?"
                )
            elif "heat" in text_lower or "flow" in text_lower:
                return (
                    "Heat is thermal energy in transit. It flows spontaneously from a higher temperature body to a lower temperature body because molecules with higher kinetic energy collide with and transfer energy to slower molecules. "
                    "\n\nDid that make sense and did you understand, or would you like another example?"
                )
            elif any(term in text_lower for term in ["which physical law", "what law", "which law"]):
                if any(term in doubt_context for term in ["energy", "conservation", "battery", "roller coaster"]):
                    return (
                        "The law you are looking for is the First Law of Thermodynamics, which is the conservation of energy. "
                        "It explains that the change in a system's internal energy equals energy transferred in as heat minus energy transferred out as work: \\(\\Delta U = Q - W\\). "
                        "Would you like to apply that relationship to a gas, a battery, or a mechanical system?"
                    )
                if any(term in doubt_context for term in ["motion", "force", "acceleration", "dynamics"]):
                    return (
                        "For a change in motion caused by a net force, Newton's Second Law is the relevant law: \\(F_{net} = ma\\). "
                        "It says the acceleration points in the direction of the net force and grows when the force increases or the mass decreases. "
                        "Can you tell me which force is unbalanced in the situation you have in mind?"
                    )
            elif any(k in text_lower for k in ["example", "another", "differently", "don't get", "dont get", "simpler"]):
                return (
                    f"Here is a concrete example of {directive.topic}: imagine a familiar system changing from one state to another. "
                    "Track the quantities entering and leaving the system, then ask which physical law explains that change. "
                    "What part of this example would you like to unpack?"
                )
            else:
                return (
                    f"For {directive.topic}, the key is to identify the physical quantities involved, the system boundary, and the law that relates them. "
                    "\n\nDid that make sense and did you understand, or would you like another example?"
                )

        # Phase 3: SOCRATIC CHALLENGE
        if directive.lesson_phase == LessonPhase.SOCRATIC_CHALLENGE:
            if "thermodynamics" in topic_lower:
                return (
                    "Awesome, let's put your thinking to the test! "
                    "Imagine a hot cup of coffee left on a table in a room at 20°C. Can thermal energy from the room spontaneously flow back into the coffee to make it boil again without an external energy source? Explain your reasoning using thermodynamics."
                )
            else:
                return (
                    "Awesome, let's put your thinking to the test! "
                    "A hockey puck is gliding across completely frictionless ice at a constant velocity of 12 m/s. Does it require a continuous forward force of 12 N to keep moving at that speed? Explain why or why not."
                )

        thermo_context = (
            any(k in last_tutor_turn for k in ["coffee", "boil", "refrigerator", "ice cube"])
            or "thermodynamic" in topic_lower
        )

        # Recovery verified after a successful transfer problem.
        if directive.lesson_phase == LessonPhase.DOUBT_CHECK:
            return (
                f"Excellent work! You applied the same principle to a brand-new situation, so your understanding of {directive.topic} is now verified. "
                "Would you like a harder challenge, or shall we explore a new topic?"
            )

        # Sound reasoning: affirm and serve a fresh transfer problem.
        if directive.lesson_phase == LessonPhase.TRANSFER_CHECK:
            if thermo_context:
                return (
                    "Spot on! That's exactly right: according to the Second Law of Thermodynamics, heat flows spontaneously only from higher to lower temperature. "
                    "\n\nNow, here is a transfer question: How does a household refrigerator manage to cool its interior by moving heat from inside to the hotter room?"
                )
            return (
                "Spot on! With the velocity constant, the acceleration is zero, so Newton's First Law tells us nothing needs to push the puck along. "
                "\n\nNow, here is a transfer question: If Voyager 1 cruises through deep space at 38,000 mph with its engines shut down, does its speed change over time?"
            )

        # "I don't know": empathetic, smaller sub-step.
        if directive.tier == InterventionTier.SCAFFOLDED_HINT:
            if thermo_context:
                return (
                    "No worries at all, that's completely okay! Let's think about everyday intuition: "
                    "Have you ever seen a cold cup of water on a table heat up all by itself and boil, or does heat always spread out into cooler surroundings? "
                    "Which direction does heat naturally flow?"
                )
            return (
                "No worries at all, that's completely okay! Let's break it down: "
                "on ordinary ice a sliding puck slowly stops. What is doing the stopping, and is that thing still there on perfectly frictionless ice?"
            )

        # Stuck after repeated hints: escalate to a clear decomposition.
        if directive.tier == InterventionTier.CONCEPTUAL_EXPLANATION:
            if thermo_context:
                return (
                    "Let's slow down and build it step by step. Step 1: heat is energy moving because of a temperature difference. "
                    "Step 2: on its own it always moves from the hotter body to the colder one, never the reverse. "
                    "Step 3: the room is at 20°C and the coffee is hotter. So which way can energy flow on its own, and could that ever make the coffee boil?"
                )
            return (
                "Let's build this step by step. Step 1: Newton's First Law says an object's velocity changes only when an unbalanced force acts on it. "
                "Step 2: on normal ice, friction is the unbalanced force that slows a puck. "
                "Step 3: on frictionless ice that friction is gone. With nothing left to change its velocity, what happens to the puck's speed?"
            )

        # Misconception: cognitive conflict via a counter-example. Rotate the
        # example so the learner never gets the same text twice in a row.
        if thermo_context:
            examples = [
                "Let's test that idea. Picture an ice cube on a table in a 20°C room. Have you ever seen the ice get colder while the room warms up? What does that tell you about the direction heat flows on its own?",
                "Here's a puzzle: a refrigerator needs to be plugged in to move heat out of its cold interior. If heat could flow from cold to hot by itself, why would it need electricity at all?",
            ]
        else:
            examples = [
                "Let's test that idea with a thought experiment. Voyager 1 has been coasting through deep space for decades with its engines off. Nothing is pushing it, yet it keeps moving. How does that fit with your idea that motion needs a push?",
                "Try this: slide a book across a carpet, then across a polished floor, then imagine a surface with no friction at all. How does the distance it travels change, and what would happen on the perfect surface?",
            ]
        for example in examples:
            if example.lower() != last_tutor_turn:
                return example
        return examples[0]

    @classmethod
    async def generate_response(
        cls,
        directive: SocraticDirective,
        student_text: str,
        conversation_history: List[Dict[str, Any]] = [],
        reference_hits: Optional[List[Dict[str, Any]]] = None,
        profile=None,
        affect: Optional[str] = None,
    ) -> str:
        from . import tutor_persona as persona
        raw_output = None
        reference_block = ""
        if reference_hits:
            from .document_store import format_references
            reference_block = (
                "\nReference material from the learner's uploaded documents:\n"
                + format_references(reference_hits) + "\n"
            )
        context_str = ""
        for turn in conversation_history[-3:]:
            context_str += f"Tutor: {turn.get('tutor', '')}\nStudent: {turn.get('user', '')}\n"

        # Use the local conversational model for every substantive teaching
        # turn. The deterministic response remains a reliable fallback when
        # Ollama is unavailable or returns low-quality/repeated text.
        use_local_model = directive.lesson_phase != LessonPhase.GREETING

        try:
            if not use_local_model:
                raise RuntimeError("deterministic classroom lifecycle response")
            prompt = CLASSROOM_PROMPT.format(
                lesson_phase=directive.lesson_phase.value,
                topic=directive.topic,
                pedagogical_goal=directive.pedagogical_goal,
                dialogue_context=context_str if context_str else "Session just started.",
                student_text=student_text,
                reference_block=reference_block,
                style_block=persona.style_block(profile, affect),
            )

            # Blocking HTTP call in a worker thread: keeps the server
            # responsive for other learners while the model is thinking.
            res = await asyncio.to_thread(
                requests.post,
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "stop": ["Student:", "Human:"]
                    }
                },
                # Small local models may need several seconds on first use;
                # a five-second cutoff made every real conversation silently
                # fall back to the canned reply.
                timeout=30.0
            )
            if res.status_code == 200:
                body = res.json()
                raw_output = body.get("response", "").strip()
        except Exception as e:
            logger.info(f"Classroom LLM generation fallback: {e}")

        if raw_output:
            normalized_output = " ".join(raw_output.lower().split())
            previous_tutor = " ".join(
                str(conversation_history[-1].get("tutor", "")).lower().split()
            ) if conversation_history else ""
            generic_fallback = "the key is to identify the physical quantities involved"
            if (
                len(raw_output) < 30
                or (previous_tutor and normalized_output == previous_tutor)
                or generic_fallback in normalized_output
            ):
                logger.info("Rejecting repetitive or generic local tutor response; using contextual fallback.")
                raw_output = None

        if raw_output:
            # Written to be heard: long model answers are cut down to their
            # opening and the question that hands the turn back.
            raw_output = persona.fit_for_voice(raw_output)
        elif affect == "frustration":
            raw_output = persona.frustration_fallback(directive.topic, f"{student_text}:{len(conversation_history)}")
        else:
            raw_output = cls._deterministic_response(directive, student_text, conversation_history, reference_hits)

        # Zero-Leakage Canary Scan
        passed, verified_output = SafetyGuardrail.verify_zero_leakage(raw_output, directive.forbidden_tokens)
        return verified_output
