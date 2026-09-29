import re
import logging
from typing import List, Tuple

logger = logging.getLogger("misconception_os.safety")

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"you\s+are\s+no\s+longer\s+a\s+tutor",
    r"reveal\s+(the\s+)?(full\s+)?(answer|solution|system\s+prompt)",
    r"give\s+me\s+the\s+(final\s+)?(answer|solution|code)",
    r"what\s+is\s+the\s+(exact\s+)?answer",
    r"just\s+tell\s+me\s+the\s+answer",
    r"dan\s+mode",
    r"act\s+as\s+(an?\s+)?uncensored",
    r"override\s+policy",
    r"bypass\s+rules",
    r"emergency.*just\s+give\s+me",
    r"i\s+have\s+an\s+exam\s+in\s+2\s+mins.*tell\s+me"
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
    "circuit", "magnetic", "magnetism", "field", "electromagnetic", "radiation",
    "relativity", "quantum", "atomic", "nuclear", "particle", "plasma", "semiconductor",
    "laser", "photoelectric", "cosmology", "astrophysics", "astronomy", "space", "star",
    "atmosphere", "air pollution", "pollution", "aerosol", "particulate", "smog",
    "climate", "weather", "greenhouse", "diffusion", "drag", "combustion", "material",
    "elasticity", "crystal", "fluid dynamics", "biophysics", "medical imaging", "ultrasound",
    "mri", "radiography", "geophysics", "seismology", "acoustic", "soundproof",
}

CLEARLY_NON_PHYSICS = {
    "recipe", "cook", "cooking", "poem", "song lyrics", "lyrics", "politics", "election",
    "president", "world war", "history essay", "stock market", "cryptocurrency", "blockchain",
    "sql query", "react component", "javascript", "python code", "programming", "translate",
    "write my email", "relationship advice", "medical diagnosis", "legal advice",
}

class SafetyGuardrail:
    @staticmethod
    def is_physics_query(user_text: str) -> bool:
        """Fast, high-recall physics boundary with interdisciplinary coverage."""
        text = re.sub(r"[^a-z0-9]+", " ", (user_text or "").lower()).strip()
        if not text:
            return True
        if any(marker in text for marker in CLEARLY_NON_PHYSICS):
            return any(anchor in text for anchor in PHYSICS_ANCHORS)
        if any(anchor in text for anchor in PHYSICS_ANCHORS):
            return True
        # Permit normal classroom front-door language; the next turn still
        # needs a physics anchor before a lesson is started.
        return text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "start", "begin"}

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
