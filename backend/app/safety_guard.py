import re
import logging
from typing import List, Tuple

logger = logging.getLogger("misconception_os.safety")

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override|bypass|skip)\s+(all\s+)?(of\s+)?(your|previous|prior|earlier|above|system|these|those|any)\b.{0,30}\b(instructions?|rules?|prompts?|guidelines|polic(y|ies)|constraints|restrictions)\b",
    r"\b(ignore|disregard|forget|override|bypass)\s+(the\s+)?(instructions?|rules?|prompts?|guidelines|polic(y|ies))\s+(above|before|you\s+were\s+given)\b",
    r"\bignore\s+(all\s+)?instructions\b",
    r"\b(ignore|disregard)\s+all\s+(the\s+)?(rules|instructions|guidelines|restrictions)\b",
    r"\b(override|bypass)\s+(the\s+)?(policy|rules|safety|filters?|guardrails?)\b",
    r"\bpretend\s+(that\s+)?(you\s+are|you're|to\s+be)\b",
    r"\byou\s+are\s+now\s+(a|an|my)\b",
    r"\b(no\s+longer|not)\s+a\s+(tutor|teacher)\b",
    r"\b(reveal|show|print|repeat|leak)\s+(me\s+)?(your\s+|the\s+)?(full\s+)?(answer|solution|system\s+prompt|hidden\s+instructions|instructions)",
    r"\b(give|tell|say|show|send)\s+(me\s+)?(just\s+)?(the\s+)?(final\s+|exact\s+|full\s+|direct\s+|correct\s+|numerical\s+)?(answer|solution|code)\b",
    r"\bwhat\s+is\s+the\s+(exact\s+|final\s+|correct\s+)?answer\b",
    r"\bjust\s+(tell|give)\s+me\b",
    r"\bdan\s+mode\b",
    r"\b(developer|god|jailbreak)\s+mode\b",
    r"\bjailbreak\b",
    r"\bact\s+as\s+(an?\s+)?(uncensored|unrestricted|different)",
    r"\bemergency\b.*\bjust\s+give\s+me\b",
    r"\bexam\s+in\s+\d+\s+min.*\btell\s+me\b",
]

# High-recall vocabulary for a physics boundary. Interdisciplinary terms are
# deliberately included: atmospheric pollution, climate, aerosols, medical
# imaging, materials, and chemistry-adjacent questions can all have a genuine
# physics framing.
PHYSICS_ANCHORS = {
    "physics", "mechanics", "motion", "kinematic", "dynamic", "force", "mass",
    "momentum", "impulse", "velocity", "acceleration", "displacement", "friction",
    "gravity", "gravitation", "orbit", "projectile", "energy", "work", "power",
    "heat", "temperature", "thermal", "thermodynamic", "entropy", "enthalpy",
    "pressure", "fluid", "viscosity", "buoyancy", "wave", "frequency", "sound",
    "resonance", "oscillation", "optics", "light", "photon", "reflection", "refraction",
    "lens", "mirror", "electric", "charge", "voltage", "current", "resistance",
    "circuit", "ohm", "ohms", "magnetic", "magnetism", "field", "electromagnetic", "radiation",
    "relativity", "quantum", "atomic", "nuclear", "particle", "plasma", "semiconductor",
    "laser", "photoelectric", "cosmology", "astrophysics", "astronomy", "space", "star",
    "atmosphere", "air pollution", "pollution", "aerosol", "particulate", "smog",
    "climate", "weather", "greenhouse", "diffusion", "drag", "combustion", "material",
    "elasticity", "crystal", "fluid dynamics", "biophysics", "medical imaging", "ultrasound",
    "mri", "radiography", "geophysics", "seismology", "acoustic", "soundproof",
    "float", "sink", "density", "buoyant", "boil", "freeze", "melt", "evaporation",
    "condensation", "rainbow", "magnet", "rocket", "speed", "fall", "falling", "weight", "spring",
    "pendulum", "vacuum", "gas", "liquid", "solid", "electron", "proton", "neutron", "atom",
    "newton", "joule", "watt", "volt", "ampere", "kelvin", "inertia", "torque", "lever", "pulley",
    "collision", "rotation", "spin", "photon", "spectrum", "prism", "telescope", "microscope",
    "thermometer", "insulator", "conductor", "capacitor", "resistor", "battery", "galaxy", "planet",
    "black hole", "universe", "big bang", "tide", "earthquake", "ice", "sky",
}

# Anchors that also have everyday meanings ("the current president",
# "work on my essay"). They only count as physics when no clearly
# non-physics marker is present.
WEAK_ANCHORS = {
    "current", "work", "power", "field", "space", "star", "material", "charge", "mass",
    "energy", "light", "weather", "climate", "sound", "pressure", "dynamic", "resistance",
    "speed", "fall", "falling", "weight", "spring", "solid", "spin", "sky", "ice", "float",
    "sink", "gas", "battery", "planet", "universe", "atmosphere", "star", "space",
}

CLEARLY_NON_PHYSICS = {
    "recipe", "cook", "cooking", "poem", "song lyrics", "lyrics", "politics", "election",
    "president", "world war", "history essay", "stock market", "cryptocurrency", "blockchain",
    "sql query", "react component", "javascript", "python code", "programming", "translate",
    "write my email", "relationship advice", "medical diagnosis", "legal advice",
    "joke", "jokes", "poem", "poetry", "story", "movie", "film", "football", "cricket", "song",
    "history", "geography", "essay", "prime minister", "celebrity", "horoscope", "dating",
}

