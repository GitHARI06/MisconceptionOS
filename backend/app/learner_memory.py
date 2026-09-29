import json
import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from .models import LearnerProfile, ConceptMastery, DiagnosticEvidence, InterventionTier
from .rag_engine import knowledge_engine
from .config import settings

logger = logging.getLogger("misconception_os.memory")

class LearnerMemoryManager:
    def __init__(self, store_path: Optional[str] = None):
        if store_path is None:
            store_path = os.path.join(settings.DATA_DIR, "learner_store.json")
        self.store_path = store_path
        self.profiles: Dict[str, LearnerProfile] = {}
        self.load_store()
        
    def load_store(self):
        try:
            if os.path.exists(self.store_path):
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for sid, pdata in data.items():
                        self.profiles[sid] = LearnerProfile(**pdata)
            logger.info(f"Loaded {len(self.profiles)} persistent learner profiles.")
        except Exception as e:
            logger.error(f"Error loading learner store: {e}")
            self.profiles = {}

    def save_store(self):
        try:
            os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                data = {sid: p.model_dump() for sid, p in self.profiles.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving learner store: {e}")

    def get_or_create_profile(self, session_id: str, unit_id: str = "physics_mechanics") -> LearnerProfile:
        if session_id not in self.profiles:
            # Initialize with concepts for the unit
            concepts = knowledge_engine.get_unit_concepts(unit_id)
            initial_states = {}
            for c in concepts:
                initial_states[c["id"]] = ConceptMastery(
                    concept_id=c["id"],
                    concept_name=c["name"],
                    mastery_prob=0.15,
                    total_attempts=0,
                    correct_reasonings=0,
                    misconceptions_logged=[],
                    recovery_verified=False
                )
            self.profiles[session_id] = LearnerProfile(
                session_id=session_id,
                unit_id=unit_id,
                concept_states=initial_states,
                conversation_history=[],
                current_tier=InterventionTier.DIAGNOSTIC_PROBE,
                stuckness_turn_count=0
            )
            self.save_store()
        return self.profiles[session_id]

    def update_state(
        self,
        session_id: str,
        user_text: str,
        tutor_text: str,
        diagnostic: DiagnosticEvidence,
        tier: InterventionTier,
        current_phase=None,
        current_topic: Optional[str] = None
    ) -> LearnerProfile:
        profile = self.get_or_create_profile(session_id)
        cid = diagnostic.affected_concept_id
        
        if cid in profile.concept_states:
            cstate = profile.concept_states[cid]
            cstate.total_attempts += 1
            
            # Bayesian / Heuristic mastery update
            if diagnostic.reasoning_soundness_score >= 0.85 and not diagnostic.is_correct_answer_with_flawed_reasoning:
                cstate.correct_reasonings += 1
                cstate.mastery_prob = min(0.98, cstate.mastery_prob + 0.35)
                profile.stuckness_turn_count = 0
            else:
                # Lower or stagnate mastery on persistent misconception
                cstate.mastery_prob = max(0.05, cstate.mastery_prob - 0.10)
                if diagnostic.detected_misconception_id and diagnostic.detected_misconception_id not in cstate.misconceptions_logged:
                    cstate.misconceptions_logged.append(diagnostic.detected_misconception_id)
                profile.stuckness_turn_count += 1
                
        profile.current_tier = tier
        profile.active_misconception_id = diagnostic.detected_misconception_id
        profile.updated_at = datetime.now().isoformat()
        
        # Persist lesson phase & topic across turns
        if current_phase is not None:
            profile.current_phase = current_phase
        if current_topic is not None:
            profile.current_topic = current_topic
        
        # Append to conversation log
        profile.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "user": user_text,
            "tutor": tutor_text,
            "tier": tier.value,
            "category": diagnostic.category.value,
            "evidence": diagnostic.pedagogical_reason,
            "confidence": diagnostic.confidence,
            "is_lucky_guess": diagnostic.is_correct_answer_with_flawed_reasoning
        })
        
        self.save_store()
        return profile

    def verify_recovery(self, session_id: str, concept_id: str):
        """Marks recovery as verified after passing the transfer challenge."""
        profile = self.get_or_create_profile(session_id)
        if concept_id in profile.concept_states:
            profile.concept_states[concept_id].recovery_verified = True
            profile.concept_states[concept_id].mastery_prob = 0.95
            self.save_store()

learner_memory = LearnerMemoryManager()