CONTEXTUAL_LEARNER_REPLIES = {
    "i don't know", "i dont know", "not sure", "no idea", "confused",
    "same time", "at the same time", "together", "because", "i think",
    "my answer", "yes", "no", "okay", "ok", "another example", "i understand",
    "i don't understand", "haven't learned", "not learned", "continue", "go on", "next",
    "example", "again", "repeat", "understood", "got it", "makes sense", "ready", "no doubts",
    "harder", "challenge",
}

def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _has_term(text: str, term: str) -> bool:
    """Whole-word match that tolerates common suffixes (wave -> waves,
    electric -> electricity) without matching inside other words
    (ok -> joke, work -> homework, star -> start)."""
    return re.search(rf"\b{re.escape(term)}(s|es|al|ic|ics|ity|ing|ed|y)?\b", text) is not None


class SafetyGuardrail:
    @staticmethod
    def _matched_anchors(text: str):
        return {anchor for anchor in PHYSICS_ANCHORS if _has_term(text, anchor)}

    @staticmethod
    def is_clearly_non_physics(user_text: str) -> bool:
        """A request that names a non-physics subject and has no specific
        physics vocabulary. These are refused without a web lookup."""
        text = _normalize(user_text)
        if not any(_has_term(text, marker) for marker in CLEARLY_NON_PHYSICS):
            return False
        strong = SafetyGuardrail._matched_anchors(text) - WEAK_ANCHORS
        return not strong

    @staticmethod
    def is_physics_query(user_text: str) -> bool:
        """Fast, high-recall physics boundary with interdisciplinary coverage."""
        text = _normalize(user_text)
        if not text:
            return True
        if SafetyGuardrail.is_clearly_non_physics(user_text):
            return False
        if SafetyGuardrail._matched_anchors(text):
            return True
        if any(_has_term(text, _normalize(reply)) for reply in CONTEXTUAL_LEARNER_REPLIES):
            # Short answers inherit the physics scope from the active lesson;
            # rejecting them here would prevent diagnosis of misconceptions.
            return True
        # Very short follow-ups ("why?", "and then?", "how come") inherit
        # the scope of the lesson they belong to.
        if len(text.split()) <= 3 and not text.isdigit():
            return True
        # Permit normal classroom front-door language; the next turn still
        # needs a physics anchor before a lesson is started.
        return text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "start", "begin"}

    @staticmethod
    def is_physics_grounding(query: str, retrieved_context: str) -> bool:
        """Use retrieved evidence as a fallback classifier for ambiguous queries.

        This is deliberately secondary to the fast vocabulary guard: live search
        is useful for unusual wording, but should not add latency to ordinary
        physics turns or become the sole authority for scope decisions.
        """
        if not retrieved_context or "no results" in retrieved_context.lower():
            return False
        from .rag_engine import STOPWORDS
        query_terms = {t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if t not in STOPWORDS}
        context_lower = retrieved_context.lower()
        physics_terms = {
            "ohm", "resistance", "voltage", "current", "charge", "circuit", "force", "motion",
            "energy", "heat", "entropy", "pressure", "fluid", "wave", "frequency", "light",
            "photon", "gravity", "mass", "momentum", "acceleration", "field", "radiation",
            "quantum", "particle", "thermodynamic", "electric", "magnetic", "physics",
        }
        query_overlap = sum(_has_term(context_lower, term) for term in query_terms if len(term) > 3)
        physics_overlap = sum(term in context_lower for term in physics_terms)
        return query_overlap >= 1 and physics_overlap >= 2

    @staticmethod
    def detect_prompt_injection(user_text: str) -> Tuple[bool, str]:
        """Detects adversarial jailbreak attempts and returns appropriate deflection."""
        if not user_text:
            return False, ""
            
        text_lower = user_text.lower().strip()
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, text_lower):
                logger.warning(f"Adversarial Prompt Injection intercepted: '{user_text}'")
                deflection_msg = (
                    "I hear that you're seeking the immediate answer! However, my core role as your Socratic coach "
                    "is to help you construct the mental model yourself so you can solve any problem on your own. "
                    "Let's step back and look at the setup: What physical quantities are at play here?"
                )
                return True, deflection_msg
                
        return False, ""

    @staticmethod
    def verify_zero_leakage(tutor_output: str, solution_redactions: List[str]) -> Tuple[bool, str]:
        """
        Layer 5 Canary: Scans output for direct answer leaks or raw solution phrases.
        Returns (passed: bool, sanitized_output: str).
        """
        if not tutor_output or not solution_redactions:
            return True, tutor_output
            
        sanitized = tutor_output
        leak_detected = False
        
        for token in solution_redactions:
            # Check for direct phrase matches
            pattern = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
            if pattern.search(sanitized):
                logger.warning(f"Leakage Canary Alert: Found forbidden token/phrase '{token}' in generated tutor text!")
                leak_detected = True
                # Redact or rephrase
                sanitized = pattern.sub("[redacted guide]", sanitized)
                
        if leak_detected:
            # Append Socratic guidance
            sanitized += "\n\n*(Notice: Let's focus on the governing relationship rather than jumping directly to the numerical outcome.)*"
            
        return not leak_detected, sanitized
